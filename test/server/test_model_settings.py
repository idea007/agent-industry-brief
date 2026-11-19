import json
from dataclasses import replace

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_saved_model_settings_route_a_scan_and_reject_revoked_models(
    harness, monkeypatch
):
    default = "industry-brief"
    summary_model = "local/reasoner"
    catalog = [
        {"id": default, "legacy_alias": True},
        {"id": "another-legacy-alias", "legacy_alias": True},
        {
            "id": summary_model,
            "name": "Local Reasoner",
            "source": {"id": "local", "name": "Local Codex", "type": "codex"},
            "capabilities": {"text": True, "tools": False, "structured": True},
            "reasoning_efforts": ["low", "high"],
            "default_reasoning_effort": "low",
        },
    ]
    settings, database, _, _ = harness
    configured = replace(
        settings,
        model_mode="real",
        content_ai_provider="model-dock-codex",
        content_ai_base_url="http://127.0.0.1:4317/v1",
        content_ai_api_key="md_key_test",
        content_ai_model=default,
        content_ai_reasoning_effort="low",
    )
    calls = []

    def gateway(request):
        assert request.headers["Authorization"] == "Bearer md_key_test"
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": catalog})
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        calls.append(payload)
        if "tools" in payload:
            name = payload["tools"][0]["function"]["name"]
            args = {"query": "AI Agent"} if name == "search_sources" else {}
            choice = {
                "finish_reason": "tool_calls",
                "message": {"tool_calls": [{
                    "id": "call_tool",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }]},
            }
        else:
            choice = {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"research_summary": "无新资料", "items": []})
                },
            }
        return httpx.Response(200, json={"model": payload["model"], "choices": [choice]})

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(gateway), **kwargs),
    )
    app = create_app(configured)
    async with app.router.lifespan_context(app):
        async with async_client(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            endpoint = "/api/model-settings"
            response = await client.get(endpoint, params={"refresh": True})
            state = response.raise_for_status().json()
            assert "md_key_test" not in response.text
            assert state["connection"]["checked"]
            assert [row["id"] for row in state["models"]] == [default, summary_model]
            assert len(state["routes"]) == 4
            update = {
                "revision": state["revision"],
                "models": [
                    {key: row[key] for key in ("id", "enabled", "reasoningPolicy", "groupPolicies")}
                    for row in state["models"]
                ],
                "routes": state["routes"],
            }
            reasoner = next(row for row in update["models"] if row["id"] == summary_model)
            reasoner["enabled"] = True
            search = next(row for row in update["routes"] if row["id"] == "monitor-search")
            search["allowedModelIds"].append(summary_model)
            assert (await client.post(endpoint, json=update)).status_code == 422
            search["allowedModelIds"].remove(summary_model)

            summary = next(row for row in update["routes"] if row["id"] == "monitor-summary")
            summary["modelId"] = summary_model
            summary["allowedModelIds"].append(summary_model)
            summary["reasoningOverrides"][summary_model] = {
                "allowedEfforts": ["low", "high"],
                "defaultEffort": "high",
            }
            saved = (await client.post(endpoint, json=update)).raise_for_status().json()
            assert saved["state"]["revision"] == 1
            assert (await client.post(endpoint, json=update)).status_code == 409
            assert database.load_model_settings()[1]["routes"] == update["routes"]

        subscription = next(row for row in database.list_subscriptions() if row.slug == "ai-agent")
        run = database.create_run(
            subscription_id=subscription.id, trigger="manual", goal="验证模型设置",
            delivery_mode="web_inbox", idempotency_key=None,
        )
        await app.state.runtime.execute(run.id)
        assert database.get_run(run.id).status == "completed"
        assert [payload["model"] for payload in calls] == [default] * 3 + [summary_model]
        assert calls[-1]["reasoning_effort"] == "high"
        assert calls[-1]["response_format"]["type"] == "json_schema"

        catalog.pop()
        calls.clear()
        run = database.create_run(
            subscription_id=subscription.id, trigger="manual", goal="验证模型授权回收",
            delivery_mode="web_inbox", idempotency_key=None,
        )
        await app.state.runtime.execute(run.id)
        assert database.get_run(run.id).error["code"] == "MODEL_CONFIGURATION_ERROR"
        assert [payload["model"] for payload in calls] == [default] * 3
