from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ai_github_reviewer.agent import (
    DEFAULT_MAX_TOOL_ROUNDS,
    PullRequestReviewAgent,
    ReviewCandidateError,
    ReviewRepairToolCallError,
    ToolResultRequiredError,
    ToolRoundLimitError,
)
from ai_github_reviewer.config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_GITHUB_API_BASE_URL,
)
from ai_github_reviewer.exceptions import (
    GitHubRetrievalError,
    InvalidPullRequestURLError,
    ModelReviewError,
    ReviewerClosedError,
    ReviewerConfigurationError,
    ReviewerError,
    ReviewProtocolError,
)
from ai_github_reviewer.github_client import GitHubClient
from ai_github_reviewer.github_url import parse_pull_request_url
from ai_github_reviewer.model_client import DeepSeekModelClient
from ai_github_reviewer.pull_request import PullRequestData, PullRequestTarget
from ai_github_reviewer.review_result import ReviewResult
from ai_github_reviewer.review_validation import ReviewValidationError


@dataclass(frozen=True, slots=True)
class ReviewerConfig:
    deepseek_api_key: str = field(repr=False)
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    github_api_base_url: str = DEFAULT_GITHUB_API_BASE_URL
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "deepseek_api_key",
            _required_text(self.deepseek_api_key, "deepseek_api_key is required"),
        )
        object.__setattr__(
            self,
            "deepseek_base_url",
            _required_text(
                self.deepseek_base_url,
                "deepseek_base_url is required",
            ).rstrip("/"),
        )
        object.__setattr__(
            self,
            "deepseek_model",
            _required_text(self.deepseek_model, "deepseek_model is required"),
        )
        object.__setattr__(
            self,
            "github_api_base_url",
            _required_text(
                self.github_api_base_url,
                "github_api_base_url is required",
            ).rstrip("/"),
        )
        if type(self.max_tool_rounds) is not int or self.max_tool_rounds < 1:
            raise ReviewerConfigurationError("max_tool_rounds must be a positive integer")


class ReviewService(Protocol):
    def review(self, target: PullRequestTarget) -> ReviewResult: ...

    def close(self) -> None: ...


class ReviewerRunner:
    def __init__(self, *, service: ReviewService) -> None:
        self._service = service
        self._closed = False

    def review(self, pull_request_url: str) -> ReviewResult:
        if self._closed:
            raise ReviewerClosedError("reviewer is closed")
        try:
            target = parse_pull_request_url(pull_request_url)
        except (TypeError, ValueError) as exc:
            raise InvalidPullRequestURLError("Invalid GitHub pull request URL") from exc

        result = self._service.review(target)
        if type(result) is not ReviewResult:
            raise ReviewProtocolError("review service returned an invalid result")
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._service.close()


def create_reviewer(config: ReviewerConfig) -> ReviewerRunner:
    if type(config) is not ReviewerConfig:
        raise ReviewerConfigurationError("config must be ReviewerConfig")

    http_client: httpx.Client | None = None
    model_client: DeepSeekModelClient | None = None
    try:
        http_client = httpx.Client(follow_redirects=False)
        github_client = GitHubClient(
            http_client=http_client,
            api_base_url=config.github_api_base_url,
        )
        model_client = DeepSeekModelClient(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            model=config.deepseek_model,
        )
        service = _ProductionReviewService(
            github_client=github_client,
            model_client=model_client,
            http_client=http_client,
            max_tool_rounds=config.max_tool_rounds,
        )
    except Exception as exc:
        if model_client is not None:
            model_client.close()
        if http_client is not None:
            http_client.close()
        if isinstance(exc, ReviewerError):
            raise
        raise ReviewerConfigurationError("reviewer dependencies could not be created") from exc
    return ReviewerRunner(service=service)


class _GitHubBoundary:
    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def get_pull_request(self, target: PullRequestTarget) -> PullRequestData:
        try:
            return self._client.get_pull_request(target)
        except Exception as exc:
            raise GitHubRetrievalError("GitHub pull request retrieval failed") from exc


class _ModelBoundary:
    def __init__(self, client: DeepSeekModelClient) -> None:
        self._client = client

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]:
        try:
            return self._client.complete(messages, tools)
        except Exception as exc:
            raise ModelReviewError("review model request failed") from exc


class _ProductionReviewService:
    def __init__(
        self,
        *,
        github_client: GitHubClient,
        model_client: DeepSeekModelClient,
        http_client: httpx.Client,
        max_tool_rounds: int,
    ) -> None:
        self._github_client = _GitHubBoundary(github_client)
        self._model_client = _ModelBoundary(model_client)
        self._owned_model_client = model_client
        self._owned_http_client = http_client
        self._max_tool_rounds = max_tool_rounds
        self._closed = False

    def review(self, target: PullRequestTarget) -> ReviewResult:
        agent = PullRequestReviewAgent(
            target=target,
            github_client=self._github_client,
            model_client=self._model_client,
            max_tool_rounds=self._max_tool_rounds,
        )
        try:
            return agent.review_result()
        except (
            ReviewCandidateError,
            ReviewRepairToolCallError,
            ReviewValidationError,
            ToolResultRequiredError,
            ToolRoundLimitError,
            TypeError,
            ValueError,
        ) as exc:
            raise ReviewProtocolError("review response failed protocol validation") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._owned_model_client.close()
        finally:
            self._owned_http_client.close()


def _required_text(value: object, message: str) -> str:
    if type(value) is not str or not value.strip():
        raise ReviewerConfigurationError(message)
    return value.strip()
