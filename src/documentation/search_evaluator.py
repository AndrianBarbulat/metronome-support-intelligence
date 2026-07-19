"""Repeatable search-quality evaluation framework."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.documentation.search import search_documentation


@dataclass
class EvalCaseResult:
    case_id: str
    query: str
    passed: bool
    expected_pages: list[str]
    actual_rank: int | None  # rank of first matching expected page (1-based), or None
    top_result: str | None
    result_titles: list[str]
    notes: str = ""


@dataclass
class EvalResult:
    total_cases: int = 0
    passed_cases: int = 0
    top1_accuracy: float = 0.0
    top3_recall: float = 0.0
    mean_reciprocal_rank: float = 0.0
    no_result_cases: int = 0
    failed_cases: list[EvalCaseResult] = field(default_factory=list)
    all_results: list[EvalCaseResult] = field(default_factory=list)


def _find_rank(result_titles: list[str], expected: list[str]) -> int | None:
    """Return 1-based rank of the first expected title in results, or None."""
    for i, title in enumerate(result_titles, start=1):
        if title in expected:
            return i
    return None


def evaluate_search(
    database_path: Path,
    cases_path: Path = Path("data/evaluation/search_cases.json"),
    limit: int = 10,
) -> EvalResult:
    """Run all search test cases and return evaluation metrics."""

    with cases_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases", [])
    total = len(cases)
    if total == 0:
        return EvalResult(total_cases=0)

    passed = 0
    rr_sum = 0.0
    no_result_count = 0
    all_results: list[EvalCaseResult] = []
    failed: list[EvalCaseResult] = []

    for case in cases:
        query = case["query"]
        expected = case.get("expected_pages", [])
        expected_top = case.get("expected_top_rank", 1)
        required_tokens = case.get("required_tokens", [])
        case_id = case.get("id", query)

        results = search_documentation(
            database_path=database_path,
            query=query,
            limit=limit,
        )

        result_titles = [r.page_title for r in results]
        top_result = result_titles[0] if result_titles else None
        rank = _find_rank(result_titles, expected)

        # Check required tokens
        token_pass = True
        if required_tokens:
            all_content = " ".join(r.content for r in results)
            all_meta = " ".join(
                " ".join(r.matched_technical_tokens)
                for r in results
                if r.matched_technical_tokens
            )
            combined = (all_content + all_meta).lower()
            for token in required_tokens:
                if token.lower() not in combined:
                    token_pass = False
                    break

        case_passed = True
        if rank is None and expected:
            case_passed = False
        elif rank is not None and rank > expected_top:
            case_passed = False
        if not token_pass:
            case_passed = False

        if case_passed:
            passed += 1
        else:
            failed.append(
                EvalCaseResult(
                    case_id=case_id,
                    query=query,
                    passed=False,
                    expected_pages=expected,
                    actual_rank=rank,
                    top_result=top_result,
                    result_titles=result_titles,
                    notes=case.get("notes", ""),
                )
            )

        if rank is not None:
            rr_sum += 1.0 / rank
        else:
            no_result_count += 1

        all_results.append(
            EvalCaseResult(
                case_id=case_id,
                query=query,
                passed=case_passed,
                expected_pages=expected,
                actual_rank=rank,
                top_result=top_result,
                result_titles=result_titles,
                notes=case.get("notes", ""),
            )
        )

    top1_accuracy = (
        sum(1 for r in all_results if r.actual_rank == 1) / total * 100
        if total > 0
        else 0
    )
    top3_recall = (
        sum(1 for r in all_results if r.actual_rank is not None and r.actual_rank <= 3) / total * 100
        if total > 0
        else 0
    )
    mrr = rr_sum / total if total > 0 else 0.0

    return EvalResult(
        total_cases=total,
        passed_cases=passed,
        top1_accuracy=top1_accuracy,
        top3_recall=top3_recall,
        mean_reciprocal_rank=mrr,
        no_result_cases=no_result_count,
        failed_cases=failed,
        all_results=all_results,
    )