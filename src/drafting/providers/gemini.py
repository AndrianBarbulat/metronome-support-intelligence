"""Gemini provider for grounded drafting via Google Generative AI SDK."""

from __future__ import annotations

import json
import os
import time
import logging

from src.drafting.providers.base import DraftingProvider
from src.drafting.providers.errors import (
    DraftingConfigurationError,
    DraftingRateLimitError,
    DraftingTimeoutError,
    DraftingInvalidResponseError,
    DraftingProviderError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds
_REQUEST_TIMEOUT = 60  # seconds


class GeminiDraftingProvider:
    """Gemini-based drafting provider using the google-genai SDK.

    Reads configuration from environment variables:

    * ``GEMINI_API_KEY``  (required)
    * ``GEMINI_MODEL``    (required)
    * ``DRAFTING_TEMPERATURE`` (default 0.2)
    * ``DRAFTING_MAX_OUTPUT_TOKENS`` (default 2048)
    """

    provider_name = "gemini"

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise DraftingConfigurationError(
                "GEMINI_API_KEY environment variable is not set. "
                "Set it in .env or use DRAFTING_PROVIDER=mock for development."
            )

        model = os.getenv("GEMINI_MODEL", "").strip()
        if not model:
            raise DraftingConfigurationError(
                "GEMINI_MODEL environment variable is not set. "
                "Set it in .env or use DRAFTING_PROVIDER=mock for development."
            )

        self.model_name = model
        self._api_key = api_key
        self._temperature = float(os.getenv("DRAFTING_TEMPERATURE", "0.2"))
        self._max_output_tokens = int(os.getenv("DRAFTING_MAX_OUTPUT_TOKENS", "2048"))

    def generate(
        self,
        *,
        system_instruction: str,
        structured_input: dict[str, object],
        output_schema: dict[str, object],
    ) -> dict[str, object]:
        """Generate a structured draft via the Gemini API.

        Uses bounded exponential backoff for transient failures.
        Does NOT retry authentication or invalid-request errors.
        Never logs the API key or full sensitive grounding packages.
        """
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)

        # Build the prompt
        full_prompt = _build_prompt(system_instruction, structured_input, output_schema)

        model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config={
                "temperature": self._temperature,
                "max_output_tokens": self._max_output_tokens,
            },
        )

        last_exception: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = model.generate_content(
                    full_prompt,
                    request_options={"timeout": _REQUEST_TIMEOUT},
                )

                # Parse response
                text = response.text.strip()
                if not text:
                    raise DraftingInvalidResponseError("Gemini returned empty response.")

                # Try to parse JSON from response
                parsed = _extract_json(text)

                # Validate against output schema
                _validate_output(parsed, output_schema)

                return parsed

            except DraftingProviderError:
                raise
            except Exception as exc:
                last_exception = exc
                retryable = _is_retryable(exc)

                if not retryable:
                    logger.error("Non-retryable Gemini error: %s", exc)
                    raise DraftingProviderError(f"Gemini error: {exc}") from exc

                if attempt < _MAX_RETRIES:
                    backoff = _INITIAL_BACKOFF * (2 ** attempt)
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
                    raise DraftingProviderError(
                        f"Gemini failed after {_MAX_RETRIES} retries: {exc}"
                    ) from exc

        raise DraftingProviderError(
            f"Gemini error: {last_exception}"
        ) from last_exception


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_prompt(
    system_instruction: str,
    structured_input: dict[str, object],
    output_schema: dict[str, object],
) -> str:
    """Build the full prompt combining system instruction and structured input."""
    input_json = json.dumps(structured_input, ensure_ascii=False, indent=2)
    schema_json = json.dumps(output_schema, ensure_ascii=False, indent=2)

    return (
        f"{system_instruction}\n\n"
        f"Here is the structured grounding data:\n\n"
        f"{input_json}\n\n"
        f"Respond with valid JSON matching this schema:\n\n"
        f"{schema_json}\n\n"
        f"Return ONLY the JSON object, with no additional text or markdown formatting."
    )


def _extract_json(text: str) -> dict[str, object]:
    """Extract a JSON object from model output, handling markdown code fences."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence
        lines = text.split("\n")
        end_idx = len(lines)
        for i, line in enumerate(lines):
            if i > 0 and line.strip().startswith("```"):
                end_idx = i
                break
        text = "\n".join(lines[1:end_idx])

    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise DraftingInvalidResponseError(
                f"Gemini returned {type(parsed).__name__} instead of a JSON object."
            )
        return parsed
    except json.JSONDecodeError as exc:
        raise DraftingInvalidResponseError(
            f"Gemini returned invalid JSON: {exc}"
        ) from exc


def _validate_output(data: dict[str, object], schema: dict[str, object]) -> None:
    """Verify that *data* has the required keys from *schema*."""
    required_keys = set(schema.get("properties", {}).keys())
    # "body" is essential
    if "body" not in data or not isinstance(data["body"], str) or not data["body"].strip():
        raise DraftingInvalidResponseError("Gemini response missing non-empty 'body' field.")

    for key in ["subject", "used_fact_codes", "used_source_urls", "claim_map"]:
        if key not in data:
            raise DraftingInvalidResponseError(
                f"Gemini response missing required field: '{key}'"
            )


def _is_retryable(exc: Exception) -> bool:
    """Determine if an exception represents a transient failure."""
    exc_str = str(exc).lower()

    retryable_indicators = [
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
    if any(ind in exc_str for ind in retryable_indicators):
        return True

    # Check for HTTP status codes in the exception
    for status in _RETRYABLE_STATUSES:
        if str(status) in exc_str:
            return True

    return False