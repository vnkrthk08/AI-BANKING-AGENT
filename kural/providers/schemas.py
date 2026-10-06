"""Validated, deliberately minimal outputs accepted from language providers."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kural.models import Intent


class IntentProposal(BaseModel):
    """A semantic classification proposal; never an instruction to take action."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("intent")
    @classmethod
    def reject_policy_only_intent(cls, value: Intent) -> Intent:
        if value == Intent.SENSITIVE_DATA:
            raise ValueError("Sensitive-data decisions belong to KURAL safety policy")
        return value
