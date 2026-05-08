from __future__ import annotations

import pytest

from writer_agent.agents import writer
from writer_agent.schemas.writer import (
    ChangedFunction,
    ContextResult,
    DraftResult,
    DraftSection,
    FactBullet,
    FileChange,
    Reference,
    ResearchResult,
)
from writer_agent.workflow.graph import writer_graph


@pytest.fixture(autouse=True)
def disable_solar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLAR_API_KEY", raising=False)
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)


def research_result() -> ResearchResult:
    return ResearchResult(
        pr_identifier="acme/demo#7",
        summary_one_line="Validate resource filters before matching",
        changed_files=[
            FileChange(
                path="demo_app/service.py",
                status="modified",
                additions=14,
                deletions=3,
                patch=(
                    "@@ -32,6 +32,7 @@ def list_resources(self, filters):\n"
                    "+        validate_filters(filters)\n"
                    "@@ -100,0 +110,8 @@\n"
                    "+def validate_filters(filters):\n"
                    "+    if filters is None:\n"
                    "+        return\n"
                ),
            ),
            FileChange(
                path="tests/test_service.py",
                status="modified",
                additions=10,
                deletions=0,
                patch="+def test_invalid_filter_values_raise_validation_error(self):\n+    pass\n",
            ),
        ],
        changed_functions=[
            ChangedFunction(
                file="demo_app/service.py",
                function_name="list_resources",
                change_kind="modified",
                summary="list_resources now validates filters before matching resources.",
            ),
            ChangedFunction(
                file="demo_app/service.py",
                function_name="validate_filters",
                change_kind="added",
                summary="validate_filters was added in demo_app/service.py.",
            ),
        ],
        tech_stack_hints=[],
        facts=[
            FactBullet(
                statement="demo_app/service.py was modified with 14 additions and 3 deletions.",
                source="diff",
                source_locator="files[0].patch",
            ),
            FactBullet(
                statement="validate_filters(filters) is called before resource matching.",
                source="diff",
                source_locator="files[0].patch L1-L2",
            ),
            FactBullet(
                statement="Validate resource filters before matching",
                source="commit_message",
                source_locator="commit:abc123",
            ),
        ],
        search_chunks=[],
    )


def context_result() -> ContextResult:
    reference = Reference(
        chunk_id="chunk_1",
        title="Python exceptions",
        url="https://docs.python.org/3/tutorial/errors.html",
        source_kind="official_docs",
        excerpt="The Python tutorial documents how exceptions can be raised and handled.",
        fetched_at="2026-05-05T00:00:00Z",
    )
    return ContextResult(
        pr_identifier="acme/demo#7",
        raw_references=[reference],
        verified_references=[reference],
        verification_log=[],
        coverage=1.0,
    )


def test_run_writer_pipeline_returns_draft_result_with_self_eval() -> None:
    result = writer.run_writer_pipeline(research_result(), context_result(), mode="full")

    assert result.draft.pr_identifier == "acme/demo#7"
    assert [section.kind for section in result.draft.sections] == [
        "intro",
        "problem",
        "cause",
        "solution",
        "result",
        "outro",
    ]
    assert result.draft.code_block_count >= 1
    assert result.draft.self_eval is not None
    assert result.draft.self_eval.overall_grade in {"A", "B", "C", "D", "F"}
    assert result.verifications


def test_minimal_context_uses_grounded_fallback_without_draft_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_draft_call(*args, **kwargs):
        pytest.fail("minimal_context should not call the draft LLM")

    monkeypatch.setenv("SOLAR_API_KEY", "test-key")
    monkeypatch.setattr(writer, "call_solar_for_draft", fail_draft_call)
    monkeypatch.setattr(writer, "call_solar_for_reflection", lambda *args, **kwargs: pytest.fail("not needed"))
    monkeypatch.setattr(writer, "call_solar_for_self_eval", lambda *args, **kwargs: pytest.fail("not needed"))

    draft = writer.generate_draft(research_result(), writer._empty_context("acme/demo#7"), mode="full")

    assert "외부 레퍼런스 없이 PR에서 확인 가능한 사실만" in draft.full_markdown
    assert "공식 문서를 추가로 확인하세요." in draft.full_markdown


def test_deterministic_checklist_removes_unverified_citations() -> None:
    research = research_result()
    draft = DraftResult(
        pr_identifier=research.pr_identifier,
        title="Filter validation writeup",
        sections=[
            DraftSection(kind="intro", title="들어가며", body_markdown="acme/demo#7", cited_references=[]),
            DraftSection(kind="problem", title="문제 상황", body_markdown="문제입니다.", cited_references=[]),
            DraftSection(kind="cause", title="원인 분석", body_markdown="원인입니다.", cited_references=[]),
            DraftSection(
                kind="solution",
                title="해결 방법",
                body_markdown="해결했습니다. [bad](https://example.com/not-verified)\n\n```python\nprint('x')\n```",
                cited_references=["https://example.com/not-verified"],
            ),
            DraftSection(kind="result", title="결과 및 효과", body_markdown="결과입니다.", cited_references=[]),
            DraftSection(kind="outro", title="마치며", body_markdown="마칩니다.", cited_references=[]),
        ],
        full_markdown="",
        word_count=0,
        code_block_count=0,
    )
    draft = writer._make_draft(research, draft.title, draft.sections)

    outcome = writer.deterministic_checklist(draft, research, context_result(), mode="full")

    assert "https://example.com/not-verified" in outcome.removed_citations
    assert "https://example.com/not-verified" not in outcome.draft.full_markdown
    cited_item = next(item for item in outcome.checklist if item.name == "cited_refs_subset_verified")
    assert cited_item.passed is False


def test_deterministic_checklist_detects_missing_sections_before_patch() -> None:
    research = research_result()
    draft = writer._make_draft(
        research,
        "Filter validation writeup",
        [
            DraftSection(kind="intro", title="들어가며", body_markdown="acme/demo#7", cited_references=[]),
            DraftSection(kind="solution", title="해결 방법", body_markdown="```diff\n+change\n```", cited_references=[]),
        ],
    )

    outcome = writer.deterministic_checklist(draft, research, context_result(), mode="full")

    four_act_item = next(item for item in outcome.checklist if item.name == "four_act_present")
    assert four_act_item.passed is False
    assert any(finding.kind == "structure_violation" for finding in outcome.findings)


def test_pr_metadata_missing_emits_finding_but_checklist_passes() -> None:
    research = research_result()
    sections = [
        DraftSection(kind="intro", title="들어가며", body_markdown="변경 내용을 정리했습니다.", cited_references=[]),
        DraftSection(kind="problem", title="문제 상황", body_markdown="문제입니다.", cited_references=[]),
        DraftSection(kind="cause", title="원인 분석", body_markdown="원인입니다.", cited_references=[]),
        DraftSection(kind="solution", title="해결 방법", body_markdown="```diff\n+change\n```", cited_references=[]),
        DraftSection(kind="result", title="결과 및 효과", body_markdown="결과입니다.", cited_references=[]),
        DraftSection(kind="outro", title="마치며", body_markdown="마칩니다.", cited_references=[]),
    ]
    draft = writer._make_draft(research, "Filter validation writeup", sections)

    outcome = writer.deterministic_checklist(draft, research, context_result(), mode="full")

    metadata_item = next(item for item in outcome.checklist if item.name == "pr_metadata_present")
    assert metadata_item.passed is True
    assert any(finding.quote == "PR metadata missing" for finding in outcome.findings)


def test_reflection_patches_missing_code_and_speculation() -> None:
    research = research_result()
    sections = [
        DraftSection(kind="intro", title="들어가며", body_markdown="아마 acme/demo#7 변경입니다.", cited_references=[]),
        DraftSection(kind="problem", title="문제 상황", body_markdown="문제만 적었습니다.", cited_references=[]),
        DraftSection(kind="cause", title="원인 분석", body_markdown="원인만 적었습니다.", cited_references=[]),
        DraftSection(kind="solution", title="해결 방법", body_markdown="해결만 적었습니다.", cited_references=[]),
        DraftSection(kind="result", title="결과 및 효과", body_markdown="결과만 적었습니다.", cited_references=[]),
        DraftSection(kind="outro", title="마치며", body_markdown="마칩니다.", cited_references=[]),
    ]
    draft = writer._make_draft(research, "Filter validation", sections)

    patched, verifications = writer.self_reflect_and_patch(draft, research, context_result(), mode="full")

    assert patched.code_block_count >= 1
    assert "아마" not in patched.full_markdown
    assert patched.revision <= 2
    assert any(item.auto_patched for item in verifications)


def test_verify_fact_in_diff_matches_patch() -> None:
    verification = writer.verify_fact_in_diff(
        "validate_filters is called before resource matching",
        research_result(),
    )

    assert verification.verdict == "consistent"
    assert verification.matches


def test_writer_graph_invokes_with_json_state() -> None:
    state = writer_graph.invoke(
        {
            "research": research_result().model_dump(mode="json"),
            "context": context_result().model_dump(mode="json"),
            "mode": "full",
        }
    )

    assert "errors" not in state
    assert state["draft"]["pr_identifier"] == "acme/demo#7"
    assert state["verifications"]


def test_writer_accepts_existing_researcher_output() -> None:
    from researcher_agent.agents import researcher as researcher_module
    from researcher_agent.schemas.research import CommitInfo, FileChange as ResearcherFileChange, RawPRData

    raw = RawPRData(
        pr_identifier="acme/demo#8",
        title="Validate resource filters before matching",
        body="Fixes #3",
        author="dev",
        base_branch="main",
        head_branch="feature/filter-validation",
        state="open",
        commits=[
            CommitInfo(
                sha="abc123",
                message="Validate resource filters before matching",
                author="dev",
                timestamp="2026-05-05T00:00:00Z",
            )
        ],
        files=[
            ResearcherFileChange(
                path="demo_app/service.py",
                status="modified",
                additions=14,
                deletions=3,
                patch="+        validate_filters(filters)\n",
            )
        ],
        linked_issues=[],
        fetched_at="2026-05-05T00:00:00+00:00",
    )
    research = researcher_module._fallback_result(raw)

    result = writer.run_writer_pipeline(research.model_dump(mode="json"), None, mode="full")

    assert result.draft.pr_identifier == "acme/demo#8"
    assert result.draft.code_block_count >= 1
    assert result.draft.self_eval is not None
