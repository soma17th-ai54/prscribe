from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import warnings
from typing import Literal, Optional

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)

from orchestration.graph import prscribe_graph

ModeOverride = Optional[Literal["full", "minimal_context"]]

_LIST_MERGE_KEYS = ("errors", "react_traces", "verifications")
PIPELINE_RECURSION_LIMIT = 5
_LOGGER = logging.getLogger("prscribe.backend")

if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    _LOGGER.addHandler(_handler)
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False


def _log_trace_events(node_name: str, events: list[dict]) -> None:
    for event in events:
        payload = {"langgraph_node": node_name, **event}
        status = event.get("status")
        if status == "error":
            _LOGGER.error(json.dumps(payload, ensure_ascii=False))
        elif status == "warning":
            _LOGGER.warning(json.dumps(payload, ensure_ascii=False))
        else:
            _LOGGER.info(json.dumps(payload, ensure_ascii=False))


def _log_node_update(node_name: str, partial: dict) -> None:
    payload = {
        "type": "node_update",
        "langgraph_node": node_name,
        "state_keys": sorted(partial.keys()),
    }
    if partial.get("errors"):
        _LOGGER.error(json.dumps(payload, ensure_ascii=False))
    else:
        _LOGGER.info(json.dumps(payload, ensure_ascii=False))


def start_run(pr_url: str, mode_override: ModeOverride) -> "queue.Queue":
    """Spawn a daemon thread that drives the LangGraph pipeline.

    The worker pushes events onto the returned Queue. The Streamlit main
    thread is the sole consumer. The worker NEVER touches st.session_state.

    Queue protocol (tuples):
      ("node_update", node_name: str, partial: dict)
      ("done",        final_state: dict)
      ("error",       exc: BaseException)
    """
    q: queue.Queue = queue.Queue()
    initial: dict = {"pr_url": pr_url}
    if mode_override is not None:
        initial["mode_override"] = mode_override

    def _worker() -> None:
        async def _drive() -> None:
            accumulated: dict = dict(initial)
            async for update in prscribe_graph.astream(
                initial,
                config={"recursion_limit": PIPELINE_RECURSION_LIMIT},
                stream_mode="updates",
            ):
                # `updates` mode yields {node_name: partial_state_dict} per step.
                for node_name, partial in update.items():
                    partial = partial or {}
                    for k, v in partial.items():
                        if k in _LIST_MERGE_KEYS and k in accumulated:
                            accumulated[k] = list(accumulated[k]) + list(v or [])
                        else:
                            accumulated[k] = v
                    _log_node_update(node_name, partial)
                    _log_trace_events(node_name, list(partial.get("react_traces") or []))
                    q.put(("node_update", node_name, partial))
            q.put(("done", accumulated))

        try:
            asyncio.run(_drive())
        except BaseException as exc:  # noqa: BLE001
            q.put(("error", exc))

    threading.Thread(target=_worker, daemon=True).start()
    return q
