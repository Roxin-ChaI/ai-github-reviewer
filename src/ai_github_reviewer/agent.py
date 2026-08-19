from collections.abc import Mapping
from typing import Final, cast

from ai_github_reviewer._protocols import GitHubReader, ReviewModel
from ai_github_reviewer.messages import (
    build_review_repair_message,
    build_system_message,
    build_tool_result_message,
    build_user_message,
    copy_assistant_message,
)
from ai_github_reviewer.pull_request import PullRequestData, PullRequestTarget
from ai_github_reviewer.review_result import (
    PullRequestInfo,
    PullRequestTargetInfo,
    ReviewResult,
)
from ai_github_reviewer.review_validation import (
    ReviewValidationError,
    ValidatedReview,
    validate_and_parse_review,
)
from ai_github_reviewer.tool_calls import execute_tool_calls
from ai_github_reviewer.tool_schema import get_pull_request_tool_schema

DEFAULT_MAX_TOOL_ROUNDS: Final = 8

_TARGET_ERROR: Final = "target must be PullRequestTarget"
_MAX_TOOL_ROUNDS_ERROR: Final = "max_tool_rounds must be a positive integer"
_TOOL_ROUND_LIMIT_ERROR: Final = "tool round limit exceeded"
_TOOL_RESULT_REQUIRED_ERROR: Final = (
    "successful pull request tool result required before final review"
)
_REVIEW_CANDIDATE_ERROR: Final = "assistant review must be a non-empty string"
_TOOL_CALLS_ERROR: Final = "assistant tool_calls must be a list or tuple"
_REPAIR_TOOL_CALLS_ERROR: Final = "tool calls are not allowed during review repair"


class ToolRoundLimitError(RuntimeError):
    pass


class ToolResultRequiredError(RuntimeError):
    pass


class ReviewCandidateError(RuntimeError):
    pass


class ReviewRepairToolCallError(RuntimeError):
    pass


class PullRequestReviewAgent:
    def __init__(
        self,
        *,
        target: PullRequestTarget,
        github_client: GitHubReader,
        model_client: ReviewModel,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ) -> None:
        if type(target) is not PullRequestTarget:
            raise ValueError(_TARGET_ERROR)
        if type(max_tool_rounds) is not int or max_tool_rounds < 1:
            raise ValueError(_MAX_TOOL_ROUNDS_ERROR)

        self._target = target
        self._github_client = github_client
        self._model_client = model_client
        self._max_tool_rounds = max_tool_rounds

    def review(self) -> str:
        return self.review_result().markdown

    def review_result(self) -> ReviewResult:
        history = [
            build_system_message(),
            build_user_message(self._target),
        ]
        tool_round_count = 0
        current_result_snapshot: PullRequestData | None = None

        while True:
            response = self._model_client.complete(
                history,
                [get_pull_request_tool_schema()],
            )
            if isinstance(response, Mapping):
                _assistant_tool_calls(response)
            assistant_message = copy_assistant_message(response)
            tool_calls = _assistant_tool_calls(assistant_message)

            if tool_calls:
                if tool_round_count >= self._max_tool_rounds:
                    raise ToolRoundLimitError(_TOOL_ROUND_LIMIT_ERROR)
                tool_round_count += 1

                history.append(assistant_message)
                executions = execute_tool_calls(
                    tool_calls,
                    self._target,
                    self._github_client,
                )
                for execution in executions:
                    history.append(build_tool_result_message(execution))
                current_result_snapshot = executions[-1].result
                continue

            if current_result_snapshot is None:
                raise ToolResultRequiredError(_TOOL_RESULT_REQUIRED_ERROR)

            changed_filenames = tuple(
                changed_file.filename for changed_file in current_result_snapshot.changed_files
            )
            candidate = _review_candidate(assistant_message)
            try:
                validated = validate_and_parse_review(candidate, changed_filenames)
            except ReviewValidationError:
                return self._repair_review(
                    history,
                    assistant_message,
                    changed_filenames,
                    current_result_snapshot,
                )
            return _build_review_result(
                self._target,
                current_result_snapshot,
                validated,
            )

    def _repair_review(
        self,
        history: list[dict[str, object]],
        invalid_assistant_message: dict[str, object],
        changed_filenames: tuple[str, ...],
        result_snapshot: PullRequestData,
    ) -> ReviewResult:
        history.append(invalid_assistant_message)
        history.append(build_review_repair_message())
        response = self._model_client.complete(
            history,
            [get_pull_request_tool_schema()],
        )
        if isinstance(response, Mapping):
            _assistant_tool_calls(response)
        assistant_message = copy_assistant_message(response)
        if _assistant_tool_calls(assistant_message):
            raise ReviewRepairToolCallError(_REPAIR_TOOL_CALLS_ERROR)

        candidate = _review_candidate(assistant_message)
        validated = validate_and_parse_review(candidate, changed_filenames)
        return _build_review_result(
            self._target,
            result_snapshot,
            validated,
        )


def _assistant_tool_calls(
    assistant_message: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    tool_calls = assistant_message.get("tool_calls")
    if tool_calls is None:
        return ()
    if type(tool_calls) not in (list, tuple):
        raise ValueError(_TOOL_CALLS_ERROR)
    collection = cast(list[object] | tuple[object, ...], tool_calls)
    return cast(tuple[Mapping[str, object], ...], tuple(collection))


def _review_candidate(
    assistant_message: Mapping[str, object],
) -> str:
    candidate = assistant_message.get("content")
    if type(candidate) is not str or not candidate.strip():
        raise ReviewCandidateError(_REVIEW_CANDIDATE_ERROR)
    return candidate


def _build_review_result(
    target: PullRequestTarget,
    snapshot: PullRequestData,
    validated: ValidatedReview,
) -> ReviewResult:
    metadata = snapshot.metadata
    return ReviewResult(
        target=PullRequestTargetInfo(
            owner=target.owner,
            repository=target.repository,
            pull_number=target.pull_number,
        ),
        pull_request=PullRequestInfo(
            title=metadata.title,
            body=metadata.body,
            state=metadata.state,
            author=metadata.author,
            base_branch=metadata.base_branch,
            head_branch=metadata.head_branch,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            changed_files=metadata.changed_files,
            additions=metadata.additions,
            deletions=metadata.deletions,
            commits=metadata.commits,
        ),
        summary=validated.summary,
        findings=validated.findings,
        test_gaps=validated.test_gaps,
        maintainability=validated.maintainability,
        assessment=validated.assessment,
        markdown=validated.markdown,
    )
