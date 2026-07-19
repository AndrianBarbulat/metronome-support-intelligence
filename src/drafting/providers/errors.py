"""Drafting provider error hierarchy."""


class DraftingProviderError(Exception):
    """Base class for all provider-level errors."""
    pass


class DraftingConfigurationError(DraftingProviderError):
    """Configuration is missing or invalid (e.g. missing API key)."""
    pass


class DraftingRateLimitError(DraftingProviderError):
    """Provider returned a rate-limit response (HTTP 429)."""
    pass


class DraftingTimeoutError(DraftingProviderError):
    """Provider request timed out."""
    pass


class DraftingInvalidResponseError(DraftingProviderError):
    """Provider returned an unparseable or malformed response."""
    pass