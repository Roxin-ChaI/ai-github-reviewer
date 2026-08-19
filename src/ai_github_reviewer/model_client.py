from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Protocol, runtime_checkable

from openai import OpenAI

from ai_github_reviewer.messages import copy_assistant_message


class CompletionParsingError(RuntimeError):
    pass


@runtime_checkable
class _SupportsModelDump(Protocol):
    def model_dump(self, *, mode: str) -> Mapping[str, object]: ...


class DeepSeekModelClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
        )
        self._model = model

    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        completion = self._client.chat.completions.create(
            model=self._model,
            messages=deepcopy(list(messages)),
            tools=deepcopy(list(tools)),
            extra_body={
                "thinking": {
                    "type": "disabled",
                }
            },
        )
        if not completion.choices:
            raise CompletionParsingError("DeepSeek completion returned no choices")

        message = completion.choices[0].message
        if isinstance(message, Mapping):
            message_mapping = message
        elif isinstance(message, _SupportsModelDump):
            message_mapping = message.model_dump(mode="json")
        else:
            raise TypeError("assistant message must be a mapping or support model_dump")
        return copy_assistant_message(message_mapping)

    def close(self) -> None:
        self._client.close()
