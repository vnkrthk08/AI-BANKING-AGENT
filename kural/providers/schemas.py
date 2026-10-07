from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kural.models import Intent


class IntentProposal(BaseModel):
    """A semantic classification proposal; never an instruction to take action."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent = Field(default=Intent.OTHER, description="The primary recognized intent")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    entities: dict[str, Any] = Field(default_factory=dict, description="Extracted slot entities e.g. date, app_installed")
    secondary_question: str | None = Field(default=None, description="Recognized side question e.g. APP_FEATURES, WHO_ARE_YOU, IS_IT_FREE")
    issue_present: bool = Field(default=False, description="Whether customer reported an app or technical issue")
    issue_category: str | None = Field(default=None, description="Category of issue: PAYMENT, LOGIN, UPDATE_CRASH, BIOMETRIC, NETWORK, GENERAL")
    issue_description: str | None = Field(default=None, description="Concise description of the reported issue")
    human_assistance_required: bool = Field(default=False, description="Whether customer needs or requested human assistance")
    customer_facts: dict[str, Any] = Field(default_factory=dict, description="Extracted customer facts e.g. {'app_installed': True}")
    callback_requested: bool = Field(default=False, description="Whether customer requested a callback")
    safety_flag: bool = Field(default=False, description="Whether customer utterance mentioned sensitive authentication data")

    @property
    def primary_intent(self) -> Intent:
        """Compatibility property for callers expecting .primary_intent."""
        return self.intent

    @model_validator(mode="before")
    @classmethod
    def handle_intent_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "primary_intent" in data and "intent" not in data:
                data["intent"] = data.pop("primary_intent")
            elif "primary_intent" in data and "intent" in data:
                data.pop("primary_intent")
        return data

    @field_validator("intent")
    @classmethod
    def reject_policy_only_intent(cls, value: Intent) -> Intent:
        if value == Intent.SENSITIVE_DATA:
            raise ValueError("Sensitive-data decisions belong to KURAL safety policy")
        return value

