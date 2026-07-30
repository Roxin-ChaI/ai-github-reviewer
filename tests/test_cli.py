import builtins
import inspect
import os
import socket
import subprocess
import sys
import webbrowser
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest

import ai_github_reviewer.cli as cli_module
from ai_github_reviewer.agent import DEFAULT_MAX_TOOL_ROUNDS
from ai_github_reviewer.pull_request import PullRequestTarget
from ai_github_reviewer.review_validation import ReviewValidationError

URL = "https://github.com/example-owner/example-repository/pull/123"
TARGET = PullRequestTarget("example-owner", "example-repository", 123)
SECRET = "controlled-deepseek-key-for-test"
NETWORK_DISABLED = "Real network access is disabled in automated tests"


@dataclass(frozen=True)
class FakeConfig:
    deepseek_api_key: str = SECRET
    deepseek_base_url: str = "https://deepseek.example.test"
    deepseek_model: str = "controlled-model"
    github_api_base_url: str = "https://github-api.example.test"


class Harness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        review: str = "controlled review",
    ) -> None:
        self.config = FakeConfig()
        self.target = TARGET
        self.review_text = review
        self.order: list[str] = []
        self.load_calls = 0
        self.url_values: list[str] = []
        self.http_kwargs: list[dict[str, object]] = []
        self.http_instances: list[object] = []
        self.http_enter = 0
        self.http_exit = 0
        self.github_args: list[tuple[object, str]] = []
        self.model_kwargs: list[dict[str, object]] = []
        self.agent_kwargs: list[dict[str, object]] = []
        self.review_calls = 0

        harness = self

        def fake_load_config() -> FakeConfig:
            harness.order.append("load_config")
            harness.load_calls += 1
            return harness.config

        def fake_parse_url(value: str) -> PullRequestTarget:
            harness.order.append("parse_pull_request_url")
            harness.url_values.append(value)
            return harness.target

        class FakeHTTPClient:
            def __init__(self, **kwargs: object) -> None:
                harness.order.append("http_client")
                harness.http_kwargs.append(deepcopy(kwargs))
                harness.http_instances.append(self)

            def __enter__(self) -> object:
                harness.order.append("http_client_enter")
                harness.http_enter += 1
                return self

            def __exit__(
                self,
                exc_type: object,
                exc_value: object,
                traceback: object,
            ) -> bool:
                harness.order.append("http_client_exit")
                harness.http_exit += 1
                return False

        class FakeGitHubClient:
            def __init__(self, http_client: object, api_base_url: str) -> None:
                harness.order.append("github_client")
                harness.github_args.append((http_client, api_base_url))

        class FakeModelClient:
            def __init__(self, **kwargs: object) -> None:
                harness.order.append("model_client")
                harness.model_kwargs.append(deepcopy(kwargs))

        class FakeAgent:
            def __init__(self, **kwargs: object) -> None:
                harness.order.append("agent")
                harness.agent_kwargs.append(dict(kwargs))

            def review(self) -> str:
                harness.order.append("review")
                harness.review_calls += 1
                return harness.review_text

        monkeypatch.setattr(cli_module, "load_config", fake_load_config)
        monkeypatch.setattr(cli_module, "parse_pull_request_url", fake_parse_url)
        monkeypatch.setattr(cli_module.httpx, "Client", FakeHTTPClient)
        monkeypatch.setattr(cli_module, "GitHubClient", FakeGitHubClient)
        monkeypatch.setattr(cli_module, "DeepSeekModelClient", FakeModelClient)
        monkeypatch.setattr(cli_module, "PullRequestReviewAgent", FakeAgent)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


def test_main_public_signature() -> None:
    assert inspect.signature(cli_module.main) == inspect.Signature(
        parameters=[
            inspect.Parameter(
                "argv",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=cli_module.Sequence[str] | None,
            )
        ],
        return_annotation=int,
    )


def test_module_has_main_execution_boundary() -> None:
    source = Path(cli_module.__file__).read_text(encoding="utf-8")

    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source


def test_pyproject_metadata_and_single_console_script() -> None:
    import tomllib

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "ai-github-reviewer"
    assert data["project"]["version"] == "0.1.0"
    assert data["project"]["requires-python"] == ">=3.12"
    assert data["project"]["scripts"] == {"ai-github-reviewer": "ai_github_reviewer.cli:main"}
    assert data["project"]["dependencies"] == [
        "httpx>=0.27,<1",
        "openai>=1.68,<3",
        "python-dotenv>=1.0,<2",
    ]
    assert data["build-system"]["build-backend"] == "setuptools.build_meta"
    assert "readme" not in data["project"]
    assert "license" not in data["project"]


@pytest.mark.parametrize(
    ("argv", "expected_rounds", "expected_url"),
    [
        ([URL], 8, URL),
        ([URL, "--max-tool-rounds", "1"], 1, URL),
        (["--max-tool-rounds", "8", URL], 8, URL),
        ([URL, "--max-tool-rounds", "17"], 17, URL),
        ([f"{URL}/"], 8, f"{URL}/"),
    ],
)
def test_valid_arguments_are_passed_unchanged(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_rounds: int,
    expected_url: str,
) -> None:
    argv_before = deepcopy(argv)

    status = cli_module.main(argv)

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == "controlled review\n"
    assert captured.err == ""
    assert argv == argv_before
    assert harness.url_values == [expected_url]
    assert harness.agent_kwargs[0]["max_tool_rounds"] == expected_rounds
    assert type(harness.agent_kwargs[0]["max_tool_rounds"]) is int


def test_repeated_round_option_uses_last_value(harness: Harness) -> None:
    cli_module.main([URL, "--max-tool-rounds", "2", "--max-tool-rounds", "5"])

    assert harness.agent_kwargs[0]["max_tool_rounds"] == 5


@pytest.mark.parametrize(
    "argv",
    [
        [],
        [URL, f"{URL}/"],
        [URL, f"{URL}/", URL],
        [URL, "--unknown"],
        [URL, "--max-tool-rounds"],
        [URL, "--max-tool-rounds", "abc"],
        [URL, "--max-tool-rounds", "1.5"],
        [URL, "--max-tool-rounds", "1e2"],
        [URL, "--max-tool-rounds", ""],
        [URL, "--max-tool-rounds", "0"],
        [URL, "--max-tool-rounds", "-1"],
        [URL, "--max-tool-rounds", "-10"],
        [URL, "--max-tool-rounds", "+0"],
        [URL, "--max-tool-rounds=true"],
    ],
)
def test_argument_errors_precede_all_dependencies(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert captured.out == ""
    assert "usage:" in captured.err
    assert "error:" in captured.err
    assert harness.load_calls == 0
    assert harness.url_values == []
    assert harness.model_kwargs == []
    assert harness.http_kwargs == []
    assert harness.github_args == []
    assert harness.agent_kwargs == []
    assert harness.review_calls == 0


@pytest.mark.parametrize("option", ["--help", "-h"])
def test_help_exits_without_dependencies(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
    option: str,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main([option])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out
    assert "pull_request_url" in captured.out
    assert "--max-tool-rounds" in captured.out
    assert captured.err == ""
    assert harness.load_calls == 0
    assert harness.url_values == []
    assert harness.http_kwargs == []
    assert harness.agent_kwargs == []


def test_dependency_wiring_and_order(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_before = deepcopy(harness.config)
    target_before = deepcopy(harness.target)

    status = cli_module.main([URL, "--max-tool-rounds", "3"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == "controlled review\n"
    assert captured.err == ""
    assert harness.load_calls == 1
    assert harness.url_values == [URL]
    assert harness.model_kwargs == [
        {
            "api_key": SECRET,
            "base_url": "https://deepseek.example.test",
            "model": "controlled-model",
        }
    ]
    assert harness.http_kwargs == [{"follow_redirects": False}]
    assert len(harness.http_instances) == 1
    assert harness.github_args == [
        (
            harness.http_instances[0],
            "https://github-api.example.test",
        )
    ]
    agent_kwargs = harness.agent_kwargs[0]
    assert agent_kwargs["target"] is harness.target
    assert agent_kwargs["github_client"] is not None
    assert agent_kwargs["model_client"] is not None
    assert agent_kwargs["max_tool_rounds"] == 3
    assert harness.review_calls == 1
    assert harness.http_enter == 1
    assert harness.http_exit == 1
    assert harness.order == [
        "load_config",
        "parse_pull_request_url",
        "model_client",
        "http_client",
        "http_client_enter",
        "github_client",
        "agent",
        "review",
        "http_client_exit",
    ]
    assert harness.config == config_before
    assert harness.target == target_before


@pytest.mark.parametrize(
    ("review", "expected"),
    [
        ("review without newline", "review without newline\n"),
        ("review with newline\n", "review with newline\n"),
        ("review with CRLF\r\n", "review with CRLF\r\n"),
        ("审查结果 ✓", "审查结果 ✓\n"),
        ("review\n\nwith\n\ninternal blanks", "review\n\nwith\n\ninternal blanks\n"),
    ],
)
def test_success_output_is_exact_and_client_closes_before_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    review: str,
    expected: str,
) -> None:
    harness = Harness(monkeypatch, review=review)
    review_before = review

    with caplog.at_level(1):
        status = cli_module.main([URL])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == expected
    assert captured.err == ""
    assert harness.review_calls == 1
    assert harness.http_exit == 1
    assert harness.order[-1] == "http_client_exit"
    assert review == review_before
    assert caplog.records == []


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://github.com/owner/repository/pull/1",
        f"{URL} {URL}",
        f"{URL}?page=1",
        f"{URL}#fragment",
        f"{URL}//",
    ],
)
def test_url_errors_stop_before_clients(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_url: str,
) -> None:
    harness = Harness(monkeypatch)
    monkeypatch.setattr(
        cli_module,
        "parse_pull_request_url",
        __import__(
            "ai_github_reviewer.github_url",
            fromlist=["parse_pull_request_url"],
        ).parse_pull_request_url,
    )

    with pytest.raises(ValueError, match="^Invalid GitHub pull request URL$"):
        cli_module.main([invalid_url])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert harness.load_calls == 1
    assert harness.model_kwargs == []
    assert harness.http_kwargs == []
    assert harness.agent_kwargs == []
    assert harness.review_calls == 0


def test_load_config_error_propagates_unchanged(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = ValueError("controlled configuration failure")
    monkeypatch.setattr(cli_module, "load_config", lambda: (_ for _ in ()).throw(error))

    with pytest.raises(ValueError) as exc_info:
        cli_module.main([URL])

    assert exc_info.value is error
    assert capsys.readouterr().out == ""
    assert harness.url_values == []
    assert harness.http_kwargs == []


@pytest.mark.parametrize(
    "stage",
    [
        "parse_url",
        "model_client",
        "http_constructor",
        "http_enter",
        "github_client",
        "agent",
        "review_runtime",
        "review_validation",
        "http_exit",
    ],
)
def test_dependency_errors_propagate_same_object_without_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stage: str,
) -> None:
    harness = Harness(monkeypatch)
    error: BaseException
    if stage == "review_validation":
        error = ReviewValidationError("controlled validation failure")
    else:
        error = RuntimeError(f"controlled {stage} failure")

    if stage == "parse_url":
        monkeypatch.setattr(
            cli_module,
            "parse_pull_request_url",
            lambda value: (_ for _ in ()).throw(error),
        )
    elif stage == "model_client":
        monkeypatch.setattr(
            cli_module,
            "DeepSeekModelClient",
            lambda **kwargs: (_ for _ in ()).throw(error),
        )
    elif stage == "http_constructor":
        monkeypatch.setattr(
            cli_module.httpx,
            "Client",
            lambda **kwargs: (_ for _ in ()).throw(error),
        )
    elif stage in {"http_enter", "http_exit"}:

        class FailingHTTPClient:
            def __init__(self, **kwargs: object) -> None:
                pass

            def __enter__(self) -> object:
                if stage == "http_enter":
                    raise error
                return self

            def __exit__(self, *args: object) -> bool:
                harness.http_exit += 1
                if stage == "http_exit":
                    raise error
                return False

        monkeypatch.setattr(cli_module.httpx, "Client", FailingHTTPClient)
    elif stage == "github_client":
        monkeypatch.setattr(
            cli_module,
            "GitHubClient",
            lambda **kwargs: (_ for _ in ()).throw(error),
        )
    elif stage == "agent":
        monkeypatch.setattr(
            cli_module,
            "PullRequestReviewAgent",
            lambda **kwargs: (_ for _ in ()).throw(error),
        )
    else:

        class FailingAgent:
            def __init__(self, **kwargs: object) -> None:
                pass

            def review(self) -> str:
                harness.review_calls += 1
                raise error

        monkeypatch.setattr(cli_module, "PullRequestReviewAgent", FailingAgent)

    with pytest.raises(type(error)) as exc_info:
        cli_module.main([URL])

    captured = capsys.readouterr()
    assert exc_info.value is error
    assert captured.out == ""
    assert captured.err == ""
    assert harness.review_calls <= 1
    if stage in {"github_client", "agent", "review_runtime", "review_validation"}:
        assert harness.http_exit == 1


def test_no_interaction_browser_subprocess_or_logging(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("forbidden side effect")

    monkeypatch.setattr(builtins, "input", fail)
    monkeypatch.setattr(sys.stdin, "read", fail)
    monkeypatch.setattr(webbrowser, "open", fail)
    monkeypatch.setattr(webbrowser, "open_new", fail)
    monkeypatch.setattr(webbrowser, "open_new_tab", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(os, "system", fail)

    with caplog.at_level(1):
        assert cli_module.main([URL]) == 0

    assert harness.review_calls == 1
    assert caplog.records == []


def test_secret_is_absent_from_output_and_module_representation(
    harness: Harness,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(1):
        cli_module.main([URL])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert SECRET not in repr(cli_module)
    assert all(SECRET not in record.getMessage() for record in caplog.records)


def test_network_guard_remains_active_after_success(harness: Harness) -> None:
    assert cli_module.main([URL]) == 0

    with pytest.raises(RuntimeError, match=NETWORK_DISABLED):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)


def test_default_round_limit_is_exact_integer_eight(harness: Harness) -> None:
    cli_module.main([URL])

    rounds = harness.agent_kwargs[0]["max_tool_rounds"]
    assert DEFAULT_MAX_TOOL_ROUNDS == 8
    assert rounds == 8
    assert type(rounds) is int
