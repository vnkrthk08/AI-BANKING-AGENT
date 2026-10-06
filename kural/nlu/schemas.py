"""Strict schemas for NLU classification output per Spec §17.2."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TimeExpression(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date_text: Optional[str] = None
    time_text: Optional[str] = None
    part_of_day: Optional[str] = None
    raw: Optional[str] = None
    relative_to: Optional[str] = None
    multiple: Optional[List[dict[str, Any]]] = None


class Entities(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time_expression: Optional[TimeExpression] = None
    issue_hint: Optional[str] = None
    question_type: Optional[str] = None
    app_detail: Optional[str] = None
    identity_detail: Optional[str] = None
    requested_language: Optional[str] = None
    note: Optional[str] = None
    flag: Optional[str] = None


class NLUResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_intent: str
    secondary_intents: List[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    language: str = "en"
    entities: Entities = Field(default_factory=Entities)
    requires_human: bool = False
    requires_callback: bool = False

    # Audit & provenance metadata
    prompt_version: str = "classify.v1.txt"
    example_bank_version: str = "v1"
    model_id: str = "gemini-2.5-flash"
