import os
import socket
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ai_github_reviewer.config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_GITHUB_API_BASE_URL,
    AppConfig,
    load_config,
)

REQUIRED_KEY_ERROR = "DEEPSEEK_API_KEY is required"
NETWORK_DISABLED_PATTERN = "Real network access is disabled in automated tests"


def test_load_config_accepts_and_trims_explicit_api_key() -> None:
    config = load_config({"DEEPSEEK_API_KEY": "  unit-test-secret  "}, dotenv_path=None)

    assert config.deepseek_api_key == "unit-test-secret"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"DEEPSEEK_API_KEY": ""},
        {"DEEPSEEK_API_KEY": " \t "},
    ],
)
def test_load_config_rejects_missing_empty_or_blank_api_key(env: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=f"^{REQUIRED_KEY_ERROR}$") as exc_info:
        load_config(env, dotenv_path=None)

    assert str(exc_info.value) == REQUIRED_KEY_ERROR


def test_openai_api_key_is_not_a_fallback() -> None:
    env = {"OPENAI_API_KEY": "unused-test-value"}

    with pytest.raises(ValueError, match=f"^{REQUIRED_KEY_ERROR}$"):
        load_config(env, dotenv_path=None)


def test_config_string_representations_hide_api_key() -> None:
    secret = "representation-test-secret"
    config = load_config({"DEEPSEEK_API_KEY": secret}, dotenv_path=None)

    assert secret not in repr(config)
    assert secret not in str(config)


def test_app_config_is_frozen() -> None:
    config = load_config({"DEEPSEEK_API_KEY": "frozen-test-secret"}, dotenv_path=None)

    with pytest.raises(FrozenInstanceError):
        config.deepseek_model = "replacement-model"


def test_optional_values_use_documented_defaults_when_missing() -> None:
    config = load_config({"DEEPSEEK_API_KEY": "default-test-secret"}, dotenv_path=None)

    assert config.deepseek_base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.deepseek_model == DEFAULT_DEEPSEEK_MODEL
    assert config.github_api_base_url == DEFAULT_GITHUB_API_BASE_URL


@pytest.mark.parametrize("blank_value", ["", " ", "\t"])
def test_blank_optional_values_use_documented_defaults(blank_value: str) -> None:
    env = {
        "DEEPSEEK_API_KEY": "blank-default-test-secret",
        "DEEPSEEK_BASE_URL": blank_value,
        "DEEPSEEK_MODEL": blank_value,
        "GITHUB_API_BASE_URL": blank_value,
    }

    config = load_config(env, dotenv_path=None)

    assert config.deepseek_base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.deepseek_model == DEFAULT_DEEPSEEK_MODEL
    assert config.github_api_base_url == DEFAULT_GITHUB_API_BASE_URL


def test_custom_optional_values_are_normalized() -> None:
    env = {
        "DEEPSEEK_API_KEY": "custom-test-secret",
        "DEEPSEEK_BASE_URL": "  https://deepseek.test/api///  ",
        "DEEPSEEK_MODEL": "  custom model name  ",
        "GITHUB_API_BASE_URL": "  https://github.test/api/v3//  ",
    }

    config = load_config(env, dotenv_path=None)

    assert config.deepseek_base_url == "https://deepseek.test/api"
    assert config.deepseek_model == "custom model name"
    assert config.github_api_base_url == "https://github.test/api/v3"


def test_load_config_reads_values_from_dotenv(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=dotenv-test-secret",
                "DEEPSEEK_BASE_URL=https://dotenv.deepseek.test///",
                "DEEPSEEK_MODEL=dotenv-model",
                "GITHUB_API_BASE_URL=https://dotenv.github.test//",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env={}, dotenv_path=dotenv_path)

    assert config == AppConfig(
        deepseek_api_key="dotenv-test-secret",
        deepseek_base_url="https://dotenv.deepseek.test",
        deepseek_model="dotenv-model",
        github_api_base_url="https://dotenv.github.test",
    )


def test_explicit_environment_takes_precedence_over_dotenv(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=dotenv-test-secret",
                "DEEPSEEK_BASE_URL=https://dotenv.deepseek.test",
                "DEEPSEEK_MODEL=dotenv-model",
                "GITHUB_API_BASE_URL=https://dotenv.github.test",
            ]
        ),
        encoding="utf-8",
    )
    env = {
        "DEEPSEEK_API_KEY": "environment-test-secret",
        "DEEPSEEK_BASE_URL": "https://environment.deepseek.test/",
        "DEEPSEEK_MODEL": "environment-model",
        "GITHUB_API_BASE_URL": "https://environment.github.test/",
    }

    config = load_config(env=env, dotenv_path=dotenv_path)

    assert config == AppConfig(
        deepseek_api_key="environment-test-secret",
        deepseek_base_url="https://environment.deepseek.test",
        deepseek_model="environment-model",
        github_api_base_url="https://environment.github.test",
    )


def test_blank_environment_value_does_not_fall_back_to_dotenv(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DEEPSEEK_API_KEY=dotenv-test-secret\nDEEPSEEK_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    env = {
        "DEEPSEEK_API_KEY": "environment-test-secret",
        "DEEPSEEK_MODEL": " ",
    }

    config = load_config(env=env, dotenv_path=dotenv_path)

    assert config.deepseek_model == DEFAULT_DEEPSEEK_MODEL


def test_dotenv_path_none_does_not_read_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=must-not-be-read\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match=f"^{REQUIRED_KEY_ERROR}$"):
        load_config(env={}, dotenv_path=None)


def test_load_config_uses_process_environment_when_env_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "  process-environment-test-secret  ")
    monkeypatch.setenv("DEEPSEEK_MODEL", "  process-model  ")

    config = load_config(env=None, dotenv_path=None)

    assert config.deepseek_api_key == "process-environment-test-secret"
    assert config.deepseek_model == "process-model"


def test_reading_dotenv_does_not_modify_process_environment(tmp_path: Path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DEEPSEEK_API_KEY=dotenv-environment-test-secret\n",
        encoding="utf-8",
    )
    environment_before = dict(os.environ)

    load_config(env={}, dotenv_path=dotenv_path)

    assert dict(os.environ) == environment_before


def test_load_config_does_not_modify_input_mapping() -> None:
    env = {
        "DEEPSEEK_API_KEY": "immutability-test-secret",
        "DEEPSEEK_BASE_URL": " https://immutable.deepseek.test/// ",
        "DEEPSEEK_MODEL": " immutable-model ",
        "GITHUB_API_BASE_URL": " https://immutable.github.test// ",
        "UNRELATED_VALUE": "preserved",
    }
    original = deepcopy(env)

    load_config(env, dotenv_path=None)

    assert env == original


def test_network_guard_blocks_standard_library_socket_entry_points() -> None:
    with pytest.raises(RuntimeError, match=NETWORK_DISABLED_PATTERN):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)

    test_socket = socket.socket()
    try:
        with pytest.raises(RuntimeError, match=NETWORK_DISABLED_PATTERN):
            test_socket.connect(("127.0.0.1", 9))
        with pytest.raises(RuntimeError, match=NETWORK_DISABLED_PATTERN):
            test_socket.connect_ex(("127.0.0.1", 9))
    finally:
        test_socket.close()


def test_in_memory_operations_work_with_network_guard() -> None:
    values = {"status": "controlled", "items": [1, 2, 3]}

    assert values["status"] == "controlled"
    assert sum(values["items"]) == 6
