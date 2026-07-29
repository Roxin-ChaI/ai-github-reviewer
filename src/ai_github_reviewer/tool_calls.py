import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from ai_github_reviewer.github_client import GitHubClient
from ai_github_reviewer.pull_request import PullRequestData, PullRequestTarget
from ai_github_reviewer.tool_schema import GET_PULL_REQUEST_TOOL_NAME

_MISSING: Final = object()
_REQUIRED_ARGUMENTS: Final = frozenset({"owner", "repository", "pull_number"})
_EXACT_ARGUMENTS_MESSAGE: Final = (
    "tool arguments must contain exactly owner, repository, and pull_number"
)
_TARGET_MISMATCH_MESSAGE: Final = "tool call target does not match authoritative target"


@dataclass(frozen=True, slots=True)
class ParsedToolCall:
    tool_call_id: str
    tool_name: str
    target: PullRequestTarget

    def __post_init__(self) -> None:
        if type(self.tool_call_id) is not str or not self.tool_call_id.strip():
            raise ValueError("tool call id must be a non-empty string")
        if type(self.tool_name) is not str or not self.tool_name.strip():
            raise ValueError("tool name must be a non-empty string")
        if type(self.target) is not PullRequestTarget:
            raise ValueError("target must be PullRequestTarget")


@dataclass(frozen=True, slots=True)
class ExecutedToolCall:
    tool_call: ParsedToolCall
    result: PullRequestData

    def __post_init__(self) -> None:
        if type(self.tool_call) is not ParsedToolCall:
            raise ValueError("tool_call must be ParsedToolCall")
        if type(self.result) is not PullRequestData:
            raise ValueError("result must be PullRequestData")


def parse_tool_call(
    tool_call: Mapping[str, object],
) -> ParsedToolCall:
    if not isinstance(tool_call, Mapping):
        raise ValueError("tool call must be a mapping")

    tool_call_id = tool_call.get("id", _MISSING)
    if type(tool_call_id) is not str or not tool_call_id.strip():
        raise ValueError("tool call id must be a non-empty string")

    tool_call_type = tool_call.get("type", _MISSING)
    if type(tool_call_type) is not str or tool_call_type != "function":
        raise ValueError("tool call type must be function")

    function = tool_call.get("function", _MISSING)
    if not isinstance(function, Mapping):
        raise ValueError("tool call function must be a mapping")

    tool_name = function.get("name", _MISSING)
    if type(tool_name) is not str or not tool_name.strip():
        raise ValueError("tool name must be a non-empty string")
    if tool_name != GET_PULL_REQUEST_TOOL_NAME:
        raise ValueError("unsupported tool")

    arguments_text = function.get("arguments", _MISSING)
    if type(arguments_text) is not str:
        raise ValueError("tool arguments must be a string")

    arguments = json.loads(arguments_text)
    if type(arguments) is not dict:
        raise ValueError("tool arguments must be a JSON object")
    if set(arguments) != _REQUIRED_ARGUMENTS:
        raise ValueError(_EXACT_ARGUMENTS_MESSAGE)

    target = PullRequestTarget(
        owner=arguments["owner"],
        repository=arguments["repository"],
        pull_number=arguments["pull_number"],
    )
    return ParsedToolCall(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        target=target,
    )


def parse_tool_calls(
    tool_calls: Iterable[Mapping[str, object]],
    authoritative_target: PullRequestTarget,
) -> tuple[ParsedToolCall, ...]:
    if type(authoritative_target) is not PullRequestTarget:
        raise ValueError("authoritative target must be PullRequestTarget")

    parsed_calls: list[ParsedToolCall] = []
    for tool_call in tool_calls:
        parsed_call = parse_tool_call(tool_call)
        if parsed_call.target != authoritative_target:
            raise ValueError(_TARGET_MISMATCH_MESSAGE)
        parsed_calls.append(parsed_call)
    return tuple(parsed_calls)


def execute_tool_calls(
    tool_calls: Iterable[Mapping[str, object]],
    authoritative_target: PullRequestTarget,
    github_client: GitHubClient,
) -> tuple[ExecutedToolCall, ...]:
    parsed_calls = parse_tool_calls(tool_calls, authoritative_target)
    executions: list[ExecutedToolCall] = []
    for parsed_call in parsed_calls:
        result = github_client.get_pull_request(parsed_call.target)
        executions.append(
            ExecutedToolCall(
                tool_call=parsed_call,
                result=result,
            )
        )
    return tuple(executions)
