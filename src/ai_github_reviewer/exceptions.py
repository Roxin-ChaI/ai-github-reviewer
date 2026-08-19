class ReviewerError(Exception):
    """Base exception for the stable public reviewer API."""


class ReviewerConfigurationError(ReviewerError, ValueError):
    """The public reviewer configuration is invalid."""


class InvalidPullRequestURLError(ReviewerError, ValueError):
    """The requested Pull Request URL is unsupported."""


class GitHubRetrievalError(ReviewerError):
    """Read-only GitHub retrieval failed."""


class ModelReviewError(ReviewerError):
    """The configured review model failed."""


class ReviewProtocolError(ReviewerError):
    """The model response did not satisfy the review protocol."""


class ReviewerClosedError(ReviewerError, RuntimeError):
    """The runner was used after its owned resources were closed."""
