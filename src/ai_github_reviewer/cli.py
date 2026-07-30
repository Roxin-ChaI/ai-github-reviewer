import argparse
from collections.abc import Sequence

import httpx

from ai_github_reviewer.agent import DEFAULT_MAX_TOOL_ROUNDS, PullRequestReviewAgent
from ai_github_reviewer.config import load_config
from ai_github_reviewer.github_client import GitHubClient
from ai_github_reviewer.github_url import parse_pull_request_url
from ai_github_reviewer.model_client import DeepSeekModelClient


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(None if argv is None else list(argv))
    config = load_config()
    target = parse_pull_request_url(args.pull_request_url)
    model_client = DeepSeekModelClient(
        api_key=config.deepseek_api_key,
        base_url=config.deepseek_base_url,
        model=config.deepseek_model,
    )

    with httpx.Client(follow_redirects=False) as http_client:
        github_client = GitHubClient(
            http_client=http_client,
            api_base_url=config.github_api_base_url,
        )
        agent = PullRequestReviewAgent(
            target=target,
            github_client=github_client,
            model_client=model_client,
            max_tool_rounds=args.max_tool_rounds,
        )
        review = agent.review()

    print(review, end="" if review.endswith("\n") else "\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-github-reviewer")
    parser.add_argument("pull_request_url")
    parser.add_argument(
        "--max-tool-rounds",
        type=_positive_integer,
        default=DEFAULT_MAX_TOOL_ROUNDS,
    )
    return parser


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than or equal to 1")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
