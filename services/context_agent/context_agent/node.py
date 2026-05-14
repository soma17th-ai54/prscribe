from context_agent.agent import _emit_trace, run_context_agent
from context_agent.self_eval import run_self_eval


async def context_node(state) -> dict:
    """LangGraph 노드 함수. GraphState → dict.
    state.research: ResearchResult (Researcher 노드 출력)
    반환: {"context": ContextResult} 또는 {"errors": [...]}"""
    trace_events = list(getattr(state, "react_traces", []) or [])
    try:
        context_result = await run_context_agent(
            state.research,
            emit_trace=trace_events.append,
        )
        _emit_trace(
            trace_events.append,
            "context_self_eval",
            "started",
            "Scoring Context Agent search quality.",
            pr_identifier=context_result.pr_identifier,
            coverage=context_result.coverage,
            verified_references=len(context_result.verified_references),
        )
        before_self_eval_trace_count = len(trace_events)
        context_result.self_eval = await run_self_eval(
            context_result,
            state.research,
            emit_trace=trace_events.append,
        )
        if context_result.self_eval is None:
            emitted_failure_trace = any(
                event.get("stage") == "context_self_eval"
                and event.get("status") in {"warning", "error"}
                for event in trace_events[before_self_eval_trace_count:]
            )
            if not emitted_failure_trace:
                _emit_trace(
                    trace_events.append,
                    "context_self_eval",
                    "warning",
                    "Context self-evaluation failed; continuing without self_eval.",
                    pr_identifier=context_result.pr_identifier,
                )
        else:
            _emit_trace(
                trace_events.append,
                "context_self_eval",
                "completed",
                "Context self-evaluation completed.",
                pr_identifier=context_result.pr_identifier,
                confidence=context_result.self_eval.confidence,
                relevance=context_result.self_eval.relevance,
                diversity=context_result.self_eval.diversity,
            )
    except Exception as e:
        _emit_trace(
            trace_events.append,
            "context_agent",
            "error",
            "Context node failed.",
            error=str(e),
        )
        return {
            "errors": state.errors + [str(e)],
            "react_traces": trace_events,
        }

    return {
        "context": context_result,
        "react_traces": trace_events,
    }
