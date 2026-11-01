"""Reusable Gemini client (official `google-genai` SDK).

- Reads GEMINI_* configuration from the shared settings; the API key is
  never logged, returned or persisted.
- Tolerates a missing SDK/key: the backend starts normally and only AI
  endpoints return a clear configuration error.
- Translates upstream failures into typed application errors
  (auth/model/network -> AiUpstreamError, quota/rate limit -> AiQuotaError).
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.exceptions import (
    AiNotConfiguredError,
    AiQuotaError,
    AiUpstreamError,
)

logger = logging.getLogger("reliefmesh.ai.client")

# Imported lazily/optionally so the app runs even without the package.
try:  # pragma: no cover - exercised implicitly
    from google import genai
    from google.genai import types as genai_types

    _SDK_ERROR_BASE: tuple[type[Exception], ...] | None = None
    for candidate in ("APIError", "ClientError", "ServerError"):
        if hasattr(genai_errors := __import__(
            "google.genai.errors", fromlist=["errors"]), candidate
        ):
            _SDK_ERROR_BASE = _SDK_ERROR_BASE or ()
            _SDK_ERROR_BASE += (getattr(genai_errors, candidate),)
    if _SDK_ERROR_BASE is None:  # pragma: no cover - defensive
        _SDK_ERROR_BASE = (Exception,)
except ImportError:  # pragma: no cover - SDK not installed
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]
    _SDK_ERROR_BASE = None


try:
    from groq import Groq
    from groq import APIError as GroqAPIError
except ImportError:
    Groq = None  # type: ignore[assignment]
    GroqAPIError = Exception  # type: ignore[assignment]


class GroqClient:
    """Wrapper around `groq.Groq` for OpenAI-compatible chat completions."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        if not api_key or not api_key.strip():
            raise AiNotConfiguredError(
                "GROQ_API_KEY is not configured; AI endpoints are unavailable.",
                details={"hint": "Set GROQ_API_KEY in backend/.env"},
            )
        if Groq is None:
            raise AiNotConfiguredError(
                "The groq SDK is not installed.",
                details={"hint": "pip install groq"},
            )
        self.model = model
        self.provider = "groq"
        self._client = Groq(api_key=api_key, timeout=timeout_seconds)

    def chat_completion(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": settings.gemini_temperature,
                "max_tokens": settings.gemini_max_output_tokens,
            }
            if tools:
                kwargs["tools"] = tools
            return self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise _translate_groq_error(exc) from exc


def _translate_groq_error(exc: Exception) -> AiUpstreamError | AiQuotaError:
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if status in (401, 403) or "api key" in text or "unauthorized" in text:
        return AiUpstreamError(
            "Groq rejected credentials (authentication failed).",
            details={"upstream_status": status},
        )
    if status == 429 or "rate limit" in text or "quota" in text:
        return AiQuotaError(
            "Groq rate limit exceeded. Try again shortly.",
            details={"upstream_status": status},
        )
    if status == 404 or "model" in text and "not found" in text:
        return AiUpstreamError(
            "The configured Groq model is unavailable.",
            details={"upstream_status": status, "model": settings.groq_model},
        )
    if "timeout" in text or "connection" in text:
        return AiUpstreamError(
            "Groq request timed out or the network is unreachable.",
            details={"upstream_status": status},
        )
    logger.warning("Groq upstream error: %s (status=%s)", type(exc).__name__, status)
    return AiUpstreamError(
        f"Groq upstream error: {str(exc)[:200]}",
        details={"upstream_status": status},
    )


class GeminiClient:
    """Thin wrapper around `google.genai.Client` for content generation."""

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        if not api_key or not api_key.strip():
            raise AiNotConfiguredError(
                "GEMINI_API_KEY is not configured; AI endpoints are unavailable.",
                details={"hint": "Set GEMINI_API_KEY in backend/.env"},
            )
        if genai is None:  # pragma: no cover - guarded by ImportError branch
            raise AiNotConfiguredError(
                "The google-genai SDK is not installed.",
                details={"hint": "pip install google-genai"},
            )
        self.model = model
        self.provider = "google-gemini"
        # The SDK builds on httpx; timeout applies per request.
        self._client = genai.Client(api_key=api_key, http_options={"timeout": timeout_seconds * 1000})

    def generate_response(self, contents: list[Any], config: Any) -> Any:
        """Call `models.generate_content` with typed upstream error mapping."""
        try:
            return self._client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except _SDK_ERROR_BASE as exc:  # type: ignore[misc]
            raise _translate_sdk_error(exc) from exc


def _translate_sdk_error(exc: Exception) -> AiUpstreamError | AiQuotaError:
    """Map an upstream SDK failure onto our typed application errors."""
    message = type(exc).__name__
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc).lower()
    # Never echo full payloads; a short class/status summary is enough.
    if (status in (401, 403)) or "api key" in text or "unauthenticated" in text or "permission" in text:
        return AiUpstreamError(
            "Gemini rejected the credentials (authentication failed).",
            details={"upstream_status": status},
        )
    if isinstance(status, int) and status == 429 or "quota" in text or "rate limit" in text:
        return AiQuotaError(
            "Gemini quota/rate limit exhausted. Try again shortly.",
            details={"upstream_status": status},
        )
    if isinstance(status, int) and status == 404 or "model" in text and "not found" in text:
        return AiUpstreamError(
            "The configured Gemini model is unavailable.",
            details={"upstream_status": status, "model": settings.gemini_model},
        )
    if "timeout" in text or "timed out" in text or "connection" in text:
        return AiUpstreamError(
            "Gemini request timed out or the network is unreachable.",
            details={"upstream_status": status},
        )
    logger.warning("Gemini upstream error: %s (status=%s)", message, status)
    return AiUpstreamError(
        "Gemini upstream is temporarily unavailable.",
        details={"upstream_status": status},
    )


def get_ai_client() -> GroqClient | GeminiClient:
    """Build (or reuse) the configured AI client (Groq prioritised)."""
    global _CLIENT_SINGLETON
    if not settings.ai_ready:
        raise AiNotConfiguredError(
            "AI integration is not configured/enabled.",
            details={"ai_enabled": settings.groq_enabled or settings.gemini_enabled, "key_configured": False},
        )
    cached = _CLIENT_SINGLETON
    if cached is not None:
        return cached

    if settings.groq_enabled and settings.groq_api_key.strip():
        client = GroqClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    else:
        client = GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    _CLIENT_SINGLETON = client
    return client


def get_gemini_client() -> GroqClient | GeminiClient:
    """Backward-compatible alias for get_ai_client."""
    return get_ai_client()


_CLIENT_SINGLETON: GroqClient | GeminiClient | None = None


def reset_gemini_client() -> None:
    """Clear the cached client."""
    global _CLIENT_SINGLETON
    _CLIENT_SINGLETON = None
