import builtins
import json
import logging
import os
import socket
from collections.abc import Mapping, Sequence
from copy import deepcopy

import openai
import pytest

import ai_github_reviewer.agent as agent_module
from ai_github_reviewer.agent import (
    DEFAULT_MAX_TOOL_ROUNDS,
    PullRequestReviewAgent,
    ReviewCandidateError,
    ToolResultRequiredError,
    ToolRoundLimitError,
)
from ai_github_reviewer.github_client import ChangedFilesIntegrityError
from ai_github_reviewer.messages import build_system_message, build_user_message
from ai_github_reviewer.pull_request import (
    ChangedFile,
    PullRequestData,
    PullRequestMetadata,
    PullRequestTarget,
    build_pull_request_data,
)
from ai_github_reviewer.review_validation import ReviewValidationError
from ai_github_reviewer.tool_schema import get_pull_request_tool_schema

TARGET = PullRequestTarget("owner", "repository", 1)
TARGET_ERROR = "target must be PullRequestTarget"
ROUNDS_ERROR = "max_tool_rounds must be a positive integer"
LIMIT_ERROR = "tool round limit exceeded"
RESULT_REQUIRED_ERROR = "successful pull request tool result required before final review"
CANDIDATE_ERROR = "assistant review must be a non-empty string"
TOOL_CALLS_ERROR = "assistant tool_calls must be a list or tuple"


class ControlledSequence(Sequence[object]):
    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> object:
        if index == 0:
            return {"id": "controlled"}
        raise IndexError


class ListSubclass(list[object]):
    pass


class TupleSubclass(tuple[object, ...]):
    pass


def _controlled_generator():
    yield {"id": "controlled"}


def _result(*filenames: str) -> PullRequestData:
    metadata = PullRequestMetadata(
        title="Controlled change",
        body=None,
        state="open",
        author="author",
        base_branch="main",
        head_branch="feature",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        changed_files=len(filenames),
        additions=len(filenames),
        deletions=0,
        commits=1,
    )
    changed_files = [
        ChangedFile(
            filename=filename,
            status="modified",
            additions=1,
            deletions=0,
            changes=1,
            patch=None,
        )
        for filename in filenames
    ]
    return build_pull_request_data(metadata, changed_files)


def _tool_call(
    call_id: str,
    *,
    target: PullRequestTarget = TARGET,
    name: str = "get_pull_request",
    arguments: str | None = None,
) -> dict[str, object]:
    if arguments is None:
        arguments = json.dumps(
            {
                "owner": target.owner,
                "repository": target.repository,
                "pull_number": target.pull_number,
            },
            separators=(",", ":"),
        )
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def _tool_response(
    *call_ids: str,
    content: object = None,
    calls: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    tool_calls: object
    if calls is None:
        tool_calls = [_tool_call(call_id) for call_id in call_ids]
    else:
        tool_calls = list(calls)
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls,
    }


def _review(
    *,
    filename: str | None = None,
    severity: str = "Low",
    assessment: str = "Approve with minor comments",
) -> str:
    if filename is None:
        findings = "No actionable issues identified from the available pull request data."
        assessment = "Approve"
    else:
        findings = f"""### Finding 1

- Severity: {severity}
- File: {filename}
- Location: Unknown
- Issue: A controlled issue exists.
- Evidence: The controlled result contains the file.
- Recommendation: Review the controlled change."""
    return f"""# Pull Request Review

## Summary

Controlled summary.

## Findings

{findings}

## Test Gaps

Controlled test gap.

## Maintainability

Controlled maintainability note.

## Final Assessment

{assessment}
"""


class ScriptedModelClient:
    def __init__(self, responses: Sequence[Mapping[str, object]]) -> None:
        self.responses = deepcopy(list(responses))
        self.requests: list[dict[str, object]] = []

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        self.requests.append(
            {
                "messages": deepcopy(list(messages)),
                "tools": deepcopy(list(tools)),
            }
        )
        if not self.responses:
            raise AssertionError("unexpected extra model call")
        return self.responses.pop(0)


class FakeGitHubClient:
    def __init__(
        self,
        outcomes: Sequence[PullRequestData | BaseException],
    ) -> None:
        self.outcomes = list(outcomes)
        self.targets: list[PullRequestTarget] = []

    def get_pull_request(
        self,
        target: PullRequestTarget,
    ) -> PullRequestData:
        self.targets.append(target)
        if not self.outcomes:
            raise AssertionError("unexpected extra GitHub call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _agent(
    responses: Sequence[Mapping[str, object]],
    outcomes: Sequence[PullRequestData | BaseException] = (),
    *,
    target: PullRequestTarget = TARGET,
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
) -> tuple[PullRequestReviewAgent, ScriptedModelClient, FakeGitHubClient]:
    model_client = ScriptedModelClient(responses)
    github_client = FakeGitHubClient(outcomes)
    agent = PullRequestReviewAgent(
        target=target,
        github_client=github_client,
        model_client=model_client,
        max_tool_rounds=max_tool_rounds,
    )
    return agent, model_client, github_client


def _roles(request: dict[str, object]) -> list[object]:
    return [message["role"] for message in request["messages"]]


def test_default_max_tool_rounds_is_eight() -> None:
    assert DEFAULT_MAX_TOOL_ROUNDS == 8


@pytest.mark.parametrize("max_tool_rounds", [1, 2, 8, 17])
def test_accepts_positive_integer_tool_round_limits(max_tool_rounds: int) -> None:
    agent, model_client, github_client = _agent(
        [{"role": "assistant", "content": _review()}],
        max_tool_rounds=max_tool_rounds,
    )

    with pytest.raises(ToolResultRequiredError, match=f"^{RESULT_REQUIRED_ERROR}$"):
        agent.review()

    assert len(model_client.requests) == 1
    assert github_client.targets == []


@pytest.mark.parametrize(
    "max_tool_rounds",
    [0, -1, True, False, "8", 8.0, None],
)
def test_rejects_invalid_tool_round_limit_before_dependencies(
    max_tool_rounds: object,
) -> None:
    model_client = ScriptedModelClient([])
    github_client = FakeGitHubClient([])

    with pytest.raises(ValueError, match=f"^{ROUNDS_ERROR}$"):
        PullRequestReviewAgent(
            target=TARGET,
            github_client=github_client,
            model_client=model_client,
            max_tool_rounds=max_tool_rounds,
        )

    assert model_client.requests == []
    assert github_client.targets == []


@pytest.mark.parametrize("invalid_target", [None, {}, object(), True])
def test_rejects_invalid_target_before_dependencies(invalid_target: object) -> None:
    model_client = ScriptedModelClient([])
    github_client = FakeGitHubClient([])

    with pytest.raises(ValueError, match=f"^{TARGET_ERROR}$"):
        PullRequestReviewAgent(
            target=invalid_target,
            github_client=github_client,
            model_client=model_client,
        )

    assert model_client.requests == []
    assert github_client.targets == []


def test_rejects_pull_request_target_subclass() -> None:
    class TargetSubclass(PullRequestTarget):
        pass

    with pytest.raises(ValueError, match=f"^{TARGET_ERROR}$"):
        PullRequestReviewAgent(
            target=TargetSubclass("owner", "repository", 1),
            github_client=FakeGitHubClient([]),
            model_client=ScriptedModelClient([]),
        )


def test_constructor_accepts_fakes_without_calling_them_or_modifying_target() -> None:
    target_before = deepcopy(TARGET)
    model_client = ScriptedModelClient([])
    github_client = FakeGitHubClient([])

    PullRequestReviewAgent(
        target=TARGET,
        github_client=github_client,
        model_client=model_client,
    )

    assert TARGET == target_before
    assert model_client.requests == []
    assert github_client.targets == []


def test_single_round_finding_review_preserves_history_and_identifiers() -> None:
    final_review = _review(filename="src/example.py")
    assistant_fixture = _tool_response("call_one")
    assistant_before = deepcopy(assistant_fixture)
    result = _result("src/example.py")
    result_before = deepcopy(result)
    target_before = deepcopy(TARGET)
    agent, model_client, github_client = _agent(
        [assistant_fixture, {"role": "assistant", "content": final_review}],
        [result],
    )

    returned = agent.review()

    assert returned is final_review
    assert len(model_client.requests) == 2
    assert github_client.targets == [TARGET]
    assert _roles(model_client.requests[0]) == ["system", "user"]
    assert _roles(model_client.requests[1]) == ["system", "user", "assistant", "tool"]
    second_history = model_client.requests[1]["messages"]
    assert second_history[2] == assistant_fixture
    assert second_history[3]["tool_call_id"] == "call_one"
    assert model_client.requests[0]["messages"] == [
        build_system_message(),
        build_user_message(TARGET),
    ]
    assert assistant_fixture == assistant_before
    assert result == result_before
    assert TARGET == target_before


def test_single_round_no_findings_review_succeeds() -> None:
    final_review = _review()
    agent, model_client, github_client = _agent(
        [_tool_response("call_one"), {"role": "assistant", "content": final_review}],
        [_result()],
    )

    assert agent.review() is final_review
    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


@pytest.mark.parametrize("tool_rounds", [2, 3])
def test_multiple_tool_rounds_have_complete_prefix_histories(
    tool_rounds: int,
) -> None:
    responses = [_tool_response(f"call_{index}") for index in range(1, tool_rounds + 1)]
    final_review = _review(filename=f"file_{tool_rounds}.py")
    responses.append({"role": "assistant", "content": final_review})
    outcomes = [_result(f"file_{index}.py") for index in range(1, tool_rounds + 1)]
    agent, model_client, github_client = _agent(responses, outcomes)

    assert agent.review() is final_review
    assert len(model_client.requests) == tool_rounds + 1
    assert len(github_client.targets) == tool_rounds
    for index, request in enumerate(model_client.requests):
        assert len(request["messages"]) == 2 + (index * 2)
        assert request["messages"][:2] == [
            build_system_message(),
            build_user_message(TARGET),
        ]
        assert request["tools"] == [get_pull_request_tool_schema()]
    assert _roles(model_client.requests[-1]) == [
        "system",
        "user",
        *["assistant", "tool"] * tool_rounds,
    ]
    tool_messages = [
        message for message in model_client.requests[-1]["messages"] if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == [
        f"call_{index}" for index in range(1, tool_rounds + 1)
    ]


def test_multiple_calls_in_one_response_are_one_round_and_keep_order() -> None:
    result_one = _result("first.py")
    result_two = _result("second.py")
    final_review = _review(filename="second.py")
    agent, model_client, github_client = _agent(
        [
            _tool_response("call_first", "call_second"),
            {"role": "assistant", "content": final_review},
        ],
        [result_one, result_two],
        max_tool_rounds=1,
    )

    assert agent.review() is final_review
    assert github_client.targets == [TARGET, TARGET]
    assert len(model_client.requests) == 2
    assert _roles(model_client.requests[1]) == [
        "system",
        "user",
        "assistant",
        "tool",
        "tool",
    ]
    messages = model_client.requests[1]["messages"]
    assert [messages[3]["tool_call_id"], messages[4]["tool_call_id"]] == [
        "call_first",
        "call_second",
    ]


@pytest.mark.parametrize(
    "second_call",
    [
        _tool_call(
            "bad_owner",
            target=PullRequestTarget("other", "repository", 1),
        ),
        _tool_call(
            "bad_repository",
            target=PullRequestTarget("owner", "other", 1),
        ),
        _tool_call(
            "bad_number",
            target=PullRequestTarget("owner", "repository", 2),
        ),
        _tool_call("bad_json", arguments="{"),
        _tool_call("bad_tool", name="unsupported"),
    ],
)
def test_batch_prevalidation_prevents_all_github_calls(
    second_call: Mapping[str, object],
) -> None:
    target_before = deepcopy(TARGET)
    agent, model_client, github_client = _agent(
        [
            _tool_response(
                calls=[_tool_call("valid"), second_call],
            )
        ],
        [_result("unused.py")],
    )

    with pytest.raises((ValueError, json.JSONDecodeError)):
        agent.review()

    assert len(model_client.requests) == 1
    assert github_client.targets == []
    assert TARGET == target_before


@pytest.mark.parametrize(
    "content",
    [_review(), "", " ", None, 1, []],
)
def test_final_response_before_tool_result_uses_prerequisite_error(
    content: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate_calls = 0

    def fail_validate(*args: object) -> str:
        nonlocal validate_calls
        validate_calls += 1
        raise AssertionError("review validation must not run")

    monkeypatch.setattr(agent_module, "validate_and_parse_review", fail_validate)
    agent, model_client, github_client = _agent(
        [{"role": "assistant", "content": content}],
    )

    with pytest.raises(ToolResultRequiredError, match=f"^{RESULT_REQUIRED_ERROR}$"):
        agent.review()

    assert len(model_client.requests) == 1
    assert github_client.targets == []
    assert validate_calls == 0


@pytest.mark.parametrize("tool_calls", [None, [], ()])
def test_absent_none_or_empty_tool_calls_are_final_response(
    tool_calls: object,
) -> None:
    response = {
        "role": "assistant",
        "content": _review(),
        "tool_calls": tool_calls,
    }
    agent, _, _ = _agent([response])

    with pytest.raises(ToolResultRequiredError, match=f"^{RESULT_REQUIRED_ERROR}$"):
        agent.review()


def test_missing_tool_calls_key_is_final_response() -> None:
    agent, _, _ = _agent([{"role": "assistant", "content": _review()}])

    with pytest.raises(ToolResultRequiredError, match=f"^{RESULT_REQUIRED_ERROR}$"):
        agent.review()


@pytest.mark.parametrize(
    "tool_calls",
    [
        "calls",
        b"calls",
        bytearray(b"calls"),
        memoryview(b"calls"),
        {},
        set(),
        frozenset(),
        range(0),
        range(1),
        1,
        True,
        _controlled_generator(),
        ControlledSequence(),
        ListSubclass(),
        TupleSubclass(),
    ],
    ids=[
        "str",
        "bytes",
        "bytearray",
        "memoryview",
        "dict",
        "set",
        "frozenset",
        "empty-range",
        "nonempty-range",
        "integer",
        "bool",
        "generator",
        "custom-sequence",
        "list-subclass",
        "tuple-subclass",
    ],
)
def test_rejects_invalid_tool_calls_root_before_execution(
    tool_calls: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute_calls = 0

    def fail_execute(*args: object) -> None:
        nonlocal execute_calls
        execute_calls += 1
        raise AssertionError("tool execution must not run")

    monkeypatch.setattr(agent_module, "execute_tool_calls", fail_execute)
    model_client = ScriptedModelClient(())
    model_client.responses.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
    github_client = FakeGitHubClient(())
    agent = PullRequestReviewAgent(
        target=TARGET,
        github_client=github_client,
        model_client=model_client,
    )

    with pytest.raises(ValueError, match=f"^{TOOL_CALLS_ERROR}$"):
        agent.review()

    assert len(model_client.requests) == 1
    assert github_client.targets == []
    assert execute_calls == 0


@pytest.mark.parametrize("container_type", [list, tuple])
@pytest.mark.parametrize("call_count", [1, 2])
def test_exact_list_and_tuple_tool_call_roots_execute_as_one_round(
    container_type: type[list[object]] | type[tuple[object, ...]],
    call_count: int,
) -> None:
    calls = container_type(_tool_call(f"call_{index}") for index in range(1, call_count + 1))
    final_review = _review(filename=f"file_{call_count}.py")
    agent, model_client, github_client = _agent(
        [
            {"role": "assistant", "content": None, "tool_calls": calls},
            {"role": "assistant", "content": final_review},
        ],
        [_result(f"file_{index}.py") for index in range(1, call_count + 1)],
        max_tool_rounds=1,
    )

    assert agent.review() is final_review
    assert len(model_client.requests) == 2
    assert len(github_client.targets) == call_count


@pytest.mark.parametrize("content", ["", " ", None, 1, [], {}])
def test_rejects_invalid_candidate_after_successful_tool_result(
    content: object,
) -> None:
    agent, model_client, github_client = _agent(
        [_tool_response("call"), {"role": "assistant", "content": content}],
        [_result()],
    )

    with pytest.raises(ReviewCandidateError, match=f"^{CANDIDATE_ERROR}$") as exc_info:
        agent.review()

    assert repr(content) not in str(exc_info.value)
    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


def test_missing_candidate_content_is_rejected_after_tool_result() -> None:
    agent, _, _ = _agent(
        [_tool_response("call"), {"role": "assistant"}],
        [_result()],
    )

    with pytest.raises(ReviewCandidateError, match=f"^{CANDIDATE_ERROR}$"):
        agent.review()


def test_content_accompanying_tool_calls_is_not_used_as_final() -> None:
    accompanying = _review()
    final_review = _review(filename="latest.py")
    agent, model_client, _ = _agent(
        [
            _tool_response("call", content=accompanying),
            {"role": "assistant", "content": final_review},
        ],
        [_result("latest.py")],
    )

    assert agent.review() is final_review
    assert len(model_client.requests) == 2
    assert model_client.requests[1]["messages"][2]["content"] == accompanying


def test_content_accompanying_tool_call_never_short_circuits_model() -> None:
    agent, model_client, github_client = _agent(
        [_tool_response("call", content=_review())],
        [_result()],
    )

    with pytest.raises(AssertionError, match="unexpected extra model call"):
        agent.review()

    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


def test_max_one_round_allows_final_response() -> None:
    final_review = _review()
    agent, model_client, github_client = _agent(
        [_tool_response("call"), {"role": "assistant", "content": final_review}],
        [_result()],
        max_tool_rounds=1,
    )

    assert agent.review() is final_review
    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


def test_max_one_round_rejects_second_tool_response_before_execution() -> None:
    agent, model_client, github_client = _agent(
        [_tool_response("call_1"), _tool_response("call_2")],
        [_result(), _result()],
        max_tool_rounds=1,
    )

    with pytest.raises(ToolRoundLimitError, match=f"^{LIMIT_ERROR}$"):
        agent.review()

    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


def test_default_eight_rounds_allow_ninth_final_response() -> None:
    responses = [_tool_response(f"call_{index}") for index in range(1, 9)]
    final_review = _review(filename="file_8.py")
    responses.append({"role": "assistant", "content": final_review})
    outcomes = [_result(f"file_{index}.py") for index in range(1, 9)]
    agent, model_client, github_client = _agent(responses, outcomes)

    assert agent.review() is final_review
    assert len(model_client.requests) == 9
    assert len(github_client.targets) == 8


def test_default_eight_rounds_reject_ninth_tool_response() -> None:
    responses = [_tool_response(f"call_{index}") for index in range(1, 10)]
    outcomes = [_result(f"file_{index}.py") for index in range(1, 10)]
    agent, model_client, github_client = _agent(responses, outcomes)

    with pytest.raises(ToolRoundLimitError, match=f"^{LIMIT_ERROR}$"):
        agent.review()

    assert len(model_client.requests) == 9
    assert len(github_client.targets) == 8


@pytest.mark.parametrize("container_type", [list, tuple])
def test_limit_error_precedes_malformed_tool_call_parsing(
    container_type: type[list[object]] | type[tuple[object, ...]],
) -> None:
    malformed = {"id": "", "type": "unsupported"}
    agent, model_client, github_client = _agent(
        [
            _tool_response("call_1"),
            {
                "role": "assistant",
                "content": None,
                "tool_calls": container_type([malformed]),
            },
        ],
        [_result()],
        max_tool_rounds=1,
    )

    with pytest.raises(ToolRoundLimitError, match=f"^{LIMIT_ERROR}$"):
        agent.review()

    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


def test_later_success_replaces_old_snapshot() -> None:
    final_review = _review(filename="new.py")
    agent, model_client, github_client = _agent(
        [
            _tool_response("old"),
            _tool_response("new"),
            {"role": "assistant", "content": final_review},
        ],
        [_result("old.py"), _result("new.py")],
    )

    assert agent.review() is final_review
    assert len(model_client.requests) == 3
    assert len(github_client.targets) == 2


def test_old_snapshot_filename_is_not_merged_with_latest_snapshot() -> None:
    invalid_review = _review(filename="old.py")
    repaired_review = _review(filename="new.py")
    agent, model_client, github_client = _agent(
        [
            _tool_response("old"),
            _tool_response("new"),
            {"role": "assistant", "content": invalid_review},
            {"role": "assistant", "content": repaired_review},
        ],
        [_result("old.py"), _result("new.py")],
    )

    assert agent.review() is repaired_review
    assert len(model_client.requests) == 4
    assert github_client.targets == [TARGET, TARGET]


def test_last_result_in_multi_call_batch_is_latest_snapshot() -> None:
    final_review = _review(filename="second.py")
    agent, _, github_client = _agent(
        [
            _tool_response("first", "second"),
            {"role": "assistant", "content": final_review},
        ],
        [_result("first.py"), _result("second.py")],
    )

    assert agent.review() is final_review
    assert len(github_client.targets) == 2


def test_first_result_in_multi_call_batch_is_not_current_snapshot() -> None:
    invalid_review = _review(filename="first.py")
    repaired_review = _review(filename="second.py")
    agent, model_client, github_client = _agent(
        [
            _tool_response("first", "second"),
            {"role": "assistant", "content": invalid_review},
            {"role": "assistant", "content": repaired_review},
        ],
        [_result("first.py"), _result("second.py")],
    )

    assert agent.review() is repaired_review
    assert len(model_client.requests) == 3
    assert github_client.targets == [TARGET, TARGET]


@pytest.mark.parametrize(
    "controlled_error",
    [
        RuntimeError("controlled GitHub failure"),
        ChangedFilesIntegrityError("controlled integrity failure"),
    ],
)
def test_later_github_failure_propagates_without_snapshot_fallback(
    controlled_error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate_calls = 0

    def fail_validate(*args: object) -> str:
        nonlocal validate_calls
        validate_calls += 1
        raise AssertionError("review validation must not run")

    monkeypatch.setattr(agent_module, "validate_and_parse_review", fail_validate)
    agent, model_client, github_client = _agent(
        [_tool_response("old"), _tool_response("failed")],
        [_result("old.py"), controlled_error],
    )

    with pytest.raises(type(controlled_error)) as exc_info:
        agent.review()

    assert exc_info.value is controlled_error
    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 2
    assert validate_calls == 0


def test_later_tool_json_failure_propagates_without_fallback() -> None:
    agent, model_client, github_client = _agent(
        [
            _tool_response("old"),
            _tool_response(calls=[_tool_call("bad", arguments="{")]),
        ],
        [_result("old.py")],
    )

    with pytest.raises(json.JSONDecodeError):
        agent.review()

    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


def test_later_target_mismatch_propagates_without_fallback() -> None:
    mismatched_call = _tool_call(
        "bad",
        target=PullRequestTarget("other", "repository", 1),
    )
    agent, model_client, github_client = _agent(
        [_tool_response("old"), _tool_response(calls=[mismatched_call])],
        [_result("old.py")],
    )

    with pytest.raises(
        ValueError,
        match="^tool call target does not match authoritative target$",
    ):
        agent.review()

    assert len(model_client.requests) == 2
    assert len(github_client.targets) == 1


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        (_review().replace("## Summary", "## summary"), "invalid review headings"),
        (
            _review(filename="unknown.py"),
            "finding file does not match changed file",
        ),
        (
            _review(filename="file.py", severity="Info"),
            "invalid finding severity",
        ),
        (
            _review().replace("\nApprove\n", "\nApproved\n"),
            "invalid final assessment",
        ),
    ],
)
def test_second_review_validation_error_propagates_without_additional_retry(
    candidate: str,
    message: str,
) -> None:
    candidate_before = deepcopy(candidate)
    agent, model_client, github_client = _agent(
        [
            _tool_response("call"),
            {"role": "assistant", "content": candidate},
            {"role": "assistant", "content": candidate},
        ],
        [_result("file.py")],
    )

    with pytest.raises(ReviewValidationError, match=f"^{message}$"):
        agent.review()

    assert len(model_client.requests) == 3
    assert model_client.responses == []
    assert len(github_client.targets) == 1
    assert candidate == candidate_before


def test_invalid_review_is_repaired_once_without_refetching_github() -> None:
    invalid_review = _review(filename="file.py").replace(
        "## Summary",
        "## Overview",
    )
    repaired_review = _review(filename="file.py")
    agent, model_client, github_client = _agent(
        [
            _tool_response("call"),
            {"role": "assistant", "content": invalid_review},
            {"role": "assistant", "content": repaired_review},
        ],
        [_result("file.py")],
    )

    assert agent.review() is repaired_review
    assert len(model_client.requests) == 3
    assert github_client.targets == [TARGET]
    assert _roles(model_client.requests[2]) == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]

    repair_history = model_client.requests[2]["messages"]
    assert repair_history[-2] == {
        "role": "assistant",
        "content": invalid_review,
    }
    repair_message = repair_history[-1]
    assert repair_message["role"] == "user"
    repair_instruction = repair_message["content"]
    assert type(repair_instruction) is str
    assert "only repair the Markdown format" in repair_instruction
    assert "six required headings" in repair_instruction
    assert "finding field format" in repair_instruction
    assert "Do not call tools again" in repair_instruction
    assert "Do not add any new conclusions" in repair_instruction
    assert "existing evidence" in repair_instruction
    assert model_client.requests[2]["tools"] == [
        get_pull_request_tool_schema(),
    ]


def test_repair_response_with_tool_calls_is_rejected_without_execution() -> None:
    invalid_review = _review(filename="file.py").replace(
        "## Summary",
        "## Overview",
    )
    agent, model_client, github_client = _agent(
        [
            _tool_response("call"),
            {"role": "assistant", "content": invalid_review},
            _tool_response("repair_call"),
        ],
        [_result("file.py")],
    )

    with pytest.raises(
        RuntimeError,
        match="^tool calls are not allowed during review repair$",
    ):
        agent.review()

    assert len(model_client.requests) == 3
    assert github_client.targets == [TARGET]
    assert _roles(model_client.requests[2]) == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert model_client.requests[2]["tools"] == [
        get_pull_request_tool_schema(),
    ]


def test_second_invalid_review_is_not_retried_again() -> None:
    first_invalid_review = _review(filename="file.py").replace(
        "## Summary",
        "## Overview",
    )
    second_invalid_review = _review(
        filename="file.py",
        severity="Info",
    )
    agent, model_client, github_client = _agent(
        [
            _tool_response("call"),
            {"role": "assistant", "content": first_invalid_review},
            {"role": "assistant", "content": second_invalid_review},
        ],
        [_result("file.py")],
    )

    with pytest.raises(
        ReviewValidationError,
        match="^invalid finding severity$",
    ):
        agent.review()

    assert len(model_client.requests) == 3
    assert model_client.responses == []
    assert github_client.targets == [TARGET]
    assert _roles(model_client.requests[2]) == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]


def test_review_can_use_second_filename_from_latest_complete_result() -> None:
    final_review = _review(filename="second.py")
    agent, _, _ = _agent(
        [_tool_response("call"), {"role": "assistant", "content": final_review}],
        [_result("first.py", "second.py")],
    )

    assert agent.review() is final_review


def test_each_model_request_gets_fresh_single_tool_schema() -> None:
    class MutatingModelClient(ScriptedModelClient):
        def complete(
            self,
            messages: Sequence[Mapping[str, object]],
            tools: Sequence[Mapping[str, object]],
        ) -> dict[str, object]:
            response = super().complete(messages, tools)
            tools[0]["function"]["name"] = "mutated"
            return response

    final_review = _review()
    model_client = MutatingModelClient(
        [_tool_response("call"), {"role": "assistant", "content": final_review}]
    )
    github_client = FakeGitHubClient([_result()])
    agent = PullRequestReviewAgent(
        target=TARGET,
        github_client=github_client,
        model_client=model_client,
    )

    assert agent.review() is final_review
    assert [request["tools"][0]["function"]["name"] for request in model_client.requests] == [
        "get_pull_request",
        "get_pull_request",
    ]


def test_assistant_message_future_fields_and_none_content_are_preserved() -> None:
    response = _tool_response("call")
    response["future_field"] = {"nested": ["value"]}
    response_before = deepcopy(response)
    final_review = _review()
    agent, model_client, _ = _agent(
        [response, {"role": "assistant", "content": final_review}],
        [_result()],
    )

    assert agent.review() is final_review
    assert model_client.requests[1]["messages"][2] == response
    assert model_client.requests[1]["messages"][2]["content"] is None
    assert response == response_before


def test_model_exception_propagates_without_github_or_retry() -> None:
    controlled_error = RuntimeError("controlled model failure")

    class FailingModelClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages: object, tools: object) -> dict[str, object]:
            self.calls += 1
            raise controlled_error

    model_client = FailingModelClient()
    github_client = FakeGitHubClient([])
    agent = PullRequestReviewAgent(
        target=TARGET,
        github_client=github_client,
        model_client=model_client,
    )

    with pytest.raises(RuntimeError) as exc_info:
        agent.review()

    assert exc_info.value is controlled_error
    assert model_client.calls == 1
    assert github_client.targets == []


def test_non_mapping_assistant_message_uses_existing_message_contract() -> None:
    class InvalidModelClient:
        def complete(self, messages: object, tools: object) -> object:
            return []

    agent = PullRequestReviewAgent(
        target=TARGET,
        github_client=FakeGitHubClient([]),
        model_client=InvalidModelClient(),
    )

    with pytest.raises(TypeError, match="^assistant message must be a mapping$"):
        agent.review()


def test_same_agent_uses_fresh_state_for_every_review() -> None:
    first_review = _review()
    second_early_review = _review()
    model_client = ScriptedModelClient(
        [
            _tool_response("first_call"),
            {"role": "assistant", "content": first_review},
            {"role": "assistant", "content": second_early_review},
        ]
    )
    github_client = FakeGitHubClient([_result()])
    agent = PullRequestReviewAgent(
        target=TARGET,
        github_client=github_client,
        model_client=model_client,
    )

    assert agent.review() is first_review
    with pytest.raises(ToolResultRequiredError, match=f"^{RESULT_REQUIRED_ERROR}$"):
        agent.review()

    assert _roles(model_client.requests[0]) == ["system", "user"]
    assert _roles(model_client.requests[2]) == ["system", "user"]
    assert len(github_client.targets) == 1


def test_inputs_results_and_model_fixtures_remain_unchanged() -> None:
    target_before = deepcopy(TARGET)
    response = _tool_response("call")
    response_before = deepcopy(response)
    result = _result("file.py")
    result_before = deepcopy(result)
    final_review = _review(filename="file.py")
    model_client = ScriptedModelClient([response, {"role": "assistant", "content": final_review}])
    response_queue_before = deepcopy(model_client.responses)
    github_client = FakeGitHubClient([result])
    result_queue_before = deepcopy(github_client.outcomes)
    agent = PullRequestReviewAgent(
        target=TARGET,
        github_client=github_client,
        model_client=model_client,
    )

    assert agent.review() is final_review
    assert TARGET == target_before
    assert response == response_before
    assert result == result_before
    assert response_queue_before[0] == response
    assert result_queue_before[0] == result


def test_agent_has_no_secret_or_external_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    controlled_secret = "controlled-deepseek-key-for-test"

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("unexpected external side effect")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(os, "getenv", fail)
    monkeypatch.setattr(openai, "OpenAI", fail)
    monkeypatch.setattr(builtins, "open", fail)
    final_review = _review()
    agent, model_client, _ = _agent(
        [_tool_response("call"), {"role": "assistant", "content": final_review}],
        [_result()],
    )

    with caplog.at_level(logging.DEBUG):
        assert agent.review() is final_review

    captured = capsys.readouterr()
    assert controlled_secret not in repr(agent)
    assert controlled_secret not in str(agent)
    assert all(controlled_secret not in repr(request) for request in model_client.requests)
    assert controlled_secret not in final_review
    assert captured.out == ""
    assert captured.err == ""
    assert caplog.records == []
