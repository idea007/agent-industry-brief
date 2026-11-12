from __future__ import annotations

import asyncio
from typing import Any

from app.domain.models import (
    ApprovalDecision,
    EvalResult,
    Run,
    RunStage,
    RunStatus,
    RunUsage,
    StructuredResultIntent,
    ToolCallIntent,
)
from app.domain.quality_pipeline import QualityPipeline
from app.harness.evals import EvalRunner
from app.harness.model_adapter import (
    MockResearchModelAdapter,
    ModelAdapterError,
    ModelDecision,
    ResearchModelAdapter,
)
from app.harness.policy import ToolPolicy
from app.harness.tools import ToolExecutionError, ToolRegistry
from app.persistence.database import Database


TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}
EVAL_FAILURE_LABELS = {
    "output_schema": "输出结构",
    "source_integrity": "来源完整性",
    "prompt_injection_boundary": "安全来源边界",
    "citation_consistency": "引用一致性",
    "fact_citation_coverage": "事实引用",
    "citation_quote_integrity": "引文完整性",
    "contradiction_handling": "来源冲突处理",
    "summary_faithfulness": "摘要数字回溯",
}


def _eval_failure_message(result: EvalResult) -> str:
    failures: list[str] = []
    for check in result.checks:
        if check.get("severity", "hard") != "hard" or check.get("passed"):
            continue
        label = EVAL_FAILURE_LABELS.get(
            str(check.get("name") or ""),
            str(check.get("name") or "质量门禁"),
        )
        detail = check.get("detail")
        count = 0
        if isinstance(detail, dict):
            count = max(
                (
                    len(value)
                    for value in detail.values()
                    if isinstance(value, list)
                ),
                default=0,
            )
        failures.append(f"{label}（{count} 条）" if count else label)
    if not failures:
        return "情报草稿未通过质量与安全检查"
    return f"情报草稿未通过{'、'.join(failures)}检查"


class AgentRuntime:
    def __init__(
        self,
        database: Database,
        registry: ToolRegistry,
        policy: ToolPolicy,
        model: ResearchModelAdapter,
        eval_runner: EvalRunner,
        *,
        step_delay_seconds: float = 0.18,
        quality_observability_enabled: bool = True,
        story_clustering_enabled: bool = True,
        claim_eval_enabled: bool = True,
        personalization_enabled: bool = True,
        max_concurrent_runs: int = 2,
    ):
        self.database = database
        self.registry = registry
        self.policy = policy
        self.model = model
        self.eval_runner = eval_runner
        self.step_delay_seconds = step_delay_seconds
        self.quality_pipeline = QualityPipeline()
        self.quality_observability_enabled = (
            quality_observability_enabled
        )
        self.story_clustering_enabled = story_clustering_enabled
        self.claim_eval_enabled = claim_eval_enabled
        self.personalization_enabled = personalization_enabled
        self.max_concurrent_runs = max(1, int(max_concurrent_runs))
        self._run_slots = asyncio.Semaphore(self.max_concurrent_runs)
        self._active_run_ids: set[str] = set()
        self._queued_run_ids: set[str] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def start(self, run_id: str) -> None:
        current = self._tasks.get(run_id)
        if current and not current.done():
            return
        self._tasks[run_id] = asyncio.create_task(
            self._execute_when_slot_available(run_id),
            name=f"agent-run:{run_id}",
        )

    def status(self) -> dict[str, int]:
        return {
            "max_concurrent_runs": self.max_concurrent_runs,
            "active_run_count": len(self._active_run_ids),
            "queued_run_count": len(self._queued_run_ids),
        }

    async def _execute_when_slot_available(self, run_id: str) -> None:
        acquired = False
        try:
            if self._run_slots.locked():
                self._queued_run_ids.add(run_id)
                run = self._require_run(run_id)
                self._event(
                    run,
                    "run.queued",
                    {
                        "queue_position": len(self._queued_run_ids),
                        "max_concurrent_runs": self.max_concurrent_runs,
                    },
                    actor={"type": "runtime", "id": "agent_runtime"},
                )

            await self._run_slots.acquire()
            acquired = True
            self._queued_run_ids.discard(run_id)
            self._active_run_ids.add(run_id)

            run = self._require_run(run_id)
            if run.status in TERMINAL_STATUSES:
                return
            if await self._cancel_if_requested(run):
                return
            await self.execute(run_id)
        except asyncio.CancelledError:
            run = self.database.get_run(run_id)
            if run and run.status not in TERMINAL_STATUSES:
                user_requested = run.cancellation_requested
                run = self.database.update_run(
                    run_id,
                    status=RunStatus.CANCELLED,
                    error={
                        "code": (
                            "USER_CANCELLED"
                            if user_requested
                            else "TASK_CANCELLED"
                        ),
                        "message": (
                            "用户取消了 Run"
                            if user_requested
                            else "后台任务被取消"
                        ),
                    },
                )
                self._event(
                    run,
                    "run.cancelled",
                    {
                        "reason": (
                            "user_requested"
                            if user_requested
                            else "background_task_cancelled"
                        )
                    },
                    actor={"type": "runtime", "id": "agent_runtime"},
                )
            raise
        finally:
            self._queued_run_ids.discard(run_id)
            self._active_run_ids.discard(run_id)
            if acquired:
                self._run_slots.release()

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.model.close()

    async def execute(self, run_id: str) -> None:
        observations: dict[str, dict[str, Any]] = {}
        try:
            run = self._require_run(run_id)
            subscription = self.database.get_subscription(run.subscription_id)
            if subscription is None:
                raise RuntimeError("订阅不存在")

            run = self.database.update_run(
                run_id, status=RunStatus.RUNNING, stage=RunStage.PLANNING
            )
            self._event(
                run,
                "run.started",
                {"goal": run.goal, "trigger": run.trigger},
                actor={"type": "runtime", "id": "agent_runtime"},
            )

            while True:
                await self._pause()
                run = self._require_run(run_id)
                if await self._cancel_if_requested(run):
                    return

                usage = RunUsage.model_validate(run.usage.model_dump())
                if usage.model_steps >= run.budget.max_model_steps:
                    await self._fail(
                        run,
                        "MODEL_STEP_BUDGET_EXHAUSTED",
                        "模型步骤预算已耗尽",
                    )
                    return

                usage.model_steps += 1
                run = self.database.update_run(run_id, usage=usage)
                visible_tools = self._next_model_tools(observations)
                self._event(
                    run,
                    "model.started",
                    {
                        "step": usage.model_steps,
                        "visible_tools": visible_tools,
                        "context": {
                            "subscription": subscription.name,
                            "observation_keys": sorted(observations),
                            "external_content_trust": "untrusted",
                        },
                    },
                    actor={"type": "model", "id": self.model.actor_id},
                )
                try:
                    decision = await self.model.decide(
                        run,
                        subscription,
                        observations,
                        self.registry.model_tool_definitions(visible_tools),
                    )
                except ModelAdapterError as exc:
                    self._event(
                        run,
                        "model.failed",
                        {
                            "code": exc.code,
                            "message": str(exc),
                            "retryable": exc.retryable,
                            "status_code": exc.status_code,
                        },
                        actor={"type": "model", "id": self.model.actor_id},
                    )
                    if exc.retryable and not visible_tools:
                        decision = await self._degraded_final_decision(
                            run,
                            subscription,
                            observations,
                            exc,
                        )
                    else:
                        await self._fail(run, exc.code, str(exc))
                        return
                usage.input_tokens += decision.input_tokens
                usage.output_tokens += decision.output_tokens
                run = self.database.update_run(run.id, usage=usage)
                intent = decision.intent
                self._event(
                    run,
                    "model.responded",
                    {
                        "provider": decision.provider,
                        "model": decision.model,
                        "intent": intent.kind,
                        "input_tokens": decision.input_tokens,
                        "output_tokens": decision.output_tokens,
                    },
                    actor={"type": "model", "id": self.model.actor_id},
                )

                if isinstance(intent, ToolCallIntent):
                    run = await self._set_stage_for_tool(run, intent.tool)
                    outcome = await self._execute_tool(
                        run, subscription, intent, usage
                    )
                    if outcome is None:
                        return
                    observations[intent.tool] = outcome
                    continue

                if isinstance(intent, StructuredResultIntent):
                    await self._finalize_research(
                        run, subscription, intent, observations
                    )
                    return

                await self._fail(
                    run,
                    "MODEL_BLOCKED",
                    getattr(intent, "reason", "模型无法继续"),
                )
                return
        except asyncio.CancelledError:
            run = self.database.get_run(run_id)
            if run and run.status not in TERMINAL_STATUSES:
                self.database.update_run(
                    run_id,
                    status=RunStatus.CANCELLED,
                    error={"code": "TASK_CANCELLED", "message": "后台任务被取消"},
                )
            raise
        except Exception as exc:
            run = self.database.get_run(run_id)
            if run and run.status not in TERMINAL_STATUSES:
                await self._fail(
                    run,
                    "UNHANDLED_RUNTIME_ERROR",
                    str(exc),
                )

    async def _execute_tool(
        self,
        run: Run,
        subscription: Any,
        intent: ToolCallIntent,
        usage: RunUsage,
    ) -> dict[str, Any] | None:
        tool_call_id = self.database.create_tool_call(
            run.id, intent.tool, intent.args, intent.reason
        )
        self._event(
            run,
            "tool.requested",
            {
                "tool_call_id": tool_call_id,
                "tool": intent.tool,
                "args": intent.args,
                "reason": intent.reason,
            },
            actor={"type": "model", "id": self.model.actor_id},
        )
        decision = self.policy.evaluate(run, intent.tool, intent.args)
        self.database.update_tool_call(
            tool_call_id,
            decision=decision.model_dump(),
            status="allowed" if decision.is_allowed else "denied",
        )
        self._event(
            run,
            "tool.allowed" if decision.is_allowed else "tool.denied",
            {
                "tool_call_id": tool_call_id,
                "tool": intent.tool,
                "decision": decision.model_dump(),
            },
            actor={"type": "policy", "id": "tool_policy"},
        )
        if decision.is_denied:
            await self._fail(run, decision.reason_code, decision.message)
            return None

        self.database.update_tool_call(tool_call_id, status="running")
        self._event(
            run,
            "tool.started",
            {"tool_call_id": tool_call_id, "tool": intent.tool},
            actor={"type": "tool", "id": intent.tool},
        )
        await self._pause()
        try:
            result, duration_ms = await self.registry.execute(
                run, subscription, intent.tool, intent.args
            )
        except ToolExecutionError as exc:
            self.database.update_tool_call(
                tool_call_id, status="failed", error=exc.as_dict()
            )
            self._event(
                run,
                "tool.failed",
                {
                    "tool_call_id": tool_call_id,
                    "tool": intent.tool,
                    "error": exc.as_dict(),
                },
                actor={"type": "tool", "id": intent.tool},
            )
            await self._fail(run, exc.code, exc.message)
            return None

        usage.tool_calls += 1
        stored_result = result
        if intent.tool == "search_sources":
            usage.search_calls += 1
            discovery_documents = result.get(
                "discovery_documents",
                result.get("documents", []),
            )
            run = self.database.update_run(
                run.id, stage=RunStage.CLUSTERING
            )
            self._stage_event(run, RunStage.CLUSTERING)
            preferences = (
                self.database.get_subscription_preferences(subscription.id)
                if self.personalization_enabled
                else None
            )
            quality_result = self.quality_pipeline.analyze_documents(
                subscription,
                discovery_documents,
                preferences,
            )
            discovery_documents = quality_result["documents"]
            analyzed_by_source_id = {
                str(document.get("source_id")): document
                for document in discovery_documents
                if document.get("source_id")
            }
            if not self.story_clustering_enabled:
                for document in discovery_documents:
                    document["cluster_id"] = None
                    document["cluster_relation"] = None
                quality_result = {
                    **quality_result,
                    "cluster_count": 0,
                    "relation_counts": {},
                    "needs_review_count": 0,
                }
            evidence_documents = [
                analyzed_by_source_id.get(
                    str(document.get("source_id")), document
                )
                for document in result.get("documents", [])
            ]
            if self.personalization_enabled:
                eligible_documents = [
                    document
                    for document in evidence_documents
                    if not document.get("personalization_muted")
                    or document.get("source_type")
                    in {"official", "policy", "research"}
                ]
                evidence_documents = eligible_documents
                evidence_documents.sort(
                    key=lambda document: (
                        float(document.get("relevance_score") or 0),
                        float(document.get("novelty_score") or 0),
                        float(document.get("ranking_score") or 0),
                    ),
                    reverse=True,
                )
            result["discovery_documents"] = discovery_documents
            result["documents"] = evidence_documents
            result["evidence_count"] = len(evidence_documents)
            result["quality"] = {
                key: value
                for key, value in quality_result.items()
                if key != "documents"
            }
            if self.quality_observability_enabled:
                relevance_scores = [
                    float(document.get("relevance_score") or 0)
                    for document in discovery_documents
                ]
                novelty_scores = [
                    float(document.get("novelty_score") or 0)
                    for document in discovery_documents
                ]
                self._event(
                    run,
                    "quality.relevance_scored",
                    {
                        "document_count": len(discovery_documents),
                        "average_relevance": round(
                            sum(relevance_scores)
                            / max(1, len(relevance_scores)),
                            4,
                        ),
                        "average_novelty": round(
                            sum(novelty_scores)
                            / max(1, len(novelty_scores)),
                            4,
                        ),
                        "personalization_enabled": (
                            self.personalization_enabled
                        ),
                    },
                    actor={"type": "runtime", "id": "quality_pipeline"},
                )
                self._event(
                    run,
                    "clustering.completed",
                    {
                        "enabled": self.story_clustering_enabled,
                        "cluster_count": quality_result["cluster_count"],
                        "relation_counts": quality_result[
                            "relation_counts"
                        ],
                        "needs_review_count": quality_result[
                            "needs_review_count"
                        ],
                        "independent_evidence_chain_count": quality_result[
                            "independent_evidence_chain_count"
                        ],
                    },
                    actor={"type": "runtime", "id": "story_clusterer"},
                )
            evidence_source_ids = {
                str(document.get("source_id"))
                for document in evidence_documents
                if document.get("source_id")
            }
            persisted_documents = self.database.save_source_documents(
                run.id,
                subscription.id,
                discovery_documents,
                evidence_source_ids=evidence_source_ids,
            )
            persisted_by_source_id = {
                document.source_id: document
                for document in persisted_documents
            }
            source_updates = result.get("source_updates", [])
            for update in source_updates:
                source_ids = {
                    str(source_id)
                    for source_id in update.get("document_source_ids", [])
                }
                update["new_document_count"] = sum(
                    persisted_by_source_id[source_id].seen_count == 1
                    for source_id in source_ids
                    if source_id in persisted_by_source_id
                )
                update["fulltext_success_count"] = len(
                    update.get("fulltext_source_ids", [])
                )
            health_changes = self.database.record_source_runtime_updates(
                subscription.id,
                source_updates,
            )
            stored_result = {
                "count": result.get("count"),
                "discovery_count": result.get(
                    "discovery_count", len(discovery_documents)
                ),
                "evidence_count": result.get(
                    "evidence_count", len(evidence_source_ids)
                ),
                "deferred_count": result.get("deferred_count", 0),
                "blocked_count": result.get("blocked_count", 0),
                "group_counts": result.get("group_counts", {}),
                "query": result.get("query"),
                "source_errors": result.get("source_errors", []),
                "fetched_source_count": result.get("fetched_source_count", 0),
                "search_query_count": result.get("search_query_count", 0),
                "fulltext_count": result.get("fulltext_count", 0),
                "trust_notice": result.get("trust_notice"),
                "quality": result.get("quality", {}),
                "document_ids": [
                    document.id for document in persisted_documents
                ],
                "documents_persisted": len(persisted_documents),
            }
            self._event(
                run,
                "collection.discovery_completed",
                {
                    "discovery_count": stored_result["discovery_count"],
                    "fetched_source_count": stored_result[
                        "fetched_source_count"
                    ],
                    "source_error_count": len(stored_result["source_errors"]),
                },
                actor={"type": "runtime", "id": "collection_pipeline"},
            )
            self._event(
                run,
                "collection.ranking_completed",
                {
                    "evidence_count": stored_result["evidence_count"],
                    "deferred_count": stored_result["deferred_count"],
                    "blocked_count": stored_result["blocked_count"],
                    "group_counts": stored_result["group_counts"],
                },
                actor={"type": "runtime", "id": "evidence_allocator"},
            )
            self._event(
                run,
                "extraction.completed",
                {
                    "attempted_count": min(
                        stored_result["evidence_count"],
                        stored_result["discovery_count"],
                    ),
                    "fulltext_success_count": stored_result["fulltext_count"],
                },
                actor={"type": "runtime", "id": "content_extractor"},
            )
            for change in health_changes:
                self._event(
                    run,
                    "source.health_changed",
                    change,
                    actor={"type": "runtime", "id": "source_health"},
                )
        self.database.update_run(run.id, usage=usage)
        self.database.update_tool_call(
            tool_call_id,
            status="completed",
            result=stored_result,
            duration_ms=duration_ms,
        )
        safe_result_summary = {
            "count": result.get("count"),
            "query": result.get("query"),
            "trust_notice": result.get("trust_notice"),
        }
        if intent.tool == "search_sources":
            safe_result_summary["documents_persisted"] = len(
                persisted_documents
            )
            safe_result_summary["discovery_count"] = result.get(
                "discovery_count", len(persisted_documents)
            )
            safe_result_summary["evidence_count"] = result.get(
                "evidence_count", result.get("count", 0)
            )
            safe_result_summary["deferred_count"] = result.get(
                "deferred_count", 0
            )
            safe_result_summary["fetched_source_count"] = result.get(
                "fetched_source_count", 0
            )
            safe_result_summary["search_query_count"] = result.get(
                "search_query_count", 0
            )
            safe_result_summary["fulltext_count"] = result.get(
                "fulltext_count", 0
            )
        self._event(
            run,
            "tool.completed",
            {
                "tool_call_id": tool_call_id,
                "tool": intent.tool,
                "duration_ms": duration_ms,
                "result_summary": safe_result_summary,
            },
            actor={"type": "tool", "id": intent.tool},
        )
        return result

    async def _finalize_research(
        self,
        run: Run,
        subscription: Any,
        intent: StructuredResultIntent,
        observations: dict[str, dict[str, Any]],
    ) -> None:
        run = self.database.update_run(
            run.id, stage=RunStage.SYNTHESIZING
        )
        self._stage_event(run, RunStage.SYNTHESIZING)
        self._event(
            run,
            "model.completed",
            {
                "item_count": len(intent.items),
                "research_summary": intent.research_summary,
            },
            actor={"type": "model", "id": self.model.actor_id},
        )
        await self._pause()

        run = self.database.update_run(run.id, stage=RunStage.EVALUATING)
        self._stage_event(run, RunStage.EVALUATING)
        documents = observations.get("search_sources", {}).get("documents", [])
        allowed_source_ids = {document["source_id"] for document in documents}
        blocked_source_ids = {
            document["source_id"]
            for document in documents
            if document.get("safety_flags")
        }
        eval_result, drafts = self.eval_runner.evaluate_items(
            intent.items,
            allowed_source_ids=allowed_source_ids,
            blocked_source_ids=blocked_source_ids,
            documents=documents,
            claim_eval_enabled=self.claim_eval_enabled,
        )
        self._event(
            run,
            "eval.completed",
            eval_result.model_dump(),
            actor={"type": "eval", "id": "hard_gate_eval"},
        )
        if not eval_result.passed:
            self.database.update_run_document_outcomes(run.id, set())
            await self._fail(
                run,
                "EVAL_FAILED",
                _eval_failure_message(eval_result),
            )
            return

        if not drafts:
            self.database.update_run_document_outcomes(run.id, set())
            search_observation = observations.get("search_sources", {})
            empty_result = {
                "reason_code": "NO_QUALIFYING_INTEL",
                "message": (
                    "深挖已完成，但本次没有发现满足相关性与证据要求的新进展。"
                    if run.research_mode == "deep_dive"
                    else "扫描已完成，但本次没有发现满足相关性与证据要求的可靠结果。"
                ),
                "research_summary": intent.research_summary,
                "discovery_count": int(
                    search_observation.get("discovery_count", len(documents))
                    or 0
                ),
                "evidence_count": int(
                    search_observation.get("evidence_count", len(documents))
                    or 0
                ),
            }
            result = {
                "research_mode": run.research_mode,
                "story_id": run.story_id,
                "research_focus": run.research_focus,
                "research_question": run.research_question,
                "research_summary": intent.research_summary,
                "item_ids": [],
                "item_count": 0,
                "eval": eval_result.model_dump(),
                "delivery": {
                    "status": "not_needed",
                    "reason": "no_qualifying_intel",
                },
                "empty_result": empty_result,
            }
            run = self.database.update_run(
                run.id,
                status=RunStatus.COMPLETED,
                result=result,
            )
            self._event(
                run,
                "run.no_results",
                empty_result,
                actor={"type": "runtime", "id": "agent_runtime"},
            )
            self._event(
                run,
                "run.completed",
                {
                    "item_count": 0,
                    "delivery_status": "not_needed",
                    "outcome": "no_qualifying_intel",
                },
                actor={"type": "runtime", "id": "agent_runtime"},
            )
            return

        documents_by_source_id = {
            str(document.get("source_id")): document
            for document in documents
            if document.get("source_id")
        }
        enriched_drafts = []
        for draft in drafts:
            draft_documents = [
                document
                for source_id in draft.source_ids
                if (
                    document := documents_by_source_id.get(source_id)
                )
            ]
            evidence_chain_count = len(
                {
                    str(document.get("evidence_chain_id"))
                    for document in draft_documents
                    if document.get("evidence_chain_id")
                }
            )
            has_direct_source = any(
                document.get("source_type")
                in {"official", "policy", "research"}
                for document in draft_documents
            )
            confidence_cap = (
                0.55
                if evidence_chain_count == 0
                else (
                    0.82
                    if evidence_chain_count == 1 and has_direct_source
                    else (
                        0.72
                        if evidence_chain_count == 1
                        else 1.0
                    )
                )
            )
            adjusted_confidence = min(
                draft.confidence_score, confidence_cap
            )
            adjusted_level = (
                "high"
                if adjusted_confidence >= 0.85
                else (
                    "medium"
                    if adjusted_confidence >= 0.60
                    else "low"
                )
            )
            enriched_drafts.append(
                draft.model_copy(
                    update={
                        "sources": self.registry.sources_from_documents(
                            draft.source_ids,
                            documents,
                            draft.source_translations,
                        ),
                        "independent_evidence_count": evidence_chain_count,
                        "confidence_score": adjusted_confidence,
                        "confidence_level": adjusted_level,
                        "confidence_reason": (
                            f"{draft.confidence_reason} "
                            f"按 {evidence_chain_count} 条独立证据链校准；"
                            "媒体覆盖数不作为独立证据数。"
                        ),
                    }
                )
            )
        drafts = enriched_drafts
        events = self.database.save_intel_events(
            run.id,
            subscription.id,
            drafts,
            target_story_id=(
                run.story_id if run.research_mode == "deep_dive" else None
            ),
        )
        self.database.update_run_document_outcomes(
            run.id,
            {
                source_id
                for draft in drafts
                for source_id in draft.source_ids
            },
        )
        result = {
            "research_mode": run.research_mode,
            "story_id": run.story_id,
            "research_focus": run.research_focus,
            "research_question": run.research_question,
            "research_summary": intent.research_summary,
            "item_ids": [event.id for event in events],
            "item_count": len(events),
            "eval": eval_result.model_dump(),
            "delivery": {"status": "pending"},
        }
        run = self.database.update_run(
            run.id, stage=RunStage.DELIVERING, result=result
        )
        self._stage_event(run, RunStage.DELIVERING)

        delivery_args = {
            "channel": run.delivery_mode,
            "item_ids": result["item_ids"],
        }
        decision = self.policy.evaluate(run, "deliver_digest", delivery_args)
        if decision.requires_approval:
            approval = self.database.create_approval(
                run.id,
                "deliver_digest",
                {
                    "channel": run.delivery_mode,
                    "item_ids": result["item_ids"],
                    "item_count": len(events),
                    "preview_titles": [event.title for event in events],
                    "reason": "公开预览渠道超出 Web Inbox 的默认预授权范围",
                    "policy": decision.model_dump(),
                },
            )
            self.database.update_run(
                run.id, status=RunStatus.WAITING_APPROVAL, result=result
            )
            self._event(
                run,
                "approval.required",
                {
                    "approval_id": approval.id,
                    "tool": "deliver_digest",
                    "request": approval.request,
                },
                actor={"type": "approval", "id": "approval_gate"},
            )
            return
        if decision.is_denied:
            await self._fail(run, decision.reason_code, decision.message)
            return

        await self._execute_delivery(run, subscription, delivery_args, result)

    async def _execute_delivery(
        self,
        run: Run,
        subscription: Any,
        delivery_args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        tool_call_id = self.database.create_tool_call(
            run.id,
            "deliver_digest",
            delivery_args,
            "投递已经通过 Eval 的情报摘要。",
        )
        self.database.update_tool_call(
            tool_call_id,
            decision={"decision": "allow", "reason_code": "DELIVERY_AUTHORIZED"},
            status="running",
        )
        self._event(
            run,
            "tool.started",
            {"tool_call_id": tool_call_id, "tool": "deliver_digest"},
            actor={"type": "tool", "id": "deliver_digest"},
        )
        delivery, duration_ms = await self.registry.execute(
            run, subscription, "deliver_digest", delivery_args
        )
        self.database.update_tool_call(
            tool_call_id,
            status="completed",
            result=delivery,
            duration_ms=duration_ms,
        )
        result = {**result, "delivery": delivery}
        run = self.database.update_run(
            run.id,
            status=RunStatus.COMPLETED,
            result=result,
        )
        self._event(
            run,
            "delivery.completed",
            delivery,
            actor={"type": "delivery", "id": "delivery_manager"},
        )
        self._event(
            run,
            "run.completed",
            {
                "item_count": result["item_count"],
                "delivery_status": delivery["status"],
            },
            actor={"type": "runtime", "id": "agent_runtime"},
        )

    async def resolve_approval(
        self, approval_id: str, payload: ApprovalDecision
    ) -> Run:
        approval = self.database.get_approval(approval_id)
        if approval is None:
            raise KeyError("Approval not found")
        if approval.status != "pending":
            raise ValueError("Approval has already been resolved")
        run = self._require_run(approval.run_id)
        subscription = self.database.get_subscription(run.subscription_id)
        if subscription is None:
            raise RuntimeError("订阅不存在")

        approved = payload.decision == "approve"
        resolved = self.database.resolve_approval(
            approval_id,
            "approved" if approved else "rejected",
            payload.model_dump(),
        )
        self._event(
            run,
            "approval.resolved",
            {
                "approval_id": resolved.id,
                "decision": payload.decision,
                "reason": payload.reason,
            },
            actor={"type": "user", "id": "local_user"},
        )
        result = run.result or {}
        if approved:
            run = self.database.update_run(run.id, status=RunStatus.RUNNING)
            await self._execute_delivery(
                run,
                subscription,
                {
                    "channel": run.delivery_mode,
                    "item_ids": result.get("item_ids", []),
                },
                result,
            )
        else:
            result = {
                **result,
                "delivery": {
                    "status": "draft_only",
                    "reason": payload.reason or "用户拒绝公开投递",
                },
            }
            run = self.database.update_run(
                run.id, status=RunStatus.COMPLETED, result=result
            )
            self._event(
                run,
                "delivery.skipped",
                result["delivery"],
                actor={"type": "delivery", "id": "delivery_manager"},
            )
            self._event(
                run,
                "run.completed",
                {
                    "item_count": result.get("item_count", 0),
                    "delivery_status": "draft_only",
                },
                actor={"type": "runtime", "id": "agent_runtime"},
            )
        return self._require_run(run.id)

    async def cancel(self, run_id: str) -> Run:
        run = self._require_run(run_id)
        if run.status in TERMINAL_STATUSES:
            return run
        run = self.database.update_run(
            run_id, cancellation_requested=True
        )
        self._event(
            run,
            "run.cancel_requested",
            {},
            actor={"type": "user", "id": "local_user"},
        )
        if run.status == RunStatus.QUEUED and run_id not in self._active_run_ids:
            task = self._tasks.get(run_id)
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            run = self._require_run(run_id)
            if run.status not in TERMINAL_STATUSES:
                run = self.database.update_run(
                    run_id,
                    status=RunStatus.CANCELLED,
                    error={
                        "code": "USER_CANCELLED",
                        "message": "用户取消了 Run",
                    },
                )
                self._event(
                    run,
                    "run.cancelled",
                    {"reason": "user_requested"},
                    actor={"type": "runtime", "id": "agent_runtime"},
                )
        return run

    async def _degraded_final_decision(
        self,
        run: Run,
        subscription: Any,
        observations: dict[str, dict[str, Any]],
        error: ModelAdapterError,
    ) -> ModelDecision:
        fallback = MockResearchModelAdapter()
        local = await fallback.decide(
            run,
            subscription,
            observations,
            [],
        )
        intent = local.intent
        if isinstance(intent, StructuredResultIntent):
            intent = StructuredResultIntent(
                items=intent.items,
                research_summary=(
                    "远程模型最终生成暂时不可用，Harness 使用本地证据提取器降级完成。"
                    f"原始错误：{error.code}。{intent.research_summary}"
                ),
            )
        self._event(
            run,
            "model.degraded",
            {
                "from": self.model.actor_id,
                "to": "local:deterministic-evidence-synthesizer",
                "reason_code": error.code,
                "source_document_count": len(
                    observations.get("search_sources", {}).get("documents", [])
                ),
            },
            actor={"type": "runtime", "id": "degradation_policy"},
        )
        return ModelDecision(
            intent=intent,
            provider="local",
            model="deterministic-evidence-synthesizer",
        )

    async def _set_stage_for_tool(self, run: Run, tool: str) -> Run:
        target = {
            "list_configured_sources": RunStage.PLANNING,
            "search_sources": RunStage.COLLECTING,
            "query_intel_history": RunStage.VERIFYING,
        }.get(tool, run.stage)
        if target == run.stage:
            return run
        run = self.database.update_run(run.id, stage=target)
        self._stage_event(run, target)
        return run

    @staticmethod
    def _next_model_tools(
        observations: dict[str, dict[str, Any]]
    ) -> list[str]:
        if "list_configured_sources" not in observations:
            return ["list_configured_sources"]
        if "search_sources" not in observations:
            return ["search_sources"]
        if "query_intel_history" not in observations:
            return ["query_intel_history"]
        return []

    async def _cancel_if_requested(self, run: Run) -> bool:
        if not run.cancellation_requested:
            return False
        run = self.database.update_run(
            run.id,
            status=RunStatus.CANCELLED,
            error={"code": "USER_CANCELLED", "message": "用户取消了 Run"},
        )
        self._event(
            run,
            "run.cancelled",
            {"reason": "user_requested"},
            actor={"type": "runtime", "id": "agent_runtime"},
        )
        return True

    async def _fail(self, run: Run, code: str, message: str) -> None:
        run = self.database.update_run(
            run.id,
            status=RunStatus.FAILED,
            error={"code": code, "message": message},
        )
        self._event(
            run,
            "run.failed",
            {"error": {"code": code, "message": message}},
            actor={"type": "runtime", "id": "agent_runtime"},
        )

    def _stage_event(self, run: Run, stage: RunStage) -> None:
        self._event(
            run,
            "run.stage_changed",
            {"stage": stage.value},
            actor={"type": "runtime", "id": "agent_runtime"},
        )

    def _event(
        self,
        run: Run,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: dict[str, str],
    ) -> None:
        self.database.append_event(
            run.id,
            event_type,
            actor=actor,
            payload=payload,
        )

    def _require_run(self, run_id: str) -> Run:
        run = self.database.get_run(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        return run

    async def _pause(self) -> None:
        if self.step_delay_seconds > 0:
            await asyncio.sleep(self.step_delay_seconds)
