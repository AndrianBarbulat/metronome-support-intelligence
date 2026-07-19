"""Orchestrates structured content processing for documentation articles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .chunker import ChunkMetadata, create_chunks
from .markdown_parser import parse_markdown
from .models import DownloadResult
from src.database.connection import get_connection
from src.database.repository import DocumentationRepository


@dataclass
class ProcessingSummary:
    discovered_count: int = 0
    processed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    sections_created: int = 0
    chunks_created: int = 0
    code_blocks_detected: int = 0
    tables_detected: int = 0
    openapi_blocks_detected: int = 0


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _chunk_to_dict(chunk, idx: int) -> dict:
    return {
        "chunk_type": chunk.chunk_type,
        "heading": chunk.heading,
        "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "token_estimate": chunk.token_estimate,
        "metadata_json": json.dumps(
            {
                "page_title": chunk.metadata.page_title,
                "source_url": chunk.metadata.source_url,
                "document_type": chunk.metadata.document_type,
                "category": chunk.metadata.category,
                "subcategory": chunk.metadata.subcategory,
                "heading_level": chunk.metadata.heading_level,
                "heading_path": chunk.metadata.heading_path,
                "http_method": chunk.metadata.http_method,
                "endpoint_path": chunk.metadata.endpoint_path,
                "operation_id": chunk.metadata.operation_id,
                "contains_code": chunk.metadata.contains_code,
                "contains_table": chunk.metadata.contains_table,
            },
            ensure_ascii=False,
        ),
    }


def process_current_documentation(
    database_path: Path,
    parser_version: str = "1.0.0",
    force: bool = False,
) -> ProcessingSummary:
    """Process all active documentation pages into structured chunks.

    Skips versions already processed with the same *parser_version*
    unless *force* is ``True``.
    """
    repo = DocumentationRepository(database_path)
    repo.initialize_schema()

    pages = repo.get_active_pages_with_current_version()
    summary = ProcessingSummary(discovered_count=len(pages))
    timestamp = _utc_now()

    total_sections = 0
    total_chunks = 0
    total_code_blocks = 0
    total_tables = 0
    total_openapi = 0

    for page in pages:
        version_id = page["version_id"]

        # Skip if already processed
        if not force:
            existing = repo.get_parsed_version(version_id, parser_version)
            if existing is not None:
                summary.skipped_count += 1
                continue

        try:
            # Parse
            parsed = parse_markdown(
                page["raw_markdown"],
                article_title=page["title"],
            )

            # Create chunks
            chunks = create_chunks(
                parsed,
                page_title=page["title"],
                source_url=page["source_url"],
                document_type=page["document_type"],
                category=page["category"],
                subcategory=page["subcategory"],
            )

            # Build parsed JSON
            parsed_json = json.dumps(
                {
                    "title": page["title"],
                    "source_url": page["source_url"],
                    "section_count": len(parsed.sections),
                    "code_block_count": len(parsed.code_blocks),
                    "table_count": len(parsed.tables),
                    "openapi_block_count": len(parsed.openapi_blocks),
                    "sections": [
                        {
                            "heading": s.heading,
                            "heading_level": s.heading_level,
                            "heading_path": s.heading_path,
                            "start_line": s.start_line,
                            "end_line": s.end_line,
                        }
                        for s in parsed.sections
                    ],
                    "openapi_metadata": [
                        {
                            "http_method": oa.http_method,
                            "endpoint_path": oa.endpoint_path,
                            "operation_id": oa.operation_id,
                            "request_fields": oa.request_fields,
                            "response_codes": oa.response_codes,
                            "warnings": oa.warnings,
                        }
                        for oa in parsed.openapi_blocks
                    ],
                },
                ensure_ascii=False,
            )

            # Store
            pv_id = repo.upsert_parsed_version(
                page_id=page["id"],
                version_id=version_id,
                parser_version=parser_version,
                parsed_json=parsed_json,
                section_count=len(parsed.sections),
                code_block_count=len(parsed.code_blocks),
                table_count=len(parsed.tables),
                openapi_block_count=len(parsed.openapi_blocks),
                timestamp=timestamp,
            )

            chunk_dicts = [_chunk_to_dict(c, i) for i, c in enumerate(chunks)]
            repo.replace_chunks(
                parsed_version_id=pv_id,
                page_id=page["id"],
                version_id=version_id,
                chunks=chunk_dicts,
                timestamp=timestamp,
            )

            summary.processed_count += 1
            total_sections += len(parsed.sections)
            total_chunks += len(chunks)
            total_code_blocks += len(parsed.code_blocks)
            total_tables += len(parsed.tables)
            total_openapi += len(parsed.openapi_blocks)

        except Exception:
            summary.failed_count += 1
            # Continue processing others

    summary.sections_created = total_sections
    summary.chunks_created = total_chunks
    summary.code_blocks_detected = total_code_blocks
    summary.tables_detected = total_tables
    summary.openapi_blocks_detected = total_openapi

    repo.close()
    return summary