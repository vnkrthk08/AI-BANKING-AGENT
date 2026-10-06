"""Explicit, one-request Gemini development smoke check; never run by pytest."""

import os
import re
import sys

from dotenv import load_dotenv

from kural.providers.gemini import GeminiAdapter, ProviderConfigurationError


def _redact_diagnostic(value: object, api_key: str | None) -> str:
    message = str(value)
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "[REDACTED_API_KEY]", message)
    message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)(x-goog-api-key|gemini_api_key|api[_ -]?key|[?&]key)\s*[:=]\s*['\"]?[^&\s,'\"}\]]+",
        r"\1=[REDACTED]",
        message,
    )
    return message[:1200]


def _find_reason(value: object) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == "reason" and isinstance(item, (str, int, float)):
                return str(item)
        for item in value.values():
            found = _find_reason(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_reason(item)
            if found is not None:
                return found
    return None


def _report_api_error(error: Exception, api_key: str | None) -> None:
    status_code = getattr(error, "code", None)
    http_response = getattr(error, "response", None)
    if status_code is None and http_response is not None:
        status_code = getattr(http_response, "status_code", None)
    status = getattr(error, "status", None)
    message = getattr(error, "message", None) or "No API message provided"
    reason = _find_reason(getattr(error, "details", None))
    print(f"Gemini smoke check failed ({type(error).__name__}).")
    print(f"http_status={status_code if status_code is not None else 'unavailable'}")
    print(f"status={_redact_diagnostic(status, api_key) if status else 'unavailable'}")
    print(f"reason={_redact_diagnostic(reason, api_key) if reason else 'unavailable'}")
    print(f"message={_redact_diagnostic(message, api_key)}")


def main() -> int:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    adapter = GeminiAdapter(
        api_key=api_key,
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
    )
    try:
        proposal = adapter.classify("My banking app is not updating")
    except ProviderConfigurationError as error:
        print(f"Gemini smoke check unavailable: {error}")
        return 2
    except Exception as error:
        _report_api_error(error, api_key)
        return 1

    print(f"intent={proposal.intent.value} confidence={proposal.confidence:.3f}")
    return 0 if proposal.intent.value == "APP_UPDATE_ISSUE" else 1


if __name__ == "__main__":
    sys.exit(main())
