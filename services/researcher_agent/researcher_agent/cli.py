from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from researcher_agent.agents.researcher import ResearcherError, run_researcher
from researcher_agent.github.client import GitHubClientError


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
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        result = run_researcher(args.source_url, pull_number=args.pr_number)
    except (GitHubClientError, ResearcherError) as exc:
        print(f"prscribe-researcher error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
