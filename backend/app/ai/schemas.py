"""Shape of what the model is allowed to say. The JSON Schema is sent to the provider (strict
mode: every property required, additionalProperties false); the Pydantic models re-validate
whatever comes back, regardless of which structured-output mode produced it."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AISuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_id: str = Field(min_length=1, max_length=60)
    proposed_text: str = Field(min_length=1, max_length=1500)
    reason: str = Field(max_length=800)
    requirement_ids: list[str] = Field(max_length=30)
    evidence_ids: list[str] = Field(max_length=30)
    confidence: Literal["high", "medium", "low"]


class AISuggestionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[AISuggestion] = Field(max_length=40)


SUGGESTION_BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "proposed_text": {"type": "string"},
                    "reason": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["target_id", "proposed_text", "reason", "requirement_ids", "evidence_ids", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}
SUGGESTION_BATCH_NAME = "resume_tailoring_suggestions"
