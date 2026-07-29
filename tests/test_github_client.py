import inspect
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import FrozenInstanceError

import httpx
import pytest

from ai_github_reviewer.github_client import (
    ChangedFilesIntegrityError,
    GitHubClient,
)
from ai_github_reviewer.pull_request import PullRequestData, PullRequestTarget

API_BASE_URL = "https://api.github.test"
METADATA_PATH = "/repos/example-owner/example-repository/pulls/123"
FILES_PATH = f"{METADATA_PATH}/files"
TARGET = PullRequestTarget(
    owner="example-owner",
    repository="example-repository",
    pull_number=123,
)
_OMIT = object()

ResponseFactory = Callable[[httpx.Request], httpx.Response]


class RecordingHandler:
    def __init__(self, responders: list[ResponseFactory]) -> None:
        self._responders = list(responders)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responders:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        return self._responders.pop(0)(request)


class SyntheticJSONResponse(httpx.Response):
    def __init__(
        self,
        payload: object,
        *,
        request: httpx.Request,
    ) -> None:
        super().__init__(200, request=request)
        self._payload = payload

    def json(self, **kwargs: object) -> object:
        return self._payload


class SyntheticLinksResponse(SyntheticJSONResponse):
    def __init__(
        self,
        payload: object,
        *,
        request: httpx.Request,
        links: object = _OMIT,
        links_error: type[Exception] | None = None,
    ) -> None:
        super().__init__(payload, request=request)
        self._synthetic_links = links
        self._links_error = links_error

    @property
    def links(self) -> object:
        if self._links_error is not None:
            raise self._links_error("synthetic links failure")
        return self._synthetic_links


def _metadata_payload(changed_files: int) -> dict[str, object]:
    return {
        "title": "Example change",
        "body": None,
        "state": "open",
        "user": {"login": "example-author"},
        "base": {"ref": "main"},
        "head": {"ref": "feature"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "changed_files": changed_files,
        "additions": 10,
        "deletions": 2,
        "commits": 1,
    }


def _file_payload(
    filename: str,
    *,
    patch: object = _OMIT,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "filename": filename,
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
    }
    if patch is not _OMIT:
        payload["patch"] = patch
    return payload


def _json_response(
    payload: object,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> ResponseFactory:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            request=request,
        )

    return responder


def _synthetic_json_response(payload: object) -> ResponseFactory:
    def responder(request: httpx.Request) -> httpx.Response:
        return SyntheticJSONResponse(payload, request=request)

    return responder


def _synthetic_links_response(
    payload: object,
    *,
    links: object = _OMIT,
    links_error: type[Exception] | None = None,
) -> ResponseFactory:
    def responder(request: httpx.Request) -> httpx.Response:
        return SyntheticLinksResponse(
            payload,
            request=request,
            links=links,
            links_error=links_error,
        )

    return responder


def _content_response(
    content: bytes,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> ResponseFactory:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=content,
            headers=headers,
            request=request,
        )

    return responder


def _link(next_reference: str) -> dict[str, str]:
    return {"Link": f'<{next_reference}>; rel="next"'}


def _run_client(
    handler: RecordingHandler,
    *,
    target: PullRequestTarget = TARGET,
    api_base_url: str = API_BASE_URL,
    follow_redirects: bool = False,
) -> PullRequestData:
    transport = httpx.MockTransport(handler)
    with httpx.Client(
        transport=transport,
        follow_redirects=follow_redirects,
    ) as http_client:
        client = GitHubClient(
            http_client=http_client,
            api_base_url=api_base_url,
        )
        return client.get_pull_request(target)


def test_public_interface_contains_only_injected_client_and_base_url() -> None:
    assert inspect.signature(GitHubClient) == inspect.Signature(
        parameters=[
            inspect.Parameter(
                "http_client",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=httpx.Client,
            ),
            inspect.Parameter(
                "api_base_url",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=str,
            ),
        ],
        return_annotation=None,
    )
    assert issubclass(ChangedFilesIntegrityError, ValueError)


def test_zero_changed_files_requests_only_metadata() -> None:
    metadata_payload = _metadata_payload(0)
    handler = RecordingHandler([_json_response(metadata_payload)])

    result = _run_client(handler)

    assert result.metadata.changed_files == 0
    assert result.changed_files == ()
    assert len(handler.requests) == 1
    assert handler.requests[0].method == "GET"
    assert handler.requests[0].url.path == METADATA_PATH


def test_single_page_returns_complete_data_and_uses_maximum_page_size() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _json_response([_file_payload("src/example.py")]),
        ]
    )

    result = _run_client(handler)

    assert result.metadata.title == "Example change"
    assert tuple(item.filename for item in result.changed_files) == ("src/example.py",)
    assert result.changed_files[0].patch is None
    assert [request.url.path for request in handler.requests] == [
        METADATA_PATH,
        FILES_PATH,
    ]
    assert dict(handler.requests[1].url.params) == {
        "per_page": "100",
        "page": "1",
    }


def test_single_page_preserves_file_order_and_all_patch_forms() -> None:
    files = [
        _file_payload("src/content.py", patch="@@ content @@"),
        _file_payload("src/missing.py"),
        _file_payload("src/none.py", patch=None),
        _file_payload("src/empty.py", patch=""),
    ]
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(4)),
            _json_response(files),
        ]
    )

    result = _run_client(handler)

    assert tuple(item.filename for item in result.changed_files) == (
        "src/content.py",
        "src/missing.py",
        "src/none.py",
        "src/empty.py",
    )
    assert tuple(item.patch for item in result.changed_files) == (
        "@@ content @@",
        None,
        None,
        "",
    )


def test_absolute_same_origin_next_is_followed_without_page_guessing() -> None:
    next_url = f"{API_BASE_URL}{FILES_PATH}?page=7&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(next_url),
            ),
            _json_response([_file_payload("src/second.py")]),
        ]
    )

    result = _run_client(handler)

    assert tuple(item.filename for item in result.changed_files) == (
        "src/first.py",
        "src/second.py",
    )
    assert [request.url.params.get("page") for request in handler.requests[1:]] == [
        "1",
        "7",
    ]
    assert str(handler.requests[2].url) == next_url


def test_relative_next_is_resolved_against_current_request() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link("?per_page=100&page=9"),
            ),
            _json_response([_file_payload("src/second.py")]),
        ]
    )

    result = _run_client(handler)

    assert tuple(item.filename for item in result.changed_files) == (
        "src/first.py",
        "src/second.py",
    )
    assert str(handler.requests[2].url) == (f"{API_BASE_URL}{FILES_PATH}?per_page=100&page=9")


def test_non_next_link_relations_are_ignored() -> None:
    last_url = f"{API_BASE_URL}{FILES_PATH}?page=99&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _json_response(
                [_file_payload("src/example.py")],
                headers={"Link": f'<{last_url}>; rel="last"'},
            ),
        ]
    )

    result = _run_client(handler)

    assert result.changed_files[0].filename == "src/example.py"
    assert len(handler.requests) == 2


def test_base_url_path_and_trailing_slash_are_preserved() -> None:
    api_base_url = f"{API_BASE_URL}/api/v3/"
    expected_path = f"/api/v3{METADATA_PATH}"
    handler = RecordingHandler([_json_response(_metadata_payload(0))])

    _run_client(handler, api_base_url=api_base_url)

    assert handler.requests[0].url.path == expected_path


def test_target_segments_cannot_change_url_components() -> None:
    target = PullRequestTarget(
        owner="owner?#",
        repository="repo/name",
        pull_number=123,
    )
    handler = RecordingHandler([_json_response(_metadata_payload(0))])

    _run_client(handler, target=target)

    assert handler.requests[0].url.raw_path == (b"/repos/owner%3F%23/repo%2Fname/pulls/123")
    assert handler.requests[0].url.host == "api.github.test"
    assert not handler.requests[0].url.query
    assert not handler.requests[0].url.fragment


def test_requests_are_get_only_and_have_no_authorization_header() -> None:
    next_url = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(next_url),
            ),
            _json_response([_file_payload("src/second.py")]),
        ]
    )
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer caller-value"},
        auth=("caller", "password"),
    )

    try:
        client = GitHubClient(http_client, API_BASE_URL)
        client.get_pull_request(TARGET)

        assert [request.method for request in handler.requests] == [
            "GET",
            "GET",
            "GET",
        ]
        assert all("authorization" not in request.headers for request in handler.requests)
        assert http_client.headers["authorization"] == "Bearer caller-value"
        assert not http_client.is_closed
    finally:
        http_client.close()


def test_client_exposes_no_write_operation() -> None:
    handler = RecordingHandler([_json_response(_metadata_payload(0))])
    transport = httpx.MockTransport(handler)

    with httpx.Client(transport=transport) as http_client:
        client = GitHubClient(http_client, API_BASE_URL)

        assert not hasattr(client, "post")
        assert not hasattr(client, "put")
        assert not hasattr(client, "patch")
        assert not hasattr(client, "delete")


@pytest.mark.parametrize(
    "invalid_base_url",
    [
        "",
        "api.github.test",
        "https://user@api.github.test",
        "https://api.github.test?query=",
        "https://api.github.test#fragment",
        None,
        True,
    ],
)
def test_invalid_api_base_url_is_rejected(
    invalid_base_url: object,
) -> None:
    handler = RecordingHandler([])
    transport = httpx.MockTransport(handler)

    with httpx.Client(transport=transport) as http_client:
        with pytest.raises(ValueError, match=r"^invalid GitHub API base URL$"):
            GitHubClient(http_client, invalid_base_url)

    assert handler.requests == []


@pytest.mark.parametrize("status_code", [302, 307])
@pytest.mark.parametrize("endpoint", ["metadata", "files"])
def test_redirects_are_not_followed(
    status_code: int,
    endpoint: str,
) -> None:
    redirect = _content_response(
        b"",
        status_code=status_code,
        headers={"Location": "https://redirect.example/elsewhere"},
    )
    responders = [redirect]
    if endpoint == "files":
        responders = [_json_response(_metadata_payload(1)), redirect]
    handler = RecordingHandler(responders)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _run_client(handler, follow_redirects=True)

    assert exc_info.value.response.status_code == status_code
    assert len(handler.requests) == (1 if endpoint == "metadata" else 2)
    assert all(request.url.host == "api.github.test" for request in handler.requests)


@pytest.mark.parametrize(
    ("page_payload", "expected_message"),
    [
        ({}, "invalid changed files page"),
        ("files", "invalid changed files page"),
        (None, "invalid changed files page"),
        (True, "invalid changed files page"),
        ([None], "invalid changed files page"),
        ([[]], "invalid changed files page"),
        (["file"], "invalid changed files page"),
        ([1], "invalid changed files page"),
        (
            [
                {
                    "filename": "src/example.py",
                    "status": "modified",
                    "additions": True,
                    "deletions": 0,
                    "changes": 1,
                }
            ],
            "invalid changed files page",
        ),
        (
            [
                {
                    "filename": "src/example.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                }
            ],
            "invalid changed files page",
        ),
    ],
)
def test_invalid_changed_files_page_is_integrity_error(
    page_payload: object,
    expected_message: str,
) -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _json_response(page_payload),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=rf"^{expected_message}$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_tuple_changed_files_page_root_is_rejected() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _synthetic_json_response((_file_payload("src/example.py"),)),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files page$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_duplicate_filename_on_same_page_is_rejected() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [
                    _file_payload("src/duplicate.py"),
                    _file_payload("src/duplicate.py"),
                ]
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^duplicate changed file filename$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_duplicate_filename_across_pages_is_rejected() -> None:
    next_url = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/duplicate.py")],
                headers=_link(next_url),
            ),
            _json_response([_file_payload("src/duplicate.py")]),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^duplicate changed file filename$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 3


def test_changed_file_count_cannot_exceed_metadata() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _json_response(
                [
                    _file_payload("src/first.py"),
                    _file_payload("src/second.py"),
                ]
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed file count exceeds metadata$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_pagination_cannot_end_before_expected_count() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response([_file_payload("src/first.py")]),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination ended before expected count$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_pagination_cannot_continue_after_expected_count() -> None:
    next_url = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _json_response(
                [_file_payload("src/example.py")],
                headers=_link(next_url),
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination continued after expected count$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_empty_page_with_next_cannot_continue() -> None:
    next_url = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(1)),
            _json_response([], headers=_link(next_url)),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination made no progress$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


@pytest.mark.parametrize(
    "next_reference",
    [
        pytest.param(
            f"http://api.github.test{FILES_PATH}?page=2&per_page=100",
            id="scheme-change",
        ),
        pytest.param(
            f"https://evil.example{FILES_PATH}?page=2&per_page=100",
            id="host-change",
        ),
        pytest.param(
            f"https://sub.api.github.test{FILES_PATH}?page=2&per_page=100",
            id="host-subdomain",
        ),
        pytest.param(
            f"https://api.github.test.{FILES_PATH}?page=2&per_page=100",
            id="host-trailing-dot",
        ),
        pytest.param(
            f"https://API.github.test{FILES_PATH}?page=2&per_page=100",
            id="authority-case",
        ),
        pytest.param(
            f"https://api.github.test:443{FILES_PATH}?page=2&per_page=100",
            id="explicit-default-port",
        ),
        pytest.param(
            f"https://api.github.test:8443{FILES_PATH}?page=2&per_page=100",
            id="other-port",
        ),
        pytest.param(
            f"https://user@api.github.test{FILES_PATH}?page=2&per_page=100",
            id="username",
        ),
        pytest.param(
            f"https://user:password@api.github.test{FILES_PATH}?page=2&per_page=100",
            id="password",
        ),
        pytest.param(
            f"https://api.github.test{FILES_PATH}?page=2&per_page=100#fragment",
            id="fragment",
        ),
        pytest.param(
            f"https://api.github.test{FILES_PATH}?page=2&per_page=100#",
            id="empty-fragment",
        ),
        pytest.param(
            f"{API_BASE_URL}/repos/other-owner/example-repository/pulls/123/files?page=2",
            id="owner-change",
        ),
        pytest.param(
            f"{API_BASE_URL}/repos/example-owner/other-repository/pulls/123/files?page=2",
            id="repository-change",
        ),
        pytest.param(
            f"{API_BASE_URL}/repos/example-owner/example-repository/pulls/456/files?page=2",
            id="pull-number-change",
        ),
        pytest.param(
            f"{API_BASE_URL}{METADATA_PATH}?page=2",
            id="metadata-endpoint",
        ),
        pytest.param(
            f"{API_BASE_URL}/repos/example-owner/example-repository/issues/123?page=2",
            id="issue-endpoint",
        ),
        pytest.param(
            f"{API_BASE_URL}/repos/example-owner/example-repository/commits/abc?page=2",
            id="commit-endpoint",
        ),
        pytest.param(
            f"{API_BASE_URL}/arbitrary?page=2",
            id="arbitrary-endpoint",
        ),
        pytest.param(
            f"{API_BASE_URL}{FILES_PATH}/extra?page=2",
            id="files-subpath",
        ),
        pytest.param(
            f"{API_BASE_URL}{FILES_PATH}/../files?page=2",
            id="dot-dot-path",
        ),
        pytest.param(
            f"{API_BASE_URL}/repos//example-owner/example-repository/pulls/123/files?page=2",
            id="repeated-slash",
        ),
        pytest.param(f"{FILES_PATH}?page=2&state=open", id="unknown-query"),
        pytest.param(f"{FILES_PATH}?page=", id="empty-page"),
        pytest.param(f"{FILES_PATH}?page=0", id="zero-page"),
        pytest.param(f"{FILES_PATH}?page=-1", id="negative-page"),
        pytest.param(f"{FILES_PATH}?page=1.5", id="decimal-page"),
        pytest.param(f"{FILES_PATH}?page=1e3", id="scientific-page"),
        pytest.param(f"{FILES_PATH}?page=+2", id="positive-sign-page"),
        pytest.param(f"{FILES_PATH}?page=%D9%A2", id="unicode-page"),
        pytest.param(f"{FILES_PATH}?page=2&page=3", id="duplicate-page"),
        pytest.param(
            f"{FILES_PATH}?page=2&per_page=100&per_page=50",
            id="duplicate-per-page",
        ),
        pytest.param(f"{FILES_PATH}?per_page=100", id="missing-page"),
        pytest.param(f"{FILES_PATH}?", id="empty-query"),
        pytest.param(f"{FILES_PATH}?Page=2", id="case-sensitive-name"),
        pytest.param(f"{FILES_PATH}?p%61ge=2", id="encoded-name"),
        pytest.param(f"{FILES_PATH}?page=%32", id="encoded-value"),
        pytest.param(
            f"//api.github.test{FILES_PATH}?page=2&per_page=100",
            id="scheme-relative",
        ),
        pytest.param(
            f"https://github.com{FILES_PATH}?page=2&per_page=100",
            id="github-web",
        ),
        pytest.param(
            f"https://api.deepseek.com{FILES_PATH}?page=2&per_page=100",
            id="deepseek",
        ),
        pytest.param(" relative?page=2", id="leading-space"),
        pytest.param("relative?page=2 ", id="trailing-space"),
    ],
)
def test_invalid_next_url_is_rejected_before_request(
    next_reference: str,
) -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(next_reference),
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2
    assert all(request.url.host == "api.github.test" for request in handler.requests)


@pytest.mark.parametrize(
    "links_error",
    [AttributeError, KeyError, TypeError, ValueError],
)
def test_links_property_raises_controlled_error(
    links_error: type[Exception],
) -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links_error=links_error,
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_links_non_mapping_is_rejected() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links=[],
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


@pytest.mark.parametrize("invalid_metadata", [None, [], "next"])
def test_next_metadata_non_mapping_is_rejected(
    invalid_metadata: object,
) -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links={"next": invalid_metadata},
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_next_metadata_missing_url_is_rejected() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links={"next": {"rel": "next"}},
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_next_metadata_empty_url_is_rejected() -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links={"next": {"url": ""}},
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


@pytest.mark.parametrize("invalid_url", [None, 123, True, []])
def test_next_metadata_non_string_url_is_rejected(
    invalid_url: object,
) -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links={"next": {"url": invalid_url}},
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_synthetic_links_metadata_requests_next_page() -> None:
    page_two = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _synthetic_links_response(
                [_file_payload("src/first.py")],
                links={"next": {"url": page_two}},
            ),
            _json_response([_file_payload("src/second.py")]),
        ]
    )

    result = _run_client(handler)

    assert [item.filename for item in result.changed_files] == [
        "src/first.py",
        "src/second.py",
    ]
    assert len(handler.requests) == 3
    assert str(handler.requests[2].url) == page_two


@pytest.mark.parametrize(
    "malformed_link",
    [
        '<>; rel="next"',
        'rel="next"',
    ],
)
def test_malformed_next_link_is_rejected(
    malformed_link: str,
) -> None:
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers={"Link": malformed_link},
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^invalid changed files next URL$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_current_page_next_is_detected_as_loop() -> None:
    current_url = f"{API_BASE_URL}{FILES_PATH}?per_page=100&page=1"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(current_url),
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination loop detected$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_query_order_cannot_hide_current_page_loop() -> None:
    equivalent_current = f"{API_BASE_URL}{FILES_PATH}?page=1&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(equivalent_current),
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination loop detected$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 2


def test_previously_visited_page_is_detected_as_loop() -> None:
    page_two = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    first_page_reordered = f"{API_BASE_URL}{FILES_PATH}?page=1&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(3)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(page_two),
            ),
            _json_response(
                [_file_payload("src/second.py")],
                headers=_link(first_page_reordered),
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination loop detected$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 3


def test_query_order_cannot_hide_visited_second_page_loop() -> None:
    page_two = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    page_two_reordered = f"{API_BASE_URL}{FILES_PATH}?per_page=100&page=2"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(3)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(page_two),
            ),
            _json_response(
                [_file_payload("src/second.py")],
                headers=_link(page_two_reordered),
            ),
        ]
    )

    with pytest.raises(
        ChangedFilesIntegrityError,
        match=r"^changed files pagination loop detected$",
    ):
        _run_client(handler)

    assert len(handler.requests) == 3


@pytest.mark.parametrize(
    "exception_type",
    [httpx.ConnectError, httpx.TimeoutException],
)
@pytest.mark.parametrize("endpoint", ["metadata", "files"])
def test_connection_and_timeout_exceptions_propagate_unchanged(
    exception_type: type[httpx.RequestError],
    endpoint: str,
) -> None:
    raised_errors: list[httpx.RequestError] = []

    def fail(request: httpx.Request) -> httpx.Response:
        error = exception_type("controlled failure", request=request)
        raised_errors.append(error)
        raise error

    responders: list[ResponseFactory] = [fail]
    if endpoint == "files":
        responders = [_json_response(_metadata_payload(1)), fail]
    handler = RecordingHandler(responders)

    with pytest.raises(exception_type) as exc_info:
        _run_client(handler)

    assert exc_info.value is raised_errors[0]
    assert len(handler.requests) == (1 if endpoint == "metadata" else 2)


@pytest.mark.parametrize("status_code", [404, 429])
@pytest.mark.parametrize("endpoint", ["metadata", "files"])
def test_http_status_errors_propagate_without_retry(
    status_code: int,
    endpoint: str,
) -> None:
    failure = _json_response({"message": "controlled"}, status_code=status_code)
    responders = [failure]
    if endpoint == "files":
        responders = [_json_response(_metadata_payload(1)), failure]
    handler = RecordingHandler(responders)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        _run_client(handler)

    assert exc_info.value.response.status_code == status_code
    assert len(handler.requests) == (1 if endpoint == "metadata" else 2)


@pytest.mark.parametrize("endpoint", ["metadata", "files"])
def test_json_decode_errors_propagate_without_retry(endpoint: str) -> None:
    invalid_json = _content_response(
        b"{not valid json",
        headers={"Content-Type": "application/json"},
    )
    responders = [invalid_json]
    if endpoint == "files":
        responders = [_json_response(_metadata_payload(1)), invalid_json]
    handler = RecordingHandler(responders)

    with pytest.raises(json.JSONDecodeError):
        _run_client(handler)

    assert len(handler.requests) == (1 if endpoint == "metadata" else 2)


@pytest.mark.parametrize(
    "metadata_payload",
    [
        [],
        {"title": "missing required fields"},
        {**_metadata_payload(1), "changed_files": True},
    ],
)
def test_invalid_metadata_stops_before_changed_files(
    metadata_payload: object,
) -> None:
    handler = RecordingHandler([_json_response(metadata_payload)])

    with pytest.raises((TypeError, ValueError)):
        _run_client(handler)

    assert len(handler.requests) == 1
    assert handler.requests[0].url.path == METADATA_PATH


def test_failure_on_later_page_returns_no_partial_result() -> None:
    page_two = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(_metadata_payload(2)),
            _json_response(
                [_file_payload("src/first.py")],
                headers=_link(page_two),
            ),
            _json_response({"message": "failure"}, status_code=500),
        ]
    )

    with pytest.raises(httpx.HTTPStatusError):
        _run_client(handler)

    assert len(handler.requests) == 3


def test_metadata_and_pages_are_not_modified() -> None:
    metadata_payload = _metadata_payload(2)
    first_page = [_file_payload("src/first.py", patch=None)]
    second_page = [_file_payload("src/second.py", patch="")]
    original_metadata = deepcopy(metadata_payload)
    original_first_page = deepcopy(first_page)
    original_second_page = deepcopy(second_page)
    page_two = f"{API_BASE_URL}{FILES_PATH}?page=2&per_page=100"
    handler = RecordingHandler(
        [
            _json_response(metadata_payload),
            _json_response(first_page, headers=_link(page_two)),
            _json_response(second_page),
        ]
    )
    original_target = TARGET

    result = _run_client(handler)

    assert TARGET is original_target
    assert TARGET == PullRequestTarget(
        "example-owner",
        "example-repository",
        123,
    )
    assert metadata_payload == original_metadata
    assert first_page == original_first_page
    assert second_page == original_second_page
    assert result.changed_files[0].patch is None
    assert result.changed_files[1].patch == ""
    with pytest.raises(FrozenInstanceError):
        result.metadata.title = "replacement"


def test_mock_transport_works_with_global_network_guard_enabled() -> None:
    handler = RecordingHandler([_json_response(_metadata_payload(0))])

    result = _run_client(handler)

    assert result.changed_files == ()
    assert len(handler.requests) == 1


def test_success_emits_no_stdout_or_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler = RecordingHandler([_json_response(_metadata_payload(0))])

    _run_client(handler)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
