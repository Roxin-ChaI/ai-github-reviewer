import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final
from urllib.parse import parse_qs, urlsplit

TARGET_URL: Final = "https://github.com/example-owner/example-repository/pull/123"
METADATA_PATH: Final = "/repos/example-owner/example-repository/pulls/123"
FILES_PATH: Final = f"{METADATA_PATH}/files"
COMPLETIONS_PATH: Final = "/chat/completions"
TOOL_CALL_ID: Final = "call_controlled_pull_request"
CONTROLLED_MODEL: Final = "controlled-model"
CONTROLLED_KEY: Final = "controlled-docker-key"
HOSTNAME_FROM_CONTAINER: Final = "host.docker.internal"

EXPECTED_REVIEW: Final = """# Pull Request Review

## Summary

The controlled change updates one example file.

## Findings

### Finding 1

- Severity: Low
- File: src/example.py
- Location: Unknown
- Issue: The controlled patch has no accompanying focused test.
- Evidence: The Tool Result contains only src/example.py and no test file.
- Recommendation: Add a focused unit test for the changed behavior.

## Test Gaps

The controlled data does not include a test file.

## Maintainability

The small patch is straightforward, but a focused test would preserve its intent.

## Final Assessment

Approve with minor comments"""

METADATA_RESPONSE: Final = {
    "title": "Controlled example change",
    "body": "A safe controlled Pull Request body.",
    "state": "open",
    "user": {"login": "example-author"},
    "base": {"ref": "main"},
    "head": {"ref": "controlled-change"},
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
    "changed_files": 1,
    "additions": 1,
    "deletions": 1,
    "commits": 1,
}
FILES_RESPONSE: Final = [
    {
        "filename": "src/example.py",
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
        "patch": "@@ -1 +1 @@\n-old_value = 1\n+new_value = 2",
    }
]


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: object | None = None


@dataclass
class ServiceRecords:
    requests: list[RecordedRequest] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, request: RecordedRequest) -> None:
        with self.lock:
            self.requests.append(request)

    def snapshot(self) -> tuple[RecordedRequest, ...]:
        with self.lock:
            return tuple(self.requests)


class QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _record(self, body: object | None = None) -> None:
        records = self.server.records
        records.append(
            RecordedRequest(
                method=self.command,
                path=urlsplit(self.path).path,
                query=urlsplit(self.path).query,
                headers={name.lower(): value for name, value in self.headers.items()},
                body=body,
            )
        )

    def _json_response(self, status: int, payload: object) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _empty_response(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class GitHubHandler(QuietHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        self._record()
        if parsed.path == METADATA_PATH and not parsed.query:
            self._json_response(200, METADATA_RESPONSE)
            return
        if parsed.path == FILES_PATH and parse_qs(parsed.query) == {
            "per_page": ["100"],
            "page": ["1"],
        }:
            self._json_response(200, FILES_RESPONSE)
            return
        self._json_response(404, {"message": "not found"})

    def do_POST(self) -> None:
        self._reject_write()

    def do_PUT(self) -> None:
        self._reject_write()

    def do_PATCH(self) -> None:
        self._reject_write()

    def do_DELETE(self) -> None:
        self._reject_write()

    def _reject_write(self) -> None:
        self._record()
        self._json_response(405, {"message": "write method rejected"})


class DeepSeekHandler(QuietHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            self._record()
            self._json_response(400, {"message": "invalid JSON"})
            return

        parsed = urlsplit(self.path)
        self._record(body)
        if parsed.path != COMPLETIONS_PATH or parsed.query or parsed.fragment:
            self._json_response(404, {"message": "not found"})
            return

        request_number = sum(
            request.method == "POST" and request.path == COMPLETIONS_PATH and not request.query
            for request in self.server.records.snapshot()
        )
        if request_number == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": TOOL_CALL_ID,
                        "type": "function",
                        "function": {
                            "name": "get_pull_request",
                            "arguments": json.dumps(
                                {
                                    "owner": "example-owner",
                                    "repository": "example-repository",
                                    "pull_number": 123,
                                },
                                separators=(",", ":"),
                            ),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif request_number == 2:
            message = {
                "role": "assistant",
                "content": EXPECTED_REVIEW,
            }
            finish_reason = "stop"
        else:
            self._json_response(409, {"message": "completion limit exceeded"})
            return

        self._json_response(
            200,
            {
                "id": f"controlled-completion-{request_number}",
                "object": "chat.completion",
                "created": 1,
                "model": CONTROLLED_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    def do_GET(self) -> None:
        self._record()
        self._json_response(405, {"message": "method rejected"})


class RecordingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        handler: type[BaseHTTPRequestHandler],
        records: ServiceRecords,
    ) -> None:
        super().__init__(("0.0.0.0", 0), handler)
        self.records = records


def _start_server(
    handler: type[BaseHTTPRequestHandler],
) -> tuple[RecordingServer, threading.Thread, ServiceRecords]:
    records = ServiceRecords()
    server = RecordingServer(handler, records)
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
    except BaseException:
        server.server_close()
        raise
    return server, thread, records


def _stop_server(server: RecordingServer, thread: threading.Thread) -> None:
    cleanup_error: BaseException | None = None
    try:
        server.shutdown()
    except BaseException as error:
        cleanup_error = error
    try:
        server.server_close()
    except BaseException as error:
        if cleanup_error is None:
            cleanup_error = error
    try:
        thread.join(timeout=5)
    except BaseException as error:
        if cleanup_error is None:
            cleanup_error = error
    if thread.is_alive() and cleanup_error is None:
        cleanup_error = RuntimeError("controlled service thread did not stop")
    if cleanup_error is not None:
        raise RuntimeError(_redact_sensitive_text(str(cleanup_error))) from None


def _single_tool(body: Mapping[str, object]) -> Mapping[str, object]:
    tools = body["tools"]
    assert type(tools) is list and len(tools) == 1
    tool = tools[0]
    assert isinstance(tool, Mapping)
    return tool


def _assert_tool_request(body: Mapping[str, object]) -> None:
    assert body["model"] == CONTROLLED_MODEL
    tool = _single_tool(body)
    assert tool["type"] == "function"
    function = tool["function"]
    assert isinstance(function, Mapping)
    assert function["name"] == "get_pull_request"
    parameters = function["parameters"]
    assert isinstance(parameters, Mapping)
    assert parameters["required"] == ["owner", "repository", "pull_number"]
    assert parameters["additionalProperties"] is False
    properties = parameters["properties"]
    assert isinstance(properties, Mapping)
    pull_number = properties["pull_number"]
    assert isinstance(pull_number, Mapping)
    assert pull_number["minimum"] == 1
    thinking = body["thinking"]
    assert isinstance(thinking, Mapping)
    assert thinking["type"] == "disabled"


def _assert_requests(
    github_records: ServiceRecords,
    deepseek_records: ServiceRecords,
) -> None:
    github = github_records.requests
    assert [(request.method, request.path) for request in github] == [
        ("GET", METADATA_PATH),
        ("GET", FILES_PATH),
    ]
    assert github[0].query == ""
    assert parse_qs(github[1].query) == {"per_page": ["100"], "page": ["1"]}
    assert all("authorization" not in request.headers for request in github)
    assert all(
        forbidden not in request.path
        for request in github
        for forbidden in ("/reviews", "/comments", "/merge")
    )

    deepseek = deepseek_records.requests
    assert len(deepseek) == 2
    assert all(request.method == "POST" for request in deepseek)
    assert all(request.path == COMPLETIONS_PATH for request in deepseek)
    first_body = deepseek[0].body
    second_body = deepseek[1].body
    assert isinstance(first_body, Mapping)
    assert isinstance(second_body, Mapping)
    _assert_tool_request(first_body)
    _assert_tool_request(second_body)

    first_messages = first_body["messages"]
    second_messages = second_body["messages"]
    assert isinstance(first_messages, list)
    assert isinstance(second_messages, list)
    assert [message["role"] for message in first_messages] == ["system", "user"]
    assert [message["role"] for message in second_messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assistant = second_messages[2]
    assert assistant["tool_calls"][0]["id"] == TOOL_CALL_ID
    assert assistant["tool_calls"][0]["function"]["name"] == "get_pull_request"
    arguments = json.loads(assistant["tool_calls"][0]["function"]["arguments"])
    assert arguments == {
        "owner": "example-owner",
        "repository": "example-repository",
        "pull_number": 123,
    }
    tool_result = second_messages[3]
    assert tool_result["tool_call_id"] == TOOL_CALL_ID
    result = json.loads(tool_result["content"])
    assert result["metadata"] == {
        "title": "Controlled example change",
        "body": "A safe controlled Pull Request body.",
        "state": "open",
        "author": "example-author",
        "base_branch": "main",
        "head_branch": "controlled-change",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "changed_files": 1,
        "additions": 1,
        "deletions": 1,
        "commits": 1,
    }
    assert result["changed_files"] == FILES_RESPONSE


def _docker_command(
    image: str,
    container_name: str,
    github_port: int,
    deepseek_port: int,
) -> list[str]:
    command = ["docker", "run", "--rm", "--name", container_name]
    if platform.system() == "Linux":
        command.extend(["--add-host", f"{HOSTNAME_FROM_CONTAINER}:host-gateway"])
    command.extend(
        [
            "-e",
            "DEEPSEEK_API_KEY",
            "-e",
            f"DEEPSEEK_BASE_URL=http://{HOSTNAME_FROM_CONTAINER}:{deepseek_port}",
            "-e",
            f"DEEPSEEK_MODEL={CONTROLLED_MODEL}",
            "-e",
            f"GITHUB_API_BASE_URL=http://{HOSTNAME_FROM_CONTAINER}:{github_port}",
            image,
            TARGET_URL,
            "--max-tool-rounds",
            "2",
        ]
    )
    return command


def _subprocess_environment() -> dict[str, str]:
    subprocess_env = dict(os.environ)
    subprocess_env["DEEPSEEK_API_KEY"] = CONTROLLED_KEY
    return subprocess_env


def _redact_sensitive_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        normalized = value.decode("utf-8", errors="replace")
    else:
        normalized = value
    return normalized.replace(CONTROLLED_KEY, "<redacted>")


def _timeout_error(error: subprocess.TimeoutExpired) -> RuntimeError:
    stdout = _redact_sensitive_text(error.stdout)
    stderr = _redact_sensitive_text(error.stderr)
    details = []
    if stdout:
        details.append(f"stdout={stdout!r}")
    if stderr:
        details.append(f"stderr={stderr!r}")
    suffix = f"; {'; '.join(details)}" if details else ""
    return RuntimeError(f"controlled Docker E2E timed out{suffix}")


def _validate_completed_process(
    completed: subprocess.CompletedProcess[str],
) -> None:
    stdout_has_secret = CONTROLLED_KEY in completed.stdout
    stderr_has_secret = CONTROLLED_KEY in completed.stderr
    if stdout_has_secret or stderr_has_secret:
        raise RuntimeError("controlled Docker E2E output contained a sensitive value")

    stdout = _redact_sensitive_text(completed.stdout)
    stderr = _redact_sensitive_text(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(
            f"controlled container exited with status {completed.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    if stdout != EXPECTED_REVIEW + "\n":
        raise AssertionError("controlled container stdout did not match expected review")
    if stderr:
        raise AssertionError("controlled container stderr was not empty")


def run(image: str) -> None:
    container_name = f"ai-github-reviewer-controlled-{uuid.uuid4().hex}"
    github_resources: tuple[RecordingServer, threading.Thread, ServiceRecords] | None = None
    deepseek_resources: tuple[RecordingServer, threading.Thread, ServiceRecords] | None = None
    cleanup_error: BaseException | None = None
    try:
        github_resources = _start_server(GitHubHandler)
        deepseek_resources = _start_server(DeepSeekHandler)
        github_server, _, github_records = github_resources
        deepseek_server, _, deepseek_records = deepseek_resources
        try:
            completed = subprocess.run(
                _docker_command(
                    image,
                    container_name,
                    github_server.server_port,
                    deepseek_server.server_port,
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
                env=_subprocess_environment(),
            )
        except subprocess.TimeoutExpired as error:
            raise _timeout_error(error) from None

        _validate_completed_process(completed)
        _assert_requests(github_records, deepseek_records)
    finally:
        primary_error_active = sys.exc_info()[0] is not None
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except BaseException as error:
            cleanup_error = error
        for resources in (deepseek_resources, github_resources):
            if resources is None:
                continue
            server, thread, _ = resources
            try:
                _stop_server(server, thread)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None and not primary_error_active:
            raise RuntimeError(_redact_sensitive_text(str(cleanup_error))) from None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the controlled Docker E2E against local fake services."
    )
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    run(args.image)
    print("controlled Docker E2E passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
