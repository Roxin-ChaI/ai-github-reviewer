from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from re import escape

import pytest

from ai_github_reviewer.pull_request import (
    ChangedFile,
    PullRequestData,
    PullRequestMetadata,
    build_pull_request_data,
    parse_changed_file,
    parse_pull_request_metadata,
)


def _metadata(*, changed_files: int = 1) -> PullRequestMetadata:
    return PullRequestMetadata(
        title="Example change",
        body="Example body",
        state="open",
        author="example-author",
        base_branch="main",
        head_branch="feature/example",
        created_at="2026-07-01T10:00:00Z",
        updated_at="2026-07-02T11:00:00Z",
        changed_files=changed_files,
        additions=12,
        deletions=3,
        commits=2,
    )


def _changed_file(
    *,
    filename: str = "src/example.py",
    patch: str | None = "@@ -1 +1 @@\n-old\n+new",
) -> ChangedFile:
    return ChangedFile(
        filename=filename,
        status="modified",
        additions=4,
        deletions=2,
        changes=6,
        patch=patch,
    )


def _metadata_payload() -> dict[str, object]:
    return {
        "title": "Example change",
        "body": "Example body",
        "state": "open",
        "user": {"login": "example-author"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/example"},
        "created_at": "2026-07-01T10:00:00Z",
        "updated_at": "2026-07-02T11:00:00Z",
        "changed_files": 1,
        "additions": 12,
        "deletions": 3,
        "commits": 2,
    }


def _changed_file_payload() -> dict[str, object]:
    return {
        "filename": "src/example.py",
        "status": "modified",
        "additions": 4,
        "deletions": 2,
        "changes": 6,
        "patch": "@@ -1 +1 @@\n-old\n+new",
    }


def test_pull_request_metadata_stores_all_fields_and_compares_by_value() -> None:
    first = _metadata()
    second = _metadata()

    assert first == second
    assert first.title == "Example change"
    assert first.body == "Example body"
    assert first.state == "open"
    assert first.author == "example-author"
    assert first.base_branch == "main"
    assert first.head_branch == "feature/example"
    assert first.created_at == "2026-07-01T10:00:00Z"
    assert first.updated_at == "2026-07-02T11:00:00Z"
    assert first.changed_files == 1
    assert first.additions == 12
    assert first.deletions == 3
    assert first.commits == 2


@pytest.mark.parametrize("body", ["", "  body with spaces  ", None])
def test_pull_request_metadata_accepts_string_or_none_body(
    body: str | None,
) -> None:
    metadata = replace(_metadata(), body=body)

    assert metadata.body == body


def test_pull_request_metadata_is_frozen_and_slotted() -> None:
    metadata = _metadata()

    with pytest.raises(FrozenInstanceError):
        metadata.title = "replacement"

    assert not hasattr(metadata, "__dict__")


@pytest.mark.parametrize(
    "field_name",
    [
        "title",
        "state",
        "author",
        "base_branch",
        "head_branch",
        "created_at",
        "updated_at",
    ],
)
@pytest.mark.parametrize("invalid_value", [None, 1, True, 1.5, b"text"])
def test_pull_request_metadata_rejects_non_string_required_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^{escape(field_name)} must be a string$",
    ):
        replace(_metadata(), **{field_name: invalid_value})


@pytest.mark.parametrize("invalid_body", [1, True, 1.5, b"text", []])
def test_pull_request_metadata_rejects_invalid_body(invalid_body: object) -> None:
    with pytest.raises(
        ValueError,
        match=r"^body must be a string or None$",
    ):
        replace(_metadata(), body=invalid_body)


@pytest.mark.parametrize(
    "field_name",
    ["changed_files", "additions", "deletions", "commits"],
)
@pytest.mark.parametrize("valid_value", [0, 1, 99])
def test_pull_request_metadata_accepts_non_negative_integer_counts(
    field_name: str,
    valid_value: int,
) -> None:
    metadata = replace(_metadata(), **{field_name: valid_value})

    assert getattr(metadata, field_name) == valid_value


@pytest.mark.parametrize(
    "field_name",
    ["changed_files", "additions", "deletions", "commits"],
)
@pytest.mark.parametrize(
    "invalid_value",
    [-1, "1", 1.0, True, False, None],
)
def test_pull_request_metadata_rejects_invalid_counts(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^{escape(field_name)} must be a non-negative integer$",
    ):
        replace(_metadata(), **{field_name: invalid_value})


def test_pull_request_metadata_preserves_string_values_exactly() -> None:
    metadata = PullRequestMetadata(
        title="  title  ",
        body="  body  ",
        state=" OPEN ",
        author=" author ",
        base_branch=" base ",
        head_branch=" head ",
        created_at=" created ",
        updated_at=" updated ",
        changed_files=0,
        additions=0,
        deletions=0,
        commits=0,
    )

    assert metadata.title == "  title  "
    assert metadata.body == "  body  "
    assert metadata.state == " OPEN "
    assert metadata.author == " author "
    assert metadata.base_branch == " base "
    assert metadata.head_branch == " head "
    assert metadata.created_at == " created "
    assert metadata.updated_at == " updated "


def test_changed_file_stores_all_fields_and_compares_by_value() -> None:
    first = _changed_file()
    second = _changed_file()

    assert first == second
    assert first.filename == "src/example.py"
    assert first.status == "modified"
    assert first.additions == 4
    assert first.deletions == 2
    assert first.changes == 6
    assert first.patch == "@@ -1 +1 @@\n-old\n+new"


@pytest.mark.parametrize("patch", ["", "  patch  ", None])
def test_changed_file_accepts_string_or_none_patch(patch: str | None) -> None:
    changed_file = _changed_file(patch=patch)

    assert changed_file.patch == patch


def test_changed_file_defaults_missing_patch_to_none() -> None:
    changed_file = ChangedFile(
        filename="src/example.py",
        status="modified",
        additions=4,
        deletions=2,
        changes=6,
    )

    assert changed_file.patch is None


def test_changed_file_is_frozen_and_slotted() -> None:
    changed_file = _changed_file()

    with pytest.raises(FrozenInstanceError):
        changed_file.filename = "src/replacement.py"

    assert not hasattr(changed_file, "__dict__")


@pytest.mark.parametrize("field_name", ["filename", "status"])
@pytest.mark.parametrize("invalid_value", [None, 1, True, 1.5, b"text"])
def test_changed_file_rejects_non_string_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^{escape(field_name)} must be a string$",
    ):
        replace(_changed_file(), **{field_name: invalid_value})


@pytest.mark.parametrize("field_name", ["additions", "deletions", "changes"])
@pytest.mark.parametrize("valid_value", [0, 1, 99])
def test_changed_file_accepts_non_negative_integer_counts(
    field_name: str,
    valid_value: int,
) -> None:
    changed_file = replace(_changed_file(), **{field_name: valid_value})

    assert getattr(changed_file, field_name) == valid_value


@pytest.mark.parametrize("field_name", ["additions", "deletions", "changes"])
@pytest.mark.parametrize(
    "invalid_value",
    [-1, "1", 1.0, True, False, None],
)
def test_changed_file_rejects_invalid_counts(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^{escape(field_name)} must be a non-negative integer$",
    ):
        replace(_changed_file(), **{field_name: invalid_value})


@pytest.mark.parametrize("invalid_patch", [1, True, 1.5, b"text", []])
def test_changed_file_rejects_invalid_patch(invalid_patch: object) -> None:
    with pytest.raises(
        ValueError,
        match=r"^patch must be a string or None$",
    ):
        replace(_changed_file(), patch=invalid_patch)


def test_changed_file_preserves_string_values_exactly() -> None:
    changed_file = ChangedFile(
        filename="  src/example.py  ",
        status=" modified ",
        additions=0,
        deletions=0,
        changes=0,
        patch="  patch  ",
    )

    assert changed_file.filename == "  src/example.py  "
    assert changed_file.status == " modified "
    assert changed_file.patch == "  patch  "


def test_pull_request_data_accepts_matching_metadata_and_files() -> None:
    metadata = _metadata()
    changed_file = _changed_file()

    data = PullRequestData(metadata=metadata, changed_files=(changed_file,))

    assert data.metadata is metadata
    assert data.changed_files == (changed_file,)


def test_pull_request_data_accepts_zero_files_when_metadata_count_is_zero() -> None:
    data = PullRequestData(metadata=_metadata(changed_files=0), changed_files=())

    assert data.changed_files == ()


def test_pull_request_data_preserves_changed_file_order() -> None:
    first = _changed_file(filename="src/first.py")
    second = _changed_file(filename="src/second.py")

    data = PullRequestData(
        metadata=_metadata(changed_files=2),
        changed_files=(first, second),
    )

    assert data.changed_files == (first, second)


def test_pull_request_data_is_frozen_and_slotted() -> None:
    data = PullRequestData(
        metadata=_metadata(),
        changed_files=(_changed_file(),),
    )

    with pytest.raises(FrozenInstanceError):
        data.changed_files = ()

    assert not hasattr(data, "__dict__")


def test_pull_request_data_rejects_invalid_metadata() -> None:
    with pytest.raises(
        ValueError,
        match=r"^metadata must be PullRequestMetadata$",
    ):
        PullRequestData(metadata=object(), changed_files=())


def test_pull_request_data_requires_changed_files_tuple() -> None:
    with pytest.raises(
        ValueError,
        match=r"^changed_files must be a tuple of ChangedFile values$",
    ):
        PullRequestData(
            metadata=_metadata(),
            changed_files=[_changed_file()],
        )


@pytest.mark.parametrize("invalid_item", [object(), "src/example.py", None])
def test_pull_request_data_rejects_non_changed_file_tuple_items(
    invalid_item: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=r"^changed_files must be a tuple of ChangedFile values$",
    ):
        PullRequestData(
            metadata=_metadata(),
            changed_files=(invalid_item,),
        )


@pytest.mark.parametrize(
    ("metadata_count", "files"),
    [
        (1, ()),
        (0, (_changed_file(),)),
        (2, (_changed_file(),)),
    ],
)
def test_pull_request_data_rejects_changed_file_count_mismatch(
    metadata_count: int,
    files: tuple[ChangedFile, ...],
) -> None:
    with pytest.raises(
        ValueError,
        match=r"^changed file count does not match metadata$",
    ):
        PullRequestData(
            metadata=_metadata(changed_files=metadata_count),
            changed_files=files,
        )


def test_pull_request_data_rejects_duplicate_filenames() -> None:
    first = _changed_file(filename="src/duplicate.py")
    second = _changed_file(filename="src/duplicate.py")

    with pytest.raises(
        ValueError,
        match=r"^changed file filenames must be unique$",
    ):
        PullRequestData(
            metadata=_metadata(changed_files=2),
            changed_files=(first, second),
        )


def test_parse_pull_request_metadata_maps_complete_payload() -> None:
    metadata = parse_pull_request_metadata(_metadata_payload())

    assert metadata == _metadata()


@pytest.mark.parametrize(
    ("body_present", "body_value"),
    [
        (True, "Example body"),
        (True, ""),
        (True, None),
        (False, None),
    ],
)
def test_parse_pull_request_metadata_handles_optional_body(
    body_present: bool,
    body_value: str | None,
) -> None:
    payload = _metadata_payload()
    if body_present:
        payload["body"] = body_value
    else:
        del payload["body"]

    metadata = parse_pull_request_metadata(payload)

    assert metadata.body == body_value


@pytest.mark.parametrize(
    "field_name",
    [
        "title",
        "state",
        "user",
        "base",
        "head",
        "created_at",
        "updated_at",
        "changed_files",
        "additions",
        "deletions",
        "commits",
    ],
)
def test_parse_pull_request_metadata_rejects_missing_required_fields(
    field_name: str,
) -> None:
    payload = _metadata_payload()
    del payload[field_name]

    with pytest.raises(
        ValueError,
        match=r"^invalid pull request metadata payload$",
    ):
        parse_pull_request_metadata(payload)


@pytest.mark.parametrize("field_name", ["user", "base", "head"])
@pytest.mark.parametrize("invalid_value", [None, "mapping", 1, [], True])
def test_parse_pull_request_metadata_requires_nested_mappings(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _metadata_payload()
    payload[field_name] = invalid_value

    with pytest.raises(
        ValueError,
        match=r"^invalid pull request metadata payload$",
    ):
        parse_pull_request_metadata(payload)


@pytest.mark.parametrize(
    ("container_name", "nested_name"),
    [
        ("user", "login"),
        ("base", "ref"),
        ("head", "ref"),
    ],
)
def test_parse_pull_request_metadata_rejects_missing_nested_fields(
    container_name: str,
    nested_name: str,
) -> None:
    payload = _metadata_payload()
    nested = payload[container_name]
    assert isinstance(nested, dict)
    del nested[nested_name]

    with pytest.raises(
        ValueError,
        match=r"^invalid pull request metadata payload$",
    ):
        parse_pull_request_metadata(payload)


@pytest.mark.parametrize(
    ("container_name", "nested_name"),
    [
        ("user", "login"),
        ("base", "ref"),
        ("head", "ref"),
    ],
)
@pytest.mark.parametrize("invalid_value", [None, 1, True, 1.5])
def test_parse_pull_request_metadata_rejects_invalid_nested_values(
    container_name: str,
    nested_name: str,
    invalid_value: object,
) -> None:
    payload = _metadata_payload()
    nested = payload[container_name]
    assert isinstance(nested, dict)
    nested[nested_name] = invalid_value

    with pytest.raises(
        ValueError,
        match=r"^invalid pull request metadata payload$",
    ):
        parse_pull_request_metadata(payload)


@pytest.mark.parametrize(
    "field_name",
    ["title", "state", "created_at", "updated_at"],
)
@pytest.mark.parametrize("invalid_value", [None, 1, True, 1.5])
def test_parse_pull_request_metadata_rejects_invalid_top_level_strings(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _metadata_payload()
    payload[field_name] = invalid_value

    with pytest.raises(
        ValueError,
        match=r"^invalid pull request metadata payload$",
    ):
        parse_pull_request_metadata(payload)


@pytest.mark.parametrize(
    "field_name",
    ["changed_files", "additions", "deletions", "commits"],
)
@pytest.mark.parametrize("invalid_value", [-1, "1", 1.0, True, False, None])
def test_parse_pull_request_metadata_rejects_invalid_counts(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _metadata_payload()
    payload[field_name] = invalid_value

    with pytest.raises(
        ValueError,
        match=r"^invalid pull request metadata payload$",
    ):
        parse_pull_request_metadata(payload)


@pytest.mark.parametrize("payload", [None, [], "payload", 1, True])
def test_parse_pull_request_metadata_rejects_non_mapping_payload(
    payload: object,
) -> None:
    with pytest.raises(
        TypeError,
        match=r"^pull request metadata payload must be a mapping$",
    ):
        parse_pull_request_metadata(payload)


def test_parse_pull_request_metadata_does_not_mutate_payload() -> None:
    payload = _metadata_payload()
    original = deepcopy(payload)

    parse_pull_request_metadata(payload)

    assert payload == original
    assert payload["user"] is not original["user"]
    assert payload["base"] is not original["base"]
    assert payload["head"] is not original["head"]


def test_parse_changed_file_maps_complete_payload() -> None:
    changed_file = parse_changed_file(_changed_file_payload())

    assert changed_file == _changed_file()


@pytest.mark.parametrize(
    ("patch_present", "patch_value"),
    [
        (True, "@@ patch"),
        (True, ""),
        (True, None),
        (False, None),
    ],
)
def test_parse_changed_file_handles_optional_patch(
    patch_present: bool,
    patch_value: str | None,
) -> None:
    payload = _changed_file_payload()
    if patch_present:
        payload["patch"] = patch_value
    else:
        del payload["patch"]

    changed_file = parse_changed_file(payload)

    assert changed_file.patch == patch_value


@pytest.mark.parametrize(
    "field_name",
    ["filename", "status", "additions", "deletions", "changes"],
)
def test_parse_changed_file_rejects_missing_required_fields(
    field_name: str,
) -> None:
    payload = _changed_file_payload()
    del payload[field_name]

    with pytest.raises(ValueError, match=r"^invalid changed file payload$"):
        parse_changed_file(payload)


@pytest.mark.parametrize("field_name", ["filename", "status"])
@pytest.mark.parametrize("invalid_value", [None, 1, True, 1.5])
def test_parse_changed_file_rejects_invalid_string_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _changed_file_payload()
    payload[field_name] = invalid_value

    with pytest.raises(ValueError, match=r"^invalid changed file payload$"):
        parse_changed_file(payload)


@pytest.mark.parametrize("field_name", ["additions", "deletions", "changes"])
@pytest.mark.parametrize("invalid_value", [-1, "1", 1.0, True, False, None])
def test_parse_changed_file_rejects_invalid_counts(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _changed_file_payload()
    payload[field_name] = invalid_value

    with pytest.raises(ValueError, match=r"^invalid changed file payload$"):
        parse_changed_file(payload)


@pytest.mark.parametrize("invalid_patch", [1, True, 1.5, b"text", []])
def test_parse_changed_file_rejects_invalid_patch(
    invalid_patch: object,
) -> None:
    payload = _changed_file_payload()
    payload["patch"] = invalid_patch

    with pytest.raises(ValueError, match=r"^invalid changed file payload$"):
        parse_changed_file(payload)


@pytest.mark.parametrize("payload", [None, [], "payload", 1, True])
def test_parse_changed_file_rejects_non_mapping_payload(payload: object) -> None:
    with pytest.raises(
        TypeError,
        match=r"^changed file payload must be a mapping$",
    ):
        parse_changed_file(payload)


def test_parse_changed_file_does_not_mutate_payload() -> None:
    payload = _changed_file_payload()
    original = deepcopy(payload)

    parse_changed_file(payload)

    assert payload == original


@pytest.mark.parametrize("container_type", [tuple, list])
def test_build_pull_request_data_accepts_tuple_or_list(
    container_type: type[tuple] | type[list],
) -> None:
    first = _changed_file(filename="src/first.py")
    second = _changed_file(filename="src/second.py")
    changed_files = container_type((first, second))

    data = build_pull_request_data(
        _metadata(changed_files=2),
        changed_files,
    )

    assert data.changed_files == (first, second)


def test_build_pull_request_data_accepts_generator_and_iterates_once() -> None:
    first = _changed_file(filename="src/first.py")
    second = _changed_file(filename="src/second.py")
    iterations = 0

    def changed_file_generator():
        nonlocal iterations
        iterations += 1
        if iterations > 1:
            raise AssertionError("generator was iterated more than once")
        yield first
        yield second

    data = build_pull_request_data(
        _metadata(changed_files=2),
        changed_file_generator(),
    )

    assert data.changed_files == (first, second)
    assert iterations == 1


def test_build_pull_request_data_copies_list_and_preserves_order() -> None:
    first = _changed_file(filename="src/first.py")
    second = _changed_file(filename="src/second.py")
    source = [first, second]

    data = build_pull_request_data(_metadata(changed_files=2), source)
    source.reverse()
    source.append(_changed_file(filename="src/third.py"))

    assert data.changed_files == (first, second)


def test_build_pull_request_data_does_not_mutate_source_list() -> None:
    first = _changed_file(filename="src/first.py")
    second = _changed_file(filename="src/second.py")
    source = [first, second]
    original = list(source)

    build_pull_request_data(_metadata(changed_files=2), source)

    assert source == original


def test_build_pull_request_data_rejects_count_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match=r"^changed file count does not match metadata$",
    ):
        build_pull_request_data(_metadata(changed_files=2), [_changed_file()])


def test_build_pull_request_data_rejects_duplicate_filenames() -> None:
    files = [
        _changed_file(filename="src/duplicate.py"),
        _changed_file(filename="src/duplicate.py"),
    ]

    with pytest.raises(
        ValueError,
        match=r"^changed file filenames must be unique$",
    ):
        build_pull_request_data(_metadata(changed_files=2), files)


def test_build_pull_request_data_rejects_non_changed_file_item() -> None:
    with pytest.raises(
        ValueError,
        match=r"^changed_files must be a tuple of ChangedFile values$",
    ):
        build_pull_request_data(_metadata(), [object()])
