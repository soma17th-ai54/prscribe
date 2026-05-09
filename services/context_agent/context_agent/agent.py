import asyncio
import json
import os

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from context_agent.models import (
    ContextResult, FactBullet, Reference,
    ResearchResult, SearchChunk, VerificationDecision,
)
from context_agent.prompts import REACT_SYSTEM_PROMPT
from context_agent.tools import (
    compare_text_to_facts, context7_search, fetch_url,
    finish, give_up, web_search,
)


def get_solar_pro() -> ChatOpenAI:
    return ChatOpenAI(
        model="solar-pro",
        base_url="https://api.upstage.ai/v1",
        api_key=os.environ["SOLAR_API_KEY"],
        temperature=0,
    )


def _build_chunk_prompt(chunk: SearchChunk, facts: list[FactBullet]) -> str:
    keywords = ", ".join(chunk.keywords)
    facts_text = "\n".join(f"- {f.statement}" for f in facts)
    return (
        f"청크 ID: {chunk.chunk_id}\n"
        f"키워드: {keywords}\n"
        f"검색 의도: {chunk.intent}\n\n"
        f"PR 사실 목록 (검증 기준):\n{facts_text}\n\n"
        f"위 키워드로 외부 문서를 검색하고, 각 결과를 compare_text_to_facts로 검증한 뒤 "
        f"consistent인 것만 finish로 반환하세요."
    )


def _parse_finish_output(messages: list, chunk_id: str) -> list[Reference]:
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and "__FINISH__:" in content:
            try:
                json_str = content.split("__FINISH__:", 1)[1].strip()
                raw_list = json.loads(json_str)
                refs = []
                for r in raw_list:
                    r["chunk_id"] = chunk_id
                    refs.append(Reference(**r))
                return refs
            except Exception:
                return []
    return []


async def _run_chunk_react(
    chunk: SearchChunk,
    facts: list[FactBullet],
    semaphore: asyncio.Semaphore,
) -> tuple[list[Reference], list[VerificationDecision]]:
    async with semaphore:
        agent = create_react_agent(
            model=get_solar_pro(),
            tools=[context7_search, web_search, fetch_url, compare_text_to_facts, finish, give_up],
            prompt=REACT_SYSTEM_PROMPT,
        )
        prompt = _build_chunk_prompt(chunk, facts)
        try:
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=prompt)]},
                    config={"recursion_limit": 20},
                ),
                timeout=90.0,
            )
            refs = _parse_finish_output(result["messages"], chunk.chunk_id)
            log = [
                VerificationDecision(
                    reference_url=ref.url,
                    verdict="consistent",
                    reasoning="ReAct 루프 내 compare_text_to_facts 통과",
                )
                for ref in refs
            ]
            return refs, log
        except (asyncio.TimeoutError, Exception):
            return [], []


async def run_context_agent(research_result: ResearchResult) -> ContextResult:
    chunks = research_result.search_chunks
    if not chunks:
        return ContextResult(
            pr_identifier=research_result.pr_identifier,
            raw_references=[],
            verified_references=[],
            verification_log=[],
            coverage=0.0,
        )

    semaphore = asyncio.Semaphore(5)
    tasks = [_run_chunk_react(chunk, research_result.facts, semaphore) for chunk in chunks]
    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_verified: list[Reference] = []
    all_log: list[VerificationDecision] = []
    covered_chunk_ids: set[str] = set()

    for chunk, outcome in zip(chunks, chunk_results):
        if isinstance(outcome, Exception):
            continue
        refs, log = outcome
        if refs:
            covered_chunk_ids.add(chunk.chunk_id)
            all_verified.extend(refs)
            all_log.extend(log)

    coverage = len(covered_chunk_ids) / len(chunks)

    return ContextResult(
        pr_identifier=research_result.pr_identifier,
        raw_references=all_verified,
        verified_references=all_verified,
        rejected_references=[],
        verification_log=all_log,
        coverage=round(coverage, 4),
    )
