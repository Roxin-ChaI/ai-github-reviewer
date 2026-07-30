import builtins
import logging
import os
import socket
from copy import deepcopy

import openai
import pytest

from ai_github_reviewer.review_validation import (
    ALLOWED_FINAL_ASSESSMENTS,
    ALLOWED_SEVERITIES,
    FINDING_LABELS,
    NO_ACTIONABLE_ISSUES,
    REQUIRED_HEADINGS,
    ReviewValidationError,
    validate_review,
)

FILENAME = "src/example.py"
CANDIDATE_ERROR = "candidate review must be a non-empty string"
FILENAMES_ERROR = "changed filenames must contain only non-empty strings"
HEADINGS_ERROR = "invalid review headings"
SECTION_ERROR = "required review section must not be empty"
FINDING_HEADINGS_ERROR = "invalid finding headings"
FINDING_FIELDS_ERROR = "invalid finding fields"
SEVERITY_ERROR = "invalid finding severity"
FILE_ERROR = "finding file does not match changed file"
NO_FINDINGS_ERROR = "invalid no-findings section"
ASSESSMENT_ERROR = "invalid final assessment"


def _finding(
    number: int = 1,
    *,
    severity: str = "High",
    filename: str = FILENAME,
    location: str = "line 10",
    issue: str = "A controlled issue exists.",
    evidence: str = "The changed line demonstrates the issue.",
    recommendation: str = "Handle the controlled case explicitly.",
) -> str:
    return "\n".join(
        [
            f"### Finding {number}",
            "",
            f"- Severity: {severity}",
            f"- File: {filename}",
            f"- Location: {location}",
            f"- Issue: {issue}",
            f"- Evidence: {evidence}",
            f"- Recommendation: {recommendation}",
        ]
    )


def _review(
    *,
    findings: str | None = None,
    summary: str = "Controlled summary.",
    test_gaps: str = "Controlled test gap.",
    maintainability: str = "Controlled maintainability note.",
    assessment: str = "Request changes",
) -> str:
    if findings is None:
        findings = _finding()
    return (
        "# Pull Request Review\n\n"
        f"## Summary\n\n{summary}\n\n"
        f"## Findings\n\n{findings}\n\n"
        f"## Test Gaps\n\n{test_gaps}\n\n"
        f"## Maintainability\n\n{maintainability}\n\n"
        f"## Final Assessment\n\n{assessment}\n"
    )


def _no_findings_review(
    *,
    assessment: str = "Approve",
    findings: str = NO_ACTIONABLE_ISSUES,
) -> str:
    return _review(findings=findings, assessment=assessment)


def _assert_error(
    message: str,
    candidate: object,
    changed_filenames: object = (FILENAME,),
) -> ReviewValidationError:
    with pytest.raises(ReviewValidationError, match=rf"^{message}$") as exc_info:
        validate_review(candidate, changed_filenames)
    return exc_info.value


def test_public_constants_are_exact_and_immutable() -> None:
    assert REQUIRED_HEADINGS == (
        "# Pull Request Review",
        "## Summary",
        "## Findings",
        "## Test Gaps",
        "## Maintainability",
        "## Final Assessment",
    )
    assert FINDING_LABELS == (
        "Severity",
        "File",
        "Location",
        "Issue",
        "Evidence",
        "Recommendation",
    )
    assert ALLOWED_SEVERITIES == ("Critical", "High", "Medium", "Low")
    assert NO_ACTIONABLE_ISSUES == (
        "No actionable issues identified from the available pull request data."
    )
    assert ALLOWED_FINAL_ASSESSMENTS == (
        "Approve",
        "Approve with minor comments",
        "Request changes",
        "Insufficient data",
    )
    for value in (
        REQUIRED_HEADINGS,
        FINDING_LABELS,
        ALLOWED_SEVERITIES,
        ALLOWED_FINAL_ASSESSMENTS,
    ):
        assert isinstance(value, tuple)


def test_validation_error_inherits_value_error() -> None:
    assert issubclass(ReviewValidationError, ValueError)


@pytest.mark.parametrize("finding_count", [1, 2, 3])
def test_accepts_one_or_more_consecutively_numbered_findings(
    finding_count: int,
) -> None:
    findings = "\n\n".join(_finding(number) for number in range(1, finding_count + 1))
    candidate = _review(findings=findings)

    returned = validate_review(candidate, [FILENAME])

    assert returned is candidate
    assert returned == candidate


@pytest.mark.parametrize("severity", ALLOWED_SEVERITIES)
def test_accepts_each_allowed_severity(severity: str) -> None:
    candidate = _review(findings=_finding(severity=severity))

    assert validate_review(candidate, [FILENAME]) is candidate


@pytest.mark.parametrize("assessment", ALLOWED_FINAL_ASSESSMENTS)
def test_accepts_each_allowed_final_assessment(assessment: str) -> None:
    candidate = _review(assessment=assessment)

    assert validate_review(candidate, [FILENAME]) is candidate


@pytest.mark.parametrize(
    "location",
    ["line 10", "file-level", "Unknown"],
)
def test_accepts_supported_location_text_without_semantic_validation(
    location: str,
) -> None:
    candidate = _review(findings=_finding(location=location))

    assert validate_review(candidate, [FILENAME]) is candidate


@pytest.mark.parametrize(
    "filename",
    [
        "src/example.py",
        "tests/example test.py",
        "源代码/示例.py",
        "src/a,b [controlled].py",
    ],
)
def test_accepts_exact_changed_filename_including_special_text(
    filename: str,
) -> None:
    candidate = _review(findings=_finding(filename=filename))

    assert validate_review(candidate, ["other.py", filename]) is candidate


def test_accepts_no_findings_with_empty_or_nonempty_filename_collection() -> None:
    candidate = _no_findings_review()

    assert validate_review(candidate, []) is candidate
    assert validate_review(candidate, [FILENAME]) is candidate


def test_accepts_lf_and_semantically_equivalent_crlf_without_modification() -> None:
    lf_candidate = _review()
    crlf_candidate = lf_candidate.replace("\n", "\r\n")

    assert validate_review(lf_candidate, [FILENAME]) is lf_candidate
    assert validate_review(crlf_candidate, [FILENAME]) is crlf_candidate
    assert "\r\n" in crlf_candidate


def test_accepts_and_preserves_surrounding_blank_lines() -> None:
    candidate = "\n\n" + _review() + "\n\n"

    returned = validate_review(candidate, [FILENAME])

    assert returned is candidate
    assert returned.startswith("\n\n")
    assert returned.endswith("\n\n\n")


@pytest.mark.parametrize("invalid_candidate", [None, 1, True, b"review", [], {}])
def test_rejects_non_string_candidate(invalid_candidate: object) -> None:
    _assert_error(CANDIDATE_ERROR, invalid_candidate)


@pytest.mark.parametrize("invalid_candidate", ["", " ", "\t", "\r\n"])
def test_rejects_empty_or_whitespace_candidate(invalid_candidate: str) -> None:
    _assert_error(CANDIDATE_ERROR, invalid_candidate)


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_rejects_each_missing_required_heading(heading: str) -> None:
    candidate = _review().replace(f"{heading}\n", "", 1)

    _assert_error(HEADINGS_ERROR, candidate)


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_rejects_each_duplicate_required_heading(heading: str) -> None:
    candidate = _review() + f"\n{heading}\n"

    _assert_error(HEADINGS_ERROR, candidate)


@pytest.mark.parametrize("first_index", range(len(REQUIRED_HEADINGS) - 1))
def test_rejects_swapped_adjacent_required_headings(first_index: int) -> None:
    first = REQUIRED_HEADINGS[first_index]
    second = REQUIRED_HEADINGS[first_index + 1]
    candidate = (
        _review()
        .replace(first, "__FIRST__", 1)
        .replace(
            second,
            first,
            1,
        )
    )
    candidate = candidate.replace("__FIRST__", second, 1)

    _assert_error(HEADINGS_ERROR, candidate)


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("# Pull Request Review", "# pull request review"),
        ("# Pull Request Review", "## Pull Request Review"),
        ("# Pull Request Review", " # Pull Request Review"),
        ("# Pull Request Review", "# Pull Request Review "),
        ("## Summary", "## summary"),
        ("## Summary", "### Summary"),
        ("## Summary", " ## Summary"),
        ("## Summary", "## Summary "),
    ],
)
def test_rejects_required_heading_case_level_or_spacing_change(
    original: str,
    replacement: str,
) -> None:
    _assert_error(HEADINGS_ERROR, _review().replace(original, replacement, 1))


def test_rejects_nonblank_text_before_title_but_accepts_blank_lines() -> None:
    _assert_error(HEADINGS_ERROR, "Preamble\n" + _review())
    candidate = "\n \n" + _review()

    assert validate_review(candidate, [FILENAME]) is candidate


def test_body_sentence_containing_heading_text_is_not_a_heading() -> None:
    candidate = _review(summary="This sentence mentions ## Findings as plain text.")

    assert validate_review(candidate, [FILENAME]) is candidate


@pytest.mark.parametrize("extra_heading", ["# Extra", "## Extra", "### Extra"])
def test_rejects_extra_h1_h2_or_h3_heading(extra_heading: str) -> None:
    candidate = _review(summary=f"Controlled summary.\n\n{extra_heading}\n\nMore text.")

    _assert_error(HEADINGS_ERROR, candidate)


@pytest.mark.parametrize(
    ("section_name", "replacement"),
    [
        ("Controlled summary.", ""),
        ("Controlled summary.", " \t"),
        ("Controlled test gap.", ""),
        ("Controlled test gap.", " \t"),
        ("Controlled maintainability note.", ""),
        ("Controlled maintainability note.", " \t"),
    ],
)
def test_rejects_empty_required_body_section(
    section_name: str,
    replacement: str,
) -> None:
    candidate = _review().replace(section_name, replacement, 1)

    _assert_error(SECTION_ERROR, candidate)


@pytest.mark.parametrize(
    "invalid_heading",
    [
        "### Finding 0",
        "### Finding 2",
        "### Finding -1",
        "### Finding +1",
        "### Finding 1.0",
        "### Finding １",
        "### Finding one",
        "### Finding 01",
        "### finding 1",
        "###Finding 1",
        "### Finding 1 extra",
        " ### Finding 1",
        "### Other 1",
    ],
)
def test_rejects_invalid_first_finding_heading(invalid_heading: str) -> None:
    candidate = _review(findings=_finding().replace("### Finding 1", invalid_heading, 1))

    _assert_error(FINDING_HEADINGS_ERROR, candidate)


@pytest.mark.parametrize(
    "invalid_heading",
    [
        "#### Finding 1",
        "##### Finding 1",
        "###### Finding 1",
        "####Finding 1",
        "#### finding 1",
        " #### Finding 1",
        "\t#### Finding 1",
    ],
)
def test_rejects_malformed_deep_finding_heading(
    invalid_heading: str,
) -> None:
    candidate = _review(findings=invalid_heading)

    _assert_error(FINDING_HEADINGS_ERROR, candidate)


def test_rejects_canonical_and_malformed_deep_finding_headings_together() -> None:
    findings = f"{_finding()}\n\n#### Finding 2\n\nControlled malformed content."
    candidate = _review(findings=findings)

    _assert_error(FINDING_HEADINGS_ERROR, candidate)


def test_deep_finding_heading_text_outside_findings_is_not_misclassified() -> None:
    sentence = "This sentence mentions #### Finding 1 as text."
    candidate = _no_findings_review().replace(
        "Controlled summary.",
        sentence,
        1,
    )
    candidate = candidate.replace(
        "Controlled test gap.",
        sentence,
        1,
    )
    candidate = candidate.replace(
        "Controlled maintainability note.",
        sentence,
        1,
    )

    assert validate_review(candidate, []) is candidate


def test_no_findings_remains_valid_after_deep_heading_detection() -> None:
    candidate = _no_findings_review()

    assert validate_review(candidate, []) is candidate


@pytest.mark.parametrize(
    "numbers",
    [
        (1, 3),
        (1, 1),
        (2, 1),
        (1, 2, 4),
        (1, 3, 2),
    ],
)
def test_rejects_skipped_repeated_or_reversed_finding_numbers(
    numbers: tuple[int, ...],
) -> None:
    candidate = _review(
        findings="\n\n".join(_finding(number) for number in numbers),
    )

    _assert_error(FINDING_HEADINGS_ERROR, candidate)


def test_rejects_finding_and_no_issues_sentence_together() -> None:
    candidate = _review(findings=f"{NO_ACTIONABLE_ISSUES}\n\n{_finding()}")

    _assert_error(FINDING_HEADINGS_ERROR, candidate)


@pytest.mark.parametrize("label", FINDING_LABELS)
def test_rejects_each_missing_finding_field(label: str) -> None:
    malformed = "\n".join(
        item for item in _finding().splitlines() if not item.startswith(f"- {label}:")
    )
    candidate = _review(findings=malformed)

    _assert_error(FINDING_FIELDS_ERROR, candidate)


@pytest.mark.parametrize("label", FINDING_LABELS)
def test_rejects_each_duplicate_finding_field(label: str) -> None:
    line = next(item for item in _finding().splitlines() if item.startswith(f"- {label}:"))
    candidate = _review(findings=_finding().replace(line, f"{line}\n{line}", 1))

    _assert_error(FINDING_FIELDS_ERROR, candidate)


@pytest.mark.parametrize("first_index", range(len(FINDING_LABELS) - 1))
def test_rejects_swapped_adjacent_finding_fields(first_index: int) -> None:
    lines = _finding().splitlines()
    field_start = 2
    first_position = field_start + first_index
    second_position = first_position + 1
    lines[first_position], lines[second_position] = (
        lines[second_position],
        lines[first_position],
    )

    _assert_error(FINDING_FIELDS_ERROR, _review(findings="\n".join(lines)))


@pytest.mark.parametrize("label", FINDING_LABELS)
@pytest.mark.parametrize(
    "transform",
    [
        lambda line: line.replace("- ", "* ", 1),
        lambda line: line[2:],
        lambda line: " " + line,
        lambda line: line.replace(": ", ":", 1),
        lambda line: line.replace(":", " :", 1),
        lambda line: line.replace(line.split(":", 1)[0], line.split(":", 1)[0].lower()),
    ],
)
def test_rejects_malformed_finding_field_prefix(
    label: str,
    transform,
) -> None:
    finding = _finding()
    line = next(item for item in finding.splitlines() if item.startswith(f"- {label}:"))
    malformed = finding.replace(line, transform(line), 1)

    _assert_error(FINDING_FIELDS_ERROR, _review(findings=malformed))


@pytest.mark.parametrize(
    ("label", "message"),
    [
        ("Severity", SEVERITY_ERROR),
        ("File", FILE_ERROR),
        ("Location", FINDING_FIELDS_ERROR),
        ("Issue", FINDING_FIELDS_ERROR),
        ("Evidence", FINDING_FIELDS_ERROR),
        ("Recommendation", FINDING_FIELDS_ERROR),
    ],
)
@pytest.mark.parametrize("value", ["", "   "])
def test_rejects_empty_or_whitespace_finding_value(
    label: str,
    message: str,
    value: str,
) -> None:
    finding = _finding()
    line = next(item for item in finding.splitlines() if item.startswith(f"- {label}:"))
    malformed = finding.replace(line, f"- {label}: {value}", 1)

    _assert_error(message, _review(findings=malformed))


def test_rejects_multiline_field_extra_text_and_combined_fields() -> None:
    base = _finding()
    multiline = base.replace(
        "- Issue: A controlled issue exists.",
        "- Issue: A controlled issue exists.\ncontinued value",
    )
    extra = base + "\nUnexpected text."
    combined = base.replace(
        "- Issue: A controlled issue exists.\n- Evidence: The changed line demonstrates the issue.",
        "- Issue: A controlled issue exists. - Evidence: controlled",
    )

    for malformed in (multiline, extra, combined):
        _assert_error(FINDING_FIELDS_ERROR, _review(findings=malformed))


def test_requires_blank_line_between_finding_heading_and_fields() -> None:
    malformed = _finding().replace("### Finding 1\n\n", "### Finding 1\n", 1)

    _assert_error(FINDING_FIELDS_ERROR, _review(findings=malformed))


def test_allows_blank_lines_between_fields_and_after_finding() -> None:
    finding = _finding().replace("\n- File:", "\n\n- File:")
    candidate = _review(findings=finding + "\n\n")

    assert validate_review(candidate, [FILENAME]) is candidate


@pytest.mark.parametrize(
    "severity",
    ["critical", "HIGH", "Info", "Warning", "Blocker", " High", "High "],
)
def test_rejects_invalid_finding_severity(severity: str) -> None:
    candidate = _review(findings=_finding(severity=severity))

    _assert_error(SEVERITY_ERROR, candidate)


@pytest.mark.parametrize(
    "filename",
    [
        "SRC/example.py",
        " src/example.py",
        "src/example.py ",
        "example.py",
        "src",
        "src/fabricated.py",
        "other/example.py",
        "src/example.py,tests/example.py",
        "src/example.py tests/example.py",
        "https://github.com/owner/repository/blob/main/src/example.py",
        "prefix/src/example.py",
        "src/example.py/suffix",
        r"src\example.py",
    ],
)
def test_rejects_non_exact_finding_filename(filename: str) -> None:
    candidate = _review(findings=_finding(filename=filename))

    _assert_error(FILE_ERROR, candidate, [FILENAME, "tests/example.py"])


def test_rejects_finding_when_changed_filename_collection_is_empty() -> None:
    _assert_error(FILE_ERROR, _review(), [])


def test_file_comparison_does_not_trim_casefold_or_normalize_path() -> None:
    exact_filename = " Src\\Example File.py "
    candidate = _review(findings=_finding(filename=exact_filename))

    assert validate_review(candidate, [exact_filename]) is candidate


@pytest.mark.parametrize(
    "invalid_findings",
    [
        "",
        " ",
        NO_ACTIONABLE_ISSUES.removesuffix("."),
        NO_ACTIONABLE_ISSUES.lower(),
        f"- {NO_ACTIONABLE_ISSUES}",
        f"**{NO_ACTIONABLE_ISSUES}**",
        f"Explanation.\n{NO_ACTIONABLE_ISSUES}",
        f"{NO_ACTIONABLE_ISSUES}\nExplanation.",
        f"{NO_ACTIONABLE_ISSUES} Second sentence.",
        f"{NO_ACTIONABLE_ISSUES}\n- Severity: High",
    ],
)
def test_rejects_invalid_no_findings_section(invalid_findings: str) -> None:
    _assert_error(
        NO_FINDINGS_ERROR,
        _no_findings_review(findings=invalid_findings),
    )


def test_finding_heading_without_fields_uses_field_error() -> None:
    _assert_error(
        FINDING_FIELDS_ERROR,
        _no_findings_review(findings="### Finding 1"),
    )


def test_no_issues_with_finding_heading_uses_heading_error() -> None:
    candidate = _no_findings_review(findings=f"{NO_ACTIONABLE_ISSUES}\n\n{_finding()}")

    _assert_error(FINDING_HEADINGS_ERROR, candidate)


@pytest.mark.parametrize(
    "assessment",
    [
        "",
        " ",
        "Reject",
        "approve",
        "- Approve",
        "Approve.",
        "Assessment: Approve",
        "Approve because this is safe.",
        "Approve\nRequest changes",
        "Approve Request changes",
        "**Approve**",
        "Approve\nSubmitted to GitHub.",
    ],
)
def test_rejects_invalid_final_assessment(assessment: str) -> None:
    _assert_error(ASSESSMENT_ERROR, _review(assessment=assessment))


def test_allows_surrounding_blank_lines_in_final_assessment() -> None:
    candidate = _review(assessment="\n\nApprove\n\n")

    assert validate_review(candidate, [FILENAME]) is candidate


@pytest.mark.parametrize(
    "collection_factory",
    [
        lambda: [FILENAME],
        lambda: (FILENAME,),
        lambda: {FILENAME},
        lambda: frozenset({FILENAME}),
        lambda: (filename for filename in [FILENAME]),
    ],
)
def test_accepts_supported_changed_filename_iterables(collection_factory) -> None:
    candidate = _review()

    assert validate_review(candidate, collection_factory()) is candidate


def test_changed_filename_generator_is_iterated_once() -> None:
    iterations = 0

    def filenames():
        nonlocal iterations
        iterations += 1
        if iterations > 1:
            raise AssertionError("generator iterated more than once")
        yield FILENAME

    assert validate_review(_review(), filenames())
    assert iterations == 1


def test_changed_filename_collections_are_not_modified() -> None:
    filename_list = [FILENAME, "tests/example.py"]
    filename_set = {FILENAME, "tests/example.py"}
    list_before = deepcopy(filename_list)
    set_before = deepcopy(filename_set)

    validate_review(_review(), filename_list)
    validate_review(_review(), filename_set)

    assert filename_list == list_before
    assert filename_set == set_before


@pytest.mark.parametrize(
    "invalid_collection",
    ["src/example.py", b"src/example.py", None, 1, True, object()],
)
def test_rejects_invalid_changed_filename_collection(
    invalid_collection: object,
) -> None:
    _assert_error(FILENAMES_ERROR, _review(), invalid_collection)


@pytest.mark.parametrize(
    "invalid_filename",
    ["", " ", "\t", None, 1, True, b"src/example.py"],
)
def test_rejects_invalid_changed_filename_element(
    invalid_filename: object,
) -> None:
    _assert_error(FILENAMES_ERROR, _review(), [FILENAME, invalid_filename])


def test_failure_text_contains_neither_candidate_collection_nor_secret() -> None:
    secret = "controlled-review-secret"
    candidate = f"{secret} invalid candidate"
    filenames = [f"{secret}/file.py"]

    error = _assert_error(HEADINGS_ERROR, candidate, filenames)

    assert candidate not in str(error)
    assert repr(filenames) not in str(error)
    assert secret not in str(error)


def test_validation_has_no_external_or_output_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("unexpected external side effect")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(os, "getenv", fail)
    monkeypatch.setattr(openai, "OpenAI", fail)
    monkeypatch.setattr(builtins, "open", fail)

    with caplog.at_level(logging.DEBUG):
        candidate = _review()
        assert validate_review(candidate, [FILENAME]) is candidate

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert caplog.records == []
