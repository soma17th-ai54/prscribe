"""End-to-end pipeline demo: researcher → context → writer"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/researcher_agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/context_agent"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/writer_agent"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from orchestration.graph import prscribe_graph


async def main(pr_url: str):
    print(f"🚀 파이프라인 시작: {pr_url}")
    print("  GitHub API → Researcher → Context → Writer ...\n")

    result = await prscribe_graph.ainvoke(
        {"pr_url": pr_url},
        config={"recursion_limit": 50},
    )

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
