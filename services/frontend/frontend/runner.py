from __future__ import annotations

import asyncio
import queue
import threading
from typing import Literal, Optional

from orchestration.graph import prscribe_graph

ModeOverride = Optional[Literal["full", "minimal_context"]]

_LIST_MERGE_KEYS = ("errors", "react_traces", "verifications")


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
                config={"recursion_limit": 50},
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
                    q.put(("node_update", node_name, partial))
            q.put(("done", accumulated))

        try:
            asyncio.run(_drive())
        except BaseException as exc:  # noqa: BLE001
            q.put(("error", exc))

    threading.Thread(target=_worker, daemon=True).start()
    return q
