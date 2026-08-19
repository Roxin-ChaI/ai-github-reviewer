import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from typing import Any

import pytest

import ai_github_reviewer
import ai_github_reviewer.runner as runner_module
from ai_github_reviewer import (
    GitHubRetrievalError,
    InvalidPullRequestURLError,
    ModelReviewError,
    ReviewerClosedError,
    ReviewerConfig,
    ReviewerConfigurationError,
    ReviewerRunner,
    ReviewProtocolError,
    ReviewResult,
    create_reviewer,
)
from ai_github_reviewer.pull_request import (
    ChangedFile,
    PullRequestData,
    PullRequestMetadata,
    PullRequestTarget,
)

URL = "https://github.com/example-owner/example-repository/pull/123"
TARGET = PullRequestTarget("example-owner", "example-repository", 123)
SECRET = "controlled-secret"


def _pull_request_data(*filenames: str) -> PullRequestData:
    return PullRequestData(
        metadata=PullRequestMetadata(
            title="Controlled change",
            body="Controlled body",
            state="open",
            author="controlled-author",
            base_branch="main",
            head_branch="feature",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-02T00:00:00Z",
            changed_files=len(filenames),
            additions=3,
            deletions=1,
            commits=2,
        ),
        changed_files=tuple(
            ChangedFile(
                filename=filename,
                status="modified",
                additions=2,
                deletions=1,
                changes=3,
                patch="@@ controlled @@",
            )
            for filename in filenames
        ),
    )


def _review() -> str:
    return """# Pull Request Review

## Summary

Controlled summary.

## Findings

### Finding 1

- Severity: High
- File: src/first.py
- Location: line 10
- Issue: First controlled issue.
- Evidence: First controlled evidence.
- Recommendation: First controlled recommendation.

### Finding 2

- Severity: Low
- File: src/second.py
- Location: file-level
- Issue: Second controlled issue.
- Evidence: Second controlled evidence.
- Recommendation: Second controlled recommendation.

## Test Gaps

Controlled test gap.

## Maintainability

Controlled maintainability note.

## Final Assessment

Request changes
"""


def _tool_response() -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "controlled-call",
                "type": "function",
                "function": {
                    "name": "get_pull_request",
                    "arguments": json.dumps(
                        {
                            "owner": TARGET.owner,
                            "repository": TARGET.repository,
                            "pull_number": TARGET.pull_number,
                        }
                    ),
                },
            }
        ],
    }


class ScriptedModel:
    def __init__(self, responses: Sequence[Mapping[str, object] | BaseException]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[object, object]] = []
        self.close_calls = 0

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        self.requests.append((deepcopy(list(messages)), deepcopy(list(tools))))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return dict(response)

    def close(self) -> None:
        self.close_calls += 1


class ScriptedGitHub:
    def __init__(self, outcome: PullRequestData | BaseException) -> None:
        self.outcome = outcome
        self.targets: list[PullRequestTarget] = []

    def get_pull_request(self, target: PullRequestTarget) -> PullRequestData:
        self.targets.append(target)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class CloseRecorder:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeService:
    def __init__(self, outcome: ReviewResult | BaseException | object) -> None:
        self.outcome = outcome
        self.targets: list[PullRequestTarget] = []
        self.close_calls = 0

    def review(self, target: PullRequestTarget) -> ReviewResult:
        self.targets.append(target)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome  # type: ignore[return-value]

    def close(self) -> None:
        self.close_calls += 1


def _production_service(
    github: ScriptedGitHub,
    model: ScriptedModel,
    http_client: CloseRecorder | None = None,
) -> tuple[runner_module._ProductionReviewService, CloseRecorder]:
    owned_http = http_client or CloseRecorder()
    return (
        runner_module._ProductionReviewService(
            github_client=github,  # type: ignore[arg-type]
            model_client=model,  # type: ignore[arg-type]
            http_client=owned_http,  # type: ignore[arg-type]
            max_tool_rounds=8,
        ),
        owned_http,
    )


def test_root_package_exports_stable_public_api() -> None:
    expected = {
        "GitHubRetrievalError",
        "InvalidPullRequestURLError",
        "ModelReviewError",
        "PullRequestInfo",
        "PullRequestTargetInfo",
        "ReviewAssessment",
        "ReviewFinding",
        "ReviewProtocolError",
        "ReviewResult",
        "ReviewService",
        "ReviewSeverity",
        "ReviewerClosedError",
        "ReviewerConfig",
        "ReviewerConfigurationError",
        "ReviewerError",
        "ReviewerRunner",
        "create_reviewer",
    }

    assert set(ai_github_reviewer.__all__) == expected
    assert all(hasattr(ai_github_reviewer, name) for name in expected)


def test_reviewer_config_normalizes_values_and_uses_real_defaults() -> None:
    config = ReviewerConfig(
        deepseek_api_key="  controlled-secret  ",
        deepseek_base_url="  https://deepseek.test///  ",
        deepseek_model="  controlled-model  ",
        github_api_base_url="  https://github.test/api///  ",
        max_tool_rounds=3,
    )

    assert config.deepseek_api_key == "controlled-secret"
    assert config.deepseek_base_url == "https://deepseek.test"
    assert config.deepseek_model == "controlled-model"
    assert config.github_api_base_url == "https://github.test/api"
    assert config.max_tool_rounds == 3
    assert ReviewerConfig(deepseek_api_key=SECRET).deepseek_model == "deepseek-v4-flash"


def test_reviewer_config_is_immutable_and_hides_secret() -> None:
    config = ReviewerConfig(deepseek_api_key=SECRET)

    assert SECRET not in repr(config)
    assert SECRET not in str(config)
    with pytest.raises(FrozenInstanceError):
        config.deepseek_model = "replacement"


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("deepseek_api_key", " ", "deepseek_api_key is required"),
        ("deepseek_base_url", "", "deepseek_base_url is required"),
        ("deepseek_model", "\t", "deepseek_model is required"),
        ("github_api_base_url", None, "github_api_base_url is required"),
        ("max_tool_rounds", 0, "max_tool_rounds must be a positive integer"),
        ("max_tool_rounds", True, "max_tool_rounds must be a positive integer"),
    ],
)
def test_reviewer_config_rejects_invalid_values(
    field_name: str,
    value: object,
    message: str,
) -> None:
    kwargs: dict[str, Any] = {"deepseek_api_key": SECRET, field_name: value}

    with pytest.raises(ReviewerConfigurationError, match=f"^{message}$"):
        ReviewerConfig(**kwargs)


def test_public_config_and_runner_expose_no_github_write_capability() -> None:
    assert "github_token" not in {item.name for item in fields(ReviewerConfig)}
    runner = ReviewerRunner(service=FakeService(object()))
    for name in (
        "comment",
        "create_review",
        "approve",
        "request_changes",
        "merge",
        "close_pull_request",
    ):
        assert not hasattr(runner, name)


def test_runner_rejects_invalid_url_with_public_exception() -> None:
    service = FakeService(object())
    runner = ReviewerRunner(service=service)

    with pytest.raises(
        InvalidPullRequestURLError,
        match="^Invalid GitHub pull request URL$",
    ) as exc_info:
        runner.review("http://github.com/owner/repo/pull/1")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert service.targets == []


def test_runner_rejects_invalid_service_result() -> None:
    runner = ReviewerRunner(service=FakeService(object()))

    with pytest.raises(
        ReviewProtocolError,
        match="^review service returned an invalid result$",
    ):
        runner.review(URL)


def test_runner_propagates_unknown_service_exception_unchanged() -> None:
    error = LookupError("controlled unknown failure")
    runner = ReviewerRunner(service=FakeService(error))

    with pytest.raises(LookupError) as exc_info:
        runner.review(URL)

    assert exc_info.value is error


def test_runner_close_is_idempotent_and_prevents_later_review() -> None:
    service = FakeService(object())
    runner = ReviewerRunner(service=service)

    runner.close()
    runner.close()

    assert service.close_calls == 1
    with pytest.raises(ReviewerClosedError, match="^reviewer is closed$"):
        runner.review(URL)
    assert service.targets == []


def test_production_pipeline_returns_typed_result_from_one_review() -> None:
    github = ScriptedGitHub(_pull_request_data("src/first.py", "src/second.py"))
    model = ScriptedModel([_tool_response(), {"role": "assistant", "content": _review()}])
    service, http_client = _production_service(github, model)
    runner = ReviewerRunner(service=service)
    url_before = deepcopy(URL)

    try:
        result = runner.review(URL)
    finally:
        runner.close()

    assert result.target.owner == "example-owner"
    assert result.target.repository == "example-repository"
    assert result.target.pull_number == 123
    assert result.pull_request.title == "Controlled change"
    assert result.pull_request.body == "Controlled body"
    assert result.pull_request.changed_files == 2
    assert result.summary == "Controlled summary."
    assert [finding.severity for finding in result.findings] == ["High", "Low"]
    assert [finding.file_path for finding in result.findings] == [
        "src/first.py",
        "src/second.py",
    ]
    assert [finding.location for finding in result.findings] == [
        "line 10",
        "file-level",
    ]
    assert result.findings[0].issue == "First controlled issue."
    assert result.findings[0].evidence == "First controlled evidence."
    assert result.findings[0].recommendation == "First controlled recommendation."
    assert result.test_gaps == "Controlled test gap."
    assert result.maintainability == "Controlled maintainability note."
    assert result.assessment == "Request changes"
    assert result.markdown == _review()
    assert github.targets == [TARGET]
    assert len(model.requests) == 2
    assert model.responses == []
    assert model.close_calls == 1
    assert http_client.close_calls == 1
    assert URL == url_before


def test_github_failure_maps_to_public_error_without_model_retry() -> None:
    controlled = RuntimeError("private GitHub detail")
    github = ScriptedGitHub(controlled)
    model = ScriptedModel([_tool_response()])
    service, _ = _production_service(github, model)
    runner = ReviewerRunner(service=service)

    with pytest.raises(
        GitHubRetrievalError,
        match="^GitHub pull request retrieval failed$",
    ) as exc_info:
        runner.review(URL)

    assert exc_info.value.__cause__ is controlled
    assert len(model.requests) == 1
    assert github.targets == [TARGET]


def test_model_failure_maps_to_public_error_without_github_call() -> None:
    controlled = RuntimeError("private model detail")
    github = ScriptedGitHub(_pull_request_data("src/first.py"))
    model = ScriptedModel([controlled])
    service, _ = _production_service(github, model)
    runner = ReviewerRunner(service=service)

    with pytest.raises(
        ModelReviewError,
        match="^review model request failed$",
    ) as exc_info:
        runner.review(URL)

    assert exc_info.value.__cause__ is controlled
    assert len(model.requests) == 1
    assert github.targets == []


def test_protocol_failure_maps_to_public_error() -> None:
    github = ScriptedGitHub(_pull_request_data("src/first.py"))
    model = ScriptedModel([{"role": "assistant", "content": _review()}])
    service, _ = _production_service(github, model)
    runner = ReviewerRunner(service=service)

    with pytest.raises(
        ReviewProtocolError,
        match="^review response failed protocol validation$",
    ) as exc_info:
        runner.review(URL)

    assert exc_info.value.__cause__ is not None
    assert github.targets == []


def test_create_reviewer_wires_real_boundaries_and_owned_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}

    class FakeHTTPClient(CloseRecorder):
        def __init__(self, **kwargs: object) -> None:
            super().__init__()
            created["http"] = self
            created["http_kwargs"] = kwargs

    class FakeGitHubClient:
        def __init__(self, **kwargs: object) -> None:
            created["github"] = self
            created["github_kwargs"] = kwargs

    class FakeModelClient(CloseRecorder):
        def __init__(self, **kwargs: object) -> None:
            super().__init__()
            created["model"] = self
            created["model_kwargs"] = kwargs

    monkeypatch.setattr(runner_module.httpx, "Client", FakeHTTPClient)
    monkeypatch.setattr(runner_module, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(runner_module, "DeepSeekModelClient", FakeModelClient)
    config = ReviewerConfig(
        deepseek_api_key=SECRET,
        deepseek_base_url="https://deepseek.test",
        deepseek_model="controlled-model",
        github_api_base_url="https://github.test",
        max_tool_rounds=4,
    )

    reviewer = create_reviewer(config)
    reviewer.close()

    assert isinstance(reviewer, ReviewerRunner)
    assert created["http_kwargs"] == {"follow_redirects": False}
    assert created["github_kwargs"] == {
        "http_client": created["http"],
        "api_base_url": "https://github.test",
    }
    assert created["model_kwargs"] == {
        "api_key": SECRET,
        "base_url": "https://deepseek.test",
        "model": "controlled-model",
    }
    assert created["model"].close_calls == 1
    assert created["http"].close_calls == 1


def test_factory_failure_closes_created_resource_and_hides_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_client = CloseRecorder()
    controlled = RuntimeError("private constructor detail")
    monkeypatch.setattr(runner_module.httpx, "Client", lambda **kwargs: http_client)
    monkeypatch.setattr(
        runner_module,
        "DeepSeekModelClient",
        lambda **kwargs: (_ for _ in ()).throw(controlled),
    )

    with pytest.raises(
        ReviewerConfigurationError,
        match="^reviewer dependencies could not be created$",
    ) as exc_info:
        create_reviewer(ReviewerConfig(deepseek_api_key=SECRET))

    assert exc_info.value.__cause__ is controlled
    assert http_client.close_calls == 1


def test_factory_rejects_non_config_without_creating_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail_http(**kwargs: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(runner_module.httpx, "Client", fail_http)

    with pytest.raises(
        ReviewerConfigurationError,
        match="^config must be ReviewerConfig$",
    ):
        create_reviewer(object())

    assert calls == 0
