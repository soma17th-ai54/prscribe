from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from writer_agent.agents.writer import WriterError, run_writer_pipeline


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return loaded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the PRScribe Writer Agent.")
    parser.add_argument("research_json", type=Path, help="Path to ResearchResult JSON.")
    parser.add_argument(
        "--context-json",
        type=Path,
        default=None,
        help="Path to ContextResult JSON. If omitted, minimal_context is used.",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "minimal_context"],
        default="full",
        help="Writer mode. full automatically falls back to minimal_context when no verified references exist.",
    )
    parser.add_argument(
        "--draft-only",
        action="store_true",
        help="Print only DraftResult JSON instead of draft plus VerificationResult list.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        research = _load_json(args.research_json)
        context = _load_json(args.context_json) if args.context_json else None
        result = run_writer_pipeline(research, context, mode=args.mode)
    except (OSError, ValueError, WriterError) as exc:
        print(f"prscribe-writer error: {exc}", file=sys.stderr)
        return 1

    payload = (
        result.draft.model_dump(mode="json")
        if args.draft_only
        else result.model_dump(mode="json")
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
