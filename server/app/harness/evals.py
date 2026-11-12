from __future__ import annotations

import hashlib
import re
from typing import Any

from app.domain.models import EvalResult, IntelEventDraft
from app.domain.quality_pipeline import (
    build_fact_citations,
    document_supports_claim,
    find_unsupported_numbers,
)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class EvalRunner:
    def evaluate_items(
        self,
        items: list[dict[str, Any]],
        *,
        allowed_source_ids: set[str],
        blocked_source_ids: set[str],
        documents: list[dict[str, Any]] | None = None,
        claim_eval_enabled: bool = True,
    ) -> tuple[EvalResult, list[IntelEventDraft]]:
        if not items:
            result, _ = self.evaluate(
                [],
                allowed_source_ids=allowed_source_ids,
                blocked_source_ids=blocked_source_ids,
                documents=documents,
                claim_eval_enabled=claim_eval_enabled,
            )
            return (
                result.model_copy(
                    update={
                        "checks": [
                            *result.checks,
                            {
                                "name": "item_quality_filter",
                                "severity": "hard",
                                "passed": True,
                                "detail": {
                                    "input_item_count": 0,
                                    "accepted_item_count": 0,
                                    "rejected_item_count": 0,
                                    "rejected_items": [],
                                },
                            },
                        ],
                        "metrics": {
                            **result.metrics,
                            "input_item_count": 0,
                            "accepted_item_count": 0,
                            "rejected_item_count": 0,
                        },
                    }
                ),
                [],
            )

        accepted: list[IntelEventDraft] = []
        rejected: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            result, drafts = self.evaluate(
                [item],
                allowed_source_ids=allowed_source_ids,
                blocked_source_ids=blocked_source_ids,
                documents=documents,
                claim_eval_enabled=claim_eval_enabled,
            )
            if result.passed and drafts:
                accepted.extend(drafts)
                continue
            rejected.append(
                {
                    "index": index,
                    "title": str(item.get("title") or f"item[{index}]")[:160],
                    "failed_checks": [
                        str(check.get("name"))
                        for check in result.checks
                        if check.get("severity", "hard") == "hard"
                        and not check.get("passed")
                    ],
                }
            )

        if not accepted:
            result, _ = self.evaluate(
                items,
                allowed_source_ids=allowed_source_ids,
                blocked_source_ids=blocked_source_ids,
                documents=documents,
                claim_eval_enabled=claim_eval_enabled,
            )
            return (
                result.model_copy(
                    update={
                        "passed": False,
                        "metrics": {
                            **result.metrics,
                            "input_item_count": len(items),
                            "accepted_item_count": 0,
                            "rejected_item_count": len(rejected),
                        },
                    }
                ),
                [],
            )

        accepted_result, accepted = self.evaluate(
            [draft.model_dump(mode="json") for draft in accepted],
            allowed_source_ids=allowed_source_ids,
            blocked_source_ids=blocked_source_ids,
            documents=documents,
            claim_eval_enabled=claim_eval_enabled,
        )
        item_filter_check = {
            "name": "item_quality_filter",
            "severity": "hard",
            "passed": accepted_result.passed,
            "detail": {
                "input_item_count": len(items),
                "accepted_item_count": len(accepted),
                "rejected_item_count": len(rejected),
                "rejected_items": rejected,
            },
        }
        return (
            accepted_result.model_copy(
                update={
                    "checks": [
                        *accepted_result.checks,
                        item_filter_check,
                    ],
                    "metrics": {
                        **accepted_result.metrics,
                        "input_item_count": len(items),
                        "accepted_item_count": len(accepted),
                        "rejected_item_count": len(rejected),
                    },
                }
            ),
            accepted,
        )

    def evaluate(
        self,
        items: list[dict[str, Any]],
        *,
        allowed_source_ids: set[str],
        blocked_source_ids: set[str],
        documents: list[dict[str, Any]] | None = None,
        claim_eval_enabled: bool = True,
    ) -> tuple[EvalResult, list[IntelEventDraft]]:
        checks: list[dict[str, Any]] = []
        drafts: list[IntelEventDraft] = []
        schema_errors: list[str] = []
        documents_by_id = {
            str(document.get("source_id")): document
            for document in documents or []
            if document.get("source_id")
        }

        for index, item in enumerate(items):
            try:
                draft = IntelEventDraft.model_validate(item)
                if documents_by_id and claim_eval_enabled:
                    draft = draft.model_copy(
                        update={
                            "facts": [
                                fact
                                if fact.citations
                                else fact.model_copy(
                                    update={
                                        "citations": build_fact_citations(
                                            fact.text,
                                            fact.source_ids,
                                            documents_by_id,
                                        )
                                    }
                                )
                                for fact in draft.facts
                            ]
                        }
                    )
                drafts.append(draft)
            except Exception as exc:
                schema_errors.append(f"item[{index}]: {exc}")

        checks.append(
            {
                "name": "output_schema",
                "severity": "hard",
                "passed": not schema_errors,
                "detail": "结构化输出符合 IntelEventDraft Schema"
                if not schema_errors
                else schema_errors,
            }
        )

        item_source_ids = {
            source_id for draft in drafts for source_id in draft.source_ids
        }
        fact_source_ids = {
            source_id
            for draft in drafts
            for fact in draft.facts
            for source_id in fact.source_ids
        }
        inference_source_ids = {
            source_id
            for draft in drafts
            for inference in draft.inferences
            for source_id in inference.source_ids
        }
        translation_source_ids = {
            translation.source_id
            for draft in drafts
            for translation in draft.source_translations
        }
        structured_citation_source_ids = {
            citation.source_id
            for draft in drafts
            for fact in draft.facts
            for citation in fact.citations
        }
        cited_source_ids = (
            item_source_ids
            | fact_source_ids
            | inference_source_ids
            | translation_source_ids
            | structured_citation_source_ids
        )
        missing_sources = sorted(cited_source_ids - allowed_source_ids)
        checks.append(
            {
                "name": "source_integrity",
                "severity": "hard",
                "passed": not missing_sources,
                "detail": "所有 Source ID 都来自当前 Run"
                if not missing_sources
                else {"missing_source_ids": missing_sources},
            }
        )

        blocked_citations = sorted(cited_source_ids & blocked_source_ids)
        checks.append(
            {
                "name": "prompt_injection_boundary",
                "severity": "hard",
                "passed": not blocked_citations,
                "detail": "疑似 Prompt Injection 来源没有进入最终情报"
                if not blocked_citations
                else {"blocked_source_ids": blocked_citations},
            }
        )

        unlisted_citations = sorted(
            (
                fact_source_ids
                | inference_source_ids
                | translation_source_ids
                | structured_citation_source_ids
            )
            - item_source_ids
        )
        checks.append(
            {
                "name": "citation_consistency",
                "severity": "hard",
                "passed": not unlisted_citations,
                "detail": "事实、推断与引文的来源都包含在事件 source_ids 中"
                if not unlisted_citations
                else {"unlisted_source_ids": unlisted_citations},
            }
        )

        total_facts = sum(len(draft.facts) for draft in drafts)
        cited_facts = sum(
            1 for draft in drafts for fact in draft.facts if fact.source_ids
        )
        structured_supported_facts = 0
        invalid_quotes: list[dict[str, str]] = []
        unsupported_claims: list[str] = []
        contradiction_count = 0
        contradiction_draft_indexes: set[int] = set()
        if documents_by_id and claim_eval_enabled:
            for draft_index, draft in enumerate(drafts):
                for fact in draft.facts:
                    fact_supported = False
                    valid_citation_source_ids: set[str] = set()
                    for citation in fact.citations:
                        document = documents_by_id.get(citation.source_id)
                        body = str((document or {}).get("body") or "")
                        quote_is_present = (
                            bool(body)
                            and _normalized_text(citation.quote)
                            in _normalized_text(body)
                        )
                        hash_is_valid = citation.quote_hash == hashlib.sha256(
                            citation.quote.encode("utf-8")
                        ).hexdigest()
                        if not quote_is_present or not hash_is_valid:
                            invalid_quotes.append(
                                {
                                    "source_id": citation.source_id,
                                    "claim": fact.text,
                                }
                            )
                            continue
                        valid_citation_source_ids.add(citation.source_id)
                        if citation.relation == "supports":
                            fact_supported = True
                        elif citation.relation == "contradicts":
                            contradiction_count += 1
                            contradiction_draft_indexes.add(draft_index)
                    if not fact_supported:
                        fact_supported = any(
                            document_supports_claim(
                                fact.text,
                                documents_by_id[source_id],
                            )
                            for source_id in valid_citation_source_ids
                            if source_id in documents_by_id
                        )
                    if fact_supported:
                        structured_supported_facts += 1
                    else:
                        unsupported_claims.append(fact.text)
            for draft_index in contradiction_draft_indexes:
                draft = drafts[draft_index]
                drafts[draft_index] = draft.model_copy(
                    update={
                        "verification_status": "conflicting",
                        "confidence_level": "low",
                        "confidence_score": min(
                            draft.confidence_score, 0.55
                        ),
                        "confidence_reason": (
                            f"{draft.confidence_reason}"
                            " 检测到来源对关键事实存在冲突，已降低置信度。"
                        ),
                    }
                )
        else:
            structured_supported_facts = cited_facts

        checks.append(
            {
                "name": "fact_citation_coverage",
                "severity": "hard",
                "passed": not unsupported_claims,
                "detail": "每条事实都有可定位的支持性引文"
                if not unsupported_claims
                else {"unsupported_claims": unsupported_claims},
            }
        )
        checks.append(
            {
                "name": "citation_quote_integrity",
                "severity": "hard",
                "passed": not invalid_quotes,
                "detail": "引文正文与哈希均可在当前 Run 来源中校验"
                if not invalid_quotes
                else {"invalid_quotes": invalid_quotes},
            }
        )
        checks.append(
            {
                "name": "contradiction_handling",
                "severity": "hard",
                "passed": all(
                    draft.verification_status == "conflicting"
                    and draft.confidence_score <= 0.55
                    for index, draft in enumerate(drafts)
                    if index in contradiction_draft_indexes
                ),
                "detail": {
                    "contradiction_count": contradiction_count,
                    "affected_item_count": len(
                        contradiction_draft_indexes
                    ),
                },
            }
        )

        unfaithful_summaries: list[dict[str, Any]] = []
        if documents_by_id and claim_eval_enabled:
            for draft in drafts:
                evidence_text = "\n".join(
                    str(documents_by_id.get(source_id, {}).get("body") or "")
                    for source_id in draft.source_ids
                )
                contextual_years: set[int] = set()
                for source_id in draft.source_ids:
                    published_at = str(
                        documents_by_id.get(source_id, {}).get(
                            "published_at"
                        )
                        or ""
                    )
                    year_match = re.match(r"(\d{4})-", published_at)
                    if year_match:
                        contextual_years.add(int(year_match.group(1)))
                missing_numbers = find_unsupported_numbers(
                    draft.summary,
                    evidence_text,
                    contextual_years=contextual_years,
                )
                if missing_numbers:
                    unfaithful_summaries.append(
                        {
                            "title": draft.title,
                            "missing_numbers": missing_numbers,
                        }
                    )
        checks.append(
            {
                "name": "summary_faithfulness",
                "severity": "hard",
                "passed": not unfaithful_summaries,
                "detail": "摘要中的关键数字均可回溯到事件来源"
                if not unfaithful_summaries
                else {"items": unfaithful_summaries},
            }
        )

        relevance_results: list[bool] = []
        story_consistency_results: list[bool] = []
        novelty_results: list[bool] = []
        evidence_independence_scores: list[float] = []
        all_evidence_chain_ids: set[str] = set()
        duplicate_event_count = 0
        seen_cluster_ids: set[str] = set()
        for draft in drafts:
            draft_documents = [
                documents_by_id[source_id]
                for source_id in draft.source_ids
                if source_id in documents_by_id
            ]
            if not draft_documents:
                continue
            relevance_scores = [
                float(document.get("relevance_score") or 0)
                for document in draft_documents
            ]
            relevance_results.append(
                max(relevance_scores, default=0) >= 0.35
                or any(
                    document.get("source_type")
                    in {"official", "policy", "research"}
                    for document in draft_documents
                )
            )
            cluster_ids = {
                str(document.get("cluster_id"))
                for document in draft_documents
                if document.get("cluster_id")
            }
            story_consistency_results.append(len(cluster_ids) <= 1)
            novelty_results.append(
                any(
                    float(document.get("novelty_score") or 0) >= 0.45
                    and document.get("cluster_relation") != "duplicate"
                    for document in draft_documents
                )
            )
            duplicate_event_count += sum(
                document.get("cluster_relation") == "duplicate"
                for document in draft_documents
            )
            new_cluster_ids = cluster_ids - seen_cluster_ids
            if cluster_ids and not new_cluster_ids:
                novelty_results[-1] = False
            seen_cluster_ids |= cluster_ids
            chain_ids = {
                str(document.get("evidence_chain_id"))
                for document in draft_documents
                if document.get("evidence_chain_id")
            }
            all_evidence_chain_ids |= chain_ids
            evidence_independence_scores.append(
                min(1.0, len(chain_ids) / 3)
            )

        checks.extend(
            [
                {
                    "name": "relevance_quality",
                    "severity": "soft",
                    "passed": all(relevance_results),
                    "detail": {
                        "passed_items": sum(relevance_results),
                        "evaluated_items": len(relevance_results),
                    },
                },
                {
                    "name": "story_consistency",
                    "severity": "soft",
                    "passed": all(story_consistency_results),
                    "detail": {
                        "passed_items": sum(story_consistency_results),
                        "evaluated_items": len(
                            story_consistency_results
                        ),
                    },
                },
                {
                    "name": "novelty_quality",
                    "severity": "soft",
                    "passed": all(novelty_results),
                    "detail": {
                        "passed_items": sum(novelty_results),
                        "evaluated_items": len(novelty_results),
                    },
                },
                {
                    "name": "evidence_independence",
                    "severity": "soft",
                    "passed": all(
                        score >= 1 / 3
                        for score in evidence_independence_scores
                    ),
                    "detail": {
                        "average_score": round(
                            sum(evidence_independence_scores)
                            / max(1, len(evidence_independence_scores)),
                            3,
                        )
                    },
                },
            ]
        )

        hard_checks = [
            check
            for check in checks
            if check.get("severity", "hard") == "hard"
        ]
        passed = all(bool(check["passed"]) for check in hard_checks)

        def rate(results: list[bool]) -> float:
            return (
                round(sum(results) / len(results), 3)
                if results
                else 1.0
            )

        return (
            EvalResult(
                passed=passed,
                checks=checks,
                metrics={
                    "item_count": len(drafts),
                    "fact_count": total_facts,
                    "citation_coverage": (
                        round(cited_facts / total_facts, 3)
                        if total_facts
                        else 1.0
                    ),
                    "citation_support_rate": (
                        round(
                            structured_supported_facts / total_facts, 3
                        )
                        if total_facts
                        else 1.0
                    ),
                    "supported_fact_count": structured_supported_facts,
                    "relevance_pass_rate": rate(relevance_results),
                    "summary_faithfulness_rate": (
                        round(
                            (len(drafts) - len(unfaithful_summaries))
                            / len(drafts),
                            3,
                        )
                        if drafts
                        else 1.0
                    ),
                    "story_consistency_rate": rate(
                        story_consistency_results
                    ),
                    "duplicate_collapse_rate": rate(novelty_results),
                    "duplicate_event_count": duplicate_event_count,
                    "evidence_independence_score": round(
                        sum(evidence_independence_scores)
                        / max(1, len(evidence_independence_scores)),
                        3,
                    ),
                    "contradiction_count": contradiction_count,
                    "summary_overreach_count": len(
                        unfaithful_summaries
                    ),
                    "independent_evidence_chain_count": len(
                        all_evidence_chain_ids
                    ),
                    "blocked_source_count": len(blocked_source_ids),
                },
            ),
            drafts,
        )
