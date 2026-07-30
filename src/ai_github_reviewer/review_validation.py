import re
from collections.abc import Iterable
from typing import Final

REQUIRED_HEADINGS: Final = (
    "# Pull Request Review",
    "## Summary",
    "## Findings",
    "## Test Gaps",
    "## Maintainability",
    "## Final Assessment",
)
FINDING_LABELS: Final = (
    "Severity",
    "File",
    "Location",
    "Issue",
    "Evidence",
    "Recommendation",
)
ALLOWED_SEVERITIES: Final = (
    "Critical",
    "High",
    "Medium",
    "Low",
)
NO_ACTIONABLE_ISSUES: Final = (
    "No actionable issues identified from the available pull request data."
)
ALLOWED_FINAL_ASSESSMENTS: Final = (
    "Approve",
    "Approve with minor comments",
    "Request changes",
    "Insufficient data",
)

_CANDIDATE_ERROR: Final = "candidate review must be a non-empty string"
_FILENAMES_ERROR: Final = "changed filenames must contain only non-empty strings"
_HEADINGS_ERROR: Final = "invalid review headings"
_SECTION_ERROR: Final = "required review section must not be empty"
_FINDING_HEADINGS_ERROR: Final = "invalid finding headings"
_FINDING_FIELDS_ERROR: Final = "invalid finding fields"
_SEVERITY_ERROR: Final = "invalid finding severity"
_FILE_ERROR: Final = "finding file does not match changed file"
_NO_FINDINGS_ERROR: Final = "invalid no-findings section"
_ASSESSMENT_ERROR: Final = "invalid final assessment"
_FINDING_HEADING_PATTERN: Final = re.compile(
    r"### Finding ([1-9][0-9]*)",
    flags=re.ASCII,
)
_MALFORMED_DEEP_FINDING_HEADING_PATTERN: Final = re.compile(
    r"[ \t]*#{4,}[ \t]*finding.*",
    flags=re.ASCII | re.IGNORECASE,
)


class ReviewValidationError(ValueError):
    pass


def validate_review(
    candidate: str,
    changed_filenames: Iterable[str],
) -> str:
    if type(candidate) is not str or not candidate.strip():
        raise ReviewValidationError(_CANDIDATE_ERROR)

    filenames = _collect_changed_filenames(changed_filenames)
    lines = candidate.splitlines()
    heading_positions = _required_heading_positions(lines)
    _validate_heading_lines(lines, heading_positions)

    (
        _,
        summary_position,
        findings_position,
        test_gaps_position,
        maintainability_position,
        final_position,
    ) = heading_positions
    summary_lines = lines[summary_position + 1 : findings_position]
    findings_lines = lines[findings_position + 1 : test_gaps_position]
    test_gaps_lines = lines[test_gaps_position + 1 : maintainability_position]
    maintainability_lines = lines[maintainability_position + 1 : final_position]
    final_assessment_lines = lines[final_position + 1 :]

    for section_lines in (
        summary_lines,
        test_gaps_lines,
        maintainability_lines,
    ):
        if not "\n".join(section_lines).strip():
            raise ReviewValidationError(_SECTION_ERROR)

    _validate_findings(findings_lines, filenames)
    _validate_final_assessment(final_assessment_lines)
    return candidate


def _collect_changed_filenames(
    changed_filenames: Iterable[str],
) -> frozenset[str]:
    if isinstance(changed_filenames, (str, bytes)) or not isinstance(
        changed_filenames,
        Iterable,
    ):
        raise ReviewValidationError(_FILENAMES_ERROR)

    collected: list[str] = []
    for filename in changed_filenames:
        if type(filename) is not str or not filename.strip():
            raise ReviewValidationError(_FILENAMES_ERROR)
        collected.append(filename)
    return frozenset(collected)


def _required_heading_positions(lines: list[str]) -> tuple[int, ...]:
    positions: list[int] = []
    for heading in REQUIRED_HEADINGS:
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise ReviewValidationError(_HEADINGS_ERROR)
        positions.append(matches[0])

    if positions != sorted(positions):
        raise ReviewValidationError(_HEADINGS_ERROR)
    return tuple(positions)


def _validate_heading_lines(
    lines: list[str],
    heading_positions: tuple[int, ...],
) -> None:
    title_position = heading_positions[0]
    findings_position = heading_positions[2]
    test_gaps_position = heading_positions[3]
    if any(line.strip() for line in lines[:title_position]):
        raise ReviewValidationError(_HEADINGS_ERROR)

    required = frozenset(REQUIRED_HEADINGS)
    for index, line in enumerate(lines):
        level = _heading_level(line)
        if level is None or line in required:
            continue
        if level == 3 and findings_position < index < test_gaps_position:
            continue
        raise ReviewValidationError(_HEADINGS_ERROR)


def _heading_level(line: str) -> int | None:
    content = line.lstrip()
    level = len(content) - len(content.lstrip("#"))
    if level in (1, 2, 3):
        return level
    return None


def _validate_findings(
    lines: list[str],
    changed_filenames: frozenset[str],
) -> None:
    if any(_MALFORMED_DEEP_FINDING_HEADING_PATTERN.fullmatch(line) for line in lines):
        raise ReviewValidationError(_FINDING_HEADINGS_ERROR)

    heading_positions = [index for index, line in enumerate(lines) if _heading_level(line) == 3]
    if not heading_positions:
        if "\n".join(lines).strip() != NO_ACTIONABLE_ISSUES:
            raise ReviewValidationError(_NO_FINDINGS_ERROR)
        return

    if NO_ACTIONABLE_ISSUES in lines:
        raise ReviewValidationError(_FINDING_HEADINGS_ERROR)
    if any(line.strip() for line in lines[: heading_positions[0]]):
        raise ReviewValidationError(_FINDING_FIELDS_ERROR)

    for expected_number, position in enumerate(heading_positions, start=1):
        match = _FINDING_HEADING_PATTERN.fullmatch(lines[position])
        if match is None or int(match.group(1)) != expected_number:
            raise ReviewValidationError(_FINDING_HEADINGS_ERROR)

        next_position = (
            heading_positions[expected_number]
            if expected_number < len(heading_positions)
            else len(lines)
        )
        _validate_finding_fields(
            lines[position + 1 : next_position],
            changed_filenames,
        )


def _validate_finding_fields(
    lines: list[str],
    changed_filenames: frozenset[str],
) -> None:
    if not lines or lines[0].strip():
        raise ReviewValidationError(_FINDING_FIELDS_ERROR)

    field_lines = [line for line in lines if line.strip()]
    if len(field_lines) != len(FINDING_LABELS):
        raise ReviewValidationError(_FINDING_FIELDS_ERROR)

    values: dict[str, str] = {}
    for label, line in zip(FINDING_LABELS, field_lines, strict=True):
        prefix = f"- {label}: "
        if not line.startswith(prefix):
            raise ReviewValidationError(_FINDING_FIELDS_ERROR)
        values[label] = line[len(prefix) :]

    severity = values["Severity"]
    if severity not in ALLOWED_SEVERITIES:
        raise ReviewValidationError(_SEVERITY_ERROR)

    filename = values["File"]
    if filename not in changed_filenames:
        raise ReviewValidationError(_FILE_ERROR)

    for label in ("Location", "Issue", "Evidence", "Recommendation"):
        if not values[label].strip():
            raise ReviewValidationError(_FINDING_FIELDS_ERROR)


def _validate_final_assessment(lines: list[str]) -> None:
    assessment = "\n".join(lines).strip()
    if assessment not in ALLOWED_FINAL_ASSESSMENTS:
        raise ReviewValidationError(_ASSESSMENT_ERROR)
