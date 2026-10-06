"""Small environment-based provider configuration and factory."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

from kural.providers.contracts import LLMProvider
from kural.providers.gemini import GeminiAdapter, ProviderConfigurationError
from kural.providers.schemas import IntentProposal


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: str | None


def load_llm_settings() -> LLMSettings:
    # Keep .env loading consistent with DATABASE_URL configuration.
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    api_key = os.getenv("GEMINI_API_KEY")
    return LLMSettings(provider=provider, model=model, api_key=api_key)


class UnavailableLLMProvider:
    """Configuration fallback that lets KURAL continue without an LLM."""

    def __init__(self, provider_name: str, model_name: str, reason: str) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.reason = reason

    def classify(self, text: str) -> IntentProposal:
        del text
        raise ProviderConfigurationError(self.reason)


def create_llm_provider() -> LLMProvider:
    settings = load_llm_settings()
    if settings.provider == "gemini":
        return GeminiAdapter(api_key=settings.api_key, model=settings.model)
    return UnavailableLLMProvider(
        settings.provider or "unconfigured", settings.model,
        "Configured LLM provider is not available",
    )
