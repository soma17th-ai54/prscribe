import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from context_agent.solar import solar_api_key


def get_solar_mini() -> ChatOpenAI:
    return ChatOpenAI(
        model="solar-mini",
        base_url="https://api.upstage.ai/v1",
        api_key=solar_api_key(),
        temperature=0,
    )


_VERIFY_SYSTEM_PROMPT = """당신은 문서 발췌문이 PR 사실과 일치하는지 판별하는 검증자입니다.

판별 기준:
- consistent: 발췌문이 PR 사실을 직접 지지하거나 확인한다
- contradicts: 발췌문이 PR 사실과 명백히 모순된다
- unrelated: 발췌문이 PR 사실과 주제 자체가 다르다
- needs_review: 관련은 있으나 일치/모순 판단이 불분명하다

reasoning은 1~3문장으로 판단 근거를 설명한다.

반드시 다음 JSON 형식으로만 응답하세요:
{"verdict": "consistent|contradicts|unrelated|needs_review", "reasoning": "판단 근거"}"""


class _VerifyOutput(BaseModel):
    verdict: Literal["consistent", "contradicts", "unrelated", "needs_review"]
    reasoning: str


async def _compare_impl(excerpt: str, facts: list[str]) -> _VerifyOutput:
    # solar-mini는 with_structured_output default(parse)를 지원하지 않으므로 json_mode 사용
    llm = get_solar_mini().with_structured_output(_VerifyOutput, method="json_mode")
    facts_text = "\n".join(f"- {f}" for f in facts)
    result = await llm.ainvoke([
        SystemMessage(content=_VERIFY_SYSTEM_PROMPT),
        HumanMessage(content=f"발췌문:\n{excerpt}\n\nPR 사실 목록:\n{facts_text}"),
    ])
    return result


@tool
async def compare_text_to_facts(excerpt: str, facts_json: str) -> str:
    """발췌문(excerpt)이 PR 사실 목록과 일치하는지 검증한다. verdict 4종 반환.
    excerpt: 검증할 문서 발췌문 (100~500자)
    facts_json: FactBullet.statement 문자열 list의 JSON (예: '["PR uses select_related", ...]')"""
    facts: list[str] = json.loads(facts_json)
    result = await _compare_impl(excerpt, facts)
    return json.dumps({"verdict": result.verdict, "reasoning": result.reasoning}, ensure_ascii=False)
