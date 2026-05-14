from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from researcher_agent.agents.researcher import ResearcherError, run_researcher
from researcher_agent.github.client import GitHubClientError

_LIST_MERGE_KEYS = ("errors", "react_traces")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the PRScribe Researcher Agent.")
    parser.add_argument(
        "source_url",
        help="GitHub PR URL or repo URL, e.g. https://github.com/OWNER/REPO/pull/1",
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        default=None,
        help="PR number when source_url is a repo URL. Defaults to latest open PR.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream Researcher LangGraph progress logs as JSON lines to stderr.",
    )
    return parser


def _merge_state(accumulated: dict, partial: dict) -> None:
    for key, value in partial.items():
        if key in _LIST_MERGE_KEYS and key in accumulated:
            accumulated[key] = list(accumulated[key]) + list(value or [])
        else:
            accumulated[key] = value


def _run_stream(source_url: str, pull_number: int | None) -> int:
    from researcher_agent.workflow.graph import researcher_graph

    initial: dict = {"pr_url": source_url}
    if pull_number is not None:
        initial["pr_number"] = pull_number

    accumulated = dict(initial)
    for update in researcher_graph.stream(
        initial,
        config={"recursion_limit": 20},
        stream_mode="updates",
    ):
        for node_name, partial in update.items():
            partial = partial or {}
            _merge_state(accumulated, partial)
            for event in partial.get("react_traces", []) or []:
                payload = {"type": "trace", "langgraph_node": node_name, **event}
                print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)

    if accumulated.get("errors"):
        for error in accumulated["errors"]:
            print(f"prscribe-researcher error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(accumulated.get("research", accumulated), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.stream:
        return _run_stream(args.source_url, args.pr_number)

    try:
        result = run_researcher(args.source_url, pull_number=args.pr_number)
    except (GitHubClientError, ResearcherError) as exc:
        print(f"prscribe-researcher error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
