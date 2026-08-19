from dataclasses import dataclass
from typing import Literal

ReviewSeverity = Literal["Critical", "High", "Medium", "Low"]
ReviewAssessment = Literal[
    "Approve",
    "Approve with minor comments",
    "Request changes",
    "Insufficient data",
]


@dataclass(frozen=True, slots=True)
class PullRequestTargetInfo:
    owner: str
    repository: str
    pull_number: int


@dataclass(frozen=True, slots=True)
class PullRequestInfo:
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


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    severity: ReviewSeverity
    file_path: str
    location: str
    issue: str
    evidence: str
    recommendation: str


@dataclass(frozen=True, slots=True)
class ReviewResult:
    target: PullRequestTargetInfo
    pull_request: PullRequestInfo
    summary: str
    findings: tuple[ReviewFinding, ...]
    test_gaps: str
    maintainability: str
    assessment: ReviewAssessment
    markdown: str
