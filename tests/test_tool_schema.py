import importlib
import os
import socket

import openai

import ai_github_reviewer.tool_schema as tool_schema_module
from ai_github_reviewer.tool_schema import (
    GET_PULL_REQUEST_TOOL_NAME,
    get_pull_request_tool_schema,
)

EXPECTED_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_pull_request",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "minLength": 1,
                },
                "repository": {
                    "type": "string",
                    "minLength": 1,
                },
                "pull_number": {
                    "type": "integer",
                    "minimum": 1,
                },
            },
            "required": [
                "owner",
                "repository",
                "pull_number",
            ],
            "additionalProperties": False,
        },
    },
}


def test_get_pull_request_tool_schema_matches_complete_contract() -> None:
    assert get_pull_request_tool_schema() == EXPECTED_SCHEMA


def test_schema_exposes_only_get_pull_request_function_tool() -> None:
    schema = get_pull_request_tool_schema()
    function = schema["function"]

    assert schema["type"] == "function"
    assert isinstance(function, dict)
    assert function["name"] == GET_PULL_REQUEST_TOOL_NAME
    assert GET_PULL_REQUEST_TOOL_NAME == "get_pull_request"


def test_schema_parameters_have_exact_properties_and_constraints() -> None:
    schema = get_pull_request_tool_schema()
    function = schema["function"]
    assert isinstance(function, dict)
    parameters = function["parameters"]
    assert isinstance(parameters, dict)
    properties = parameters["properties"]
    assert isinstance(properties, dict)

    assert parameters["type"] == "object"
    assert set(properties) == {"owner", "repository", "pull_number"}
    assert properties["owner"] == {"type": "string", "minLength": 1}
    assert properties["repository"] == {"type": "string", "minLength": 1}
    assert properties["pull_number"] == {"type": "integer", "minimum": 1}
    assert parameters["required"] == ["owner", "repository", "pull_number"]
    assert parameters["additionalProperties"] is False


def test_schema_contains_no_write_tool_or_credential_field() -> None:
    schema_text = repr(get_pull_request_tool_schema()).lower()

    for forbidden in (
        "create_review",
        "create_comment",
        "merge",
        "close",
        "commit",
        "code_execution",
        "github_token",
        "authorization",
        "api_key",
    ):
        assert forbidden not in schema_text


def test_each_schema_call_returns_fresh_nested_collections() -> None:
    first = get_pull_request_tool_schema()
    second = get_pull_request_tool_schema()
    first_function = first["function"]
    second_function = second["function"]
    assert isinstance(first_function, dict)
    assert isinstance(second_function, dict)
    first_parameters = first_function["parameters"]
    second_parameters = second_function["parameters"]
    assert isinstance(first_parameters, dict)
    assert isinstance(second_parameters, dict)
    first_properties = first_parameters["properties"]
    second_properties = second_parameters["properties"]
    assert isinstance(first_properties, dict)
    assert isinstance(second_properties, dict)

    assert first == second
    assert first is not second
    assert first_function is not second_function
    assert first_parameters is not second_parameters
    assert first_properties is not second_properties
    assert first_properties["owner"] is not second_properties["owner"]
    assert first_properties["repository"] is not second_properties["repository"]
    assert first_properties["pull_number"] is not second_properties["pull_number"]
    assert first_parameters["required"] is not second_parameters["required"]


def test_mutating_one_schema_does_not_affect_later_result() -> None:
    first = get_pull_request_tool_schema()
    first_function = first["function"]
    assert isinstance(first_function, dict)
    first_parameters = first_function["parameters"]
    assert isinstance(first_parameters, dict)
    first_properties = first_parameters["properties"]
    assert isinstance(first_properties, dict)
    owner = first_properties["owner"]
    assert isinstance(owner, dict)
    required = first_parameters["required"]
    assert isinstance(required, list)

    first["type"] = "replacement"
    first_function["name"] = "replacement"
    owner["minLength"] = 99
    required.append("extra")

    assert get_pull_request_tool_schema() == EXPECTED_SCHEMA


def test_schema_module_reload_has_no_external_side_effects(
    monkeypatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("unexpected external side effect")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(os, "getenv", fail)
    monkeypatch.setattr(openai, "OpenAI", fail)

    reloaded = importlib.reload(tool_schema_module)

    assert reloaded.get_pull_request_tool_schema() == EXPECTED_SCHEMA
