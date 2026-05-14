import asyncio
import json
import time
from typing import Any, Callable

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from context_agent.models import (
    ContextResult, FactBullet, Reference,
    ResearchResult, SearchChunk, VerificationDecision,
)
from context_agent.prompts import REACT_SYSTEM_PROMPT
from context_agent.solar import solar_api_key
from context_agent.tools import (
    compare_text_to_facts, context7_search, fetch_url,
    finish, give_up, web_search,
)

TraceEmitter = Callable[[dict[str, Any]], None]
CONTEXT_RECURSION_LIMIT = 10
CONTEXT_CHUNK_TIMEOUT_SECONDS = 90.0


def get_solar_pro() -> ChatOpenAI:
    return ChatOpenAI(
        model="solar-pro",
        base_url="https://api.upstage.ai/v1",
        api_key=solar_api_key(),
        temperature=0,
    )


def _trace_event(
    stage: str,
    status: str,
    message: str,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "node": "context",
        "stage": stage,
        "status": status,
        "message": message,
        "metadata": {key: value for key, value in metadata.items() if value is not None},
    }


def _emit_trace(
    emit_trace: TraceEmitter | None,
    stage: str,
    status: str,
    message: str,
    **metadata: Any,
) -> None:
    if emit_trace is None:
        return
    emit_trace(_trace_event(stage, status, message, **metadata))


def _duration_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


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


def _parse_give_up_reason(messages: list) -> str | None:
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and "__GIVE_UP__:" in content:
            return content.split("__GIVE_UP__:", 1)[1].strip() or "unknown"
    return None


async def _run_chunk_react(
    chunk: SearchChunk,
    facts: list[FactBullet],
    semaphore: asyncio.Semaphore,
    emit_trace: TraceEmitter | None = None,
) -> tuple[list[Reference], list[VerificationDecision]]:
    async with semaphore:
        started_at = time.perf_counter()
        keywords = ", ".join(chunk.keywords)
        _emit_trace(
            emit_trace,
            "context_chunk",
            "started",
            "Starting Context ReAct search for a search chunk.",
            chunk_id=chunk.chunk_id,
            intent=chunk.intent,
            keywords=keywords,
            related_files=chunk.related_files,
        )
        prompt = _build_chunk_prompt(chunk, facts)
        try:
            agent = create_react_agent(
                model=get_solar_pro(),
                tools=[context7_search, web_search, fetch_url, compare_text_to_facts, finish, give_up],
                prompt=REACT_SYSTEM_PROMPT,
            )
            _emit_trace(
                emit_trace,
                "context_chunk",
                "running",
                "Calling Context ReAct agent for search, fetch, and verification.",
                chunk_id=chunk.chunk_id,
                recursion_limit=CONTEXT_RECURSION_LIMIT,
                timeout_seconds=CONTEXT_CHUNK_TIMEOUT_SECONDS,
            )
            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=prompt)]},
                    config={"recursion_limit": CONTEXT_RECURSION_LIMIT},
                ),
                timeout=CONTEXT_CHUNK_TIMEOUT_SECONDS,
            )
            refs = _parse_finish_output(result["messages"], chunk.chunk_id)
            give_up_reason = _parse_give_up_reason(result["messages"])
            if refs:
                _emit_trace(
                    emit_trace,
                    "context_chunk",
                    "completed",
                    "Context chunk produced verified references.",
                    chunk_id=chunk.chunk_id,
                    verified_references=len(refs),
                    duration_ms=_duration_ms(started_at),
                )
            elif give_up_reason:
                _emit_trace(
                    emit_trace,
                    "context_chunk",
                    "warning",
                    "Context chunk gave up without verified references.",
                    chunk_id=chunk.chunk_id,
                    reason=give_up_reason,
                    duration_ms=_duration_ms(started_at),
                )
            else:
                _emit_trace(
                    emit_trace,
                    "context_chunk",
                    "warning",
                    "Context chunk ended without a finish payload.",
                    chunk_id=chunk.chunk_id,
                    duration_ms=_duration_ms(started_at),
                )
            log = [
                VerificationDecision(
                    reference_url=ref.url,
                    verdict="consistent",
                    reasoning="ReAct 루프 내 compare_text_to_facts 통과",
                )
                for ref in refs
            ]
            return refs, log
        except asyncio.TimeoutError:
            _emit_trace(
                emit_trace,
                "context_chunk",
                "error",
                "Context chunk timed out.",
                chunk_id=chunk.chunk_id,
                timeout_seconds=CONTEXT_CHUNK_TIMEOUT_SECONDS,
                duration_ms=_duration_ms(started_at),
            )
            return [], []
        except Exception as exc:
            _emit_trace(
                emit_trace,
                "context_chunk",
                "error",
                "Context chunk failed.",
                chunk_id=chunk.chunk_id,
                error=str(exc),
                duration_ms=_duration_ms(started_at),
            )
            return [], []


async def run_context_agent(
    research_result: ResearchResult,
    emit_trace: TraceEmitter | None = None,
) -> ContextResult:
    started_at = time.perf_counter()
    chunks = research_result.search_chunks
    _emit_trace(
        emit_trace,
        "context_agent",
        "started",
        "Context Agent started.",
        pr_identifier=research_result.pr_identifier,
        search_chunks=len(chunks),
        facts=len(research_result.facts),
    )
    if not chunks:
        _emit_trace(
            emit_trace,
            "context_agent",
            "warning",
            "No search chunks were provided; skipping external context search.",
            pr_identifier=research_result.pr_identifier,
            duration_ms=_duration_ms(started_at),
        )
        return ContextResult(
            pr_identifier=research_result.pr_identifier,
            raw_references=[],
            verified_references=[],
            verification_log=[],
            coverage=0.0,
        )

    semaphore = asyncio.Semaphore(5)
    tasks = [
        _run_chunk_react(chunk, research_result.facts, semaphore, emit_trace=emit_trace)
        for chunk in chunks
    ]
    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_verified: list[Reference] = []
    all_log: list[VerificationDecision] = []
    covered_chunk_ids: set[str] = set()

    for chunk, outcome in zip(chunks, chunk_results):
        if isinstance(outcome, Exception):
            _emit_trace(
                emit_trace,
                "context_chunk",
                "error",
                "Context chunk task raised after gather.",
                chunk_id=chunk.chunk_id,
                error=str(outcome),
            )
            continue
        refs, log = outcome
        if refs:
            covered_chunk_ids.add(chunk.chunk_id)
            all_verified.extend(refs)
            all_log.extend(log)

    coverage = len(covered_chunk_ids) / len(chunks)
    _emit_trace(
        emit_trace,
        "context_agent",
        "completed",
        "Context Agent completed.",
        pr_identifier=research_result.pr_identifier,
        coverage=round(coverage, 4),
        verified_references=len(all_verified),
        covered_chunks=len(covered_chunk_ids),
        total_chunks=len(chunks),
        duration_ms=_duration_ms(started_at),
    )

    return ContextResult(
        pr_identifier=research_result.pr_identifier,
        raw_references=all_verified,
        verified_references=all_verified,
        rejected_references=[],
        verification_log=all_log,
        coverage=round(coverage, 4),
    )
