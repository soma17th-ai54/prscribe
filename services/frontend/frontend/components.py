from __future__ import annotations

import json
from typing import Any

import streamlit as st

_STEP_LABELS = ["대기", "Researcher", "Context", "Writer"]
_DIM_LABELS_KO = {
    "accuracy": "정확성",
    "readability": "가독성",
    "structure": "구조",
    "code_explanation": "코드 설명",
}


# ──────────────────────────────────────────────────────────────────────────
# Progress
# ──────────────────────────────────────────────────────────────────────────
def render_progress(current_step: int, total: int = 3) -> None:
    current_step = max(0, min(current_step, total))
    st.progress(current_step / total)
    label = _STEP_LABELS[current_step] if current_step < len(_STEP_LABELS) else "?"
    st.caption(f"단계 {current_step}/{total} — {label}")


# ──────────────────────────────────────────────────────────────────────────
# Header (Writer grade)
# ──────────────────────────────────────────────────────────────────────────
def render_writer_grade_header(draft: dict | None) -> None:
    if not draft:
        return
    self_eval = draft.get("self_eval")
    if not self_eval:
        return
    grade = self_eval.get("overall_grade", "?")
    avg = self_eval.get("judge_average")
    avg_str = f"{avg:.1f}/5.0" if isinstance(avg, (int, float)) else "—"
    msg = f"**Final Grade: {grade}** ({avg_str})"
    if grade in ("A", "B"):
        st.success(msg)
    elif grade == "C":
        st.info(msg)
    else:  # D, F, ?
        st.warning(msg + " — 사람 검토 권장")


# ──────────────────────────────────────────────────────────────────────────
# Draft tab
# ──────────────────────────────────────────────────────────────────────────
def render_draft(draft: dict | None) -> None:
    if not draft:
        st.info("초안이 아직 생성되지 않았습니다.")
        return

    title = draft.get("title", "(제목 없음)")
    md = draft.get("full_markdown", "")
    pr_id = draft.get("pr_identifier", "draft")
    revision = draft.get("revision", 0)

    st.subheader(title)
    cols = st.columns([1, 1, 1, 4])
    cols[0].metric("Words", draft.get("word_count", 0))
    cols[1].metric("Code blocks", draft.get("code_block_count", 0))
    cols[2].metric("Revision", revision)
    if revision > 0:
        cols[3].markdown("🩹 **수정됨** — reflection 자동 패치 적용")

    safe_name = pr_id.replace("/", "_").replace("#", "_") or "draft"
    st.download_button(
        label="📥 Markdown 다운로드",
        data=md,
        file_name=f"{safe_name}.md",
        mime="text/markdown",
    )

    st.divider()
    if md:
        st.markdown(md)
    else:
        st.warning("본문이 비어 있습니다.")


# ──────────────────────────────────────────────────────────────────────────
# Self-Eval cards (Writer / Context / Researcher)
# ──────────────────────────────────────────────────────────────────────────
def render_self_eval_cards(state: dict) -> None:
    st.caption(
        "ⓘ self-eval은 같은 모델 가족이 자기 출력을 평가하므로 점수가 후할 수 있습니다. "
        "정확한 회귀 측정은 골든셋(사람 채점) 비교가 필요합니다."
    )
    _render_writer_card((state.get("draft") or {}).get("self_eval"))
    _render_context_card((state.get("context") or {}).get("self_eval"))
    _render_researcher_card((state.get("research") or {}).get("self_eval"))


def _missing_card(title: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption("평가 실패 — 초안은 정상 생성됨")


def _stars(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def _render_writer_card(se: dict | None) -> None:
    if not se:
        _missing_card("Writer self-eval")
        return
    grade = se.get("overall_grade", "?")
    avg = se.get("judge_average")
    avg_str = f"{avg:.1f}/5.0" if isinstance(avg, (int, float)) else "—"
    with st.container(border=True):
        st.markdown(f"**Writer** — Grade: `{grade}` ({avg_str})")
        scores = {js.get("dimension"): js for js in (se.get("judge_scores") or [])}
        cols = st.columns(4)
        for i, dim in enumerate(("accuracy", "readability", "structure", "code_explanation")):
            js = scores.get(dim) or {}
            score = js.get("score")
            cols[i].metric(_DIM_LABELS_KO[dim], _stars(score))
            rationale = js.get("rationale")
            if rationale:
                cols[i].caption(rationale)

        checklist = se.get("checklist") or []
        passed = sum(1 for c in checklist if c.get("passed"))
        total = len(checklist)
        rate = se.get("checklist_pass_rate")
        rate_str = f"({rate:.0%})" if isinstance(rate, (int, float)) else ""
        st.markdown(f"**Checklist:** {passed}/{total} 통과 {rate_str}")
        for c in checklist:
            mark = "✅" if c.get("passed") else "❌"
            detail = c.get("detail")
            line = f"- {mark} `{c.get('name','?')}`"
            if detail:
                line += f" — {detail}"
            st.markdown(line)

        suggestions = se.get("suggestions") or []
        if suggestions:
            st.markdown("**Suggestions:**")
            for s in suggestions:
                st.markdown(f"- {s}")


def _render_context_card(se: dict | None) -> None:
    if not se:
        _missing_card("Context self-eval")
        return
    with st.container(border=True):
        st.markdown(f"**Context** — Confidence: `{se.get('confidence', '?')}/5`")
        cov = se.get("coverage")
        cov_str = f"{cov:.0%}" if isinstance(cov, (int, float)) else "—"
        cols = st.columns(3)
        cols[0].metric("Coverage", cov_str)
        cols[1].metric("Relevance", _stars(se.get("relevance")))
        cols[2].metric("Diversity", _stars(se.get("diversity")))
        rationale = se.get("rationale")
        if rationale:
            st.caption(rationale)


def _render_researcher_card(se: dict | None) -> None:
    if not se:
        _missing_card("Researcher self-eval")
        return
    with st.container(border=True):
        st.markdown(f"**Researcher** — Confidence: `{se.get('confidence', '?')}/5`")
        cov = se.get("coverage")
        gnd = se.get("groundedness")
        cov_str = f"{cov:.0%}" if isinstance(cov, (int, float)) else "—"
        gnd_str = f"{gnd:.0%}" if isinstance(gnd, (int, float)) else "—"
        cols = st.columns(3)
        cols[0].metric("Coverage", cov_str)
        cols[1].metric("Groundedness", gnd_str)
        cols[2].metric("Chunk quality", _stars(se.get("chunk_quality")))
        rationale = se.get("rationale")
        if rationale:
            st.caption(rationale)


# ──────────────────────────────────────────────────────────────────────────
# Agent trace
# ──────────────────────────────────────────────────────────────────────────
def format_trace_event(event: dict) -> str:
    stage = event.get("stage") or event.get("node") or "agent"
    status = event.get("status") or "info"
    message = event.get("message") or ""
    if message:
        return f"`{stage}` · {status} — {message}"
    return f"`{stage}` · {status}"


def render_trace_updates(events: list[dict], limit: int = 4) -> None:
    if not events:
        return
    for event in events[-limit:]:
        st.caption(format_trace_event(event))


def render_agent_trace(state: dict) -> None:
    events = list(state.get("react_traces") or [])
    if not events:
        st.info("표시할 Agent trace가 아직 없습니다.")
        return

    st.caption(f"총 {len(events)}개 trace event")
    for index, event in enumerate(events, start=1):
        title = format_trace_event(event)
        with st.expander(f"{index}. {title}", expanded=index == len(events)):
            metadata = event.get("metadata")
            if metadata:
                st.json(metadata)
            else:
                st.caption("metadata 없음")
            st.code(json.dumps(event, ensure_ascii=False, indent=2), language="json")


# ──────────────────────────────────────────────────────────────────────────
# Errors tab
# ──────────────────────────────────────────────────────────────────────────
def render_errors(errors: list[str]) -> None:
    if not errors:
        st.success("에러 없음")
        return
    for e in errors:
        st.error(e)
