"""Tests for mock and Gemini drafting providers."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import os
import pytest

from src.drafting.providers.mock import MockDraftingProvider, MOCK_MODES
from src.drafting.providers.errors import (
    DraftingProviderError,
    DraftingConfigurationError,
    DraftingInvalidResponseError,
)

# Sample grounding input used across tests
_SAMPLE_INPUT = {
    "draft_type": "customer_update",
    "audience": "customer",
    "tone": "professional",
    "confirmed_facts": [
        {
            "fact_code": "request.endpoint.present",
            "statement": "Request hit POST /v1/contracts/create.",
            "fact_type": "request_evidence",
            "evidence_reference": "ticket.1",
            "confirmation_status": "observed",
        }
    ],
    "observed_facts": [
        {
            "fact_code": "response.status.present",
            "statement": "Response returned HTTP 409.",
            "fact_type": "response_evidence",
            "evidence_reference": "ticket.1",
            "confirmation_status": "observed",
        }
    ],
    "documentation_facts": [],
    "hypotheses": [
        {
            "fact_code": "hyp.uniqueness",
            "statement": "Uniqueness key may have been reused.",
            "fact_type": "hypothesis",
            "evidence_reference": "ticket.1",
            "confirmation_status": "unconfirmed",
        }
    ],
    "missing_evidence": [],
    "resolution_facts": [],
    "feedback_facts": [],
    "documentation_sources": [
        {"source_url": "https://docs.metronome.com/api/contracts/create"}
    ],
    "allowed_identifiers": {},
    "required_sections": ["Acknowledgement", "Next steps"],
}


class TestMockProviderValidModes:
    """Tests for valid mock provider behavior."""

    def test_valid_mode_returns_structured_output(self):
        provider = MockDraftingProvider(mode="valid")
        result = provider.generate(
            system_instruction="Test instruction.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert isinstance(result, dict)
        assert "subject" in result
        assert "body" in result
        assert "used_fact_codes" in result
        assert "used_source_urls" in result
        assert "claim_map" in result

    def test_valid_mode_subject_is_string(self):
        provider = MockDraftingProvider(mode="valid")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert isinstance(result["subject"], str)

    def test_valid_mode_body_not_empty(self):
        provider = MockDraftingProvider(mode="valid")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert len(result["body"]) > 0

    def test_valid_mode_used_fact_codes_is_list(self):
        provider = MockDraftingProvider(mode="valid")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert isinstance(result["used_fact_codes"], list)
        assert len(result["used_fact_codes"]) > 0

    def test_valid_mode_used_source_urls_is_list(self):
        provider = MockDraftingProvider(mode="valid")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert isinstance(result["used_source_urls"], list)

    def test_valid_mode_claim_map_is_list(self):
        provider = MockDraftingProvider(mode="valid")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert isinstance(result["claim_map"], list)

    def test_provider_name_and_model(self):
        provider = MockDraftingProvider(mode="valid")
        assert provider.provider_name == "mock"
        assert provider.model_name == "mock-deterministic"


class TestMockProviderInvalidModes:
    """Tests for mock provider error/invalid modes."""

    def test_unknown_fact_mode(self):
        provider = MockDraftingProvider(mode="unknown_fact")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert result["used_fact_codes"][0] == "contract.created.success"

    def test_unknown_source_mode(self):
        provider = MockDraftingProvider(mode="unknown_source")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert "docs.example.com/not-in-grounding" in result["used_source_urls"][0]

    def test_unsupported_root_cause_mode(self):
        provider = MockDraftingProvider(mode="unsupported_root_cause")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert "root cause" in result["body"].lower()

    def test_unlabelled_hypothesis_mode(self):
        provider = MockDraftingProvider(mode="unlabelled_hypothesis")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        body = result["body"].lower()
        # Should contain hypothesis claim without hedging
        assert "reused" in body

    def test_secret_leak_mode(self):
        provider = MockDraftingProvider(mode="secret_leak")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        assert "sk_live" in result["body"]

    def test_missing_section_mode(self):
        provider = MockDraftingProvider(mode="missing_section")
        result = provider.generate(
            system_instruction="Test.",
            structured_input=_SAMPLE_INPUT,
            output_schema={},
        )
        # Very short body, missing required sections
        assert result["subject"] is None
        assert result["claim_map"] == []

    def test_provider_failure_mode_raises(self):
        provider = MockDraftingProvider(mode="provider_failure")
        with pytest.raises(DraftingProviderError):
            provider.generate(
                system_instruction="Test.",
                structured_input=_SAMPLE_INPUT,
                output_schema={},
            )

    def test_invalid_json_mode_raises(self):
        provider = MockDraftingProvider(mode="invalid_json")
        with pytest.raises(DraftingProviderError):
            provider.generate(
                system_instruction="Test.",
                structured_input=_SAMPLE_INPUT,
                output_schema={},
            )

    def test_unknown_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown mock mode"):
            MockDraftingProvider(mode="nonexistent")


class TestGeminiProviderConfiguration:
    """Tests for Gemini provider configuration validation (no live API calls)."""

    def test_missing_api_key_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "")
        from src.drafting.providers.gemini import GeminiDraftingProvider

        with pytest.raises(DraftingConfigurationError, match="GEMINI_API_KEY"):
            GeminiDraftingProvider()

    def test_missing_model_raises_configuration_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GEMINI_MODEL", "")
        from src.drafting.providers.gemini import GeminiDraftingProvider

        with pytest.raises(DraftingConfigurationError, match="GEMINI_MODEL"):
            GeminiDraftingProvider()

    def test_valid_configuration_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
        from src.drafting.providers.gemini import GeminiDraftingProvider

        provider = GeminiDraftingProvider()
        assert provider.provider_name == "gemini"
        assert provider.model_name == "gemini-2.0-flash"

    def test_temperature_and_max_tokens_defaults(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
        from src.drafting.providers.gemini import GeminiDraftingProvider

        provider = GeminiDraftingProvider()
        assert provider._temperature == 0.2
        assert provider._max_output_tokens == 2048

    def test_custom_temperature_and_max_tokens(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
        monkeypatch.setenv("DRAFTING_TEMPERATURE", "0.1")
        monkeypatch.setenv("DRAFTING_MAX_OUTPUT_TOKENS", "1024")
        from src.drafting.providers.gemini import GeminiDraftingProvider

        provider = GeminiDraftingProvider()
        assert provider._temperature == 0.1
        assert provider._max_output_tokens == 1024