"""End-to-end pipeline demo: researcher → context → writer"""
import asyncio
import json
import sys
import os
import warnings

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/researcher_agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/context_agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/writer_agent"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from orchestration.graph import prscribe_graph

_LIST_MERGE_KEYS = ("errors", "react_traces", "verifications")
PIPELINE_RECURSION_LIMIT = 5


def _merge_state(accumulated: dict, partial: dict) -> None:
    for key, value in partial.items():
        if key in _LIST_MERGE_KEYS and key in accumulated:
            accumulated[key] = list(accumulated[key]) + list(value or [])
        else:
            accumulated[key] = value


def _print_trace(node_name: str, partial: dict) -> None:
    print(f"[backend] node_update node={node_name} keys={sorted(partial.keys())}", flush=True)
    for event in partial.get("react_traces", []) or []:
        payload = {"langgraph_node": node_name, **event}
        print(f"[backend] trace {json.dumps(payload, ensure_ascii=False)}", flush=True)


async def main(pr_url: str):
    print(f"🚀 파이프라인 시작: {pr_url}")
    print("  GitHub API → Researcher → Context → Writer ...\n")

    result = {"pr_url": pr_url}
    async for update in prscribe_graph.astream(
        {"pr_url": pr_url},
        config={"recursion_limit": PIPELINE_RECURSION_LIMIT},
        stream_mode="updates",
    ):
        for node_name, partial in update.items():
            partial = partial or {}
            _merge_state(result, partial)
            _print_trace(node_name, partial)

    errors = result.get("errors", [])
    if errors:
        print("❌ 오류 발생:")
        for e in errors:
            print(f"  - {e}")

    research = result.get("research", {})
    if research:
        print("══════════════════════════════════════════════")
        print("📋  RESEARCHER 결과")
        print("══════════════════════════════════════════════")
        print(f"  PR:    {research.get('pr_identifier')}")
        print(f"  요약:  {research.get('summary_one_line')}")
        print(f"  변경파일: {len(research.get('changed_files', []))}개")
        print(f"  사실(facts): {len(research.get('facts', []))}개")

    context = result.get("context", {})
    if context:
        print("\n══════════════════════════════════════════════")
        print("🔍  CONTEXT AGENT 결과")
        print("══════════════════════════════════════════════")
        print(f"  Coverage: {context.get('coverage', 0.0)*100:.1f}%")
        verified = context.get("verified_references", [])
        print(f"  검증된 참조: {len(verified)}개")
        for ref in verified[:3]:
            print(f"    · {ref.get('url', '')[:80]}")

    draft = result.get("draft", {})
    if draft:
        print("\n══════════════════════════════════════════════")
        print("✍️   WRITER 결과")
        print("══════════════════════════════════════════════")
        print(f"  제목:  {draft.get('title', '(없음)')}")
        print(f"  태그:  {', '.join(draft.get('tags', []))}")
        grade = (draft.get("self_eval") or {}).get("overall_grade", "?")
        print(f"  자체평가 등급: {grade}")

        md = draft.get("full_markdown", "")
        out_path = os.path.join(os.path.dirname(__file__), "draft_output.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\n📄 전체 본문 저장됨: {out_path}")
    else:
        print("\n⚠️  draft 없음 — writer 실패 또는 에러 확인")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_demo.py <PR_URL>")
        print("  e.g. python run_demo.py https://github.com/owner/repo/pull/123")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
