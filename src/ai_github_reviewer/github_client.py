import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import httpx

from ai_github_reviewer.pull_request import (
    ChangedFile,
    PullRequestData,
    PullRequestTarget,
    build_pull_request_data,
    parse_changed_file,
    parse_pull_request_metadata,
)

_INVALID_API_BASE_URL: Final = "invalid GitHub API base URL"
_INVALID_PAGE: Final = "invalid changed files page"
_DUPLICATE_FILENAME: Final = "duplicate changed file filename"
_COUNT_EXCEEDS_METADATA: Final = "changed file count exceeds metadata"
_PAGINATION_ENDED_EARLY: Final = "changed files pagination ended before expected count"
_PAGINATION_CONTINUED: Final = "changed files pagination continued after expected count"
_PAGINATION_NO_PROGRESS: Final = "changed files pagination made no progress"
_PAGINATION_LOOP: Final = "changed files pagination loop detected"
_INVALID_NEXT_URL: Final = "invalid changed files next URL"
_MISSING_LINK_METADATA: Final = object()
_NEXT_RELATION: Final = re.compile(
    r"""\brel\s*=\s*(?:"next"|'next'|next)(?=\s*(?:;|,|$))""",
    re.IGNORECASE,
)
_POSITIVE_ASCII_INTEGER: Final = re.compile(r"[0-9]+")
_PAGINATION_PARAMETERS: Final = frozenset({"page", "per_page"})

PageIdentity = tuple[str, str, str, tuple[tuple[str, str], ...]]


class ChangedFilesIntegrityError(ValueError):
    """Changed-file pagination or completeness is invalid."""


class GitHubClient:
    def __init__(
        self,
        http_client: httpx.Client,
        api_base_url: str,
    ) -> None:
        (
            self._api_base_url,
            self._api_scheme,
            self._api_authority,
            self._api_base_path,
        ) = _validate_api_base_url(api_base_url)
        self._http_client = http_client

    def get_pull_request(
        self,
        target: PullRequestTarget,
    ) -> PullRequestData:
        metadata_url, files_url, files_path = self._target_urls(target)

        metadata_response = self._get(metadata_url)
        metadata_payload = metadata_response.json()
        metadata = parse_pull_request_metadata(metadata_payload)

        if metadata.changed_files == 0:
            return build_pull_request_data(metadata, ())

        first_response = self._get(
            files_url,
            params=(("per_page", "100"), ("page", "1")),
        )
        current_url = str(first_response.request.url)
        visited = {_page_identity(current_url)}
        response = first_response
        changed_files: list[ChangedFile] = []
        filenames: set[str] = set()

        while True:
            page = self._parse_changed_files_page(response)
            for changed_file in page:
                if changed_file.filename in filenames:
                    raise ChangedFilesIntegrityError(_DUPLICATE_FILENAME)
                filenames.add(changed_file.filename)
                changed_files.append(changed_file)

            if len(changed_files) > metadata.changed_files:
                raise ChangedFilesIntegrityError(_COUNT_EXCEEDS_METADATA)

            next_reference = _next_reference(response)
            if len(changed_files) == metadata.changed_files:
                if next_reference is not None:
                    raise ChangedFilesIntegrityError(_PAGINATION_CONTINUED)
                return build_pull_request_data(metadata, changed_files)

            if next_reference is None:
                raise ChangedFilesIntegrityError(_PAGINATION_ENDED_EARLY)
            if not page:
                raise ChangedFilesIntegrityError(_PAGINATION_NO_PROGRESS)

            next_url, next_identity = self._validate_next_url(
                next_reference,
                current_url=current_url,
                files_path=files_path,
            )
            if next_identity in visited:
                raise ChangedFilesIntegrityError(_PAGINATION_LOOP)

            visited.add(next_identity)
            response = self._get(next_url)
            current_url = str(response.request.url)

    def _target_urls(
        self,
        target: PullRequestTarget,
    ) -> tuple[str, str, str]:
        owner = _encode_path_segment(target.owner)
        repository = _encode_path_segment(target.repository)
        resource_path = (
            f"{self._api_base_path}/repos/{owner}/{repository}/pulls/{target.pull_number}"
        )
        files_path = f"{resource_path}/files"
        metadata_url = urlunsplit(
            (
                self._api_scheme,
                self._api_authority,
                resource_path,
                "",
                "",
            )
        )
        files_url = urlunsplit(
            (
                self._api_scheme,
                self._api_authority,
                files_path,
                "",
                "",
            )
        )
        return metadata_url, files_url, files_path

    def _get(
        self,
        url: str,
        *,
        params: tuple[tuple[str, str], ...] | None = None,
    ) -> httpx.Response:
        request = self._http_client.build_request("GET", url, params=params)
        request.headers.pop("authorization", None)
        response = self._http_client.send(
            request,
            auth=None,
            follow_redirects=False,
        )
        response.raise_for_status()
        return response

    def _parse_changed_files_page(
        self,
        response: httpx.Response,
    ) -> list[ChangedFile]:
        payload = response.json()
        if type(payload) is not list:
            raise ChangedFilesIntegrityError(_INVALID_PAGE)

        page: list[ChangedFile] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise ChangedFilesIntegrityError(_INVALID_PAGE)
            try:
                page.append(parse_changed_file(item))
            except ValueError:
                raise ChangedFilesIntegrityError(_INVALID_PAGE) from None
        return page

    def _validate_next_url(
        self,
        reference: str,
        *,
        current_url: str,
        files_path: str,
    ) -> tuple[str, PageIdentity]:
        if (
            not reference
            or reference != reference.strip()
            or "#" in reference
            or any(_is_forbidden_url_character(character) for character in reference)
        ):
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)

        try:
            reference_parts = urlsplit(reference)
        except ValueError:
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL) from None

        if not reference_parts.scheme and reference_parts.netloc:
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)
        if _has_unsafe_path_syntax(reference_parts.path):
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)

        try:
            resolved = urljoin(current_url, reference)
            parsed = urlsplit(resolved)
            has_userinfo = parsed.username is not None or parsed.password is not None
        except ValueError:
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL) from None

        if (
            parsed.scheme != self._api_scheme
            or parsed.netloc != self._api_authority
            or has_userinfo
            or parsed.fragment
            or parsed.path != files_path
        ):
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)

        query = _validate_pagination_query(parsed.query)
        return resolved, (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            query,
        )


def _validate_api_base_url(api_base_url: str) -> tuple[str, str, str, str]:
    if type(api_base_url) is not str:
        raise ValueError(_INVALID_API_BASE_URL)

    normalized = api_base_url.rstrip("/")
    try:
        parsed = urlsplit(normalized)
        has_userinfo = parsed.username is not None or parsed.password is not None
    except ValueError:
        raise ValueError(_INVALID_API_BASE_URL) from None

    if (
        not normalized
        or not parsed.scheme
        or not parsed.netloc
        or has_userinfo
        or parsed.query
        or parsed.fragment
        or "?" in normalized
        or "#" in normalized
    ):
        raise ValueError(_INVALID_API_BASE_URL)

    return (
        normalized,
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
    )


def _encode_path_segment(value: str) -> str:
    encoded = quote(value, safe="")
    if encoded in {".", ".."}:
        return encoded.replace(".", "%2E")
    return encoded


def _next_reference(response: httpx.Response) -> str | None:
    raw_header = response.headers.get("link")
    try:
        links = response.links
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL) from None

    if not isinstance(links, Mapping):
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)
    try:
        next_link = links.get("next", _MISSING_LINK_METADATA)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL) from None

    if next_link is _MISSING_LINK_METADATA:
        if raw_header is not None and _NEXT_RELATION.search(raw_header):
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)
        return None
    if not isinstance(next_link, Mapping):
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)

    try:
        reference = next_link.get("url")
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL) from None
    if type(reference) is not str or not reference:
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)
    return reference


def _validate_pagination_query(
    query: str,
) -> tuple[tuple[str, str], ...]:
    parameters: dict[str, str] = {}
    if not query:
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)

    for field in query.split("&"):
        name, separator, value = field.partition("=")
        if (
            separator != "="
            or name not in _PAGINATION_PARAMETERS
            or name in parameters
            or _POSITIVE_ASCII_INTEGER.fullmatch(value) is None
            or int(value) <= 0
        ):
            raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)
        parameters[name] = value

    if "page" not in parameters:
        raise ChangedFilesIntegrityError(_INVALID_NEXT_URL)
    return tuple(sorted(parameters.items()))


def _page_identity(url: str) -> PageIdentity:
    parsed = urlsplit(url)
    return (
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        _validate_pagination_query(parsed.query),
    )


def _has_unsafe_path_syntax(path: str) -> bool:
    decoded_path = unquote(path)
    return "//" in path or any(segment in {".", ".."} for segment in decoded_path.split("/"))


def _is_forbidden_url_character(character: str) -> bool:
    return character.isspace() or ord(character) < 32 or ord(character) == 127
