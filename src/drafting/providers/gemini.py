"""Gemini provider for grounded drafting via the google-genai SDK."""

from __future__ import annotations

import json
import logging
import os
import time

from src.drafting.providers.base import DraftingProvider
from src.drafting.providers.errors import (
    DraftingConfigurationError,
    DraftingRateLimitError,
    DraftingTimeoutError,
    DraftingInvalidResponseError,
    DraftingProviderError,
    DraftingAuthenticationError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds
_REQUEST_TIMEOUT = 60  # seconds (applied via httpx)

# HTTP status codes considered transient
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class GeminiDraftingProvider:
    """Gemini drafting provider using the ``google-genai`` SDK (``google.genai``).

    Environment Variables
    ---------------------
    ``GEMINI_API_KEY``
        Required.  The Gemini API key.
    ``GEMINI_MODEL``
        Required.  The model name (e.g. ``"gemini-2.5-flash"``).
    ``DRAFTING_TEMPERATURE``
        Float, default ``0.2``.
    ``DRAFTING_MAX_OUTPUT_TOKENS``
        Integer, default ``2048``.
    """

    provider_name = "gemini"

    def __init__(self) -> None:
        self._api_key = _require_env("GEMINI_API_KEY")
        self.model_name = _require_env("GEMINI_MODEL")
        self._temperature = float(os.getenv("DRAFTING_TEMPERATURE", "0.2"))
        self._max_output_tokens = int(os.getenv("DRAFTING_MAX_OUTPUT_TOKENS", "2048"))
        self._timeout = float(
            os.getenv("DRAFTING_REQUEST_TIMEOUT", str(_REQUEST_TIMEOUT))
        )

        if not (0.0 <= self._temperature <= 2.0):
            raise DraftingConfigurationError(
                f"DRAFTING_TEMPERATURE must be 0.0–2.0, got {self._temperature}"
            )
        if self._max_output_tokens < 1:
            raise DraftingConfigurationError(
                f"DRAFTING_MAX_OUTPUT_TOKENS must be >= 1, got {self._max_output_tokens}"
            )

    # ------------------------------------------------------------------
    def generate(
        self,
        *,
        system_instruction: str,
        structured_input: dict[str, object],
        output_schema: dict[str, object],
    ) -> dict[str, object]:
        """Generate a structured draft via the Gemini API."""
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._api_key,
            http_options={"timeout": self._timeout * 1000},  # milliseconds
        )

        # Build the contents – combine system instruction & grounding input
        contents = _build_contents(system_instruction, structured_input)

        config = types.GenerateContentConfig(
            temperature=self._temperature,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=output_schema,
        )

        last_exception: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )

                # Prefer parsed when available, else parse text
                parsed = _extract_parsed(response, output_schema)
                return parsed

            except DraftingProviderError:
                raise
            except Exception as exc:
                last_exception = exc
                retryable = _is_retryable(exc)

                if not retryable:
                    logger.error("Non-retryable Gemini error: %s", exc)
                    _raise_normalized(exc)

                if attempt < _MAX_RETRIES:
                    backoff = _INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        "Gemini retryable error (attempt %d/%d): %s. "
                        "Backing off %.1fs.",
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        backoff,
                    )
                    time.sleep(backoff)
                else:
                    _raise_normalized(exc)

        raise DraftingProviderError(
            f"Gemini failed after {_MAX_RETRIES} retries: {last_exception}"
        ) from last_exception


# ======================================================================
# Helpers
# ======================================================================


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise DraftingConfigurationError(
            f"{name} environment variable is not set."
        )
    return value


def _build_contents(
    system_instruction: str,
    structured_input: dict[str, object],
) -> str:
    input_json = json.dumps(structured_input, ensure_ascii=False, indent=2)
    return (
        f"{system_instruction}\n\n"
        f"Here is the structured grounding data:\n\n"
        f"{input_json}\n\n"
        f"Return ONLY the JSON object, with no additional text or markdown formatting."
    )


def _extract_parsed(
    response,
    output_schema: dict[str, object],
) -> dict[str, object]:
    """Extract a structured dict from the API response.

    Tries ``response.parsed`` first (typed), then falls back to
    ``response.text`` with strict JSON parsing.
    """
    # Option 1 — typed parsed output
    if hasattr(response, "parsed") and response.parsed is not None:
        parsed = response.parsed
        if isinstance(parsed, dict):
            _validate_output(parsed, output_schema)
            return parsed
        # If parsed returned a non-dict, try text fallback

    # Option 2 — text JSON parsing
    text = ""
    if hasattr(response, "text") and response.text:
        text = response.text
    elif hasattr(response, "result") and hasattr(response.result, "candidates"):
        try:
            text = response.result.candidates[0].content.parts[0].text
        except (IndexError, AttributeError):
            pass

    if not text or not text.strip():
        raise DraftingInvalidResponseError("Gemini returned empty response.")

    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        end_idx = len(lines)
        for i, line in enumerate(lines):
            if i > 0 and line.strip().startswith("```"):
                end_idx = i
                break
        text = "\n".join(lines[1:end_idx])

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DraftingInvalidResponseError(
            f"Gemini returned invalid JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise DraftingInvalidResponseError(
            f"Gemini returned {type(parsed).__name__} instead of a JSON object."
        )

    _validate_output(parsed, output_schema)
    return parsed


def _validate_output(data: dict[str, object], schema: dict[str, object]) -> None:
    if "body" not in data or not isinstance(data["body"], str) or not data["body"].strip():
        raise DraftingInvalidResponseError("Gemini response missing non-empty 'body' field.")
    for key in ("subject", "used_fact_codes", "used_source_urls", "claim_map"):
        if key not in data:
            raise DraftingInvalidResponseError(
                f"Gemini response missing required field: '{key}'"
            )


def _is_retryable(exc: Exception) -> bool:
    exc_str = str(exc).lower()
    indicators = [
        "timeout",
        "timed out",
        "connection",
        "network",
        "reset",
        "429",
        "500",
        "502",
        "503",
        "504",
        "rate limit",
        "rate-limited",
        "resource exhausted",
        "unavailable",
        "internal server error",
    ]
    if any(ind in exc_str for ind in indicators):
        return True
    for status in _RETRYABLE_STATUSES:
        if str(status) in exc_str:
            return True
    return False


def _raise_normalized(exc: Exception) -> None:
    exc_str = str(exc).lower()

    # Permanent authentication / authorization failures
    auth_indicators = [
        "api key not valid",
        "api_key not valid",
        "permission denied",
        "forbidden",
        "unauthorized",
        "authentication",
        "invalid key",
        "403",
        "401",
    ]
    if any(ind in exc_str for ind in auth_indicators):
        raise DraftingAuthenticationError(str(exc)) from exc

    # Rate limit
    rate_indicators = ["rate limit", "rate-limited", "429", "resource exhausted", "quota"]
    if any(ind in exc_str for ind in rate_indicators):
        raise DraftingRateLimitError(str(exc)) from exc

    # Timeout
    timeout_indicators = ["timeout", "timed out"]
    if any(ind in exc_str for ind in timeout_indicators):
        raise DraftingTimeoutError(str(exc)) from exc

    # Fallback
    raise DraftingProviderError(str(exc)) from exc