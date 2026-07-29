from dataclasses import FrozenInstanceError

import pytest

from ai_github_reviewer.github_url import parse_pull_request_url
from ai_github_reviewer.pull_request import PullRequestTarget

INVALID_URL_MESSAGE = "Invalid GitHub pull request URL"
URL_TYPE_MESSAGE = "pull request URL must be a string"


def test_pull_request_target_creation_and_equality() -> None:
    target = PullRequestTarget(owner="Example-Owner", repository="Example_Repo", pull_number=123)
    equal_target = PullRequestTarget(
        owner="Example-Owner",
        repository="Example_Repo",
        pull_number=123,
    )

    assert target == equal_target
    assert repr(target) == (
        "PullRequestTarget(owner='Example-Owner', repository='Example_Repo', pull_number=123)"
    )


def test_pull_request_target_is_frozen() -> None:
    target = PullRequestTarget(owner="owner", repository="repository", pull_number=1)

    with pytest.raises(FrozenInstanceError):
        target.pull_number = 2


def test_pull_request_target_preserves_string_content() -> None:
    target = PullRequestTarget(owner=" Owner ", repository=" Repository ", pull_number=1)

    assert target.owner == " Owner "
    assert target.repository == " Repository "


@pytest.mark.parametrize("owner", ["", " ", "\t", None, 123, True])
def test_pull_request_target_rejects_invalid_owner(owner: object) -> None:
    with pytest.raises(ValueError) as exc_info:
        PullRequestTarget(owner=owner, repository="repository", pull_number=1)  # type: ignore[arg-type]

    assert str(exc_info.value) == "owner must be a non-empty string"


@pytest.mark.parametrize("repository", ["", " ", "\n", None, 123, False])
def test_pull_request_target_rejects_invalid_repository(repository: object) -> None:
    with pytest.raises(ValueError) as exc_info:
        PullRequestTarget(owner="owner", repository=repository, pull_number=1)  # type: ignore[arg-type]

    assert str(exc_info.value) == "repository must be a non-empty string"


@pytest.mark.parametrize("pull_number", [0, -1, "1", 1.0, True, False, None])
def test_pull_request_target_rejects_invalid_pull_number(pull_number: object) -> None:
    with pytest.raises(ValueError) as exc_info:
        PullRequestTarget(
            owner="owner",
            repository="repository",
            pull_number=pull_number,  # type: ignore[arg-type]
        )

    assert str(exc_info.value) == "pull_number must be a positive integer"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/octo-org/example-repo/pull/123",
            PullRequestTarget("octo-org", "example-repo", 123),
        ),
        (
            "https://github.com/Owner_123/repo.name-2/pull/7/",
            PullRequestTarget("Owner_123", "repo.name-2", 7),
        ),
        (
            "https://github.com/a1/b_2.c-3/pull/1",
            PullRequestTarget("a1", "b_2.c-3", 1),
        ),
    ],
)
def test_parse_pull_request_url_accepts_supported_forms(
    url: str,
    expected: PullRequestTarget,
) -> None:
    original_url = url

    target = parse_pull_request_url(url)

    assert isinstance(target, PullRequestTarget)
    assert target == expected
    assert url == original_url


@pytest.mark.parametrize("url", [None, 123, 1.5, True, object()])
def test_parse_pull_request_url_rejects_non_string_input(url: object) -> None:
    with pytest.raises(TypeError) as exc_info:
        parse_pull_request_url(url)  # type: ignore[arg-type]

    assert str(exc_info.value) == URL_TYPE_MESSAGE


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param(
            " https://github.com/owner/repository/pull/1",
            id="leading-whitespace",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1 ",
            id="trailing-whitespace",
        ),
        pytest.param(
            "https://github.com/own er/repository/pull/1",
            id="middle-space",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1\n",
            id="newline",
        ),
        pytest.param(
            "https://github.com/owner/\trepository/pull/1",
            id="tab",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1 https://github.com/owner/repository/pull/2",
            id="multiple-urls",
        ),
        pytest.param(
            "github.com/owner/repository/pull/1",
            id="missing-scheme",
        ),
        pytest.param(
            "http://github.com/owner/repository/pull/1",
            id="http",
        ),
        pytest.param(
            "ftp://github.com/owner/repository/pull/1",
            id="ftp",
        ),
        pytest.param(
            "HTTPS://github.com/owner/repository/pull/1",
            id="uppercase-scheme",
        ),
        pytest.param(
            "https://example.com/owner/repository/pull/1",
            id="non-github-host",
        ),
        pytest.param(
            "https://www.github.com/owner/repository/pull/1",
            id="www-subdomain",
        ),
        pytest.param(
            "https://api.github.com/owner/repository/pull/1",
            id="api-subdomain",
        ),
        pytest.param(
            "https://github.example.com/owner/repository/pull/1",
            id="enterprise-host",
        ),
        pytest.param(
            "https://github.com.evil.example/owner/repository/pull/1",
            id="host-suffix",
        ),
        pytest.param(
            "https://github.local/owner/repository/pull/1",
            id="local-host",
        ),
        pytest.param(
            "https://GitHub.com/owner/repository/pull/1",
            id="host-case-variant",
        ),
        pytest.param(
            "https://github.com./owner/repository/pull/1",
            id="host-trailing-dot",
        ),
        pytest.param(
            "https://user@github.com/owner/repository/pull/1",
            id="username",
        ),
        pytest.param(
            "https://user:password@github.com/owner/repository/pull/1",
            id="password",
        ),
        pytest.param(
            "https://github.com:443/owner/repository/pull/1",
            id="explicit-default-port",
        ),
        pytest.param(
            "https://github.com:8443/owner/repository/pull/1",
            id="explicit-other-port",
        ),
        pytest.param(
            "https://git.io/owner/repository/pull/1",
            id="shortened-url",
        ),
        pytest.param(
            "https://github.comevil.example/owner/repository/pull/1",
            id="extra-host-text",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1?page=1",
            id="query",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1?",
            id="empty-query-delimiter",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1#section",
            id="fragment",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1#",
            id="empty-fragment-delimiter",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1?page=1#section",
            id="query-and-fragment",
        ),
        pytest.param(
            "https://github.com/owner/repository",
            id="repository-home",
        ),
        pytest.param(
            "https://github.com/owner/repository/issues/1",
            id="issue",
        ),
        pytest.param(
            "https://github.com/owner/repository/commit/abc",
            id="commit",
        ),
        pytest.param(
            "https://github.com/owner/repository/actions/1",
            id="actions",
        ),
        pytest.param(
            "https://github.com/owner/repository/releases/1",
            id="releases",
        ),
        pytest.param(
            "https://github.com//repository/pull/1",
            id="missing-owner",
        ),
        pytest.param(
            "https://github.com/owner//pull/1",
            id="missing-repository",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull",
            id="missing-number",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/0",
            id="zero-number",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/-1",
            id="negative-number",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1.5",
            id="decimal-number",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1e3",
            id="scientific-number",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/+1",
            id="positive-sign",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/abc",
            id="alphabetic-number",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/١٢٣",
            id="non-ascii-digits",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1/files",
            id="extra-segment",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1//",
            id="double-trailing-slash",
        ),
        pytest.param(
            "https://github.com/owner/repository/pull/1///",
            id="multiple-trailing-slashes",
        ),
        pytest.param(
            "https://github.com/owner//repository/pull/1",
            id="internal-double-slash",
        ),
        pytest.param(
            "https://github.com/owner/repository/Pull/1",
            id="pull-case",
        ),
        pytest.param(
            "https://github.com/owner/repository/pulls/1",
            id="pulls-path",
        ),
    ],
)
def test_parse_pull_request_url_rejects_invalid_strings(url: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_pull_request_url(url)

    assert str(exc_info.value) == INVALID_URL_MESSAGE


def test_parser_operates_with_global_network_guard_enabled() -> None:
    target = parse_pull_request_url("https://github.com/example-owner/example-repo/pull/42")

    assert target == PullRequestTarget("example-owner", "example-repo", 42)
