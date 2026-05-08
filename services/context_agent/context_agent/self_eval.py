import os
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from context_agent.models import ContextResult, ContextSelfEval, ResearchResult
from context_agent.prompts import SELF_EVAL_SYSTEM_PROMPT


def get_solar_mini() -> ChatOpenAI:
    return ChatOpenAI(
        model="solar-mini",
        base_url="https://api.upstage.ai/v1",
        api_key=os.environ["SOLAR_API_KEY"],
        temperature=0,
    )


async def run_self_eval(
    context_result: ContextResult,
    research_result: ResearchResult,
) -> Optional[ContextSelfEval]:
    """ContextSelfEval 생성. 실패 시 None 반환 (노드 자체는 정상 반환)."""
    try:
        # solar-mini는 json_mode 사용 (parse() 미지원)
        llm = get_solar_mini().with_structured_output(ContextSelfEval, method="json_mode")

        domains = list({
            r.url.split("/")[2]
            for r in context_result.verified_references
            if "/" in r.url
        })
        facts_text = "\n".join(f"- {f.statement}" for f in research_result.facts)
        refs_text = "\n".join(
            f"- [{r.source_kind}] {r.title}: {r.excerpt[:100]}"
            for r in context_result.verified_references
        )

        human_msg = (
            f"PR: {context_result.pr_identifier}\n"
            f"PR 사실 목록:\n{facts_text}\n\n"
            f"verified_references ({len(context_result.verified_references)}개):\n{refs_text}\n\n"
            f"coverage (결정적): {context_result.coverage}\n"
            f"출처 도메인 목록: {domains}"
        )

        result = await llm.ainvoke([
            SystemMessage(content=SELF_EVAL_SYSTEM_PROMPT),
            HumanMessage(content=human_msg),
        ])

        # 페널티: coverage < 0.3 → confidence ≤ 2
        if context_result.coverage < 0.3 and result.confidence > 2:
            result = result.model_copy(update={"confidence": 2})

        return result
    except Exception:
        return None
