import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from dotenv import dotenv_values

DEFAULT_DEEPSEEK_BASE_URL: Final = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL: Final = "deepseek-v4-flash"
DEFAULT_GITHUB_API_BASE_URL: Final = "https://api.github.com"

_DEEPSEEK_API_KEY: Final = "DEEPSEEK_API_KEY"
_DEEPSEEK_BASE_URL: Final = "DEEPSEEK_BASE_URL"
_DEEPSEEK_MODEL: Final = "DEEPSEEK_MODEL"
_GITHUB_API_BASE_URL: Final = "GITHUB_API_BASE_URL"
_SUPPORTED_VARIABLES: Final = (
    _DEEPSEEK_API_KEY,
    _DEEPSEEK_BASE_URL,
    _DEEPSEEK_MODEL,
    _GITHUB_API_BASE_URL,
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    deepseek_api_key: str = field(repr=False)
    deepseek_base_url: str
    deepseek_model: str
    github_api_base_url: str


def load_config(
    env: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = ".env",
) -> AppConfig:
    current_env = os.environ if env is None else env
    file_values: Mapping[str, str | None] = {}
    if dotenv_path is not None:
        file_values = dotenv_values(dotenv_path=dotenv_path, interpolate=False)

    values = {
        name: current_env[name] if name in current_env else file_values.get(name)
        for name in _SUPPORTED_VARIABLES
    }

    api_key = _required_api_key(values[_DEEPSEEK_API_KEY])
    deepseek_base_url = _optional_value(
        values[_DEEPSEEK_BASE_URL],
        DEFAULT_DEEPSEEK_BASE_URL,
    ).rstrip("/")
    deepseek_model = _optional_value(
        values[_DEEPSEEK_MODEL],
        DEFAULT_DEEPSEEK_MODEL,
    )
    github_api_base_url = _optional_value(
        values[_GITHUB_API_BASE_URL],
        DEFAULT_GITHUB_API_BASE_URL,
    ).rstrip("/")

    return AppConfig(
        deepseek_api_key=api_key,
        deepseek_base_url=deepseek_base_url,
        deepseek_model=deepseek_model,
        github_api_base_url=github_api_base_url,
    )


def _required_api_key(value: str | None) -> str:
    if value is None:
        raise ValueError("DEEPSEEK_API_KEY is required")

    normalized = value.strip()
    if not normalized:
        raise ValueError("DEEPSEEK_API_KEY is required")
    return normalized


def _optional_value(value: str | None, default: str) -> str:
    if value is None:
        return default

    normalized = value.strip()
    return normalized or default
