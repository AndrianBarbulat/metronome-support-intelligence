"""Abstract provider protocol for drafting generation."""

from __future__ import annotations

from typing import Protocol


class DraftingProvider(Protocol):
    """Protocol that all drafting providers must implement.

    The drafting service depends on this interface rather than
    importing any specific provider directly.
    """

    provider_name: str
    model_name: str

    def generate(
        self,
        *,
        system_instruction: str,
        structured_input: dict[str, object],
        output_schema: dict[str, object],
    ) -> dict[str, object]:
        """Generate a structured draft from the supplied grounding input.

        Parameters
        ----------
        system_instruction:
            The full system prompt including version, rules, and required
            sections.
        structured_input:
            The sanitized grounding package serialized as a dictionary.
        output_schema:
            The expected JSON output schema.  The provider must return a
            dictionary matching this schema.

        Returns
        -------
        dict
            A dictionary matching the output schema.

        Raises
        ------
        DraftingProviderError
            On any failure (configuration, network, rate-limit, timeout,
            or invalid response).
        """
        ...