from __future__ import annotations

import os
import queue
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from frontend import components
from frontend.runner import start_run

# repo root .env (services/frontend/frontend/app.py → parents[3] = repo root)
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

st.set_page_config(page_title="PRScribe", page_icon="📝", layout="wide")

# ── session_state init ──────────────────────────────────────────────
_DEFAULTS = {
    "queue": None,
    "graph_state": {},
    "status": "idle",      # idle | running | done | error
    "current_step": 0,     # 0..3
    "error": None,
}
for _k, _v in _DEFAULTS.items():
    st.session_state.setdefault(_k, _v)


_LIST_MERGE_KEYS = ("errors", "react_traces", "verifications")


def _merge_partial_state(current: dict, partial: dict | None) -> dict:
    merged = dict(current)
    for key, value in (partial or {}).items():
        if key in _LIST_MERGE_KEYS and key in merged:
            merged[key] = list(merged[key]) + list(value or [])
        else:
            merged[key] = value
    return merged


# ── sidebar ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    gh_token = st.text_input(
        "GitHub Token",
        type="password",
        value=os.getenv("GITHUB_TOKEN", ""),
        help="private repo / rate limit 회피용 (선택)",
    )
    solar_key = st.text_input(
        "Solar API Key",
        type="password",
        value=os.getenv("UPSTAGE_API_KEY") or os.getenv("SOLAR_API_KEY", ""),
        help="Researcher / Context / Writer 모두 사용",
    )
    mode_choice = st.selectbox(
        "Writer 모드",
        ["auto", "full", "minimal_context"],
        index=0,
        help="auto: context coverage<0.2면 minimal, 아니면 full",
    )

# Apply sidebar → process env (before spawning the worker thread)
if gh_token:
    os.environ["GITHUB_TOKEN"] = gh_token
if solar_key:
    os.environ["UPSTAGE_API_KEY"] = solar_key
    os.environ["SOLAR_API_KEY"] = solar_key


# ── header ──────────────────────────────────────────────────────────
st.title("📝 GitHub PR → 기술 블로그 초안 생성기")
components.render_writer_grade_header(
    st.session_state["graph_state"].get("draft")
)


# ── input form ──────────────────────────────────────────────────────
with st.form("run_form", clear_on_submit=False):
    pr_url_input = st.text_input(
        "PR URL",
        placeholder="https://github.com/owner/repo/pull/123",
    )
    submitted = st.form_submit_button(
        "🚀 생성",
        disabled=(st.session_state["status"] == "running"),
    )

if submitted:
    pr_url = pr_url_input.strip()
    if not pr_url:
        st.error("PR URL을 입력하세요.")
    elif not solar_key:
        st.error("Solar API Key가 필요합니다 (사이드바 또는 .env).")
    else:
        st.session_state.update(
            graph_state={},
            current_step=0,
            error=None,
            status="running",
        )
        override = None if mode_choice == "auto" else mode_choice
        st.session_state["queue"] = start_run(pr_url, override)


# ── progress + drain loop (only while running) ──────────────────────
progress_slot = st.empty()
status_slot = st.empty()

if st.session_state["status"] == "running":
    q: queue.Queue = st.session_state["queue"]
    NODE_TO_STEP = {"researcher": 1, "context": 2, "writer": 3}

    with status_slot.status("파이프라인 실행 중...", expanded=True) as status:
        while True:
            try:
                event = q.get(timeout=0.1)
            except queue.Empty:
                time.sleep(0.05)
                continue

            kind = event[0]
            if kind == "node_update":
                _, node_name, partial = event
                st.session_state["graph_state"] = _merge_partial_state(
                    st.session_state["graph_state"],
                    partial,
                )
                st.session_state["current_step"] = max(
                    st.session_state["current_step"],
                    NODE_TO_STEP.get(node_name, 0),
                )
                status.update(label=f"단계: **{node_name}** 완료")
                components.render_trace_updates((partial or {}).get("react_traces") or [])
                with progress_slot.container():
                    components.render_progress(st.session_state["current_step"])
            elif kind == "done":
                _, final = event
                st.session_state["graph_state"] = final
                # if researcher errored, current_step may still be 0; bump to whatever we got
                if final.get("draft"):
                    st.session_state["current_step"] = 3
                elif final.get("context"):
                    st.session_state["current_step"] = max(
                        st.session_state["current_step"], 2
                    )
                elif final.get("research"):
                    st.session_state["current_step"] = max(
                        st.session_state["current_step"], 1
                    )
                st.session_state["status"] = "done"
                status.update(label="완료", state="complete")
                break
            elif kind == "error":
                _, exc = event
                st.session_state["error"] = f"{type(exc).__name__}: {exc}"
                st.session_state["status"] = "error"
                status.update(label="실패", state="error")
                break

    st.rerun()  # one final rerun so tabs render at page root, outside st.status


# ── result tabs (rendered after run completes) ──────────────────────
if st.session_state["status"] in {"done", "error"}:
    state = st.session_state["graph_state"]
    components.render_progress(st.session_state["current_step"])

    tab_draft, tab_trace, tab_eval, tab_err = st.tabs(
        ["📝 초안", "Agent Trace", "🎯 Self-Eval", "🐞 Errors"]
    )
    with tab_draft:
        components.render_draft(state.get("draft"))
    with tab_trace:
        components.render_agent_trace(state)
    with tab_eval:
        components.render_self_eval_cards(state)
    with tab_err:
        errs = list(state.get("errors") or [])
        if st.session_state["error"]:
            errs.append(st.session_state["error"])
        components.render_errors(errs)
elif st.session_state["status"] == "idle":
    st.info("좌측 사이드바에서 키를 확인한 뒤, PR URL을 입력하고 **생성**을 누르세요.")
