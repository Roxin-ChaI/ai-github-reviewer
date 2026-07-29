from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

_MISSING: Final = object()
_INVALID_METADATA_PAYLOAD: Final = "invalid pull request metadata payload"
_INVALID_CHANGED_FILE_PAYLOAD: Final = "invalid changed file payload"


@dataclass(frozen=True, slots=True)
class PullRequestTarget:
    owner: str
    repository: str
    pull_number: int

    def __post_init__(self) -> None:
        if type(self.owner) is not str or not self.owner.strip():
            raise ValueError("owner must be a non-empty string")
        if type(self.repository) is not str or not self.repository.strip():
            raise ValueError("repository must be a non-empty string")
        if type(self.pull_number) is not int or self.pull_number <= 0:
            raise ValueError("pull_number must be a positive integer")


@dataclass(frozen=True, slots=True)
class PullRequestMetadata:
    title: str
    body: str | None
    state: str
    author: str
    base_branch: str
    head_branch: str
    created_at: str
    updated_at: str
    changed_files: int
    additions: int
    deletions: int
    commits: int

    def __post_init__(self) -> None:
        string_values = (
            ("title", self.title),
            ("state", self.state),
            ("author", self.author),
            ("base_branch", self.base_branch),
            ("head_branch", self.head_branch),
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        )
        for field_name, value in string_values:
            if type(value) is not str:
                raise ValueError(f"{field_name} must be a string")

        if self.body is not None and type(self.body) is not str:
            raise ValueError("body must be a string or None")

        count_values = (
            ("changed_files", self.changed_files),
            ("additions", self.additions),
            ("deletions", self.deletions),
            ("commits", self.commits),
        )
        for field_name, value in count_values:
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ChangedFile:
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str | None = None

    def __post_init__(self) -> None:
        string_values = (
            ("filename", self.filename),
            ("status", self.status),
        )
        for field_name, value in string_values:
            if type(value) is not str:
                raise ValueError(f"{field_name} must be a string")

        count_values = (
            ("additions", self.additions),
            ("deletions", self.deletions),
            ("changes", self.changes),
        )
        for field_name, value in count_values:
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

        if self.patch is not None and type(self.patch) is not str:
            raise ValueError("patch must be a string or None")


@dataclass(frozen=True, slots=True)
class PullRequestData:
    metadata: PullRequestMetadata
    changed_files: tuple[ChangedFile, ...]

    def __post_init__(self) -> None:
        if type(self.metadata) is not PullRequestMetadata:
            raise ValueError("metadata must be PullRequestMetadata")
        if type(self.changed_files) is not tuple or any(
            type(changed_file) is not ChangedFile for changed_file in self.changed_files
        ):
            raise ValueError("changed_files must be a tuple of ChangedFile values")
        if len(self.changed_files) != self.metadata.changed_files:
            raise ValueError("changed file count does not match metadata")

        filenames = tuple(changed_file.filename for changed_file in self.changed_files)
        if len(set(filenames)) != len(filenames):
            raise ValueError("changed file filenames must be unique")


def parse_pull_request_metadata(
    payload: Mapping[str, object],
) -> PullRequestMetadata:
    if not isinstance(payload, Mapping):
        raise TypeError("pull request metadata payload must be a mapping")

    user = payload.get("user", _MISSING)
    base = payload.get("base", _MISSING)
    head = payload.get("head", _MISSING)
    if not all(isinstance(value, Mapping) for value in (user, base, head)):
        raise ValueError(_INVALID_METADATA_PAYLOAD)

    values = (
        payload.get("title", _MISSING),
        payload.get("state", _MISSING),
        user.get("login", _MISSING),
        base.get("ref", _MISSING),
        head.get("ref", _MISSING),
        payload.get("created_at", _MISSING),
        payload.get("updated_at", _MISSING),
        payload.get("changed_files", _MISSING),
        payload.get("additions", _MISSING),
        payload.get("deletions", _MISSING),
        payload.get("commits", _MISSING),
    )
    if any(value is _MISSING for value in values):
        raise ValueError(_INVALID_METADATA_PAYLOAD)

    (
        title,
        state,
        author,
        base_branch,
        head_branch,
        created_at,
        updated_at,
        changed_files,
        additions,
        deletions,
        commits,
    ) = values
    try:
        return PullRequestMetadata(
            title=title,
            body=payload.get("body"),
            state=state,
            author=author,
            base_branch=base_branch,
            head_branch=head_branch,
            created_at=created_at,
            updated_at=updated_at,
            changed_files=changed_files,
            additions=additions,
            deletions=deletions,
            commits=commits,
        )
    except ValueError:
        raise ValueError(_INVALID_METADATA_PAYLOAD) from None


def parse_changed_file(payload: Mapping[str, object]) -> ChangedFile:
    if not isinstance(payload, Mapping):
        raise TypeError("changed file payload must be a mapping")

    values = (
        payload.get("filename", _MISSING),
        payload.get("status", _MISSING),
        payload.get("additions", _MISSING),
        payload.get("deletions", _MISSING),
        payload.get("changes", _MISSING),
    )
    if any(value is _MISSING for value in values):
        raise ValueError(_INVALID_CHANGED_FILE_PAYLOAD)

    filename, status, additions, deletions, changes = values
    try:
        return ChangedFile(
            filename=filename,
            status=status,
            additions=additions,
            deletions=deletions,
            changes=changes,
            patch=payload.get("patch"),
        )
    except ValueError:
        raise ValueError(_INVALID_CHANGED_FILE_PAYLOAD) from None


def build_pull_request_data(
    metadata: PullRequestMetadata,
    changed_files: Iterable[ChangedFile],
) -> PullRequestData:
    return PullRequestData(
        metadata=metadata,
        changed_files=tuple(changed_files),
    )
