from __future__ import annotations

from typing import Any

from app.domain.models import PolicyDecision, Run, RunStage


class ToolPolicy:
    _stage_tools: dict[RunStage, set[str]] = {
        RunStage.PLANNING: {"list_configured_sources"},
        RunStage.COLLECTING: {"list_configured_sources", "search_sources"},
        RunStage.VERIFYING: {"search_sources", "query_intel_history"},
        RunStage.SYNTHESIZING: {"query_intel_history"},
        RunStage.DELIVERING: {"deliver_digest"},
    }

    def visible_tools(self, run: Run) -> list[str]:
        return sorted(self._stage_tools.get(run.stage, set()))

    def evaluate(self, run: Run, tool: str, args: dict[str, Any]) -> PolicyDecision:
        if tool not in self._stage_tools.get(run.stage, set()):
            return PolicyDecision(
                decision="deny",
                reason_code="TOOL_NOT_VISIBLE_IN_STAGE",
                message=f"{tool} 在 {run.stage.value} 阶段不可见",
            )

        if run.usage.tool_calls >= run.budget.max_tool_calls:
            return PolicyDecision(
                decision="deny",
                reason_code="TOOL_BUDGET_EXHAUSTED",
                message="本次 Run 的工具调用预算已耗尽",
            )

        if tool == "search_sources":
            query = str(args.get("query", "")).strip()
            if not query or len(query) > 500:
                return PolicyDecision(
                    decision="deny",
                    reason_code="INVALID_SEARCH_QUERY",
                    message="搜索查询为空或超出长度限制",
                )
            if run.usage.search_calls >= run.budget.max_search_calls:
                return PolicyDecision(
                    decision="deny",
                    reason_code="SEARCH_BUDGET_EXHAUSTED",
                    message="本次 Run 的搜索预算已耗尽",
                )

        if tool == "deliver_digest":
            channel = args.get("channel")
            if channel == "public_preview":
                return PolicyDecision(
                    decision="require_approval",
                    reason_code="PUBLIC_DELIVERY_REQUIRES_APPROVAL",
                    message="发送到公开预览渠道前需要用户确认",
                    constraints={"max_uses": 1},
                )
            if channel != "web_inbox":
                return PolicyDecision(
                    decision="deny",
                    reason_code="DELIVERY_CHANNEL_NOT_ALLOWED",
                    message="当前版本只允许 Web Inbox 或公开预览草稿",
                )

        return PolicyDecision(
            decision="allow",
            reason_code="WITHIN_RUN_SCOPE",
            message="动作在当前 Run 的工具、阶段和预算范围内",
            constraints={"timeout_seconds": 15},
        )
