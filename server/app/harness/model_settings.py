from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints
from pydantic.alias_generators import to_camel

from app.config import Settings
from app.persistence.database import Database


FEATURES = {
    "monitor-search": ("新闻检索", "行业扫描", "tools"),
    "monitor-summary": ("简报整理", "行业扫描", "structured"),
    "deep-dive-search": ("深挖检索", "故事深挖", "tools"),
    "deep-dive-summary": ("进展研判", "故事深挖", "structured"),
}
ModelId = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Effort = Annotated[str, StringConstraints(min_length=1, max_length=30)]


class SettingsPayload(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class ReasoningPolicy(SettingsPayload):
    allowed_efforts: list[Effort] = Field(min_length=1, max_length=32)
    default_effort: Effort


class ModelPreference(SettingsPayload):
    id: ModelId
    enabled: StrictBool
    reasoning_policy: ReasoningPolicy | None = None
    group_policies: dict[str, ReasoningPolicy] = Field(default_factory=dict)


class FeaturePreference(SettingsPayload):
    id: str
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    kind: Literal["tools", "structured"]
    group: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
    selection: Literal["single", "multiple"]
    model_id: str = Field(max_length=512)
    allowed_model_ids: list[ModelId] = Field(max_length=1000)
    reasoning_overrides: dict[ModelId, ReasoningPolicy] = Field(default_factory=dict)


class ModelConfiguration(SettingsPayload):
    models: list[ModelPreference] = Field(max_length=1000)
    routes: list[FeaturePreference] = Field(max_length=len(FEATURES))


class ModelConfigurationUpdate(ModelConfiguration):
    revision: int = Field(ge=0)


class SettingsConflict(ValueError):
    pass


@dataclass(frozen=True)
class ModelSelection:
    id: str
    source_type: str
    reasoning_effort: str | None


def _compatible(kind: str, model: dict[str, Any]) -> bool:
    capabilities = model["capabilities"]
    return capabilities.get("text") is not False and capabilities.get(kind) is not False


def _catalog_entry(model_id: str, row: dict[str, Any]) -> dict[str, Any]:
    source = row.get("source") or {}
    if not isinstance(source, dict):
        source = {}
    source_id = source.get("id")
    if isinstance(source_id, str) and source_id:
        source_type = source.get("type")
        source = {
            "id": source_id,
            "name": str(source.get("name") or source_id)[:100],
            "type": source_type if source_type in ("openai", "ollama", "codex") else "openai",
        }
    else:
        source = {"id": "model-dock-aliases", "name": "Model Dock", "type": "alias"}
    capabilities = row.get("capabilities")
    levels = row.get("reasoning_efforts")
    effort = row.get("default_reasoning_effort")
    context = row.get("context_window")
    return {
        "id": model_id,
        "name": str(row.get("name") or model_id)[:300],
        "connectionId": source["id"],
        "source": source,
        "capabilities": {
            key: capabilities[key]
            for key in ("text", "tools", "structured", "thinking", "image_generation")
            if isinstance(capabilities, dict) and isinstance(capabilities.get(key), bool)
        },
        "contextWindow": context if type(context) is int and context > 0 else None,
        "reasoningEfforts": list(dict.fromkeys(
            level for level in levels if isinstance(level, str) and 0 < len(level) <= 30
        )) if isinstance(levels, list) else [],
        "defaultEffort": effort if isinstance(effort, str) else None,
        "legacyAlias": row.get("legacy_alias") is True,
        "available": bool(row),
    }


def _validate_policy(policy: ReasoningPolicy | None, available: list[str]) -> list[str]:
    if policy is None:
        return available
    chosen = policy.allowed_efforts
    if (len(chosen) != len(set(chosen)) or not set(chosen).issubset(available)
            or policy.default_effort not in chosen):
        raise ValueError("请选择模型开放的思考深度，并从中指定默认值。")
    return chosen


class ModelSettings:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.configured = (
            settings.model_mode == "real"
            and settings.content_ai_provider == "model-dock-codex"
        )
        self.catalog: dict[str, dict[str, Any]] = {}
        self.catalog_error = ""
        self.catalog_checked = False
        self._refresh_lock = asyncio.Lock()

    @property
    def features(self) -> list[dict[str, Any]]:
        default_model = self.settings.content_ai_model if self.configured else ""
        return [
            {
                "id": feature_id,
                "name": name,
                "kind": kind,
                "group": group,
                "selection": "multiple",
                "modelId": default_model,
                "allowedModelIds": [default_model] if default_model else [],
                "reasoningOverrides": {},
            }
            for feature_id, (name, group, kind) in FEATURES.items()
        ]

    async def refresh(self) -> None:
        if not self.configured:
            return
        async with self._refresh_lock:
            base_url = (self.settings.content_ai_base_url or "").rstrip("/")
            try:
                async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                    response = await client.get(
                        f"{base_url}/models",
                        headers={"Authorization": f"Bearer {self.settings.content_ai_api_key}"},
                    )
                response.raise_for_status()
                data = response.json()
                rows = data.get("data") if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("Invalid model catalog")
                catalog = {}
                for row in rows:
                    model_id = row.get("id") if isinstance(row, dict) else None
                    if not isinstance(model_id, str) or not 0 < len(model_id) <= 512:
                        continue
                    if model_id in ("__proto__", "constructor", "prototype"):
                        continue
                    entry = _catalog_entry(model_id, row)
                    if (entry["capabilities"].get("image_generation")
                            and entry["capabilities"].get("text") is not True):
                        continue
                    catalog[model_id] = entry
            except httpx.HTTPStatusError as exc:
                self.catalog_error = f"无法读取 Model Dock 授权目录（HTTP {exc.response.status_code}）。"
                return
            except (httpx.RequestError, ValueError):
                self.catalog_error = "无法读取 Model Dock 授权目录，请检查网关是否可用。"
                return
            self.catalog = {
                **{key: {**entry, "available": False} for key, entry in self.catalog.items()},
                **catalog,
            }
            self.catalog_error = ""
            self.catalog_checked = True

    def snapshot(self) -> dict[str, Any]:
        revision, saved = self.database.load_model_settings()
        catalog = self.catalog.copy()
        preferences = {row["id"]: row for row in saved.get("models", [])}
        default_model = self.settings.content_ai_model
        remembered_ids = dict.fromkeys([default_model, *preferences]) if self.configured else {}
        for model_id in remembered_ids:
            catalog.setdefault(model_id, _catalog_entry(model_id, {}))
        models = []
        sources = {}
        for model_id, entry in catalog.items():
            if entry["legacyAlias"] and model_id not in remembered_ids:
                continue
            source = entry["source"]
            sources[source["id"]] = {
                **source,
                "enabled": self.catalog_checked and not self.catalog_error,
                "status": "error" if self.catalog_error else "connected",
            }
            preference = preferences.get(model_id, {})
            effort = self.settings.content_ai_reasoning_effort
            models.append({
                **entry,
                "defaultEffort": effort if model_id == default_model
                and effort in entry["reasoningEfforts"] else entry["defaultEffort"],
                "available": entry["available"] and not self.catalog_error,
                "enabled": preference.get("enabled", model_id == default_model),
                "reasoningPolicy": preference.get("reasoningPolicy"),
                "groupPolicies": preference.get("groupPolicies", {}),
            })
        return {
            "revision": revision,
            "settingsRevision": revision,
            "connection": {
                "configured": self.configured,
                "checked": self.catalog_checked,
                "error": self.catalog_error,
            },
            "connections": list(sources.values()),
            "models": models,
            "routes": saved.get("routes", self.features),
            "features": self.features,
        }

    def save(self, update: ModelConfigurationUpdate) -> dict[str, Any]:
        if not self.configured:
            raise ValueError("当前项目尚未配置 Model Dock。")
        current = self.snapshot()
        if update.revision != current["revision"]:
            raise SettingsConflict("设置已在其他页面更改，请撤销草稿并加载最新设置。")
        previous_models = {row["id"]: row for row in current["models"]}
        previous_routes = {row["id"]: row for row in current["routes"]}
        models = {row.id: row for row in update.models}
        if len(models) != len(update.models) or models.keys() != previous_models.keys():
            raise ValueError("模型目录已变化，请刷新模型后再保存。")
        groups = {route.group for route in update.routes if route.group}
        for model in update.models:
            previous = previous_models[model.id]
            if model.enabled and not previous["enabled"] and not previous["available"]:
                raise ValueError("只能启用当前项目已授权的模型。")
            levels = _validate_policy(model.reasoning_policy, previous["reasoningEfforts"])
            for group, policy in model.group_policies.items():
                if group not in groups:
                    raise ValueError("思考设置引用了不存在的功能分组。")
                _validate_policy(policy, levels)
        known_routes = set()
        for route in update.routes:
            feature = FEATURES.get(route.id)
            if not feature or route.id in known_routes or route.kind != feature[2]:
                raise ValueError("只能配置新闻简报已有的功能。")
            known_routes.add(route.id)
            previous = previous_routes.get(route.id, {})
            allowed = set(route.allowed_model_ids)
            if (len(allowed) != len(route.allowed_model_ids) or not allowed.issubset(models)
                    or route.selection == "single" and len(allowed) > 1):
                raise ValueError("功能的候选模型无效。")
            if route.model_id and (route.model_id not in models or (
                route.model_id not in allowed and route.model_id != previous.get("modelId")
            )):
                raise ValueError("请从功能的候选模型中指定默认模型。")
            for model_id in allowed:
                entry = previous_models[model_id]
                introduced = model_id not in previous.get("allowedModelIds", [])
                new_default = model_id == route.model_id and route.model_id != previous.get("modelId")
                if (introduced or new_default) and (
                    not models[model_id].enabled or not entry["available"]
                    or not _compatible(route.kind, entry)
                ):
                    raise ValueError("所选模型不可用或不支持该功能。")
            for model_id, policy in route.reasoning_overrides.items():
                if model_id not in models:
                    raise ValueError("思考设置引用了未知模型。")
                model = models[model_id]
                parent = model.group_policies.get(route.group) or model.reasoning_policy
                levels = parent.allowed_efforts if parent else previous_models[model_id]["reasoningEfforts"]
                _validate_policy(policy, levels)
        config = update.model_dump(by_alias=True, exclude={"revision"})
        if not self.database.save_model_settings(update.revision, config):
            raise SettingsConflict("设置已在其他页面更改，请撤销草稿并加载最新设置。")
        return self.snapshot()

    async def for_run(self) -> ModelConfiguration | None:
        if not self.configured:
            return None
        revision, saved = self.database.load_model_settings()
        if not revision:
            return None
        await self.refresh()
        return ModelConfiguration.model_validate(saved)

    def resolve(
        self,
        configuration: ModelConfiguration,
        catalog: dict[str, dict[str, Any]],
        catalog_error: str,
        *,
        research_mode: str,
        final_step: bool,
    ) -> ModelSelection | None:
        workflow = "deep-dive" if research_mode == "deep_dive" else "monitor"
        feature_id = f"{workflow}-{'summary' if final_step else 'search'}"
        feature = next((row for row in configuration.routes if row.id == feature_id), None)
        model_id = feature.model_id if feature else self.settings.content_ai_model
        preference = next((row for row in configuration.models if row.id == model_id), None)
        if preference and not preference.enabled:
            raise ValueError(f"「{FEATURES[feature_id][0]}」的模型已停用，请在设置中启用模型。")
        if feature is None:
            return None
        if catalog_error:
            raise ValueError(catalog_error)
        model = catalog.get(model_id)
        if (not model or not model["available"] or model_id not in feature.allowed_model_ids
                or not preference or not _compatible(feature.kind, model)):
            raise ValueError(f"「{feature.name}」的默认模型不可用，请在设置中选择已授权的模型。")
        levels = _validate_policy(preference.reasoning_policy, model["reasoningEfforts"])
        group = preference.group_policies.get(feature.group)
        levels = _validate_policy(group, levels)
        override = feature.reasoning_overrides.get(model_id)
        _validate_policy(override, levels)
        policy = override or group or preference.reasoning_policy
        effort = policy.default_effort if policy else model["defaultEffort"]
        if not policy and model_id == self.settings.content_ai_model:
            configured_effort = self.settings.content_ai_reasoning_effort
            if model["source"]["type"] == "alias" or configured_effort in levels:
                effort = configured_effort
        return ModelSelection(model_id, model["source"]["type"], effort)
