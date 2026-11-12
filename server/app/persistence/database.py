from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.domain.focus import (
    infer_focus_domain,
    infer_focus_type,
    normalize_custom_focus_topic,
    resolve_focus_domain,
    resolve_focus_type,
)
from app.domain.models import (
    Approval,
    AlertMatch,
    AlertRule,
    AlertRuleCreate,
    CustomSource,
    CustomSourceCreate,
    Digest,
    FocusType,
    IntelEvent,
    IntelEventDraft,
    IntelFeedback,
    IntelFeedbackCreate,
    Run,
    RunBudget,
    RunEvent,
    RunStage,
    RunStatus,
    RunUsage,
    SourceDocument,
    SourceRuntimeState,
    Story,
    StoryDocument,
    StoryRelation,
    StoryWatch,
    StoryWatchUpsert,
    Subscription,
    SubscriptionCreate,
    SubscriptionPreferences,
    SubscriptionPreferencesUpdate,
    new_id,
    utc_now,
)
from app.domain.story_clustering import (
    StoryFingerprint,
    classify_story_relation,
    match_story,
)
from app.domain.story_lifecycle import find_story_supersessions

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "spm",
}

STORY_WATCH_INTERVALS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").casefold()
    port = parsed.port
    if port and not (
        (parsed.scheme.casefold() == "https" and port == 443)
        or (parsed.scheme.casefold() == "http" and port == 80)
    ):
        hostname = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in TRACKING_QUERY_KEYS
        ],
        doseq=True,
    )
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            hostname,
            path,
            query,
            "",
        )
    )


def _content_hash(content: str) -> str:
    normalized = " ".join(content.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _event_dedupe_key(
    subscription_id: str,
    source_ids: list[str],
    sources: list[Any],
) -> str:
    source_urls: set[str] = set()
    for source in sources:
        url = (
            source.get("url")
            if isinstance(source, dict)
            else getattr(source, "url", None)
        )
        if isinstance(url, str) and url:
            source_urls.add(_canonical_url(url))
    identifiers = sorted(source_urls or set(source_ids))
    material = "\n".join([subscription_id, *identifiers])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _source_urls(sources: list[Any]) -> frozenset[str]:
    urls: set[str] = set()
    for source in sources:
        if isinstance(source, dict):
            candidates = (source.get("canonical_url"), source.get("url"))
        else:
            candidates = (
                getattr(source, "canonical_url", None),
                getattr(source, "url", None),
            )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                urls.add(_canonical_url(candidate))
    return frozenset(urls)


def _source_content_origins(sources: list[Any]) -> frozenset[str]:
    origins: set[str] = set()
    for source in sources:
        origin = (
            source.get("content_origin")
            if isinstance(source, dict)
            else getattr(source, "content_origin", None)
        )
        if isinstance(origin, str) and origin:
            origins.add(origin)
    return frozenset(origins)


def _story_fingerprint(
    *,
    title: str,
    category: str,
    tags: list[str],
    event_time: datetime | str,
    source_ids: list[str],
    sources: list[Any],
) -> StoryFingerprint:
    parsed_time = (
        datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        if isinstance(event_time, str)
        else event_time
    )
    if parsed_time.tzinfo is None:
        parsed_time = parsed_time.replace(tzinfo=timezone.utc)
    return StoryFingerprint(
        title=title,
        category=category,
        tags=frozenset(tags),
        event_time=parsed_time,
        source_ids=frozenset(source_ids),
        source_urls=_source_urls(sources),
        content_origins=_source_content_origins(sources),
    )


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS data_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                include_keywords TEXT NOT NULL,
                exclude_keywords TEXT NOT NULL,
                languages TEXT NOT NULL,
                lookback_hours INTEGER NOT NULL,
                max_items INTEGER NOT NULL,
                minimum_importance REAL NOT NULL,
                schedule_label TEXT NOT NULL,
                accent TEXT NOT NULL,
                focus_type TEXT NOT NULL DEFAULT 'industry',
                focus_domain TEXT NOT NULL DEFAULT 'general',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                trigger TEXT NOT NULL,
                goal TEXT NOT NULL,
                research_mode TEXT NOT NULL DEFAULT 'monitor',
                story_id TEXT,
                research_focus TEXT,
                research_question TEXT,
                delivery_mode TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                budget TEXT NOT NULL,
                usage TEXT NOT NULL,
                cancellation_requested INTEGER NOT NULL DEFAULT 0,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS run_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload TEXT NOT NULL,
                visibility TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(run_id, seq),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tool_calls (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                args TEXT NOT NULL,
                reason TEXT NOT NULL,
                decision TEXT,
                status TEXT NOT NULL,
                result TEXT,
                error TEXT,
                duration_ms INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS intel_events (
                id TEXT PRIMARY KEY,
                story_id TEXT,
                run_id TEXT NOT NULL,
                subscription_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                category TEXT NOT NULL,
                tags TEXT NOT NULL,
                event_time TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                importance_score REAL NOT NULL,
                importance_reason TEXT NOT NULL,
                confidence_level TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                confidence_reason TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                facts TEXT NOT NULL,
                inferences TEXT NOT NULL,
                source_ids TEXT NOT NULL,
                sources TEXT NOT NULL DEFAULT '[]',
                dedupe_key TEXT,
                change_summary TEXT,
                independent_evidence_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_documents (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                latest_url TEXT NOT NULL,
                title TEXT NOT NULL,
                publisher TEXT NOT NULL,
                source_type TEXT NOT NULL,
                published_at TEXT NOT NULL,
                content_excerpt TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                content_origin TEXT NOT NULL,
                author TEXT,
                image_url TEXT,
                word_count INTEGER NOT NULL DEFAULT 0,
                reliability REAL NOT NULL DEFAULT 0.5,
                safety_flags TEXT NOT NULL DEFAULT '[]',
                configured_source_id TEXT,
                query_template_id TEXT,
                query_focus_tier TEXT NOT NULL DEFAULT 'core',
                retrieval_channel TEXT,
                source_group TEXT,
                ranking_score REAL,
                ranking_reasons TEXT NOT NULL DEFAULT '[]',
                focus_tier TEXT NOT NULL DEFAULT 'unmatched',
                focus_relation_score REAL NOT NULL DEFAULT 0,
                fetch_status TEXT,
                extraction_status TEXT,
                duplicate_of_document_id TEXT,
                relevance_score REAL,
                keyword_match_score REAL,
                entity_match_score REAL,
                semantic_match_score REAL,
                source_prior_score REAL,
                user_preference_score REAL,
                novelty_score REAL,
                novelty_components TEXT NOT NULL DEFAULT '{}',
                event_elements TEXT NOT NULL DEFAULT '{}',
                cluster_id TEXT,
                cluster_relation TEXT,
                evidence_chain_id TEXT,
                evidence_relation_type TEXT,
                independence_score REAL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_run_id TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(subscription_id, canonical_url),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id),
                FOREIGN KEY(last_run_id) REFERENCES runs(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_runtime_states (
                subscription_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                etag TEXT,
                last_modified TEXT,
                last_success_at TEXT,
                last_failure_at TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_new_document_at TEXT,
                request_count INTEGER NOT NULL DEFAULT 0,
                new_document_count INTEGER NOT NULL DEFAULT 0,
                selected_document_count INTEGER NOT NULL DEFAULT 0,
                fulltext_success_count INTEGER NOT NULL DEFAULT 0,
                average_duration_ms REAL NOT NULL DEFAULT 0,
                health_status TEXT NOT NULL DEFAULT 'healthy',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(subscription_id, source_key),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS stories (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                canonical_title TEXT NOT NULL,
                primary_subjects TEXT NOT NULL DEFAULT '[]',
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                first_event_at TEXT NOT NULL,
                latest_event_at TEXT NOT NULL,
                current_intel_event_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id),
                FOREIGN KEY(current_intel_event_id) REFERENCES intel_events(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS story_relations (
                id TEXT PRIMARY KEY,
                from_story_id TEXT NOT NULL,
                to_story_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                reason TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(from_story_id, to_story_id, relation),
                FOREIGN KEY(from_story_id) REFERENCES stories(id),
                FOREIGN KEY(to_story_id) REFERENCES stories(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS story_documents (
                story_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                evidence_chain_id TEXT NOT NULL,
                attributed_source TEXT,
                is_primary INTEGER NOT NULL DEFAULT 0,
                independence_score REAL NOT NULL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                PRIMARY KEY(story_id, document_id),
                FOREIGN KEY(story_id) REFERENCES stories(id),
                FOREIGN KEY(document_id) REFERENCES source_documents(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS story_watches (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL UNIQUE,
                subscription_id TEXT NOT NULL,
                research_focus TEXT NOT NULL DEFAULT 'latest',
                question TEXT NOT NULL,
                cadence TEXT NOT NULL DEFAULT 'manual',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_id TEXT,
                last_checked_at TEXT,
                next_check_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(story_id) REFERENCES stories(id),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id),
                FOREIGN KEY(last_run_id) REFERENCES runs(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS intel_feedback (
                id TEXT PRIMARY KEY,
                intel_event_id TEXT NOT NULL,
                subscription_id TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                reason_code TEXT,
                note TEXT,
                target TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(intel_event_id, feedback_type, target),
                FOREIGN KEY(intel_event_id) REFERENCES intel_events(id),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS subscription_preferences (
                subscription_id TEXT PRIMARY KEY,
                category_weights TEXT NOT NULL DEFAULT '{}',
                entity_weights TEXT NOT NULL DEFAULT '{}',
                source_weights TEXT NOT NULL DEFAULT '{}',
                followed_entities TEXT NOT NULL DEFAULT '[]',
                context_entities TEXT NOT NULL DEFAULT '[]',
                muted_entities TEXT NOT NULL DEFAULT '[]',
                muted_sources TEXT NOT NULL DEFAULT '[]',
                minimum_importance REAL NOT NULL DEFAULT 0,
                alert_importance_threshold REAL NOT NULL DEFAULT 8,
                digest_frequency TEXT NOT NULL DEFAULT 'weekly',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_rules (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                name TEXT NOT NULL,
                entities TEXT NOT NULL DEFAULT '[]',
                event_types TEXT NOT NULL DEFAULT '[]',
                minimum_importance REAL NOT NULL DEFAULT 8,
                minimum_confidence REAL NOT NULL DEFAULT 0.7,
                require_official INTEGER NOT NULL DEFAULT 0,
                minimum_evidence_chains INTEGER NOT NULL DEFAULT 1,
                frequency TEXT NOT NULL DEFAULT 'instant',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alert_matches (
                alert_id TEXT NOT NULL,
                intel_event_id TEXT NOT NULL,
                matched_at TEXT NOT NULL,
                PRIMARY KEY(alert_id, intel_event_id),
                FOREIGN KEY(alert_id) REFERENCES alert_rules(id),
                FOREIGN KEY(intel_event_id) REFERENCES intel_events(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS digests (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                period TEXT NOT NULL,
                period_key TEXT NOT NULL,
                title TEXT NOT NULL,
                content_markdown TEXT NOT NULL,
                intel_event_ids TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                UNIQUE(subscription_id, period, period_key),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS run_documents (
                run_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'discovered',
                discovered_at TEXT NOT NULL,
                PRIMARY KEY(run_id, document_id),
                FOREIGN KEY(run_id) REFERENCES runs(id),
                FOREIGN KEY(document_id) REFERENCES source_documents(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                request TEXT NOT NULL,
                decision TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS custom_sources (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                resolved_url TEXT NOT NULL,
                collection_mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(subscription_id, url),
                FOREIGN KEY(subscription_id) REFERENCES subscriptions(id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS runs_created_idx ON runs(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS events_run_seq_idx ON run_events(run_id, seq)",
            "CREATE INDEX IF NOT EXISTS intel_subscription_time_idx ON intel_events(subscription_id, event_time DESC)",
            "CREATE INDEX IF NOT EXISTS source_documents_subscription_time_idx ON source_documents(subscription_id, published_at DESC)",
            "CREATE INDEX IF NOT EXISTS run_documents_run_idx ON run_documents(run_id, outcome)",
            "CREATE INDEX IF NOT EXISTS approvals_status_idx ON approvals(status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS custom_sources_subscription_idx ON custom_sources(subscription_id, status)",
            "CREATE INDEX IF NOT EXISTS source_runtime_health_idx ON source_runtime_states(subscription_id, health_status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS stories_subscription_time_idx ON stories(subscription_id, latest_event_at DESC)",
            "CREATE INDEX IF NOT EXISTS story_relations_from_idx ON story_relations(from_story_id, relation)",
            "CREATE INDEX IF NOT EXISTS story_documents_story_idx ON story_documents(story_id, evidence_chain_id)",
            "CREATE INDEX IF NOT EXISTS story_watches_due_idx ON story_watches(enabled, cadence, next_check_at)",
            "CREATE INDEX IF NOT EXISTS story_watches_subscription_idx ON story_watches(subscription_id, enabled, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS intel_feedback_event_idx ON intel_feedback(intel_event_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS alert_rules_subscription_idx ON alert_rules(subscription_id, enabled)",
            "CREATE INDEX IF NOT EXISTS digests_subscription_idx ON digests(subscription_id, period, period_key DESC)",
        ]
        with self.connect() as connection:
            for statement in statements:
                connection.execute(statement)
            subscription_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(subscriptions)"
                ).fetchall()
            }
            if "focus_type" not in subscription_columns:
                connection.execute(
                    "ALTER TABLE subscriptions ADD COLUMN "
                    "focus_type TEXT NOT NULL DEFAULT 'industry'"
                )
                legacy_custom_rows = connection.execute(
                    """
                    SELECT id, name, include_keywords
                    FROM subscriptions
                    WHERE slug LIKE 'custom-%'
                    """
                ).fetchall()
                for row in legacy_custom_rows:
                    focus_type = infer_focus_type(
                        row["name"],
                        _json_load(row["include_keywords"], []),
                    )
                    connection.execute(
                        "UPDATE subscriptions SET focus_type = ? WHERE id = ?",
                        (focus_type.value, row["id"]),
                    )
            entertainment_migration = (
                "2026-08-01-custom-entertainment-focus"
            )
            migration_applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE name = ?",
                (entertainment_migration,),
            ).fetchone()
            if migration_applied is None:
                legacy_industry_rows = connection.execute(
                    """
                    SELECT id, name, include_keywords
                    FROM subscriptions
                    WHERE slug LIKE 'custom-%' AND focus_type = 'industry'
                    """
                ).fetchall()
                for row in legacy_industry_rows:
                    focus_type = infer_focus_type(
                        row["name"],
                        _json_load(row["include_keywords"], []),
                    )
                    if focus_type.value == "entertainment":
                        connection.execute(
                            "UPDATE subscriptions SET focus_type = ? "
                            "WHERE id = ?",
                            (focus_type.value, row["id"]),
                        )
                connection.execute(
                    "INSERT INTO data_migrations (name, applied_at) "
                    "VALUES (?, ?)",
                    (entertainment_migration, utc_now().isoformat()),
                )
            product_migration = "2026-08-04-custom-product-focus"
            migration_applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE name = ?",
                (product_migration,),
            ).fetchone()
            if migration_applied is None:
                legacy_product_rows = connection.execute(
                    """
                    SELECT id, name, include_keywords
                    FROM subscriptions
                    WHERE slug LIKE 'custom-%' AND focus_type = 'industry'
                    """
                ).fetchall()
                for row in legacy_product_rows:
                    focus_type = infer_focus_type(
                        row["name"],
                        _json_load(row["include_keywords"], []),
                    )
                    if focus_type == FocusType.PRODUCT:
                        connection.execute(
                            "UPDATE subscriptions SET focus_type = ?, "
                            "updated_at = ? WHERE id = ?",
                            (
                                focus_type.value,
                                utc_now().isoformat(),
                                row["id"],
                            ),
                        )
                connection.execute(
                    "INSERT INTO data_migrations (name, applied_at) "
                    "VALUES (?, ?)",
                    (product_migration, utc_now().isoformat()),
                )
            entity_profile_migration = "2026-08-04-custom-entity-profile"
            migration_applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE name = ?",
                (entity_profile_migration,),
            ).fetchone()
            if migration_applied is None:
                custom_focus_rows = connection.execute(
                    """
                    SELECT id, name, include_keywords, focus_type
                    FROM subscriptions
                    WHERE slug LIKE 'custom-%'
                    """
                ).fetchall()
                for row in custom_focus_rows:
                    inferred = infer_focus_type(
                        row["name"],
                        _json_load(row["include_keywords"], []),
                    )
                    if inferred in {
                        FocusType.PERSON,
                        FocusType.PRODUCT,
                        FocusType.TEAM,
                    } and inferred.value != row["focus_type"]:
                        connection.execute(
                            "UPDATE subscriptions SET focus_type = ?, "
                            "updated_at = ? WHERE id = ?",
                            (
                                inferred.value,
                                utc_now().isoformat(),
                                row["id"],
                            ),
                        )
                connection.execute(
                    "INSERT INTO data_migrations (name, applied_at) "
                    "VALUES (?, ?)",
                    (entity_profile_migration, utc_now().isoformat()),
                )
            subscription_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(subscriptions)"
                ).fetchall()
            }
            if "focus_domain" not in subscription_columns:
                connection.execute(
                    "ALTER TABLE subscriptions ADD COLUMN "
                    "focus_domain TEXT NOT NULL DEFAULT 'general'"
                )
            domain_migration = "2026-08-04-focus-domain"
            migration_applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE name = ?",
                (domain_migration,),
            ).fetchone()
            if migration_applied is None:
                focus_rows = connection.execute(
                    """
                    SELECT id, name, include_keywords, focus_type
                    FROM subscriptions
                    """
                ).fetchall()
                for row in focus_rows:
                    domain = infer_focus_domain(
                        row["name"],
                        _json_load(row["include_keywords"], []),
                        FocusType(row["focus_type"]),
                    )
                    connection.execute(
                        "UPDATE subscriptions SET focus_domain = ? WHERE id = ?",
                        (domain.value, row["id"]),
                    )
                connection.execute(
                    "INSERT INTO data_migrations (name, applied_at) "
                    "VALUES (?, ?)",
                    (domain_migration, utc_now().isoformat()),
                )
            content_goal_migration = "2026-08-02-custom-content-goals"
            migration_applied = connection.execute(
                "SELECT 1 FROM data_migrations WHERE name = ?",
                (content_goal_migration,),
            ).fetchone()
            if migration_applied is None:
                custom_rows = connection.execute(
                    """
                    SELECT id, name, slug, topic, include_keywords
                    FROM subscriptions
                    WHERE slug LIKE 'custom-%'
                    """
                ).fetchall()
                for row in custom_rows:
                    topic = normalize_custom_focus_topic(
                        name=row["name"],
                        topic=row["topic"],
                        keywords=_json_load(row["include_keywords"], []),
                        slug=row["slug"],
                    )
                    if topic != row["topic"]:
                        connection.execute(
                            "UPDATE subscriptions SET topic = ?, updated_at = ? "
                            "WHERE id = ?",
                            (topic, utc_now().isoformat(), row["id"]),
                        )
                connection.execute(
                    "INSERT INTO data_migrations (name, applied_at) "
                    "VALUES (?, ?)",
                    (content_goal_migration, utc_now().isoformat()),
                )
            run_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(runs)"
                ).fetchall()
            }
            if "research_mode" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN "
                    "research_mode TEXT NOT NULL DEFAULT 'monitor'"
                )
            if "story_id" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN story_id TEXT"
                )
            if "research_focus" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN research_focus TEXT"
                )
            if "research_question" not in run_columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN research_question TEXT"
                )
            intel_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(intel_events)"
                ).fetchall()
            }
            if "sources" not in intel_columns:
                connection.execute(
                    "ALTER TABLE intel_events "
                    "ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'"
                )
            if "dedupe_key" not in intel_columns:
                connection.execute(
                    "ALTER TABLE intel_events ADD COLUMN dedupe_key TEXT"
                )
            if "story_id" not in intel_columns:
                connection.execute(
                    "ALTER TABLE intel_events ADD COLUMN story_id TEXT"
                )
            if "change_summary" not in intel_columns:
                connection.execute(
                    "ALTER TABLE intel_events ADD COLUMN change_summary TEXT"
                )
            if "independent_evidence_count" not in intel_columns:
                connection.execute(
                    "ALTER TABLE intel_events ADD COLUMN "
                    "independent_evidence_count INTEGER NOT NULL DEFAULT 0"
                )
            source_document_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(source_documents)"
                ).fetchall()
            }
            source_document_additions = {
                "configured_source_id": "TEXT",
                "query_template_id": "TEXT",
                "query_focus_tier": "TEXT NOT NULL DEFAULT 'core'",
                "retrieval_channel": "TEXT",
                "source_group": "TEXT",
                "ranking_score": "REAL",
                "ranking_reasons": "TEXT NOT NULL DEFAULT '[]'",
                "focus_tier": "TEXT NOT NULL DEFAULT 'unmatched'",
                "focus_relation_score": "REAL NOT NULL DEFAULT 0",
                "fetch_status": "TEXT",
                "extraction_status": "TEXT",
                "duplicate_of_document_id": "TEXT",
                "relevance_score": "REAL",
                "keyword_match_score": "REAL",
                "entity_match_score": "REAL",
                "semantic_match_score": "REAL",
                "source_prior_score": "REAL",
                "user_preference_score": "REAL",
                "novelty_score": "REAL",
                "novelty_components": "TEXT NOT NULL DEFAULT '{}'",
                "event_elements": "TEXT NOT NULL DEFAULT '{}'",
                "cluster_id": "TEXT",
                "cluster_relation": "TEXT",
                "evidence_chain_id": "TEXT",
                "evidence_relation_type": "TEXT",
                "independence_score": "REAL",
            }
            for column, declaration in source_document_additions.items():
                if column not in source_document_columns:
                    connection.execute(
                        f"ALTER TABLE source_documents "
                        f"ADD COLUMN {column} {declaration}"
                    )
            preference_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(subscription_preferences)"
                ).fetchall()
            }
            if "context_entities" not in preference_columns:
                connection.execute(
                    "ALTER TABLE subscription_preferences ADD COLUMN "
                    "context_entities TEXT NOT NULL DEFAULT '[]'"
                )
            rows = connection.execute(
                """
                SELECT id, subscription_id, source_ids, sources
                FROM intel_events
                WHERE dedupe_key IS NULL OR dedupe_key = ''
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE intel_events SET dedupe_key = ? WHERE id = ?",
                    (
                        _event_dedupe_key(
                            row["subscription_id"],
                            _json_load(row["source_ids"], []),
                            _json_load(row["sources"], []),
                        ),
                        row["id"],
                    ),
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS intel_subscription_dedupe_idx
                ON intel_events(subscription_id, dedupe_key)
                """
            )
            self._backfill_story_ids(connection)
            self._backfill_stories(connection)
            self._refresh_story_lifecycle(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS intel_subscription_story_idx
                ON intel_events(subscription_id, story_id)
                """
            )
            historical_searches = connection.execute(
                """
                SELECT tc.run_id, r.subscription_id, r.status,
                       tc.result, tc.created_at
                FROM tool_calls AS tc
                JOIN runs AS r ON r.id = tc.run_id
                WHERE tc.tool = 'search_sources'
                  AND tc.status = 'completed'
                  AND tc.result IS NOT NULL
                ORDER BY tc.created_at
                """
            ).fetchall()
            selected_rows = connection.execute(
                "SELECT run_id, source_ids FROM intel_events"
            ).fetchall()
        selected_by_run: dict[str, set[str]] = {}
        for row in selected_rows:
            selected_by_run.setdefault(row["run_id"], set()).update(
                _json_load(row["source_ids"], [])
            )
        for row in historical_searches:
            result = _json_load(row["result"], {})
            documents = result.get("documents", [])
            if not isinstance(documents, list) or not documents:
                continue
            self.save_source_documents(
                row["run_id"],
                row["subscription_id"],
                [
                    document
                    for document in documents
                    if isinstance(document, dict)
                ],
                seen_at=row["created_at"],
            )
            if row["status"] == RunStatus.COMPLETED.value:
                self.update_run_document_outcomes(
                    row["run_id"],
                    selected_by_run.get(row["run_id"], set()),
                )

    @staticmethod
    def _row_story_fingerprint(row: sqlite3.Row) -> StoryFingerprint:
        return _story_fingerprint(
            title=row["title"],
            category=row["category"],
            tags=_json_load(row["tags"], []),
            event_time=row["event_time"],
            source_ids=_json_load(row["source_ids"], []),
            sources=_json_load(row["sources"], []),
        )

    def _backfill_story_ids(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT id, story_id, subscription_id, title, category, tags,
                   event_time, source_ids, sources
            FROM intel_events
            ORDER BY subscription_id, event_time
            """
        ).fetchall()
        candidates: dict[
            str,
            list[tuple[str, StoryFingerprint]],
        ] = {}
        for row in rows:
            subscription_candidates = candidates.setdefault(
                row["subscription_id"],
                [],
            )
            fingerprint = self._row_story_fingerprint(row)
            story_id = row["story_id"]
            if not story_id:
                matches = [
                    (match, candidate_story_id)
                    for candidate_story_id, candidate in subscription_candidates
                    if (match := match_story(fingerprint, candidate)) is not None
                ]
                story_id = (
                    max(matches, key=lambda item: item[0].score)[1]
                    if matches
                    else new_id("story")
                )
                connection.execute(
                    "UPDATE intel_events SET story_id = ? WHERE id = ?",
                    (story_id, row["id"]),
                )
            subscription_candidates.append((story_id, fingerprint))

    def _backfill_stories(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT id, story_id, subscription_id, title, category, tags,
                   event_time, created_at
            FROM intel_events
            WHERE story_id IS NOT NULL
            ORDER BY event_time, created_at
            """
        ).fetchall()
        for row in rows:
            tags = [
                str(tag)
                for tag in _json_load(row["tags"], [])
                if str(tag).strip()
            ]
            fingerprint = hashlib.sha256(
                "\n".join(
                    [
                        row["subscription_id"],
                        row["category"],
                        row["title"].casefold(),
                        *sorted(tag.casefold() for tag in tags),
                    ]
                ).encode("utf-8")
            ).hexdigest()
            existing = connection.execute(
                "SELECT latest_event_at FROM stories WHERE id = ?",
                (row["story_id"],),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO stories (
                        id, subscription_id, canonical_title,
                        primary_subjects, event_type, status,
                        first_event_at, latest_event_at,
                        current_intel_event_id, fingerprint,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["story_id"],
                        row["subscription_id"],
                        row["title"],
                        _json_dump(tags[:8]),
                        row["category"],
                        row["event_time"],
                        row["event_time"],
                        row["id"],
                        fingerprint,
                        row["created_at"],
                        row["created_at"],
                    ),
                )
            elif row["event_time"] >= existing["latest_event_at"]:
                connection.execute(
                    """
                    UPDATE stories
                    SET canonical_title = ?, primary_subjects = ?,
                        event_type = ?, latest_event_at = ?,
                        current_intel_event_id = ?, fingerprint = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        row["title"],
                        _json_dump(tags[:8]),
                        row["category"],
                        row["event_time"],
                        row["id"],
                        fingerprint,
                        row["created_at"],
                        row["story_id"],
                    ),
                )

    def _refresh_story_lifecycle(
        self,
        connection: sqlite3.Connection,
        subscription_id: str | None = None,
    ) -> None:
        subscription_query = "SELECT id, name, focus_type FROM subscriptions"
        values: tuple[str, ...] = ()
        if subscription_id:
            subscription_query += " WHERE id = ?"
            values = (subscription_id,)
        subscriptions = connection.execute(
            subscription_query,
            values,
        ).fetchall()
        subject_focus_types = {
            FocusType.COMPANY.value,
            FocusType.PERSON.value,
            FocusType.PRODUCT.value,
            FocusType.TEAM.value,
            FocusType.SPORTS.value,
            FocusType.EVENT.value,
        }
        now = utc_now().isoformat()
        for subscription in subscriptions:
            rows = connection.execute(
                """
                SELECT ie.*
                FROM stories AS story
                JOIN intel_events AS ie
                  ON ie.id = story.current_intel_event_id
                WHERE story.subscription_id = ?
                ORDER BY story.latest_event_at DESC
                LIMIT 200
                """,
                (subscription["id"],),
            ).fetchall()
            events = [self._intel_event_from_row(row) for row in rows]
            supersessions = find_story_supersessions(
                events,
                focus_name=subscription["name"],
                focus_is_subject=(
                    subscription["focus_type"] in subject_focus_types
                ),
            )
            connection.execute(
                """
                UPDATE stories
                SET status = 'active'
                WHERE subscription_id = ? AND status = 'stale'
                """,
                (subscription["id"],),
            )
            for supersession in supersessions:
                connection.execute(
                    """
                    UPDATE stories
                    SET status = 'stale', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, supersession.anticipated_story_id),
                )
                connection.execute(
                    """
                    INSERT INTO story_relations (
                        id, from_story_id, to_story_id, relation,
                        reason, confidence, created_at
                    ) VALUES (?, ?, ?, 'superseded_by', ?, ?, ?)
                    ON CONFLICT(from_story_id, to_story_id, relation)
                    DO UPDATE SET
                        reason = excluded.reason,
                        confidence = excluded.confidence
                    """,
                    (
                        new_id("relation"),
                        supersession.anticipated_story_id,
                        supersession.resolution_story_id,
                        supersession.reason,
                        supersession.confidence,
                        now,
                    ),
                )

    def _story_id_for_draft(
        self,
        connection: sqlite3.Connection,
        subscription_id: str,
        draft: IntelEventDraft,
    ) -> str:
        fingerprint = _story_fingerprint(
            title=draft.title,
            category=draft.category,
            tags=draft.tags,
            event_time=draft.event_time,
            source_ids=draft.source_ids,
            sources=draft.sources,
        )
        rows = connection.execute(
            """
            SELECT story_id, title, category, tags, event_time,
                   source_ids, sources
            FROM intel_events
            WHERE subscription_id = ?
              AND story_id IS NOT NULL
            ORDER BY event_time DESC
            LIMIT 80
            """,
            (subscription_id,),
        ).fetchall()
        matches = [
            (match, row["story_id"])
            for row in rows
            if (
                match := match_story(
                    fingerprint,
                    self._row_story_fingerprint(row),
                )
            )
            is not None
        ]
        if not matches:
            return new_id("story")
        return max(matches, key=lambda item: item[0].score)[1]

    def seed_subscriptions(self) -> None:
        seeds = [
            SubscriptionCreate(
                name="AI Agent",
                slug="ai-agent",
                topic="自主规划与执行复杂任务的智能代理系统、Agent Harness、MCP、Coding Agent、评估与安全",
                include_keywords=[
                    "AI Agent",
                    "Agentic AI",
                    "多智能体",
                    "Coding Agent",
                    "工具调用",
                    "Agent Harness",
                    "MCP",
                ],
                exclude_keywords=[
                    "房地产经纪人",
                    "保险代理人",
                    "招聘代理",
                    "旅行代理",
                    "课程促销",
                    "培训招生",
                ],
                lookback_hours=168,
                max_items=18,
                schedule_label="每天 08:30",
                accent="#6366F1",
            ),
            SubscriptionCreate(
                name="机器人",
                slug="robot",
                topic="人形机器人、具身智能、机器人量产与产业落地",
                include_keywords=[
                    "人形机器人",
                    "具身智能",
                    "Embodied AI",
                    "humanoid robot",
                    "robot learning",
                    "VLA",
                    "量产交付",
                ],
                exclude_keywords=[
                    "扫地机器人促销",
                    "玩具机器人",
                    "机器人教育加盟",
                    "少儿编程招生",
                    "课程促销",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 09:00",
                accent="#F59E0B",
            ),
            SubscriptionCreate(
                name="数字人",
                slug="digital-human",
                topic="AIGC 驱动的数字人技术、数字分身与商业应用",
                include_keywords=[
                    "数字人",
                    "数智人",
                    "数字分身",
                    "虚拟主播",
                    "AI avatar",
                    "digital human",
                    "实时渲染",
                    "口型同步",
                ],
                exclude_keywords=[
                    "课程促销",
                    "AI主播说新闻",
                    "AI 主播说新闻",
                    "主播说新闻",
                    "主播说丨",
                    "天气播报",
                    "股市播报",
                    "中考成绩",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 09:10",
                accent="#EC4899",
            ),
            SubscriptionCreate(
                name="虚拟人",
                slug="virtual-human",
                topic="虚拟偶像、VTuber 生态、内容运营与粉丝经济",
                include_keywords=[
                    "虚拟人",
                    "VTuber",
                    "虚拟偶像",
                    "虚拟艺人",
                    "hololive",
                    "NIJISANJI",
                    "virtual creator",
                ],
                exclude_keywords=[
                    "AI主播说新闻",
                    "数字人客服",
                    "盗版下载",
                    "福利视频",
                    "课程促销",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 09:20",
                accent="#8B5CF6",
            ),
            SubscriptionCreate(
                name="Live2D",
                slug="live2d",
                topic="2D 动态立绘技术、Live2D Cubism 工具链与创作生态",
                include_keywords=[
                    "Live2D",
                    "Cubism",
                    "Cubism SDK",
                    "2D avatar",
                    "VTuber 技术",
                    "动画绑定",
                ],
                exclude_keywords=[
                    "破解版",
                    "盗版下载",
                    "免费下载站",
                    "壁纸下载",
                    "课程招生",
                ],
                lookback_hours=336,
                max_items=12,
                schedule_label="每天 09:30",
                accent="#06B6D4",
            ),
            SubscriptionCreate(
                name="大模型",
                slug="llm",
                topic="基础大语言模型的发布、评测、推理能力与竞争格局",
                include_keywords=[
                    "大模型",
                    "LLM",
                    "基础模型",
                    "推理模型",
                    "GPT",
                    "Claude",
                    "Gemini",
                    "Llama",
                    "Mistral",
                ],
                exclude_keywords=[
                    "账号共享",
                    "破解版",
                    "网盘下载",
                    "提示词大全",
                    "课程促销",
                    "培训招生",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 09:40",
                accent="#10B981",
            ),
            SubscriptionCreate(
                name="元宇宙",
                slug="metaverse",
                topic="虚拟世界、XR 硬件、空间计算与沉浸式应用趋势",
                include_keywords=[
                    "元宇宙",
                    "XR",
                    "AR",
                    "VR",
                    "空间计算",
                    "mixed reality",
                    "OpenXR",
                    "WebXR",
                ],
                exclude_keywords=[
                    "币价",
                    "炒币",
                    "空投领取",
                    "链游打金",
                    "虚拟币荐股",
                    "课程促销",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 09:50",
                accent="#F97316",
            ),
            SubscriptionCreate(
                name="自动驾驶",
                slug="autonomous",
                topic="L4/L5 自动驾驶、Robotaxi、端到端技术与商业落地",
                include_keywords=[
                    "自动驾驶",
                    "无人驾驶",
                    "Robotaxi",
                    "智驾",
                    "端到端驾驶",
                    "ADAS",
                    "城市NOA",
                    "量产落地",
                ],
                exclude_keywords=[
                    "二手车促销",
                    "驾校招生",
                    "车险报价",
                    "汽车改装教程",
                    "司机招聘",
                    "课程促销",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 10:00",
                accent="#14B8A6",
            ),
            SubscriptionCreate(
                name="AI 生命科学",
                slug="biotech",
                topic="AI 在药物研发、蛋白质结构、基因组学与生物计算的进展",
                include_keywords=[
                    "AI 生命科学",
                    "AI 制药",
                    "AlphaFold",
                    "AI drug discovery",
                    "protein design",
                    "生物计算",
                    "基因组学",
                    "临床验证",
                ],
                exclude_keywords=[
                    "保健品促销",
                    "减肥药购买",
                    "养生秘方",
                    "股票推荐",
                    "医美广告",
                    "课程促销",
                ],
                lookback_hours=336,
                max_items=12,
                schedule_label="每天 10:10",
                accent="#F43F5E",
            ),
            SubscriptionCreate(
                name="AI 芯片",
                slug="chip",
                topic="AI 训练推理芯片、GPU、NPU、算力基础设施与供应链",
                include_keywords=[
                    "AI 芯片",
                    "GPU",
                    "NPU",
                    "AI accelerator",
                    "算力集群",
                    "HBM",
                    "先进封装",
                    "AI inference",
                ],
                exclude_keywords=[
                    "显卡二手交易",
                    "装机推荐",
                    "游戏帧率",
                    "挖矿教程",
                    "驱动下载站",
                    "课程促销",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 10:20",
                accent="#0EA5E9",
            ),
            SubscriptionCreate(
                name="多模态",
                slug="multimodal",
                topic="跨模态理解、图像视频生成、语音与统一多模态模型",
                include_keywords=[
                    "多模态",
                    "multimodal model",
                    "图文理解",
                    "视频生成",
                    "语音模型",
                    "视觉语言模型",
                    "VLM",
                    "audio model",
                ],
                exclude_keywords=[
                    "写真教程",
                    "换脸软件",
                    "破解下载",
                    "提示词大全",
                    "课程促销",
                    "培训招生",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 10:30",
                accent="#A855F7",
            ),
            SubscriptionCreate(
                name="开源模型",
                slug="open-source",
                topic="开源 AI 模型发布、社区、许可证与开发者生态",
                include_keywords=[
                    "开源模型",
                    "Open Source AI",
                    "open weights",
                    "Llama",
                    "Mistral",
                    "Hugging Face",
                    "模型许可证",
                    "Transformers",
                    "vLLM",
                ],
                exclude_keywords=[
                    "模型盗版下载",
                    "夸克网盘",
                    "百度网盘",
                    "一键整合包",
                    "账号共享",
                    "课程促销",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="每天 10:40",
                accent="#22C55E",
            ),
            # Keep the former product subscription addressable for old Runs and
            # fixtures, but hide it from the reference-aligned product UI.
            SubscriptionCreate(
                name="游戏研发观察",
                slug="game-dev",
                topic="游戏引擎、研发工具、技术美术、发行政策与工作室动态",
                include_keywords=[
                    "游戏引擎",
                    "Unity",
                    "Unreal Engine",
                    "Godot",
                    "Bevy",
                    "游戏研发",
                    "实时渲染",
                    "技术美术",
                ],
                exclude_keywords=[
                    "游戏下载",
                    "破解版",
                    "礼包码",
                    "手游推荐",
                    "抽奖活动",
                    "课程招生",
                ],
                lookback_hours=168,
                max_items=12,
                schedule_label="工作日 18:00",
                accent="#ffc486",
            ),
        ]
        for seed in seeds:
            seed_focus_type = resolve_focus_type(
                seed.focus_type,
                name=seed.name,
                keywords=seed.include_keywords,
            )
            seed_focus_domain = resolve_focus_domain(
                seed.focus_domain,
                name=seed.name,
                keywords=seed.include_keywords,
                focus_type=seed_focus_type,
            )
            try:
                self.create_subscription(seed)
            except sqlite3.IntegrityError:
                with self.connect() as connection:
                    connection.execute(
                        """
                        UPDATE subscriptions
                        SET name = ?, topic = ?, include_keywords = ?,
                            exclude_keywords = ?, languages = ?,
                            lookback_hours = ?, max_items = ?,
                            minimum_importance = ?, schedule_label = ?,
                            accent = ?, focus_type = ?, focus_domain = ?,
                            updated_at = ?
                        WHERE slug = ?
                        """,
                        (
                            seed.name,
                            seed.topic,
                            _json_dump(seed.include_keywords),
                            _json_dump(seed.exclude_keywords),
                            _json_dump(seed.languages),
                            seed.lookback_hours,
                            seed.max_items,
                            seed.minimum_importance,
                            seed.schedule_label,
                            seed.accent,
                            seed_focus_type.value,
                            seed_focus_domain.value,
                            utc_now().isoformat(),
                            seed.slug,
                        ),
                    )
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE subscriptions
                SET enabled = 0, updated_at = ?
                WHERE slug = 'game-dev'
                """,
                (utc_now().isoformat(),),
            )

    def create_subscription(self, payload: SubscriptionCreate) -> Subscription:
        now = utc_now()
        focus_type = resolve_focus_type(
            payload.focus_type,
            name=payload.name,
            keywords=payload.include_keywords,
        )
        focus_domain = resolve_focus_domain(
            payload.focus_domain,
            name=payload.name,
            keywords=payload.include_keywords,
            focus_type=focus_type,
        )
        topic = normalize_custom_focus_topic(
            name=payload.name,
            topic=payload.topic,
            keywords=payload.include_keywords,
            slug=payload.slug,
        )
        subscription = Subscription(
            id=new_id("sub"),
            **payload.model_dump(
                exclude={"focus_type", "focus_domain", "topic"}
            ),
            topic=topic,
            focus_type=focus_type,
            focus_domain=focus_domain,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO subscriptions (
                    id, name, slug, topic, include_keywords, exclude_keywords,
                    languages, lookback_hours, max_items, minimum_importance,
                    schedule_label, accent, focus_type, enabled, created_at,
                    focus_domain, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription.id,
                    subscription.name,
                    subscription.slug,
                    subscription.topic,
                    _json_dump(subscription.include_keywords),
                    _json_dump(subscription.exclude_keywords),
                    _json_dump(subscription.languages),
                    subscription.lookback_hours,
                    subscription.max_items,
                    subscription.minimum_importance,
                    subscription.schedule_label,
                    subscription.accent,
                    subscription.focus_type.value,
                    int(subscription.enabled),
                    subscription.created_at.isoformat(),
                    subscription.focus_domain.value,
                    subscription.updated_at.isoformat(),
                ),
            )
        return subscription

    def list_subscriptions(self) -> list[Subscription]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subscriptions ORDER BY created_at"
            ).fetchall()
        return [self._subscription_from_row(row) for row in rows]

    def get_subscription(self, subscription_id: str) -> Subscription | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
            ).fetchone()
        return self._subscription_from_row(row) if row else None

    def create_custom_source(
        self,
        payload: CustomSourceCreate,
        *,
        resolved_url: str,
        collection_mode: str,
    ) -> CustomSource:
        now = utc_now()
        source = CustomSource(
            id=new_id("source"),
            **payload.model_dump(),
            resolved_url=resolved_url,
            collection_mode=collection_mode,
            status="active",
            created_at=now,
            updated_at=now,
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO custom_sources (
                    id, subscription_id, name, url, source_type,
                    resolved_url, collection_mode, status, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    source.id,
                    source.subscription_id,
                    source.name,
                    source.url,
                    source.source_type,
                    source.resolved_url,
                    source.collection_mode,
                    source.status,
                    source.created_at.isoformat(),
                    source.updated_at.isoformat(),
                ),
            )
        return source

    def list_custom_sources(
        self,
        *,
        subscription_id: str | None = None,
        status: str | None = None,
    ) -> list[CustomSource]:
        clauses: list[str] = []
        values: list[Any] = []
        if subscription_id:
            clauses.append("subscription_id = ?")
            values.append(subscription_id)
        if status:
            clauses.append("status = ?")
            values.append(status)
        query = "SELECT * FROM custom_sources"
        if clauses:
            query += f" WHERE {' AND '.join(clauses)}"
        query += " ORDER BY created_at"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._custom_source_from_row(row) for row in rows]

    def delete_custom_source(self, source_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM custom_sources WHERE id = ?", (source_id,)
            )
        return cursor.rowcount > 0

    def update_custom_source_status(
        self,
        source_id: str,
        *,
        status: str,
        last_error: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE custom_sources
                SET status = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, last_error, utc_now().isoformat(), source_id),
            )

    def create_run(
        self,
        *,
        subscription_id: str,
        trigger: str,
        goal: str,
        research_mode: str = "monitor",
        story_id: str | None = None,
        research_focus: str | None = None,
        research_question: str | None = None,
        delivery_mode: str,
        idempotency_key: str | None,
        budget: RunBudget | None = None,
    ) -> Run:
        if idempotency_key:
            with self.connect() as connection:
                existing = connection.execute(
                    "SELECT * FROM runs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
            if existing:
                return self._run_from_row(existing)

        now = utc_now()
        run = Run(
            id=new_id("run"),
            subscription_id=subscription_id,
            trigger=trigger,
            goal=goal,
            research_mode=research_mode,
            story_id=story_id,
            research_focus=research_focus,
            research_question=research_question,
            delivery_mode=delivery_mode,
            status=RunStatus.QUEUED,
            stage=RunStage.PLANNING,
            budget=budget or RunBudget(),
            usage=RunUsage(),
            created_at=now,
            updated_at=now,
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, subscription_id, trigger, goal, research_mode,
                    story_id, research_focus, research_question,
                    delivery_mode, idempotency_key,
                    status, stage,
                    budget, usage,
                    cancellation_requested, result, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?)
                """,
                (
                    run.id,
                    run.subscription_id,
                    run.trigger,
                    run.goal,
                    run.research_mode,
                    run.story_id,
                    run.research_focus,
                    run.research_question,
                    run.delivery_mode,
                    idempotency_key,
                    run.status.value,
                    run.stage.value,
                    _json_dump(run.budget.model_dump()),
                    _json_dump(run.usage.model_dump()),
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                ),
            )
        return run

    def get_run(self, run_id: str) -> Run | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(self, limit: int = 30) -> list[Run]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def reconcile_interrupted_runs(self) -> list[Run]:
        """Fail non-terminal in-flight Runs left behind by a stopped process."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at
                """
            ).fetchall()
        recovered: list[Run] = []
        for row in rows:
            run = self.update_run(
                row["id"],
                status=RunStatus.FAILED,
                error={
                    "code": "PROCESS_RESTARTED",
                    "message": "上一次进程在 Run 完成前退出，请使用 Retry 创建新的幂等 Run。",
                },
            )
            self.append_event(
                run.id,
                "run.reconciled",
                actor={"type": "runtime", "id": "startup_reconciler"},
                payload={
                    "previous_status": row["status"],
                    "resolution": "failed_retryable",
                },
            )
            self.append_event(
                run.id,
                "run.failed",
                actor={"type": "runtime", "id": "startup_reconciler"},
                payload={"error": run.error},
            )
            recovered.append(run)
        return recovered

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        stage: RunStage | None = None,
        usage: RunUsage | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        cancellation_requested: bool | None = None,
    ) -> Run:
        assignments: list[str] = ["updated_at = ?"]
        values: list[Any] = [utc_now().isoformat()]
        if status is not None:
            assignments.append("status = ?")
            values.append(status.value)
        if stage is not None:
            assignments.append("stage = ?")
            values.append(stage.value)
        if usage is not None:
            assignments.append("usage = ?")
            values.append(_json_dump(usage.model_dump()))
        if result is not None:
            assignments.append("result = ?")
            values.append(_json_dump(result))
        if error is not None:
            assignments.append("error = ?")
            values.append(_json_dump(error))
        if cancellation_requested is not None:
            assignments.append("cancellation_requested = ?")
            values.append(int(cancellation_requested))
        values.append(run_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE id = ?", values
            )
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        return run

    def append_event(
        self,
        run_id: str,
        event_type: str,
        *,
        actor: dict[str, str],
        payload: dict[str, Any],
        visibility: str = "user",
    ) -> RunEvent:
        timestamp = utc_now()
        event_id = new_id("evt")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            seq = int(row["next_seq"])
            connection.execute(
                """
                INSERT INTO run_events (
                    id, run_id, seq, type, actor, payload, visibility, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    run_id,
                    seq,
                    event_type,
                    _json_dump(actor),
                    _json_dump(payload),
                    visibility,
                    timestamp.isoformat(),
                ),
            )
        return RunEvent(
            id=event_id,
            run_id=run_id,
            seq=seq,
            type=event_type,
            actor=actor,
            payload=payload,
            visibility=visibility,
            timestamp=timestamp,
        )

    def list_events(
        self, run_id: str, *, after_seq: int = 0, visibility: str = "user"
    ) -> list[RunEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND seq > ? AND visibility = ?
                ORDER BY seq
                """,
                (run_id, after_seq, visibility),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def create_tool_call(
        self, run_id: str, tool: str, args: dict[str, Any], reason: str
    ) -> str:
        tool_call_id = new_id("call")
        now = utc_now().isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_calls (
                    id, run_id, tool, args, reason, decision, status,
                    result, error, duration_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, 'requested', NULL, NULL, NULL, ?, ?)
                """,
                (
                    tool_call_id,
                    run_id,
                    tool,
                    _json_dump(args),
                    reason,
                    now,
                    now,
                ),
            )
        return tool_call_id

    def update_tool_call(
        self,
        tool_call_id: str,
        *,
        decision: dict[str, Any] | None = None,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        assignments = ["updated_at = ?"]
        values: list[Any] = [utc_now().isoformat()]
        for name, value in (
            ("decision", _json_dump(decision) if decision is not None else None),
            ("status", status),
            ("result", _json_dump(result) if result is not None else None),
            ("error", _json_dump(error) if error is not None else None),
            ("duration_ms", duration_ms),
        ):
            if value is not None:
                assignments.append(f"{name} = ?")
                values.append(value)
        values.append(tool_call_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE tool_calls SET {', '.join(assignments)} WHERE id = ?", values
            )

    def save_source_documents(
        self,
        run_id: str,
        subscription_id: str,
        documents: list[dict[str, Any]],
        *,
        seen_at: str | None = None,
        evidence_source_ids: set[str] | None = None,
    ) -> list[SourceDocument]:
        now = seen_at or utc_now().isoformat()
        with self.connect() as connection:
            for document in documents:
                source_id = str(document.get("source_id") or "").strip()
                url = str(document.get("url") or "").strip()
                title = str(document.get("title") or "").strip()
                if not source_id or not url or not title:
                    continue
                canonical_url = _canonical_url(url)
                body = str(document.get("body") or "")
                safety_flags = [
                    str(flag)
                    for flag in document.get("safety_flags", [])
                    if isinstance(flag, str)
                ]
                outcome = (
                    "blocked"
                    if safety_flags
                    else (
                        "discovered"
                        if evidence_source_ids is None
                        or source_id in evidence_source_ids
                        else "deferred"
                    )
                )
                existing = connection.execute(
                    """
                    SELECT id, seen_count, last_seen_at
                    FROM source_documents
                    WHERE subscription_id = ? AND canonical_url = ?
                    """,
                    (subscription_id, canonical_url),
                ).fetchone()
                if existing:
                    document_id = existing["id"]
                    already_linked = connection.execute(
                        """
                        SELECT 1 FROM run_documents
                        WHERE run_id = ? AND document_id = ?
                        """,
                        (run_id, document_id),
                    ).fetchone()
                    seen_count = int(existing["seen_count"]) + (
                        0 if already_linked else 1
                    )
                    if now >= existing["last_seen_at"]:
                        connection.execute(
                            """
                            UPDATE source_documents
                            SET source_id = ?, latest_url = ?, title = ?,
                                publisher = ?, source_type = ?, published_at = ?,
                                content_excerpt = ?, content_hash = ?,
                                content_origin = ?, author = ?, image_url = ?,
                                word_count = ?, reliability = ?,
                                safety_flags = ?, configured_source_id = ?,
                                query_template_id = ?, query_focus_tier = ?,
                                retrieval_channel = ?,
                                source_group = ?, ranking_score = ?,
                                ranking_reasons = ?, focus_tier = ?,
                                focus_relation_score = ?, fetch_status = ?,
                                extraction_status = ?,
                                duplicate_of_document_id = ?,
                                relevance_score = ?, keyword_match_score = ?,
                                entity_match_score = ?, semantic_match_score = ?,
                                source_prior_score = ?,
                                user_preference_score = ?, novelty_score = ?,
                                novelty_components = ?,
                                event_elements = ?, cluster_id = ?,
                                cluster_relation = ?, evidence_chain_id = ?,
                                evidence_relation_type = ?,
                                independence_score = ?, last_seen_at = ?,
                                last_run_id = ?, seen_count = ?
                            WHERE id = ?
                            """,
                            (
                                source_id,
                                url,
                                title,
                                str(document.get("publisher") or "未知来源"),
                                str(document.get("source_type") or "public"),
                                str(document.get("published_at") or now),
                                " ".join(body.split())[:1500],
                                _content_hash(body),
                                str(document.get("content_origin") or "feed"),
                                document.get("author"),
                                document.get("image_url"),
                                max(0, int(document.get("word_count") or 0)),
                                min(
                                    1.0,
                                    max(
                                        0.0,
                                        float(
                                            document.get("reliability") or 0.5
                                        ),
                                    ),
                                ),
                                _json_dump(safety_flags),
                                document.get("configured_source_id"),
                                document.get("query_template_id"),
                                document.get("query_focus_tier", "core"),
                                document.get("retrieval_channel"),
                                document.get("source_group"),
                                document.get("ranking_score"),
                                _json_dump(
                                    document.get("ranking_reasons", [])
                                ),
                                document.get("focus_tier", "unmatched"),
                                document.get("focus_relation_score", 0),
                                document.get("fetch_status"),
                                document.get("extraction_status"),
                                document.get("duplicate_of_document_id"),
                                document.get("relevance_score"),
                                document.get("keyword_match_score"),
                                document.get("entity_match_score"),
                                document.get("semantic_match_score"),
                                document.get("source_prior_score"),
                                document.get("user_preference_score"),
                                document.get("novelty_score"),
                                _json_dump(
                                    document.get("novelty_components", {})
                                ),
                                _json_dump(document.get("event_elements", {})),
                                document.get("cluster_id"),
                                document.get("cluster_relation"),
                                document.get("evidence_chain_id"),
                                document.get("evidence_relation_type"),
                                document.get("independence_score"),
                                now,
                                run_id,
                                seen_count,
                                document_id,
                            ),
                        )
                    elif not already_linked:
                        connection.execute(
                            """
                            UPDATE source_documents
                            SET seen_count = ?
                            WHERE id = ?
                            """,
                            (seen_count, document_id),
                        )
                else:
                    document_id = new_id("doc")
                    connection.execute(
                        """
                        INSERT INTO source_documents (
                            id, subscription_id, source_id, canonical_url,
                            latest_url, title, publisher, source_type,
                            published_at, content_excerpt, content_hash,
                            content_origin, author, image_url, word_count,
                            reliability, safety_flags, configured_source_id,
                            query_template_id, query_focus_tier,
                            retrieval_channel, source_group,
                            ranking_score, ranking_reasons, focus_tier,
                            focus_relation_score, fetch_status,
                            extraction_status, duplicate_of_document_id,
                            relevance_score, keyword_match_score,
                            entity_match_score, semantic_match_score,
                            source_prior_score, user_preference_score,
                            novelty_score, novelty_components,
                            event_elements, cluster_id,
                            cluster_relation, evidence_chain_id,
                            evidence_relation_type, independence_score,
                            first_seen_at,
                            last_seen_at, last_run_id, seen_count
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, 1
                        )
                        """,
                        (
                            document_id,
                            subscription_id,
                            source_id,
                            canonical_url,
                            url,
                            title,
                            str(document.get("publisher") or "未知来源"),
                            str(document.get("source_type") or "public"),
                            str(document.get("published_at") or now),
                            " ".join(body.split())[:1500],
                            _content_hash(body),
                            str(document.get("content_origin") or "feed"),
                            document.get("author"),
                            document.get("image_url"),
                            max(0, int(document.get("word_count") or 0)),
                            min(
                                1.0,
                                max(
                                    0.0,
                                    float(document.get("reliability") or 0.5),
                                ),
                            ),
                            _json_dump(safety_flags),
                            document.get("configured_source_id"),
                            document.get("query_template_id"),
                            document.get("query_focus_tier", "core"),
                            document.get("retrieval_channel"),
                            document.get("source_group"),
                            document.get("ranking_score"),
                            _json_dump(document.get("ranking_reasons", [])),
                            document.get("focus_tier", "unmatched"),
                            document.get("focus_relation_score", 0),
                            document.get("fetch_status"),
                            document.get("extraction_status"),
                            document.get("duplicate_of_document_id"),
                            document.get("relevance_score"),
                            document.get("keyword_match_score"),
                            document.get("entity_match_score"),
                            document.get("semantic_match_score"),
                            document.get("source_prior_score"),
                            document.get("user_preference_score"),
                            document.get("novelty_score"),
                            _json_dump(
                                document.get("novelty_components", {})
                            ),
                            _json_dump(document.get("event_elements", {})),
                            document.get("cluster_id"),
                            document.get("cluster_relation"),
                            document.get("evidence_chain_id"),
                            document.get("evidence_relation_type"),
                            document.get("independence_score"),
                            now,
                            now,
                            run_id,
                        ),
                    )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO run_documents (
                        run_id, document_id, source_id, outcome, discovered_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (run_id, document_id, source_id, outcome, now),
                )
            rows = connection.execute(
                """
                SELECT sd.*, rd.outcome AS last_outcome
                FROM source_documents AS sd
                JOIN run_documents AS rd ON rd.document_id = sd.id
                WHERE rd.run_id = ?
                ORDER BY sd.published_at DESC
                """,
                (run_id,),
            ).fetchall()
        return [self._source_document_from_row(row) for row in rows]

    def update_run_document_outcomes(
        self,
        run_id: str,
        selected_source_ids: set[str],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE run_documents
                SET outcome = 'reviewed'
                WHERE run_id = ? AND outcome = 'discovered'
                """,
                (run_id,),
            )
            if selected_source_ids:
                placeholders = ",".join("?" for _ in selected_source_ids)
                selected_source_keys = connection.execute(
                    f"""
                    SELECT DISTINCT sd.configured_source_id
                    FROM run_documents AS rd
                    JOIN source_documents AS sd ON sd.id = rd.document_id
                    WHERE rd.run_id = ?
                      AND rd.outcome = 'reviewed'
                      AND rd.source_id IN ({placeholders})
                      AND sd.configured_source_id IS NOT NULL
                    """,
                    (run_id, *sorted(selected_source_ids)),
                ).fetchall()
                connection.execute(
                    f"""
                    UPDATE run_documents
                    SET outcome = 'selected'
                    WHERE run_id = ?
                      AND outcome = 'reviewed'
                      AND source_id IN ({placeholders})
                    """,
                    (run_id, *sorted(selected_source_ids)),
                )
                for row in selected_source_keys:
                    connection.execute(
                        """
                        UPDATE source_runtime_states
                        SET selected_document_count =
                                selected_document_count + 1,
                            updated_at = ?
                        WHERE source_key = ?
                          AND subscription_id = (
                              SELECT subscription_id
                              FROM runs
                              WHERE id = ?
                          )
                        """,
                        (
                            utc_now().isoformat(),
                            row["configured_source_id"],
                            run_id,
                        ),
                    )

    def list_source_runtime_states(
        self,
        *,
        subscription_id: str,
    ) -> list[SourceRuntimeState]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM source_runtime_states
                WHERE subscription_id = ?
                ORDER BY health_status, source_key
                """,
                (subscription_id,),
            ).fetchall()
        return [self._source_runtime_state_from_row(row) for row in rows]

    def record_source_runtime_updates(
        self,
        subscription_id: str,
        updates: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        now = utc_now()
        now_value = now.isoformat()
        health_changes: list[dict[str, str]] = []
        with self.connect() as connection:
            for update in updates:
                source_key = str(update.get("source_key") or "").strip()
                if not source_key:
                    continue
                existing = connection.execute(
                    """
                    SELECT *
                    FROM source_runtime_states
                    WHERE subscription_id = ? AND source_key = ?
                    """,
                    (subscription_id, source_key),
                ).fetchone()
                previous_requests = (
                    int(existing["request_count"]) if existing else 0
                )
                request_count = previous_requests + 1
                duration_ms = max(0, int(update.get("duration_ms") or 0))
                previous_average = (
                    float(existing["average_duration_ms"]) if existing else 0
                )
                average_duration_ms = (
                    previous_average * previous_requests + duration_ms
                ) / request_count
                success = bool(update.get("success"))
                previous_failures = (
                    int(existing["consecutive_failures"]) if existing else 0
                )
                consecutive_failures = 0 if success else previous_failures + 1
                new_count = max(0, int(update.get("new_document_count") or 0))
                fulltext_count = max(
                    0, int(update.get("fulltext_success_count") or 0)
                )
                last_new_document_at = (
                    now_value
                    if new_count
                    else (
                        existing["last_new_document_at"] if existing else None
                    )
                )
                last_new_is_stale = last_new_document_at is None
                if last_new_document_at:
                    try:
                        parsed_last_new = datetime.fromisoformat(
                            str(last_new_document_at).replace("Z", "+00:00")
                        )
                        if parsed_last_new.tzinfo is None:
                            parsed_last_new = parsed_last_new.replace(
                                tzinfo=timezone.utc
                            )
                        last_new_is_stale = (
                            now - parsed_last_new >= timedelta(days=14)
                        )
                    except ValueError:
                        last_new_is_stale = True
                if consecutive_failures >= 5:
                    health_status = "failing"
                elif consecutive_failures >= 3:
                    health_status = "degraded"
                elif (
                    success
                    and not new_count
                    and request_count >= 10
                    and last_new_is_stale
                ):
                    health_status = "stale"
                else:
                    health_status = "healthy"
                previous_status = (
                    str(existing["health_status"]) if existing else "healthy"
                )
                if previous_status != health_status:
                    health_changes.append(
                        {
                            "source_key": source_key,
                            "from": previous_status,
                            "to": health_status,
                        }
                    )
                connection.execute(
                    """
                    INSERT INTO source_runtime_states (
                        subscription_id, source_key, etag, last_modified,
                        last_success_at, last_failure_at, consecutive_failures,
                        last_new_document_at, request_count,
                        new_document_count, selected_document_count,
                        fulltext_success_count, average_duration_ms,
                        health_status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subscription_id, source_key) DO UPDATE SET
                        etag = excluded.etag,
                        last_modified = excluded.last_modified,
                        last_success_at = excluded.last_success_at,
                        last_failure_at = excluded.last_failure_at,
                        consecutive_failures = excluded.consecutive_failures,
                        last_new_document_at = excluded.last_new_document_at,
                        request_count = excluded.request_count,
                        new_document_count = excluded.new_document_count,
                        fulltext_success_count = excluded.fulltext_success_count,
                        average_duration_ms = excluded.average_duration_ms,
                        health_status = excluded.health_status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        subscription_id,
                        source_key,
                        update.get("etag")
                        or (existing["etag"] if existing else None),
                        update.get("last_modified")
                        or (existing["last_modified"] if existing else None),
                        (
                            now_value
                            if success
                            else (
                                existing["last_success_at"]
                                if existing
                                else None
                            )
                        ),
                        (
                            now_value
                            if not success
                            else (
                                existing["last_failure_at"]
                                if existing
                                else None
                            )
                        ),
                        consecutive_failures,
                        last_new_document_at,
                        request_count,
                        (
                            (int(existing["new_document_count"]) if existing else 0)
                            + new_count
                        ),
                        (
                            int(existing["selected_document_count"])
                            if existing
                            else 0
                        ),
                        (
                            (
                                int(existing["fulltext_success_count"])
                                if existing
                                else 0
                            )
                            + fulltext_count
                        ),
                        average_duration_ms,
                        health_status,
                        now_value,
                    ),
                )
        return health_changes

    def list_source_query_metrics(
        self,
        *,
        subscription_id: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT sd.query_template_id,
                       COUNT(*) AS discovery_count,
                       SUM(CASE WHEN sd.first_seen_at = rd.discovered_at
                           THEN 1 ELSE 0 END) AS new_document_count,
                       SUM(CASE WHEN rd.outcome NOT IN ('deferred', 'blocked')
                           THEN 1 ELSE 0 END) AS evidence_count,
                       SUM(CASE WHEN rd.outcome = 'selected'
                           THEN 1 ELSE 0 END) AS selected_count,
                       MAX(sd.published_at) AS latest_published_at,
                       MAX(rd.discovered_at) AS last_run_at
                FROM run_documents AS rd
                JOIN source_documents AS sd ON sd.id = rd.document_id
                WHERE sd.subscription_id = ?
                  AND sd.query_template_id IS NOT NULL
                GROUP BY sd.query_template_id
                ORDER BY selected_count DESC, evidence_count DESC,
                         sd.query_template_id
                """,
                (subscription_id,),
            ).fetchall()
        return [
            {
                "query_template_id": row["query_template_id"],
                "discovery_count": row["discovery_count"],
                "new_document_count": row["new_document_count"],
                "evidence_count": row["evidence_count"],
                "selected_count": row["selected_count"],
                "new_content_rate": round(
                    row["new_document_count"] / row["discovery_count"], 4
                )
                if row["discovery_count"]
                else 0,
                "evidence_rate": round(
                    row["evidence_count"] / row["discovery_count"], 4
                )
                if row["discovery_count"]
                else 0,
                "selection_rate": round(
                    row["selected_count"] / row["evidence_count"], 4
                )
                if row["evidence_count"]
                else 0,
                "latest_published_at": row["latest_published_at"],
                "last_run_at": row["last_run_at"],
            }
            for row in rows
        ]

    def list_source_documents(
        self,
        *,
        subscription_id: str | None = None,
        outcome: str | None = None,
        retrieval_channel: str | None = None,
        limit: int = 100,
    ) -> list[SourceDocument]:
        values: list[Any] = []
        query = """
            SELECT sd.*, COALESCE(
                (
                    SELECT rd.outcome
                    FROM run_documents AS rd
                    WHERE rd.document_id = sd.id
                    ORDER BY rd.discovered_at DESC
                    LIMIT 1
                ),
                'discovered'
            ) AS last_outcome
            FROM source_documents AS sd
        """
        conditions: list[str] = []
        if subscription_id:
            conditions.append("sd.subscription_id = ?")
            values.append(subscription_id)
        if outcome:
            conditions.append(
                """
                COALESCE(
                    (
                        SELECT latest_rd.outcome
                        FROM run_documents AS latest_rd
                        WHERE latest_rd.document_id = sd.id
                        ORDER BY latest_rd.discovered_at DESC
                        LIMIT 1
                    ),
                    'discovered'
                ) = ?
                """
            )
            values.append(outcome)
        if retrieval_channel:
            conditions.append("sd.retrieval_channel = ?")
            values.append(retrieval_channel)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY sd.published_at DESC, sd.last_seen_at DESC LIMIT ?"
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._source_document_from_row(row) for row in rows]

    def list_run_documents(self, run_id: str) -> list[SourceDocument]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT sd.*, rd.outcome AS last_outcome
                FROM source_documents AS sd
                JOIN run_documents AS rd ON rd.document_id = sd.id
                WHERE rd.run_id = ?
                ORDER BY sd.published_at DESC
                """,
                (run_id,),
            ).fetchall()
        return [self._source_document_from_row(row) for row in rows]

    def _sync_story_for_event(
        self,
        connection: sqlite3.Connection,
        event: IntelEvent,
    ) -> None:
        fingerprint_model = _story_fingerprint(
            title=event.title,
            category=event.category,
            tags=event.tags,
            event_time=event.event_time,
            source_ids=event.source_ids,
            sources=event.sources,
        )
        fingerprint = hashlib.sha256(
            "\n".join(
                [
                    event.subscription_id,
                    event.category,
                    event.title.casefold(),
                    *sorted(tag.casefold() for tag in event.tags),
                ]
            ).encode("utf-8")
        ).hexdigest()
        existing_story = connection.execute(
            "SELECT * FROM stories WHERE id = ?",
            (event.story_id,),
        ).fetchone()
        previous_event = None
        if (
            existing_story
            and existing_story["current_intel_event_id"] != event.id
        ):
            previous_event = connection.execute(
                "SELECT * FROM intel_events WHERE id = ?",
                (existing_story["current_intel_event_id"],),
            ).fetchone()

        document_rows: list[sqlite3.Row] = []
        if event.source_ids:
            placeholders = ",".join("?" for _ in event.source_ids)
            document_rows = connection.execute(
                f"""
                SELECT *
                FROM source_documents
                WHERE subscription_id = ?
                  AND source_id IN ({placeholders})
                """,
                (event.subscription_id, *event.source_ids),
            ).fetchall()
        chain_ids = {
            str(row["evidence_chain_id"])
            for row in document_rows
            if row["evidence_chain_id"]
        }
        extracted_subjects = [
            str(subject)
            for row in document_rows
            for subject in (
                _json_load(row["event_elements"], {}).get(
                    "primary_subjects"
                )
                or _json_load(row["event_elements"], {}).get(
                    "subjects", []
                )
            )
            if str(subject).strip()
        ]
        story_subjects = list(
            dict.fromkeys([*extracted_subjects, *event.tags])
        )[:12]
        evidence_count = len(chain_ids) or min(len(document_rows), 1)
        if evidence_count and not event.independent_evidence_count:
            event.independent_evidence_count = evidence_count
        if previous_event is not None and not event.change_summary:
            previous_fact_texts = {
                str(fact.get("text") or "")
                for fact in _json_load(previous_event["facts"], [])
                if isinstance(fact, dict)
            }
            new_fact_texts = [
                fact.text
                for fact in event.facts
                if fact.text not in previous_fact_texts
            ]
            change_lines = [
                f"上次：{previous_event['summary']}",
                f"本次：{event.summary}",
            ]
            if new_fact_texts:
                change_lines.append(f"新增证据事实：{new_fact_texts[0]}")
            change_lines.append(
                f"证据：{event.independent_evidence_count} 条独立证据链"
            )
            event.change_summary = "\n".join(change_lines)[:600]
        connection.execute(
            """
            UPDATE intel_events
            SET change_summary = ?, independent_evidence_count = ?
            WHERE id = ?
            """,
            (
                event.change_summary,
                event.independent_evidence_count,
                event.id,
            ),
        )

        if existing_story is None:
            connection.execute(
                """
                INSERT INTO stories (
                    id, subscription_id, canonical_title,
                    primary_subjects, event_type, status,
                    first_event_at, latest_event_at,
                    current_intel_event_id, fingerprint,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.story_id,
                    event.subscription_id,
                    event.title,
                    _json_dump(story_subjects),
                    event.category,
                    event.event_time.isoformat(),
                    event.event_time.isoformat(),
                    event.id,
                    fingerprint,
                    event.created_at.isoformat(),
                    event.created_at.isoformat(),
                ),
            )
        elif event.event_time.isoformat() >= existing_story["latest_event_at"]:
            connection.execute(
                """
                UPDATE stories
                SET canonical_title = ?, primary_subjects = ?,
                    event_type = ?, latest_event_at = ?,
                    current_intel_event_id = ?, fingerprint = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    event.title,
                    _json_dump(story_subjects),
                    event.category,
                    event.event_time.isoformat(),
                    event.id,
                    fingerprint,
                    event.created_at.isoformat(),
                    event.story_id,
                ),
            )

        primary_document_id = None
        if document_rows:
            primary_document_id = max(
                document_rows,
                key=lambda row: (
                    float(row["independence_score"] or 0),
                    float(row["reliability"] or 0),
                ),
            )["id"]
        for row in document_rows:
            relation_type = (
                row["evidence_relation_type"] or "reporting"
            )
            chain_id = row["evidence_chain_id"]
            if not chain_id:
                material = (
                    f"{relation_type}:{row['publisher']}:{row['canonical_url']}"
                )
                chain_id = "chain_" + hashlib.sha256(
                    material.encode("utf-8")
                ).hexdigest()[:16]
            connection.execute(
                """
                INSERT INTO story_documents (
                    story_id, document_id, relation_type,
                    evidence_chain_id, attributed_source,
                    is_primary, independence_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id, document_id) DO UPDATE SET
                    relation_type = excluded.relation_type,
                    evidence_chain_id = excluded.evidence_chain_id,
                    attributed_source = excluded.attributed_source,
                    is_primary = excluded.is_primary,
                    independence_score = excluded.independence_score
                """,
                (
                    event.story_id,
                    row["id"],
                    relation_type,
                    chain_id,
                    row["publisher"],
                    int(row["id"] == primary_document_id),
                    float(row["independence_score"] or 0.5),
                    event.created_at.isoformat(),
                ),
            )

        if existing_story is not None:
            return
        candidates = connection.execute(
            """
            SELECT ie.*
            FROM stories AS story
            JOIN intel_events AS ie
              ON ie.id = story.current_intel_event_id
            WHERE story.subscription_id = ? AND story.id != ?
            ORDER BY story.latest_event_at DESC
            LIMIT 50
            """,
            (event.subscription_id, event.story_id),
        ).fetchall()
        relations = [
            (
                relation,
                row,
            )
            for row in candidates
            if (
                relation := classify_story_relation(
                    fingerprint_model,
                    self._row_story_fingerprint(row),
                )
            )
            is not None
            and relation.relation in {"follow_up", "related"}
        ]
        if not relations:
            return
        relation, row = max(relations, key=lambda item: item[0].score)
        relation_id = new_id("relation")
        connection.execute(
            """
            INSERT OR IGNORE INTO story_relations (
                id, from_story_id, to_story_id, relation,
                reason, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation_id,
                row["story_id"],
                event.story_id,
                relation.relation,
                relation.reason,
                relation.score,
                event.created_at.isoformat(),
            ),
        )

    def save_intel_events(
        self,
        run_id: str,
        subscription_id: str,
        drafts: list[IntelEventDraft],
        *,
        target_story_id: str | None = None,
    ) -> list[IntelEvent]:
        now = utc_now()
        events: list[IntelEvent] = []
        with self.connect() as connection:
            if target_story_id:
                target_story = connection.execute(
                    "SELECT subscription_id FROM stories WHERE id = ?",
                    (target_story_id,),
                ).fetchone()
                if target_story is None:
                    raise ValueError("Target story not found")
                if target_story["subscription_id"] != subscription_id:
                    raise ValueError(
                        "Target story does not belong to this subscription"
                    )
            for draft in drafts:
                serialized_source_ids = _json_dump(draft.source_ids)
                dedupe_key = _event_dedupe_key(
                    subscription_id,
                    draft.source_ids,
                    draft.sources,
                )
                existing = connection.execute(
                    """
                    SELECT id, story_id, first_seen_at
                    FROM intel_events
                    WHERE subscription_id = ? AND dedupe_key = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (subscription_id, dedupe_key),
                ).fetchone()
                story_id = (
                    existing["story_id"]
                    if existing
                    else (
                        target_story_id
                        or self._story_id_for_draft(
                            connection,
                            subscription_id,
                            draft,
                        )
                    )
                )
                event = IntelEvent(
                    id=existing["id"] if existing else new_id("intel"),
                    story_id=story_id,
                    run_id=run_id,
                    subscription_id=subscription_id,
                    first_seen_at=existing["first_seen_at"] if existing else now,
                    created_at=now,
                    **draft.model_dump(),
                )
                if existing:
                    connection.execute(
                        """
                        UPDATE intel_events
                        SET run_id = ?, title = ?, summary = ?, category = ?,
                            tags = ?, event_time = ?, importance_score = ?,
                            importance_reason = ?, confidence_level = ?,
                            confidence_score = ?, confidence_reason = ?,
                            verification_status = ?, facts = ?, inferences = ?,
                            source_ids = ?, sources = ?, dedupe_key = ?,
                            change_summary = ?,
                            independent_evidence_count = ?, created_at = ?
                        WHERE id = ?
                        """,
                        (
                            event.run_id,
                            event.title,
                            event.summary,
                            event.category,
                            _json_dump(event.tags),
                            event.event_time.isoformat(),
                            event.importance_score,
                            event.importance_reason,
                            event.confidence_level,
                            event.confidence_score,
                            event.confidence_reason,
                            event.verification_status,
                            _json_dump(
                                [item.model_dump() for item in event.facts]
                            ),
                            _json_dump(
                                [item.model_dump() for item in event.inferences]
                            ),
                            serialized_source_ids,
                            _json_dump(
                                [
                                    item.model_dump(mode="json")
                                    for item in event.sources
                                ]
                            ),
                            dedupe_key,
                            event.change_summary,
                            event.independent_evidence_count,
                            event.created_at.isoformat(),
                            event.id,
                        ),
                    )
                    events.append(event)
                    self._sync_story_for_event(connection, event)
                    continue
                connection.execute(
                    """
                    INSERT INTO intel_events (
                        id, story_id, run_id, subscription_id, title, summary,
                        category, tags, event_time, first_seen_at, importance_score,
                        importance_reason, confidence_level, confidence_score,
                        confidence_reason, verification_status, facts, inferences,
                        source_ids, sources, dedupe_key, change_summary,
                        independent_evidence_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.story_id,
                        event.run_id,
                        event.subscription_id,
                        event.title,
                        event.summary,
                        event.category,
                        _json_dump(event.tags),
                        event.event_time.isoformat(),
                        event.first_seen_at.isoformat(),
                        event.importance_score,
                        event.importance_reason,
                        event.confidence_level,
                        event.confidence_score,
                        event.confidence_reason,
                        event.verification_status,
                        _json_dump([item.model_dump() for item in event.facts]),
                        _json_dump(
                            [item.model_dump() for item in event.inferences]
                        ),
                        serialized_source_ids,
                        _json_dump(
                            [item.model_dump(mode="json") for item in event.sources]
                        ),
                        dedupe_key,
                        event.change_summary,
                        event.independent_evidence_count,
                        event.created_at.isoformat(),
                    ),
                )
                self._sync_story_for_event(connection, event)
                events.append(event)
            if events:
                self._refresh_story_lifecycle(connection, subscription_id)
            for event in events:
                story = connection.execute(
                    "SELECT status FROM stories WHERE id = ?",
                    (event.story_id,),
                ).fetchone()
                if story is None or story["status"] != "stale":
                    self._match_alerts_for_event(connection, event)
            if events:
                self._upsert_digest(
                    connection,
                    subscription_id,
                    period=self._digest_frequency_for(
                        connection, subscription_id
                    ),
                )
        return events

    @staticmethod
    def _digest_frequency_for(
        connection: sqlite3.Connection,
        subscription_id: str,
    ) -> str:
        row = connection.execute(
            """
            SELECT digest_frequency
            FROM subscription_preferences
            WHERE subscription_id = ?
            """,
            (subscription_id,),
        ).fetchone()
        return str(row["digest_frequency"]) if row else "weekly"

    def _match_alerts_for_event(
        self,
        connection: sqlite3.Connection,
        event: IntelEvent,
    ) -> None:
        rules = connection.execute(
            """
            SELECT *
            FROM alert_rules
            WHERE subscription_id = ? AND enabled = 1
            """,
            (event.subscription_id,),
        ).fetchall()
        searchable = f"{event.title} {' '.join(event.tags)}".casefold()
        for rule in rules:
            entities = _json_load(rule["entities"], [])
            event_types = _json_load(rule["event_types"], [])
            if entities and not any(
                str(entity).casefold() in searchable for entity in entities
            ):
                continue
            if event_types and event.category not in event_types:
                continue
            if event.importance_score < rule["minimum_importance"]:
                continue
            if event.confidence_score < rule["minimum_confidence"]:
                continue
            if (
                event.independent_evidence_count
                < rule["minimum_evidence_chains"]
            ):
                continue
            if rule["require_official"] and not any(
                source.source_type in {"official", "policy", "research"}
                for source in event.sources
            ):
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO alert_matches (
                    alert_id, intel_event_id, matched_at
                ) VALUES (?, ?, ?)
                """,
                (rule["id"], event.id, event.created_at.isoformat()),
            )

    def _upsert_digest(
        self,
        connection: sqlite3.Connection,
        subscription_id: str,
        *,
        period: str,
    ) -> None:
        if period not in {"daily", "weekly"}:
            return
        now = utc_now()
        period_key = (
            now.date().isoformat()
            if period == "daily"
            else f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        )
        title = "今日行业变化" if period == "daily" else "本周行业变化"
        rows = connection.execute(
            """
            SELECT ie.*
            FROM intel_events AS ie
            JOIN stories AS story ON story.id = ie.story_id
            WHERE ie.subscription_id = ? AND story.status != 'stale'
            ORDER BY ie.event_time DESC
            LIMIT 40
            """,
            (subscription_id,),
        ).fetchall()
        important = sorted(
            rows,
            key=lambda row: (
                -float(row["importance_score"]),
                row["event_time"],
            ),
        )[:5]
        changes = [
            row for row in rows if row["change_summary"]
        ][:8]
        new_events = [
            row
            for row in rows
            if row["first_seen_at"] == row["created_at"]
        ][:8]
        conflicts = [
            row
            for row in rows
            if row["verification_status"] == "conflicting"
        ][:8]
        content = [
            f"# {title}",
            "",
            "## 最重要的 5 个事件",
            "",
            *(
                [
                    f"- {row['title']}（重要度 {float(row['importance_score']):.1f}）"
                    for row in important
                ]
                or ["- 当前周期暂无通过质量门禁的事件。"]
            ),
            "",
            "## 新出现的公司、产品和技术",
            "",
            *(
                [f"- {row['title']}" for row in new_events]
                or ["- 当前周期暂无首次出现且已通过 Eval 的事件。"]
            ),
            "",
            "## 持续事件的实质进展",
            "",
            *(
                [f"- {row['change_summary']}" for row in changes]
                or ["- 当前周期暂无可确认的实质进展。"]
            ),
            "",
            "## 存在冲突或仍待确认的线索",
            "",
            *(
                [f"- {row['title']}" for row in conflicts]
                or ["- 当前周期没有已记录的证据冲突。"]
            ),
            "",
            "## 来源覆盖与漏报风险",
            "",
            "- 简报只引用已通过 Eval 的情报事件；样本不足时不生成趋势结论。",
        ]
        digest_id = new_id("digest")
        connection.execute(
            """
            INSERT INTO digests (
                id, subscription_id, period, period_key, title,
                content_markdown, intel_event_ids, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscription_id, period, period_key) DO UPDATE SET
                title = excluded.title,
                content_markdown = excluded.content_markdown,
                intel_event_ids = excluded.intel_event_ids,
                created_at = excluded.created_at
            """,
            (
                digest_id,
                subscription_id,
                period,
                period_key,
                title,
                "\n".join(content),
                _json_dump([row["id"] for row in rows]),
                now.isoformat(),
            ),
        )

    def list_intel_events(
        self,
        *,
        subscription_id: str | None = None,
        limit: int = 50,
        include_stale_stories: bool = True,
    ) -> list[IntelEvent]:
        query = (
            "SELECT ie.* FROM intel_events AS ie "
            "LEFT JOIN stories AS story ON story.id = ie.story_id"
        )
        values: list[Any] = []
        clauses: list[str] = []
        if subscription_id:
            clauses.append("ie.subscription_id = ?")
            values.append(subscription_id)
        if not include_stale_stories:
            clauses.append("COALESCE(story.status, 'active') != 'stale'")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += (
            " ORDER BY ie.importance_score DESC, ie.event_time DESC LIMIT ?"
        )
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._intel_event_from_row(row) for row in rows]

    def get_intel_event(self, intel_event_id: str) -> IntelEvent | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM intel_events WHERE id = ?",
                (intel_event_id,),
            ).fetchone()
        return self._intel_event_from_row(row) if row else None

    def list_stories(
        self,
        *,
        subscription_id: str | None = None,
        limit: int = 100,
    ) -> list[Story]:
        query = "SELECT * FROM stories"
        values: list[Any] = []
        if subscription_id:
            query += " WHERE subscription_id = ?"
            values.append(subscription_id)
        query += " ORDER BY latest_event_at DESC LIMIT ?"
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._story_from_row(row) for row in rows]

    def get_story(self, story_id: str) -> Story | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM stories WHERE id = ?",
                (story_id,),
            ).fetchone()
        return self._story_from_row(row) if row else None

    def get_story_watch(self, story_id: str) -> StoryWatch | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM story_watches WHERE story_id = ?",
                (story_id,),
            ).fetchone()
        return self._story_watch_from_row(row) if row else None

    def list_story_watches(
        self,
        *,
        subscription_id: str | None = None,
        enabled: bool | None = None,
    ) -> list[StoryWatch]:
        clauses: list[str] = []
        values: list[Any] = []
        if subscription_id:
            clauses.append("subscription_id = ?")
            values.append(subscription_id)
        if enabled is not None:
            clauses.append("enabled = ?")
            values.append(int(enabled))
        query = "SELECT * FROM story_watches"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._story_watch_from_row(row) for row in rows]

    def upsert_story_watch(
        self,
        story_id: str,
        payload: StoryWatchUpsert,
    ) -> StoryWatch:
        story = self.get_story(story_id)
        if story is None:
            raise KeyError(story_id)
        now = utc_now()
        next_check_at = self._next_story_watch_at(
            payload.cadence,
            now,
            enabled=payload.enabled,
        )
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM story_watches WHERE story_id = ?",
                (story_id,),
            ).fetchone()
            watch_id = existing["id"] if existing else new_id("watch")
            created_at = existing["created_at"] if existing else now.isoformat()
            connection.execute(
                """
                INSERT INTO story_watches (
                    id, story_id, subscription_id, research_focus, question,
                    cadence, enabled, last_run_id, last_checked_at,
                    next_check_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(story_id) DO UPDATE SET
                    research_focus = excluded.research_focus,
                    question = excluded.question,
                    cadence = excluded.cadence,
                    enabled = excluded.enabled,
                    next_check_at = excluded.next_check_at,
                    updated_at = excluded.updated_at
                """,
                (
                    watch_id,
                    story.id,
                    story.subscription_id,
                    payload.research_focus,
                    payload.question,
                    payload.cadence,
                    int(payload.enabled),
                    existing["last_run_id"] if existing else None,
                    existing["last_checked_at"] if existing else None,
                    next_check_at.isoformat() if next_check_at else None,
                    created_at,
                    now.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM story_watches WHERE story_id = ?",
                (story_id,),
            ).fetchone()
        return self._story_watch_from_row(row)

    def list_due_story_watches(
        self,
        now: datetime,
        *,
        limit: int = 50,
    ) -> list[StoryWatch]:
        normalized_now = (
            now.replace(tzinfo=timezone.utc)
            if now.tzinfo is None
            else now.astimezone(timezone.utc)
        )
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM story_watches
                WHERE enabled = 1
                  AND cadence IN ('daily', 'weekly')
                  AND next_check_at IS NOT NULL
                  AND next_check_at <= ?
                ORDER BY next_check_at ASC
                LIMIT ?
                """,
                (normalized_now.isoformat(), limit),
            ).fetchall()
        return [self._story_watch_from_row(row) for row in rows]

    def mark_story_watch_triggered(
        self,
        watch_id: str,
        run_id: str,
        *,
        checked_at: datetime | None = None,
    ) -> StoryWatch | None:
        now = checked_at or utc_now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM story_watches WHERE id = ?",
                (watch_id,),
            ).fetchone()
            if existing is None:
                return None
            next_check_at = self._next_story_watch_at(
                existing["cadence"],
                now,
                enabled=bool(existing["enabled"]),
            )
            connection.execute(
                """
                UPDATE story_watches
                SET last_run_id = ?, last_checked_at = ?,
                    next_check_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    run_id,
                    now.isoformat(),
                    next_check_at.isoformat() if next_check_at else None,
                    now.isoformat(),
                    watch_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM story_watches WHERE id = ?",
                (watch_id,),
            ).fetchone()
        return self._story_watch_from_row(row)

    def get_active_story_run(self, story_id: str) -> Run | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM runs
                WHERE story_id = ?
                  AND status IN ('queued', 'running', 'waiting_approval')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (story_id,),
            ).fetchone()
        return self._run_from_row(row) if row else None

    @staticmethod
    def _next_story_watch_at(
        cadence: str,
        now: datetime,
        *,
        enabled: bool,
    ) -> datetime | None:
        if not enabled:
            return None
        interval = STORY_WATCH_INTERVALS.get(cadence)
        return now + interval if interval else None

    def list_story_timeline(self, story_id: str) -> list[IntelEvent]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM intel_events
                WHERE story_id = ?
                ORDER BY event_time, created_at
                """,
                (story_id,),
            ).fetchall()
        return [self._intel_event_from_row(row) for row in rows]

    def list_story_relations(self, story_id: str) -> list[StoryRelation]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM story_relations
                WHERE from_story_id = ? OR to_story_id = ?
                ORDER BY created_at
                """,
                (story_id, story_id),
            ).fetchall()
        return [self._story_relation_from_row(row) for row in rows]

    def list_story_documents(self, story_id: str) -> list[StoryDocument]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM story_documents
                WHERE story_id = ?
                ORDER BY is_primary DESC, independence_score DESC
                """,
                (story_id,),
            ).fetchall()
        return [self._story_document_from_row(row) for row in rows]

    def list_feedback(
        self,
        *,
        intel_event_id: str,
    ) -> list[IntelFeedback]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM intel_feedback
                WHERE intel_event_id = ?
                ORDER BY created_at
                """,
                (intel_event_id,),
            ).fetchall()
        return [self._feedback_from_row(row) for row in rows]

    def create_feedback(
        self,
        intel_event_id: str,
        payload: IntelFeedbackCreate,
    ) -> IntelFeedback:
        now = utc_now()
        target = payload.target or ""
        with self.connect() as connection:
            event = connection.execute(
                """
                SELECT id, subscription_id, tags, source_ids
                FROM intel_events
                WHERE id = ?
                """,
                (intel_event_id,),
            ).fetchone()
            if event is None:
                raise KeyError("Intel event not found")
            existing = connection.execute(
                """
                SELECT *
                FROM intel_feedback
                WHERE intel_event_id = ? AND feedback_type = ? AND target = ?
                """,
                (intel_event_id, payload.feedback_type, target),
            ).fetchone()
            if existing:
                return self._feedback_from_row(existing)
            feedback = IntelFeedback(
                id=new_id("feedback"),
                intel_event_id=intel_event_id,
                subscription_id=event["subscription_id"],
                created_at=now,
                **payload.model_dump(),
            )
            connection.execute(
                """
                INSERT INTO intel_feedback (
                    id, intel_event_id, subscription_id, feedback_type,
                    reason_code, note, target, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.id,
                    feedback.intel_event_id,
                    feedback.subscription_id,
                    feedback.feedback_type,
                    feedback.reason_code,
                    feedback.note,
                    target,
                    feedback.created_at.isoformat(),
                ),
            )
            preferences = self._preferences_from_connection(
                connection, event["subscription_id"]
            )
            entity_weights = dict(preferences.entity_weights)
            source_weights = dict(preferences.source_weights)
            followed_entities = list(preferences.followed_entities)
            muted_sources = list(preferences.muted_sources)
            if feedback.feedback_type in {"valuable", "not_relevant"}:
                adjustment = (
                    0.10
                    if feedback.feedback_type == "valuable"
                    else -0.15
                )
                for tag in _json_load(event["tags"], [])[:8]:
                    entity_weights[str(tag)] = max(
                        -1,
                        min(
                            1,
                            entity_weights.get(str(tag), 0) + adjustment,
                        ),
                    )
            if feedback.feedback_type == "follow_entity" and target:
                followed_entities = list(
                    dict.fromkeys([*followed_entities, target])
                )
            if feedback.feedback_type == "mute_source" and target:
                muted_sources = list(
                    dict.fromkeys([*muted_sources, target])
                )
                source_weights[target] = -1
            self._write_preferences(
                connection,
                preferences.model_copy(
                    update={
                        "entity_weights": entity_weights,
                        "source_weights": source_weights,
                        "followed_entities": followed_entities,
                        "muted_sources": muted_sources,
                        "updated_at": now,
                    }
                ),
            )
        return feedback

    def delete_feedback(
        self,
        intel_event_id: str,
        feedback_type: str,
        *,
        target: str | None = None,
    ) -> bool:
        normalized_target = target or ""
        with self.connect() as connection:
            event = connection.execute(
                """
                SELECT subscription_id, tags
                FROM intel_events
                WHERE id = ?
                """,
                (intel_event_id,),
            ).fetchone()
            if event is None:
                return False
            cursor = connection.execute(
                """
                DELETE FROM intel_feedback
                WHERE intel_event_id = ? AND feedback_type = ? AND target = ?
                """,
                (intel_event_id, feedback_type, normalized_target),
            )
            if cursor.rowcount <= 0:
                return False

            preferences = self._preferences_from_connection(
                connection, event["subscription_id"]
            )
            entity_weights = dict(preferences.entity_weights)
            source_weights = dict(preferences.source_weights)
            followed_entities = list(preferences.followed_entities)
            muted_sources = list(preferences.muted_sources)
            if feedback_type in {"valuable", "not_relevant"}:
                inverse_adjustment = (
                    -0.10 if feedback_type == "valuable" else 0.15
                )
                for tag in _json_load(event["tags"], [])[:8]:
                    key = str(tag)
                    updated = max(
                        -1,
                        min(
                            1,
                            entity_weights.get(key, 0)
                            + inverse_adjustment,
                        ),
                    )
                    if abs(updated) < 1e-9:
                        entity_weights.pop(key, None)
                    else:
                        entity_weights[key] = updated
            if feedback_type == "follow_entity" and normalized_target:
                remaining = connection.execute(
                    """
                    SELECT 1
                    FROM intel_feedback
                    WHERE subscription_id = ?
                      AND feedback_type = 'follow_entity'
                      AND target = ?
                    LIMIT 1
                    """,
                    (event["subscription_id"], normalized_target),
                ).fetchone()
                if remaining is None:
                    followed_entities = [
                        value
                        for value in followed_entities
                        if value != normalized_target
                    ]
            if feedback_type == "mute_source" and normalized_target:
                remaining = connection.execute(
                    """
                    SELECT 1
                    FROM intel_feedback
                    WHERE subscription_id = ?
                      AND feedback_type = 'mute_source'
                      AND target = ?
                    LIMIT 1
                    """,
                    (event["subscription_id"], normalized_target),
                ).fetchone()
                if remaining is None:
                    muted_sources = [
                        value
                        for value in muted_sources
                        if value != normalized_target
                    ]
                    source_weights.pop(normalized_target, None)
            self._write_preferences(
                connection,
                preferences.model_copy(
                    update={
                        "entity_weights": entity_weights,
                        "source_weights": source_weights,
                        "followed_entities": followed_entities,
                        "muted_sources": muted_sources,
                        "updated_at": utc_now(),
                    }
                ),
            )
        return True

    def _preferences_from_connection(
        self,
        connection: sqlite3.Connection,
        subscription_id: str,
    ) -> SubscriptionPreferences:
        row = connection.execute(
            """
            SELECT *
            FROM subscription_preferences
            WHERE subscription_id = ?
            """,
            (subscription_id,),
        ).fetchone()
        if row:
            return self._preferences_from_row(row)
        return SubscriptionPreferences(
            subscription_id=subscription_id,
            updated_at=utc_now(),
        )

    def get_subscription_preferences(
        self,
        subscription_id: str,
    ) -> SubscriptionPreferences:
        with self.connect() as connection:
            return self._preferences_from_connection(
                connection, subscription_id
            )

    def _write_preferences(
        self,
        connection: sqlite3.Connection,
        preferences: SubscriptionPreferences,
    ) -> None:
        connection.execute(
            """
            INSERT INTO subscription_preferences (
                subscription_id, category_weights, entity_weights,
                source_weights, followed_entities, context_entities,
                muted_entities, muted_sources, minimum_importance,
                alert_importance_threshold, digest_frequency, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscription_id) DO UPDATE SET
                category_weights = excluded.category_weights,
                entity_weights = excluded.entity_weights,
                source_weights = excluded.source_weights,
                followed_entities = excluded.followed_entities,
                context_entities = excluded.context_entities,
                muted_entities = excluded.muted_entities,
                muted_sources = excluded.muted_sources,
                minimum_importance = excluded.minimum_importance,
                alert_importance_threshold =
                    excluded.alert_importance_threshold,
                digest_frequency = excluded.digest_frequency,
                updated_at = excluded.updated_at
            """,
            (
                preferences.subscription_id,
                _json_dump(preferences.category_weights),
                _json_dump(preferences.entity_weights),
                _json_dump(preferences.source_weights),
                _json_dump(preferences.followed_entities),
                _json_dump(preferences.context_entities),
                _json_dump(preferences.muted_entities),
                _json_dump(preferences.muted_sources),
                preferences.minimum_importance,
                preferences.alert_importance_threshold,
                preferences.digest_frequency,
                preferences.updated_at.isoformat(),
            ),
        )

    def update_subscription_preferences(
        self,
        subscription_id: str,
        payload: SubscriptionPreferencesUpdate,
    ) -> SubscriptionPreferences:
        now = utc_now()
        with self.connect() as connection:
            current = self._preferences_from_connection(
                connection, subscription_id
            )
            updates = {
                key: value
                for key, value in payload.model_dump().items()
                if value is not None
            }
            for weight_field in (
                "category_weights",
                "entity_weights",
                "source_weights",
            ):
                if weight_field in updates:
                    updates[weight_field] = {
                        str(key): max(-1, min(1, float(value)))
                        for key, value in updates[weight_field].items()
                    }
            preferences = current.model_copy(
                update={**updates, "updated_at": now}
            )
            self._write_preferences(connection, preferences)
        return preferences

    def list_alert_rules(
        self,
        *,
        subscription_id: str | None = None,
    ) -> list[AlertRule]:
        query = "SELECT * FROM alert_rules"
        values: list[Any] = []
        if subscription_id:
            query += " WHERE subscription_id = ?"
            values.append(subscription_id)
        query += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._alert_rule_from_row(row) for row in rows]

    def list_alert_matches(
        self,
        *,
        subscription_id: str | None = None,
        limit: int = 100,
    ) -> list[AlertMatch]:
        query = """
            SELECT match.*
            FROM alert_matches AS match
            JOIN alert_rules AS rule ON rule.id = match.alert_id
        """
        values: list[Any] = []
        if subscription_id:
            query += " WHERE rule.subscription_id = ?"
            values.append(subscription_id)
        query += " ORDER BY match.matched_at DESC LIMIT ?"
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [
            AlertMatch(
                alert_id=row["alert_id"],
                intel_event_id=row["intel_event_id"],
                matched_at=row["matched_at"],
            )
            for row in rows
        ]

    def create_alert_rule(self, payload: AlertRuleCreate) -> AlertRule:
        now = utc_now()
        rule = AlertRule(
            id=new_id("alert"),
            created_at=now,
            updated_at=now,
            **payload.model_dump(),
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO alert_rules (
                    id, subscription_id, name, entities, event_types,
                    minimum_importance, minimum_confidence,
                    require_official, minimum_evidence_chains,
                    frequency, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    rule.subscription_id,
                    rule.name,
                    _json_dump(rule.entities),
                    _json_dump(rule.event_types),
                    rule.minimum_importance,
                    rule.minimum_confidence,
                    int(rule.require_official),
                    rule.minimum_evidence_chains,
                    rule.frequency,
                    int(rule.enabled),
                    rule.created_at.isoformat(),
                    rule.updated_at.isoformat(),
                ),
            )
        return rule

    def update_alert_rule(
        self,
        alert_id: str,
        payload: AlertRuleCreate,
    ) -> AlertRule | None:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM alert_rules WHERE id = ?",
                (alert_id,),
            ).fetchone()
            if not existing:
                return None
            connection.execute(
                """
                UPDATE alert_rules
                SET subscription_id = ?, name = ?, entities = ?,
                    event_types = ?, minimum_importance = ?,
                    minimum_confidence = ?, require_official = ?,
                    minimum_evidence_chains = ?, frequency = ?,
                    enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.subscription_id,
                    payload.name,
                    _json_dump(payload.entities),
                    _json_dump(payload.event_types),
                    payload.minimum_importance,
                    payload.minimum_confidence,
                    int(payload.require_official),
                    payload.minimum_evidence_chains,
                    payload.frequency,
                    int(payload.enabled),
                    now.isoformat(),
                    alert_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM alert_rules WHERE id = ?",
                (alert_id,),
            ).fetchone()
        return self._alert_rule_from_row(row)

    def list_digests(
        self,
        *,
        subscription_id: str | None = None,
        limit: int = 30,
    ) -> list[Digest]:
        query = "SELECT * FROM digests"
        values: list[Any] = []
        if subscription_id:
            query += " WHERE subscription_id = ?"
            values.append(subscription_id)
        query += " ORDER BY period_key DESC LIMIT ?"
        values.append(limit)
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._digest_from_row(row) for row in rows]

    def create_approval(
        self, run_id: str, tool_name: str, request: dict[str, Any]
    ) -> Approval:
        approval = Approval(
            id=new_id("approval"),
            run_id=run_id,
            tool_name=tool_name,
            status="pending",
            request=request,
            created_at=utc_now(),
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    id, run_id, tool_name, status, request, decision,
                    created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL)
                """,
                (
                    approval.id,
                    approval.run_id,
                    approval.tool_name,
                    approval.status,
                    _json_dump(approval.request),
                    approval.created_at.isoformat(),
                ),
            )
        return approval

    def get_approval(self, approval_id: str) -> Approval | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
        return self._approval_from_row(row) if row else None

    def get_pending_approval_for_run(self, run_id: str) -> Approval | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM approvals
                WHERE run_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return self._approval_from_row(row) if row else None

    def list_approvals(self, status: str | None = None) -> list[Approval]:
        query = "SELECT * FROM approvals"
        values: list[Any] = []
        if status:
            query += " WHERE status = ?"
            values.append(status)
        query += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def resolve_approval(
        self, approval_id: str, status: str, decision: dict[str, Any]
    ) -> Approval:
        resolved_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE approvals
                SET status = ?, decision = ?, resolved_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, _json_dump(decision), resolved_at.isoformat(), approval_id),
            )
        approval = self.get_approval(approval_id)
        if approval is None:
            raise KeyError(f"Approval not found: {approval_id}")
        return approval

    @staticmethod
    def _subscription_from_row(row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            topic=row["topic"],
            include_keywords=_json_load(row["include_keywords"], []),
            exclude_keywords=_json_load(row["exclude_keywords"], []),
            languages=_json_load(row["languages"], []),
            lookback_hours=row["lookback_hours"],
            max_items=row["max_items"],
            minimum_importance=row["minimum_importance"],
            schedule_label=row["schedule_label"],
            accent=row["accent"],
            focus_type=row["focus_type"],
            focus_domain=row["focus_domain"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _custom_source_from_row(row: sqlite3.Row) -> CustomSource:
        return CustomSource(
            id=row["id"],
            subscription_id=row["subscription_id"],
            name=row["name"],
            url=row["url"],
            source_type=row["source_type"],
            resolved_url=row["resolved_url"],
            collection_mode=row["collection_mode"],
            status=row["status"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> Run:
        return Run(
            id=row["id"],
            subscription_id=row["subscription_id"],
            trigger=row["trigger"],
            goal=row["goal"],
            research_mode=row["research_mode"],
            story_id=row["story_id"],
            research_focus=row["research_focus"],
            research_question=row["research_question"],
            delivery_mode=row["delivery_mode"],
            status=row["status"],
            stage=row["stage"],
            budget=RunBudget.model_validate(_json_load(row["budget"], {})),
            usage=RunUsage.model_validate(_json_load(row["usage"], {})),
            cancellation_requested=bool(row["cancellation_requested"]),
            result=_json_load(row["result"], None),
            error=_json_load(row["error"], None),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> RunEvent:
        return RunEvent(
            id=row["id"],
            run_id=row["run_id"],
            seq=row["seq"],
            type=row["type"],
            actor=_json_load(row["actor"], {}),
            payload=_json_load(row["payload"], {}),
            visibility=row["visibility"],
            timestamp=row["timestamp"],
        )

    @staticmethod
    def _intel_event_from_row(row: sqlite3.Row) -> IntelEvent:
        return IntelEvent(
            id=row["id"],
            story_id=row["story_id"],
            run_id=row["run_id"],
            subscription_id=row["subscription_id"],
            title=row["title"],
            summary=row["summary"],
            category=row["category"],
            tags=_json_load(row["tags"], []),
            event_time=row["event_time"],
            first_seen_at=row["first_seen_at"],
            importance_score=row["importance_score"],
            importance_reason=row["importance_reason"],
            confidence_level=row["confidence_level"],
            confidence_score=row["confidence_score"],
            confidence_reason=row["confidence_reason"],
            verification_status=row["verification_status"],
            facts=_json_load(row["facts"], []),
            inferences=_json_load(row["inferences"], []),
            source_ids=_json_load(row["source_ids"], []),
            sources=_json_load(row["sources"], []),
            change_summary=row["change_summary"],
            independent_evidence_count=row["independent_evidence_count"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _source_document_from_row(row: sqlite3.Row) -> SourceDocument:
        return SourceDocument(
            id=row["id"],
            subscription_id=row["subscription_id"],
            source_id=row["source_id"],
            canonical_url=row["canonical_url"],
            latest_url=row["latest_url"],
            title=row["title"],
            publisher=row["publisher"],
            source_type=row["source_type"],
            published_at=row["published_at"],
            content_excerpt=row["content_excerpt"],
            content_hash=row["content_hash"],
            content_origin=row["content_origin"],
            author=row["author"],
            image_url=row["image_url"],
            word_count=row["word_count"],
            reliability=row["reliability"],
            safety_flags=_json_load(row["safety_flags"], []),
            configured_source_id=row["configured_source_id"],
            query_template_id=row["query_template_id"],
            query_focus_tier=row["query_focus_tier"],
            retrieval_channel=row["retrieval_channel"],
            source_group=row["source_group"],
            ranking_score=row["ranking_score"],
            ranking_reasons=_json_load(row["ranking_reasons"], []),
            focus_tier=row["focus_tier"],
            focus_relation_score=row["focus_relation_score"],
            fetch_status=row["fetch_status"],
            extraction_status=row["extraction_status"],
            duplicate_of_document_id=row["duplicate_of_document_id"],
            relevance_score=row["relevance_score"],
            keyword_match_score=row["keyword_match_score"],
            entity_match_score=row["entity_match_score"],
            semantic_match_score=row["semantic_match_score"],
            source_prior_score=row["source_prior_score"],
            user_preference_score=row["user_preference_score"],
            novelty_score=row["novelty_score"],
            novelty_components=_json_load(
                row["novelty_components"], {}
            ),
            event_elements=_json_load(row["event_elements"], {}),
            cluster_id=row["cluster_id"],
            cluster_relation=row["cluster_relation"],
            evidence_chain_id=row["evidence_chain_id"],
            evidence_relation_type=row["evidence_relation_type"],
            independence_score=row["independence_score"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            last_run_id=row["last_run_id"],
            seen_count=row["seen_count"],
            last_outcome=row["last_outcome"],
        )

    @staticmethod
    def _story_from_row(row: sqlite3.Row) -> Story:
        return Story(
            id=row["id"],
            subscription_id=row["subscription_id"],
            canonical_title=row["canonical_title"],
            primary_subjects=_json_load(row["primary_subjects"], []),
            event_type=row["event_type"],
            status=row["status"],
            first_event_at=row["first_event_at"],
            latest_event_at=row["latest_event_at"],
            current_intel_event_id=row["current_intel_event_id"],
            fingerprint=row["fingerprint"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _story_relation_from_row(row: sqlite3.Row) -> StoryRelation:
        return StoryRelation(
            id=row["id"],
            from_story_id=row["from_story_id"],
            to_story_id=row["to_story_id"],
            relation=row["relation"],
            reason=row["reason"],
            confidence=row["confidence"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _story_document_from_row(row: sqlite3.Row) -> StoryDocument:
        return StoryDocument(
            story_id=row["story_id"],
            document_id=row["document_id"],
            relation_type=row["relation_type"],
            evidence_chain_id=row["evidence_chain_id"],
            attributed_source=row["attributed_source"],
            is_primary=bool(row["is_primary"]),
            independence_score=row["independence_score"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _story_watch_from_row(row: sqlite3.Row) -> StoryWatch:
        return StoryWatch(
            id=row["id"],
            story_id=row["story_id"],
            subscription_id=row["subscription_id"],
            research_focus=row["research_focus"],
            question=row["question"],
            cadence=row["cadence"],
            enabled=bool(row["enabled"]),
            last_run_id=row["last_run_id"],
            last_checked_at=row["last_checked_at"],
            next_check_at=row["next_check_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _feedback_from_row(row: sqlite3.Row) -> IntelFeedback:
        return IntelFeedback(
            id=row["id"],
            intel_event_id=row["intel_event_id"],
            subscription_id=row["subscription_id"],
            feedback_type=row["feedback_type"],
            reason_code=row["reason_code"],
            note=row["note"],
            target=row["target"] or None,
            created_at=row["created_at"],
        )

    @staticmethod
    def _preferences_from_row(
        row: sqlite3.Row,
    ) -> SubscriptionPreferences:
        return SubscriptionPreferences(
            subscription_id=row["subscription_id"],
            category_weights=_json_load(row["category_weights"], {}),
            entity_weights=_json_load(row["entity_weights"], {}),
            source_weights=_json_load(row["source_weights"], {}),
            followed_entities=_json_load(row["followed_entities"], []),
            context_entities=_json_load(row["context_entities"], []),
            muted_entities=_json_load(row["muted_entities"], []),
            muted_sources=_json_load(row["muted_sources"], []),
            minimum_importance=row["minimum_importance"],
            alert_importance_threshold=row["alert_importance_threshold"],
            digest_frequency=row["digest_frequency"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _alert_rule_from_row(row: sqlite3.Row) -> AlertRule:
        return AlertRule(
            id=row["id"],
            subscription_id=row["subscription_id"],
            name=row["name"],
            entities=_json_load(row["entities"], []),
            event_types=_json_load(row["event_types"], []),
            minimum_importance=row["minimum_importance"],
            minimum_confidence=row["minimum_confidence"],
            require_official=bool(row["require_official"]),
            minimum_evidence_chains=row["minimum_evidence_chains"],
            frequency=row["frequency"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _digest_from_row(row: sqlite3.Row) -> Digest:
        return Digest(
            id=row["id"],
            subscription_id=row["subscription_id"],
            period=row["period"],
            period_key=row["period_key"],
            title=row["title"],
            content_markdown=row["content_markdown"],
            intel_event_ids=_json_load(row["intel_event_ids"], []),
            created_at=row["created_at"],
        )

    @staticmethod
    def _source_runtime_state_from_row(
        row: sqlite3.Row,
    ) -> SourceRuntimeState:
        return SourceRuntimeState(
            subscription_id=row["subscription_id"],
            source_key=row["source_key"],
            etag=row["etag"],
            last_modified=row["last_modified"],
            last_success_at=row["last_success_at"],
            last_failure_at=row["last_failure_at"],
            consecutive_failures=row["consecutive_failures"],
            last_new_document_at=row["last_new_document_at"],
            request_count=row["request_count"],
            new_document_count=row["new_document_count"],
            selected_document_count=row["selected_document_count"],
            fulltext_success_count=row["fulltext_success_count"],
            average_duration_ms=row["average_duration_ms"],
            health_status=row["health_status"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> Approval:
        return Approval(
            id=row["id"],
            run_id=row["run_id"],
            tool_name=row["tool_name"],
            status=row["status"],
            request=_json_load(row["request"], {}),
            decision=_json_load(row["decision"], None),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )
