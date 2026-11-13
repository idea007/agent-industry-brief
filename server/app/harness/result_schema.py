from __future__ import annotations

from typing import Any


def _object_schema(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STRING = {"type": "string"}
_NUMBER = {"type": "number"}
_STRINGS = {"type": "array", "items": _STRING}
_SOURCE_QUOTES = {
    "type": "array",
    "minItems": 1,
    "items": _object_schema(
        source_id=_STRING,
        quote={"type": "string", "minLength": 1, "maxLength": 320},
    ),
}

# The model supplies source quotes. Eval builds and checks the stored citations.
RESEARCH_RESULT_SCHEMA = _object_schema(
    kind={"type": "string", "enum": ["structured_result"]},
    research_summary=_STRING,
    items={
        "type": "array",
        "items": _object_schema(
            title=_STRING,
            summary=_STRING,
            category=_STRING,
            tags=_STRINGS,
            event_time=_STRING,
            importance_score=_NUMBER,
            importance_reason=_STRING,
            confidence_level=_STRING,
            confidence_score=_NUMBER,
            confidence_reason=_STRING,
            verification_status=_STRING,
            facts={
                "type": "array",
                "minItems": 1,
                "items": _object_schema(
                    text=_STRING,
                    source_ids=_STRINGS,
                    source_quotes=_SOURCE_QUOTES,
                ),
            },
            inferences={
                "type": "array",
                "items": _object_schema(text=_STRING, source_ids=_STRINGS),
            },
            source_ids=_STRINGS,
            source_translations={
                "type": "array",
                "items": _object_schema(source_id=_STRING, content_zh=_STRING),
            },
        ),
    },
)
