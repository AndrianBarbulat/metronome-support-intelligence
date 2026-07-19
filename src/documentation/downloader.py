"""Async article downloader with retry and concurrency control."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx

from .models import DocumentationEntry, DownloadResult

USER_AGENT = "MetronomeSupportIntelligence/0.1"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BASE_DELAY = 0.5

_RETRYABLE_STATUSES = frozenset({429} | set(range(500, 600)))


def _is_retryable(exc: Exception | None, status: int | None) -> bool:
    if exc is not None:
        # Network-level errors (connect, read, timeout) are retryable.
        return True
    return status is not None and status in _RETRYABLE_STATUSES


async def _download_once(
    client: httpx.AsyncClient, url: str
) -> tuple[str | None, int | None, str | None]:
    """Return ``(body, status, final_url)`` or raise on transport error."""
    response = await client.get(url, follow_redirects=True)
    return response.text, response.status_code, str(response.url)


async def download_article(
    client: httpx.AsyncClient,
    entry: DocumentationEntry,
    semaphore: asyncio.Semaphore,
) -> DownloadResult:
    """Download *entry.url* with retries and bounded concurrency.

    Returns a :class:`DownloadResult` that is always truthy for ``.success``
    or provides ``.error_type`` / ``.error_message`` on failure.
    """
    url = entry.url
    last_error_type: str | None = None
    last_error_message: str | None = None

    async with semaphore:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                body, status, final_url = await _download_once(client, url)
            except httpx.TimeoutException:
                last_error_type = "timeout"
                last_error_message = "Request timed out"
            except httpx.ConnectError:
                last_error_type = "connection_error"
                last_error_message = "Failed to connect"
            except Exception as exc:
                last_error_type = "network_error"
                last_error_message = str(exc)
            else:
                if status is not None and status >= 400:
                    last_error_type = "http_error"
                    last_error_message = f"HTTP {status}"
                    if not _is_retryable(None, status):
                        return DownloadResult(
                            url=url,
                            success=False,
                            http_status=status,
                            final_url=final_url,
                            error_type=last_error_type,
                            error_message=last_error_message,
                        )
                else:
                    # Success
                    return DownloadResult(
                        url=url,
                        success=True,
                        raw_markdown=body,
                        http_status=status,
                        final_url=final_url,
                    )

            # Only reachable when a retryable failure occurred
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        return DownloadResult(
            url=url,
            success=False,
            error_type=last_error_type or "unknown",
            error_message=last_error_message or "Unknown error after retries",
        )