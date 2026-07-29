import os
import socket
from copy import deepcopy
from dataclasses import dataclass

import pytest

import ai_github_reviewer.model_client as model_client_module
from ai_github_reviewer.model_client import (
    CompletionParsingError,
    DeepSeekModelClient,
)
from ai_github_reviewer.tool_schema import get_pull_request_tool_schema

CONTROLLED_SECRET = "controlled-deepseek-key-for-test"
NO_CHOICES_MESSAGE = "DeepSeek completion returned no choices"
NETWORK_DISABLED_PATTERN = "Real network access is disabled in automated tests"


@dataclass
class Records:
    constructors: list[dict[str, object]]
    calls: list[dict[str, object]]


class FakeMessage:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = deepcopy(payload)
        self.dump_calls: list[dict[str, object]] = []

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        self.dump_calls.append(deepcopy(kwargs))
        return deepcopy(self.payload)


class FakeChoice:
    def __init__(self, message: object) -> None:
        self.message = message


class FakeCompletion:
    def __init__(self, choices: list[FakeChoice] | tuple[FakeChoice, ...]) -> None:
        self.choices = choices


class FakeCompletions:
    def __init__(
        self,
        records: Records,
        outcome: object,
        *,
        mutate_inputs: bool = False,
    ) -> None:
        self._records = records
        self._outcome = outcome
        self._mutate_inputs = mutate_inputs

    def create(self, **kwargs: object) -> object:
        self._records.calls.append(deepcopy(kwargs))
        if self._mutate_inputs:
            messages = kwargs["messages"]
            tools = kwargs["tools"]
            assert isinstance(messages, list)
            assert isinstance(tools, list)
            messages[0]["content"] = "mutated by fake"
            messages.append({"role": "assistant", "content": "extra"})
            tools[0]["function"]["name"] = "mutated_by_fake"
            tools.append({"type": "function", "function": {"name": "extra"}})
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class FakeChat:
    def __init__(self, completions: FakeCompletions) -> None:
        self.completions = completions


def _assistant_payload(
    *,
    content: str | None = "Review text",
    tool_calls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": "assistant",
        "content": content,
        "refusal": None,
    }
    if tool_calls is not None:
        payload["tool_calls"] = tool_calls
    return payload


def _tool_call(
    tool_call_id: str = "call_example",
    *,
    arguments: str = (
        '{"owner":"example-owner","repository":"example-repository","pull_number":123}'
    ),
) -> dict[str, object]:
    return {
        "id": tool_call_id,
        "type": "function",
        "function": {
            "name": "get_pull_request",
            "arguments": arguments,
        },
    }


def _completion(
    payload: dict[str, object] | None = None,
    *,
    choices_type: type[list] | type[tuple] = list,
) -> FakeCompletion:
    if payload is None:
        payload = _assistant_payload()
    choices = choices_type((FakeChoice(FakeMessage(payload)),))
    return FakeCompletion(choices)


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
    *,
    mutate_inputs: bool = False,
) -> Records:
    records = Records(constructors=[], calls=[])

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            records.constructors.append(deepcopy(kwargs))
            self.chat = FakeChat(
                FakeCompletions(
                    records,
                    outcome,
                    mutate_inputs=mutate_inputs,
                )
            )

    monkeypatch.setattr(model_client_module, "OpenAI", FakeOpenAI)
    return records


def _client() -> DeepSeekModelClient:
    return DeepSeekModelClient(
        api_key=CONTROLLED_SECRET,
        base_url="https://api.deepseek.test",
        model="deepseek-v4-flash",
    )


def _messages() -> list[dict[str, object]]:
    return [
        {"role": "system", "content": "controlled system"},
        {
            "role": "user",
            "content": "controlled user",
            "nested": {"values": ["original"]},
        },
    ]


def _tools() -> list[dict[str, object]]:
    return [get_pull_request_tool_schema()]


def test_constructor_passes_exact_configuration_and_disables_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _install_fake_openai(monkeypatch, _completion())

    client = _client()

    assert isinstance(client, DeepSeekModelClient)
    assert records.constructors == [
        {
            "api_key": CONTROLLED_SECRET,
            "base_url": "https://api.deepseek.test",
            "max_retries": 0,
        }
    ]
    assert records.calls == []


def test_constructor_is_called_once_and_does_not_read_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _install_fake_openai(monkeypatch, _completion())
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-read")
    environment_before = dict(os.environ)
    api_key = CONTROLLED_SECRET
    base_url = "https://api.deepseek.test"
    model = "deepseek-v4-flash"

    DeepSeekModelClient(api_key=api_key, base_url=base_url, model=model)

    assert len(records.constructors) == 1
    assert records.constructors[0]["api_key"] == api_key
    assert records.constructors[0]["base_url"] == base_url
    assert api_key == CONTROLLED_SECRET
    assert base_url == "https://api.deepseek.test"
    assert model == "deepseek-v4-flash"
    assert dict(os.environ) == environment_before


def test_client_representations_do_not_expose_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch, _completion())

    client = _client()

    assert CONTROLLED_SECRET not in repr(client)
    assert CONTROLLED_SECRET not in str(client)


def test_complete_sends_only_required_request_fields_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _install_fake_openai(monkeypatch, _completion())
    messages = _messages()
    tools = _tools()

    _client().complete(messages, tools)

    assert len(records.calls) == 1
    request = records.calls[0]
    assert set(request) == {"model", "messages", "tools", "extra_body"}
    assert request["model"] == "deepseek-v4-flash"
    assert request["messages"] == messages
    assert request["tools"] == tools
    assert request["extra_body"] == {
        "thinking": {
            "type": "disabled",
        }
    }
    assert "stream" not in request


def test_complete_preserves_message_and_tool_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _install_fake_openai(monkeypatch, _completion())
    messages = [
        {"role": "system", "content": "first"},
        {"role": "user", "content": "second"},
        {"role": "tool", "content": "third", "tool_call_id": "call_example"},
    ]
    first_tool = get_pull_request_tool_schema()
    second_tool = deepcopy(first_tool)
    second_tool["function"]["name"] = "controlled-second"
    tools = [first_tool, second_tool]

    _client().complete(messages, tools)

    request = records.calls[0]
    assert [message["content"] for message in request["messages"]] == [
        "first",
        "second",
        "third",
    ]
    assert [tool["function"]["name"] for tool in request["tools"]] == [
        "get_pull_request",
        "controlled-second",
    ]


def test_complete_does_not_modify_caller_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _install_fake_openai(
        monkeypatch,
        _completion(),
        mutate_inputs=True,
    )
    messages = _messages()
    tools = _tools()
    messages_before = deepcopy(messages)
    tools_before = deepcopy(tools)

    _client().complete(messages, tools)

    assert messages == messages_before
    assert messages[1]["nested"] == {"values": ["original"]}
    assert tools == tools_before
    assert tools[0]["function"]["name"] == "get_pull_request"
    assert len(records.calls) == 1


@pytest.mark.parametrize("content", ["Review text", None, ""])
def test_complete_preserves_content(
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
) -> None:
    message = FakeMessage(_assistant_payload(content=content))
    completion = FakeCompletion([FakeChoice(message)])
    _install_fake_openai(monkeypatch, completion)

    assistant = _client().complete(_messages(), _tools())

    assert assistant["role"] == "assistant"
    assert assistant["content"] == content
    assert message.dump_calls == [{"mode": "json"}]


def test_complete_preserves_single_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _assistant_payload(content=None, tool_calls=[_tool_call()])
    _install_fake_openai(monkeypatch, _completion(payload))

    assistant = _client().complete(_messages(), _tools())

    assert assistant == payload
    assert assistant["tool_calls"][0]["id"] == "call_example"
    assert assistant["tool_calls"][0]["function"]["name"] == "get_pull_request"
    assert assistant["tool_calls"][0]["function"]["arguments"] == (
        '{"owner":"example-owner","repository":"example-repository","pull_number":123}'
    )


def test_complete_preserves_multiple_tool_calls_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_arguments = '{"owner":"first","repository":"repo","pull_number":1}'
    second_arguments = '{ "owner": "second", "repository": "repo", "pull_number": 2 }'
    payload = _assistant_payload(
        content=None,
        tool_calls=[
            _tool_call("call_first", arguments=first_arguments),
            _tool_call("call_second", arguments=second_arguments),
        ],
    )
    _install_fake_openai(monkeypatch, _completion(payload))

    assistant = _client().complete(_messages(), _tools())

    assert [call["id"] for call in assistant["tool_calls"]] == [
        "call_first",
        "call_second",
    ]
    assert [call["function"]["arguments"] for call in assistant["tool_calls"]] == [
        first_arguments,
        second_arguments,
    ]


def test_complete_returns_first_choice_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeMessage(_assistant_payload(content="first"))
    second = FakeMessage(_assistant_payload(content="second"))
    completion = FakeCompletion([FakeChoice(first), FakeChoice(second)])
    _install_fake_openai(monkeypatch, completion)

    assistant = _client().complete(_messages(), _tools())

    assert assistant["content"] == "first"
    assert first.dump_calls == [{"mode": "json"}]
    assert second.dump_calls == []


def test_complete_accepts_already_normalized_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _assistant_payload(content=None, tool_calls=[_tool_call()])
    completion = FakeCompletion([FakeChoice(message)])
    _install_fake_openai(monkeypatch, completion)

    assistant = _client().complete(_messages(), _tools())

    assert assistant == message
    assert assistant is not message
    assert assistant["tool_calls"] is not message["tool_calls"]


def test_complete_returns_deep_copy_independent_from_sdk_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _assistant_payload(content=None, tool_calls=[_tool_call()])
    message = FakeMessage(payload)
    completion = FakeCompletion([FakeChoice(message)])
    completion_before = deepcopy(completion)
    _install_fake_openai(monkeypatch, completion)

    assistant = _client().complete(_messages(), _tools())

    assistant["tool_calls"][0]["function"]["name"] = "replacement"
    assert message.payload == payload
    assert message.payload["tool_calls"][0]["function"]["name"] == "get_pull_request"
    assert completion.choices[0].message.payload == (completion_before.choices[0].message.payload)


def test_complete_preserves_additional_public_message_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _assistant_payload()
    payload["annotations"] = [{"type": "controlled", "value": ["nested"]}]
    payload["future_public_field"] = {"nested": ["value"]}
    _install_fake_openai(monkeypatch, _completion(payload))

    assistant = _client().complete(_messages(), _tools())

    assert assistant == payload


@pytest.mark.parametrize("choices", [[], ()])
def test_complete_rejects_no_choices_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    choices: list[FakeChoice] | tuple[FakeChoice, ...],
) -> None:
    records = _install_fake_openai(monkeypatch, FakeCompletion(choices))
    client = _client()

    with pytest.raises(
        CompletionParsingError,
        match=rf"^{NO_CHOICES_MESSAGE}$",
    ) as exc_info:
        client.complete(_messages(), _tools())

    assert str(exc_info.value) == NO_CHOICES_MESSAGE
    assert CONTROLLED_SECRET not in str(exc_info.value)
    assert len(records.constructors) == 1
    assert len(records.calls) == 1


class ControlledSDKError(RuntimeError):
    pass


@pytest.mark.parametrize(
    "error",
    [
        ControlledSDKError("controlled API failure"),
        ControlledSDKError("controlled rate limit"),
        ControlledSDKError("controlled connection failure"),
    ],
)
def test_complete_propagates_sdk_errors_unchanged_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: ControlledSDKError,
) -> None:
    records = _install_fake_openai(monkeypatch, error)
    client = _client()

    with pytest.raises(ControlledSDKError) as exc_info:
        client.complete(_messages(), _tools())

    captured = capsys.readouterr()
    assert exc_info.value is error
    assert len(records.constructors) == 1
    assert len(records.calls) == 1
    assert captured.out == ""
    assert captured.err == ""
    assert CONTROLLED_SECRET not in str(exc_info.value)


def test_complete_propagates_model_dump_error_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ValueError("controlled serialization failure")

    class FailingMessage:
        def model_dump(self, **kwargs: object) -> dict[str, object]:
            raise error

    records = _install_fake_openai(
        monkeypatch,
        FakeCompletion([FakeChoice(FailingMessage())]),
    )

    with pytest.raises(ValueError) as exc_info:
        _client().complete(_messages(), _tools())

    assert exc_info.value is error
    assert len(records.calls) == 1


def test_complete_rejects_message_without_public_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _install_fake_openai(
        monkeypatch,
        FakeCompletion([FakeChoice(object())]),
    )

    with pytest.raises(
        TypeError,
        match=r"^assistant message must be a mapping or support model_dump$",
    ):
        _client().complete(_messages(), _tools())

    assert len(records.calls) == 1


def test_model_client_emits_no_output_and_hides_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_openai(monkeypatch, _completion())
    client = _client()

    assistant = client.complete(_messages(), _tools())

    captured = capsys.readouterr()
    assert CONTROLLED_SECRET not in repr(client)
    assert CONTROLLED_SECRET not in str(client)
    assert CONTROLLED_SECRET not in repr(assistant)
    assert CONTROLLED_SECRET not in captured.out
    assert CONTROLLED_SECRET not in captured.err
    assert captured.out == ""
    assert captured.err == ""


def test_fake_model_client_runs_with_network_guard_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai(monkeypatch, _completion())

    assistant = _client().complete(_messages(), _tools())

    assert assistant["role"] == "assistant"
    with pytest.raises(RuntimeError, match=NETWORK_DISABLED_PATTERN):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)
