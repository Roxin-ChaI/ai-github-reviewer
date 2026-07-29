from typing import Final

GET_PULL_REQUEST_TOOL_NAME: Final = "get_pull_request"


def get_pull_request_tool_schema() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": GET_PULL_REQUEST_TOOL_NAME,
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
