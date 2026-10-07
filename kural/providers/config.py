"""Small environment-based provider configuration and factory."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

from kural.providers.contracts import LLMProvider
from kural.providers.gemini import GeminiAdapter, ProviderConfigurationError
from kural.providers.openai_compatible import OpenAICompatibleAdapter
from kural.providers.schemas import IntentProposal


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None = None
    timeout: float = 2.0


def load_llm_settings() -> LLMSettings:
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "2.0").strip())

    if provider == "groq":
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        api_key = os.getenv("GROQ_API_KEY")
        base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        return LLMSettings(provider=provider, model=model, api_key=api_key, base_url=base_url, timeout=timeout)
    elif provider in {"openrouter", "qwen"}:
        model = os.getenv("OPENROUTER_MODEL", "qwen/qwen3.8-27b").strip()
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        return LLMSettings(provider=provider, model=model, api_key=api_key, base_url=base_url, timeout=timeout)

    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    api_key = os.getenv("GEMINI_API_KEY")
    return LLMSettings(provider=provider, model=model, api_key=api_key, timeout=timeout)


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
        return GeminiAdapter(api_key=settings.api_key, model=settings.model, timeout_seconds=settings.timeout)
    elif settings.provider in {"groq", "openrouter", "qwen"}:
        return OpenAICompatibleAdapter(
            api_key=settings.api_key,
            model=settings.model,
            base_url=settings.base_url or "https://api.groq.com/openai/v1",
            timeout=settings.timeout,
            provider_name=settings.provider,
        )
    return UnavailableLLMProvider(
        settings.provider or "unconfigured", settings.model,
        "Configured LLM provider is not available",
    )


get_llm_provider = create_llm_provider


