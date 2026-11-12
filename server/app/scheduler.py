from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.focus import build_monitor_goal
from app.domain.models import StoryWatch, Subscription, utc_now
from app.harness.runtime import AgentRuntime
from app.persistence.database import Database
from app.story_tracking import StoryWatchRunActive, trigger_story_watch


SCHEDULE_PATTERN = re.compile(
    r"^(?P<kind>每天|工作日)\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})$"
)


class RunScheduler:
    def __init__(
        self,
        database: Database,
        runtime: AgentRuntime,
        *,
        enabled: bool = False,
        poll_seconds: float = 30,
        catch_up_hours: float = 6,
        timezone_name: str = "Asia/Shanghai",
    ):
        self.database = database
        self.runtime = runtime
        self.enabled = enabled
        self.poll_seconds = max(1, poll_seconds)
        self.catch_up_hours = max(0, catch_up_hours)
        self.timezone = ZoneInfo(timezone_name)
        self.timezone_name = timezone_name
        self._task: asyncio.Task[None] | None = None
        self._last_tick_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "timezone": self.timezone_name,
            "poll_seconds": self.poll_seconds,
            "catch_up_hours": self.catch_up_hours,
            "last_tick_at": (
                self._last_tick_at.isoformat() if self._last_tick_at else None
            ),
            "last_error": self._last_error,
        }

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def tick(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        local_now = self._localize(now or utc_now())
        self._last_tick_at = local_now
        outcomes: list[dict[str, Any]] = []
        for subscription in self.database.list_subscriptions():
            outcome = self._evaluate_subscription(
                subscription,
                now=local_now,
                force=force,
            )
            outcomes.append(outcome)
        watch_outcomes = [
            self._evaluate_story_watch(watch, now=local_now)
            for watch in self.database.list_due_story_watches(local_now)
        ]
        triggered = [outcome for outcome in outcomes if outcome["triggered"]]
        triggered_watches = [
            outcome for outcome in watch_outcomes if outcome["triggered"]
        ]
        return {
            "timestamp": local_now.isoformat(),
            "force": force,
            "triggered_count": len(triggered) + len(triggered_watches),
            "runs": triggered,
            "subscriptions": outcomes,
            "story_watches": watch_outcomes,
        }

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            await asyncio.sleep(self.poll_seconds)

    def _evaluate_subscription(
        self,
        subscription: Subscription,
        *,
        now: datetime,
        force: bool,
    ) -> dict[str, Any]:
        base = {
            "subscription_id": subscription.id,
            "subscription_name": subscription.name,
            "schedule_label": subscription.schedule_label,
            "triggered": False,
        }
        if not subscription.enabled:
            return {**base, "reason": "subscription_disabled"}
        parsed = self._parse_schedule(subscription.schedule_label)
        if parsed is None:
            return {**base, "reason": "unsupported_schedule_label"}
        kind, hour, minute = parsed
        if kind == "工作日" and now.weekday() >= 5 and not force:
            return {**base, "reason": "not_a_workday"}

        scheduled_at = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        lag = now - scheduled_at
        if not force and (
            lag < timedelta(0)
            or lag > timedelta(hours=self.catch_up_hours)
        ):
            return {**base, "reason": "outside_due_window"}

        slot = f"{scheduled_at.date().isoformat()}:{hour:02d}{minute:02d}"
        idempotency_key = f"schedule:{subscription.slug}:{slot}"
        run = self.database.create_run(
            subscription_id=subscription.id,
            trigger="schedule",
            goal=build_monitor_goal(
                name=subscription.name,
                topic=subscription.topic,
                keywords=subscription.include_keywords,
                slug=subscription.slug,
                lookback_hours=subscription.lookback_hours,
                scheduled=True,
            ),
            delivery_mode="web_inbox",
            idempotency_key=idempotency_key,
        )
        if self.database.list_events(run.id):
            return {
                **base,
                "reason": "slot_already_triggered",
                "run_id": run.id,
                "idempotency_key": idempotency_key,
            }
        self.database.append_event(
            run.id,
            "run.created",
            actor={"type": "scheduler", "id": "run_scheduler"},
            payload={
                "subscription_id": subscription.id,
                "subscription_name": subscription.name,
                "schedule_label": subscription.schedule_label,
                "scheduled_at": scheduled_at.isoformat(),
                "idempotency_key": idempotency_key,
            },
        )
        self.runtime.start(run.id)
        return {
            **base,
            "triggered": True,
            "reason": "scheduled_slot_due" if not force else "forced_tick",
            "run_id": run.id,
            "idempotency_key": idempotency_key,
        }

    def _evaluate_story_watch(
        self,
        watch: StoryWatch,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        base = {
            "story_watch_id": watch.id,
            "story_id": watch.story_id,
            "subscription_id": watch.subscription_id,
            "cadence": watch.cadence,
            "triggered": False,
        }
        due_slot = (
            watch.next_check_at.isoformat()
            if watch.next_check_at
            else now.isoformat()
        )
        idempotency_key = f"story-watch:{watch.id}:{due_slot}"
        try:
            run, triggered = trigger_story_watch(
                self.database,
                self.runtime,
                watch,
                trigger="schedule",
                actor={"type": "scheduler", "id": "story_watch_scheduler"},
                checked_at=now,
                idempotency_key=idempotency_key,
            )
        except StoryWatchRunActive as exc:
            self.database.mark_story_watch_triggered(
                watch.id,
                exc.run.id,
                checked_at=now,
            )
            return {
                **base,
                "reason": "story_research_already_running",
                "run_id": exc.run.id,
                "idempotency_key": idempotency_key,
            }
        except KeyError:
            return {**base, "reason": "story_not_found"}
        return {
            **base,
            "triggered": triggered,
            "reason": "story_watch_due" if triggered else "slot_already_triggered",
            "run_id": run.id,
            "idempotency_key": idempotency_key,
        }

    def _localize(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self.timezone)
        return value.astimezone(self.timezone)

    @staticmethod
    def _parse_schedule(label: str) -> tuple[str, int, int] | None:
        match = SCHEDULE_PATTERN.fullmatch(label.strip())
        if match is None:
            return None
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if hour > 23 or minute > 59:
            return None
        return match.group("kind"), hour, minute
