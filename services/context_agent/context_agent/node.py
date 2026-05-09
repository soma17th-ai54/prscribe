from context_agent.agent import run_context_agent
from context_agent.self_eval import run_self_eval


async def context_node(state) -> dict:
    """LangGraph 노드 함수. GraphState → dict.
    state.research: ResearchResult (Researcher 노드 출력)
    반환: {"context": ContextResult} 또는 {"errors": [...]}"""
    try:
        context_result = await run_context_agent(state.research)
        context_result.self_eval = await run_self_eval(context_result, state.research)
    except Exception as e:
        return {"errors": state.errors + [str(e)]}

    return {
        "context": context_result,
        "react_traces": state.react_traces,
    }
