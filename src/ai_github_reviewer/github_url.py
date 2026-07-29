import re
from typing import Final, NoReturn
from urllib.parse import urlsplit

from ai_github_reviewer.pull_request import PullRequestTarget

_INVALID_URL_MESSAGE: Final = "Invalid GitHub pull request URL"
_URL_TYPE_MESSAGE: Final = "pull request URL must be a string"
_PULL_REQUEST_PATH: Final = re.compile(r"/([^/]+)/([^/]+)/pull/([0-9]+)/?")


def parse_pull_request_url(url: str) -> PullRequestTarget:
    if type(url) is not str:
        raise TypeError(_URL_TYPE_MESSAGE)

    if (
        not url
        or not url.startswith("https://")
        or "?" in url
        or "#" in url
        or any(_is_forbidden_character(character) for character in url)
    ):
        _raise_invalid_url()

    try:
        parsed = urlsplit(url)
    except ValueError:
        _raise_invalid_url()

    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        _raise_invalid_url()

    path_match = _PULL_REQUEST_PATH.fullmatch(parsed.path)
    if path_match is None:
        _raise_invalid_url()

    owner, repository, pull_number_text = path_match.groups()
    pull_number = int(pull_number_text)
    if pull_number <= 0:
        _raise_invalid_url()

    return PullRequestTarget(
        owner=owner,
        repository=repository,
        pull_number=pull_number,
    )


def _is_forbidden_character(character: str) -> bool:
    return character.isspace() or ord(character) < 32 or ord(character) == 127


def _raise_invalid_url() -> NoReturn:
    raise ValueError(_INVALID_URL_MESSAGE)
