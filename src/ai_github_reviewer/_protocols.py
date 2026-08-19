from collections.abc import Mapping, Sequence
from typing import Protocol

from ai_github_reviewer.pull_request import PullRequestData, PullRequestTarget


class GitHubReader(Protocol):
    def get_pull_request(self, target: PullRequestTarget) -> PullRequestData: ...


class ReviewModel(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]: ...
