from dataclasses import dataclass


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
