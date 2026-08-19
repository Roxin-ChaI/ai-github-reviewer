from copy import deepcopy
from typing import Any

from ai_github_reviewer import (
    PullRequestInfo,
    PullRequestTargetInfo,
    ReviewerConfig,
    ReviewerRunner,
    ReviewFinding,
    ReviewResult,
)

URL = "https://github.com/example-owner/example-repository/pull/123"


def _result(target: Any) -> ReviewResult:
    return ReviewResult(
        target=PullRequestTargetInfo(
            owner=target.owner,
            repository=target.repository,
            pull_number=target.pull_number,
        ),
        pull_request=PullRequestInfo(
            title="Controlled change",
            body=None,
            state="open",
            author="reviewer-test",
            base_branch="main",
            head_branch="feature",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-02T00:00:00Z",
            changed_files=1,
            additions=1,
            deletions=0,
            commits=1,
        ),
        summary="Controlled summary.",
        findings=(
            ReviewFinding(
                severity="Low",
                file_path="src/example.py",
                location="line 10",
                issue="A controlled issue exists.",
                evidence="The changed line demonstrates the issue.",
                recommendation="Handle the controlled case explicitly.",
            ),
        ),
        test_gaps="Controlled test gap.",
        maintainability="Controlled maintainability note.",
        assessment="Approve with minor comments",
        markdown="# Pull Request Review\n",
    )


class FakeService:
    def __init__(self) -> None:
        self.targets: list[Any] = []
        self.close_calls = 0

    def review(self, target: Any) -> ReviewResult:
        self.targets.append(target)
        return _result(target)

    def close(self) -> None:
        self.close_calls += 1


def test_external_consumer_uses_root_public_api_only() -> None:
    config = ReviewerConfig(deepseek_api_key="controlled-key")
    service = FakeService()
    runner = ReviewerRunner(service=service)
    url_before = deepcopy(URL)

    try:
        result = runner.review(URL)
    finally:
        runner.close()

    assert config.deepseek_model == "deepseek-v4-flash"
    assert result.summary == "Controlled summary."
    assert result.findings[0].severity == "Low"
    assert result.findings[0].file_path == "src/example.py"
    assert result.markdown == "# Pull Request Review\n"
    assert len(service.targets) == 1
    target = service.targets[0]
    assert (target.owner, target.repository, target.pull_number) == (
        "example-owner",
        "example-repository",
        123,
    )
    assert service.close_calls == 1
    assert URL == url_before
