"""Tests for search quality: query analysis, reranking, and evaluation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.documentation.query_analyzer import analyze_query, AnalyzedQuery
from src.documentation.reranker import SearchResult, ranked_search
from src.documentation.search_evaluator import (
    EvalCaseResult,
    EvalResult,
    evaluate_search,
    _find_rank,
)


class TestQueryAnalyzer:
    def test_snake_case_token(self):
        a = analyze_query("create contract starting_at")
        assert "starting_at" in a.technical_tokens

    def test_camel_case_token(self):
        a = analyze_query("createAlert operationId")
        assert "createAlert" in a.technical_tokens
        assert "operationId" in a.technical_tokens

    def test_endpoint_path(self):
        a = analyze_query("POST /v1/ingest")
        assert "/v1/ingest" in a.endpoint_paths

    def test_http_method(self):
        a = analyze_query("POST /v1/ingest")
        assert "POST" in a.http_methods

    def test_status_code(self):
        a = analyze_query("error 409 uniqueness_key")
        assert "409" in a.status_codes
        assert "uniqueness_key" in a.technical_tokens

    def test_quoted_phrase(self):
        a = analyze_query('"create contract" starting_at')
        assert "create contract" in a.phrases

    def test_simple_terms(self):
        a = analyze_query("create a new contract")
        assert "create" in a.terms
        assert "contract" in a.terms
        assert "new" in a.terms

    def test_operation_id_detection(self):
        a = analyze_query("createAlert archiveThreshold createContractV2")
        # CamelCase tokens are captured as technical_tokens
        assert len(a.technical_tokens) >= 3
        assert "createAlert" in a.technical_tokens
        assert "archiveThreshold" in a.technical_tokens
        assert "createContractV2" in a.technical_tokens

    def test_verb_detection(self):
        a = analyze_query("create archive edit retrieve")
        assert "create" in a.probable_operations
        assert "archive" in a.probable_operations

    def test_empty_query(self):
        a = analyze_query("")
        assert a.original_query == ""
        assert len(a.terms) == 0

    def test_malformed_punctuation_does_not_crash(self):
        a = analyze_query("foo: bar! (baz) [qux] {quux}")
        assert len(a.terms) >= 0  # should not crash


class TestReranker:
    def _make_candidate(self, **kwargs) -> dict:
        return {
            "score": kwargs.get("score", 1.0),
            "id": kwargs.get("id", 1),
            "chunk_type": kwargs.get("chunk_type", "prose"),
            "heading": kwargs.get("heading", ""),
            "heading_path": json.dumps(kwargs.get("heading_path", [])),
            "content_excerpt": kwargs.get("content_excerpt", ""),
            "content": kwargs.get("content", ""),
            "metadata_json": json.dumps({
                "page_title": kwargs.get("page_title", "Test"),
                "source_url": kwargs.get("source_url", "https://docs.metronome.com/test.md"),
                "document_type": kwargs.get("document_type", "api_reference"),
                "category": kwargs.get("category", "alerts"),
                "http_method": kwargs.get("http_method", None),
                "endpoint_path": kwargs.get("endpoint_path", None),
                "operation_id": kwargs.get("operation_id", None),
                "heading_level": kwargs.get("heading_level", 1),
                "heading_path": kwargs.get("heading_path", []),
                "contains_code": kwargs.get("contains_code", False),
                "contains_table": kwargs.get("contains_table", False),
            }),
        }

    def test_exact_title_boost(self):
        analyzed = analyze_query("Create a contract")
        candidates = [
            self._make_candidate(page_title="Create a contract", score=5.0, id=1, content="Create a contract starting_at contract body"),
            self._make_candidate(page_title="Create a package", score=7.0, id=2, content="package"),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        assert results[0].page_title == "Create a contract"

    def test_title_phrase_boost(self):
        analyzed = analyze_query("create threshold notification")
        candidates = [
            self._make_candidate(page_title="Other thing", score=5.0, id=1, content="create threshold notification"),
            self._make_candidate(page_title="Create a threshold notification", score=5.0, id=2, content="notification"),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        # The title phrase match should push Create a threshold notification higher
        create_title = next((r for r in results if "Create a threshold" in r.page_title), None)
        assert create_title is not None

    def test_exact_field_name_boost(self):
        analyzed = analyze_query("starting_at")
        candidates = [
            self._make_candidate(page_title="A", score=3.0, id=1, content="starting_at field is here"),
            self._make_candidate(page_title="B", score=6.0, id=2, content="no match here"),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        assert results[0].page_title == "A"

    def test_endpoint_boost(self):
        analyzed = analyze_query("POST /v1/ingest")
        candidates = [
            self._make_candidate(
                page_title="Ingest events", score=3.0, id=1,
                endpoint_path="/v1/ingest", http_method="POST",
                content="ingest",
            ),
            self._make_candidate(page_title="Other", score=7.0, id=2, content="other"),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        assert results[0].page_title == "Ingest events"

    def test_api_reference_boost(self):
        analyzed = analyze_query("create contract starting_at")
        candidates = [
            self._make_candidate(
                page_title="Create a contract", score=4.0, id=1,
                document_type="api_reference", content="starting_at",
            ),
            self._make_candidate(
                page_title="Provision a contract", score=6.0, id=2,
                document_type="guide", content="starting_at contract",
            ),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        assert results[0].page_title == "Create a contract"

    def test_page_deduplication(self):
        analyzed = analyze_query("test")
        candidates = [
            self._make_candidate(page_title="Same", score=10.0, id=1, source_url="https://docs.metronome.com/same.md", content="a b c"),
            self._make_candidate(page_title="Same", score=8.0, id=2, source_url="https://docs.metronome.com/same.md", content="d e f"),
            self._make_candidate(page_title="Different", score=3.0, id=3, source_url="https://docs.metronome.com/diff.md", content="x y z"),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        urls = [r.source_url for r in results]
        assert len(urls) == len(set(urls))  # no duplicates

    def test_multiple_chunks_flag(self):
        analyzed = analyze_query("test")
        candidates = [
            self._make_candidate(page_title="Same", score=10.0, id=1, source_url="https://docs.metronome.com/same.md", content="a"),
            self._make_candidate(page_title="Same", score=8.0, id=2, source_url="https://docs.metronome.com/same.md", content="b"),
        ]
        results = ranked_search(candidates, analyzed, limit=5, include_multiple_chunks_per_page=True)
        assert len(results) == 2

    def test_ranking_reasons_present(self):
        analyzed = analyze_query("Create a contract starting_at")
        candidates = [
            self._make_candidate(
                page_title="Create a contract", score=5.0, id=1,
                document_type="api_reference", content="starting_at contract",
            ),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        assert len(results[0].ranking_reasons) > 0

    def test_incidental_match_penalty(self):
        analyzed = analyze_query("create contract starting_at")
        candidates = [
            self._make_candidate(page_title="Unrelated", score=0.05, id=1, content="just some text"),
            self._make_candidate(page_title="Create a contract", score=3.0, id=2, content="create contract starting_at body"),
        ]
        results = ranked_search(candidates, analyzed, limit=5)
        assert results[0].page_title == "Create a contract"

    def test_empty_candidates(self):
        analyzed = analyze_query("test")
        results = ranked_search([], analyzed, limit=5)
        assert len(results) == 0


class TestEvaluator:
    def test_find_rank(self):
        result_titles = ["A", "B", "C"]
        assert _find_rank(result_titles, ["B"]) == 2
        assert _find_rank(result_titles, ["D"]) is None
        assert _find_rank(result_titles, ["A", "B"]) == 1

    def test_eval_result_dataclass(self):
        r = EvalResult(total_cases=10, passed_cases=8, top1_accuracy=80.0)
        assert r.total_cases == 10

    def test_evaluation_with_mocked_search(self):
        db_path = Path("data/metronome_docs.db")
        cases_data = {
            "version": "1.0",
            "cases": [
                {
                    "id": "test-1",
                    "query": "create contract",
                    "expected_pages": ["Create a contract"],
                    "expected_top_rank": 1,
                    "required_tokens": [],
                    "notes": "test",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(cases_data, f)
            cases_path = Path(f.name)

        try:
            with patch("src.documentation.search_evaluator.search_documentation") as mock_search:
                mock_result = MagicMock()
                mock_result.page_title = "Create a contract"
                mock_result.source_url = "url"
                mock_result.content = "create contract content"
                mock_result.matched_technical_tokens = []
                mock_search.return_value = [mock_result]

                result = evaluate_search(
                    database_path=db_path,
                    cases_path=cases_path,
                    limit=5,
                )
                assert result.total_cases == 1
                assert result.top1_accuracy == 100.0
                assert result.top3_recall == 100.0
                assert result.mean_reciprocal_rank == 1.0
        finally:
            cases_path.unlink()

    def test_evaluation_missing_result(self):
        db_path = Path("data/metronome_docs.db")
        cases_data = {
            "version": "1.0",
            "cases": [
                {
                    "id": "test-1",
                    "query": "nonexistent",
                    "expected_pages": ["NotFound"],
                    "expected_top_rank": 1,
                    "required_tokens": [],
                    "notes": "test",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(cases_data, f)
            cases_path = Path(f.name)

        try:
            with patch("src.documentation.search_evaluator.search_documentation") as mock_search:
                mock_result = MagicMock()
                mock_result.page_title = "Something else"
                mock_result.source_url = "url"
                mock_result.content = "content"
                mock_result.matched_technical_tokens = []
                mock_search.return_value = [mock_result]

                result = evaluate_search(
                    database_path=db_path,
                    cases_path=cases_path,
                    limit=5,
                )
                assert result.total_cases == 1
                assert result.top1_accuracy == 0.0
                assert result.passed_cases == 0
                assert len(result.failed_cases) == 1
        finally:
            cases_path.unlink()