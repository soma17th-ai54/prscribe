from context_agent.models import (
    Reference, VerificationDecision, ContextSelfEval, ContextResult,
    SearchChunk, FactBullet,
)


def test_reference_requires_fields():
    ref = Reference(
        chunk_id="c1",
        title="Django ORM docs",
        url="https://docs.djangoproject.com/orm",
        source_kind="official_docs",
        excerpt="QuerySet lazy evaluation...",
        fetched_at="2026-05-08T00:00:00",
    )
    assert ref.chunk_id == "c1"


def test_verification_decision_verdict_values():
    d = VerificationDecision(
        reference_url="https://example.com",
        verdict="consistent",
        reasoning="PR fact matches doc excerpt.",
    )
    assert d.verdict == "consistent"


def test_context_result_coverage_range():
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        ContextResult(
            pr_identifier="owner/repo#1",
            raw_references=[],
            verified_references=[],
            verification_log=[],
            coverage=1.5,
        )


def test_search_chunk_keywords_validator_removes_excess():
    chunk = SearchChunk(
        chunk_id="c1",
        keywords=["a", "b", "c", "d", "e", "f", "g", "h"],  # 8개 → 7개로 잘림
        intent="best_practice",
    )
    assert len(chunk.keywords) == 7


def test_search_chunk_empty_keywords_raises():
    import pytest
    with pytest.raises(Exception):
        SearchChunk(chunk_id="c1", keywords=[], intent="concept_lookup")
