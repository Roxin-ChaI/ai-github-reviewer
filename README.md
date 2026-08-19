# AI GitHub Reviewer

English | [简体中文](README.zh-CN.md)

AI GitHub Reviewer is a single-agent, read-only reviewer with a command-line interface
and a synchronous public Python API. It reviews one public GitHub Pull Request using
DeepSeek's OpenAI-compatible Chat Completions API and one strict `get_pull_request`
tool. The CLI prints the validated Markdown review; the Python API returns that same
Markdown together with an immutable structured result.

## Key Features

- Strict parsing of standard `github.com` Pull Request URLs.
- An immutable authoritative Pull Request target derived from the user URL.
- Unauthenticated, GET-only GitHub API access.
- Complete Pull Request metadata and changed-file retrieval, including safe pagination.
- A bounded Tool Calling loop with a configurable round limit.
- Deterministic validation of the final Markdown review.
- A typed public runner API with explicit configuration and lifecycle boundaries.
- Final-only CLI output with no progress or debug text on success.
- Network-isolated automated tests.
- Minimal Docker delivery and GitHub Actions CI.

## Read-only and Trust Model

The application does not publish a GitHub Review, create comments, merge or close a
Pull Request, or perform any other GitHub write. It does not accept a GitHub token.
Pull Request titles, bodies, patches, filenames, and Tool Results are untrusted data.
The model cannot replace or redefine the authoritative target. GitHub data is obtained
only by dispatching the `get_pull_request` tool.

The application does not execute, build, import, or test Pull Request code, and it does
not analyze a local repository. Its findings are based only on the most recent
successful and complete Tool Result.

## Requirements

- Python 3.12 or newer.
- A valid DeepSeek API key.
- One public Pull Request hosted on `github.com`.
- Docker only when using the container workflow.

## Installation

Create and activate a virtual environment, then install the application:

```console
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

For development and quality checks:

```console
python -m pip install -e ".[dev]"
```

No GitHub token is required or supported.

## Public Python API

The public API is synchronous and does not print the review. The runner owns its
GitHub and model clients, so callers must close it:

```python
import os

from ai_github_reviewer import ReviewerConfig, create_reviewer

reviewer = create_reviewer(
    ReviewerConfig(deepseek_api_key=os.environ["DEEPSEEK_API_KEY"])
)
try:
    result = reviewer.review(
        "https://github.com/OWNER/REPOSITORY/pull/NUMBER"
    )
finally:
    reviewer.close()

print(result.summary)
for finding in result.findings:
    print(finding.severity, finding.file_path, finding.location)
print(result.markdown)
```

`ReviewResult` exposes the authoritative target, Pull Request metadata, summary,
ordered findings, test gaps, maintainability notes, final assessment, and the original
validated Markdown. Each finding exposes severity, file path, textual location,
issue, evidence, and recommendation. It does not fabricate line numbers, confidence,
metrics, token usage, or risk scores.

The root package also exports stable public error categories for configuration,
invalid Pull Request URLs, GitHub retrieval, model execution, review protocol
validation, and use after close. Causes remain available through exception chaining;
secrets are not copied into public error messages.

The public factory preserves the same anonymous GitHub REST GET-only boundary as the
CLI. It accepts no GitHub token and exposes no operation for comments, reviews,
approval, requested changes, merges, or other GitHub writes.

## Configuration

Copy `.env.example` to the Git-ignored `.env` file and set the DeepSeek key:

```console
cp .env.example .env
```

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | Yes | None | DeepSeek API authentication. |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com` | OpenAI-compatible DeepSeek API base URL. |
| `DEEPSEEK_MODEL` | No | `deepseek-v4-flash` | Model used for the review. |
| `GITHUB_API_BASE_URL` | No | `https://api.github.com` | Public GitHub REST API base URL. |

Trailing slashes on base URLs are normalized. A missing or blank
`DEEPSEEK_API_KEY` causes configuration loading to fail. `OPENAI_API_KEY` is not read
as a fallback. The `.env` file is ignored by Git; never commit a real secret.

## CLI Usage

Review one Pull Request:

```console
ai-github-reviewer PULL_REQUEST_URL
```

Set the bounded Tool Calling limit explicitly:

```console
ai-github-reviewer PULL_REQUEST_URL --max-tool-rounds 8
```

Show module help:

```console
python -m ai_github_reviewer.cli --help
```

Exactly one URL is accepted. `--max-tool-rounds` defaults to `8` and has a minimum of
`1`. Success returns status `0`, and stdout contains only the final validated review.
Application exceptions propagate without being wrapped by the CLI.

## Supported Pull Request URLs

Only these standard forms are accepted:

```text
https://github.com/OWNER/REPOSITORY/pull/NUMBER
https://github.com/OWNER/REPOSITORY/pull/NUMBER/
```

`NUMBER` must be a positive integer. HTTP URLs, hosts other than exactly `github.com`,
userinfo, explicit ports, query strings, fragments, extra paths, multiple URLs,
GitHub Enterprise URLs, and other GitHub resource types are rejected before any
GitHub or DeepSeek request.

## Review Format

A successful review contains exactly these six headings in this order:

```text
# Pull Request Review
## Summary
## Findings
## Test Gaps
## Maintainability
## Final Assessment
```

Each finding is numbered consecutively with `### Finding N` and uses these fields in
this exact order:

```text
### Finding 1

- Severity: Low
- File: src/example.py
- Location: line 10
- Issue: non-empty text
- Evidence: non-empty text
- Recommendation: non-empty text
```

`Severity` is exactly one of `Critical`, `High`, `Medium`, or `Low`. `File` must
exactly match a changed filename in the most recent successful and complete Tool
Result. When no reliable actionable issue exists, the Findings section contains only:

```text
No actionable issues identified from the available pull request data.
```

The Final Assessment section contains exactly one of:

```text
Approve
Approve with minor comments
Request changes
Insufficient data
```

The application never claims that this review was published to GitHub.

## Failure Behavior

Invalid URLs, missing API keys, GitHub HTTP or rate-limit errors, invalid GitHub
responses, incomplete changed-file data, invalid Tool Calls, target mismatches, Tool
round exhaustion, model completion errors, and invalid final reviews fail explicitly.
Failures are not retried, replaced with a fallback, repaired, rewritten, or printed as
a partial review.

## Testing and Quality

```console
python -m pip check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Pytest uses a global network guard that blocks real socket connections. The controlled
Docker E2E harness is not collected or run by default pytest.

## Docker

Build the release image:

```console
docker build --tag ai-github-reviewer:0.1.0 .
```

Check the container CLI:

```console
docker run --rm ai-github-reviewer:0.1.0 --help
```

Run against one public Pull Request:

```console
docker run --rm --env-file .env ai-github-reviewer:0.1.0 https://github.com/OWNER/REPOSITORY/pull/NUMBER
```

The Dockerfile does not copy `.env`, and no secret is embedded in the image. The
default image entrypoint is `ai-github-reviewer`.

## Controlled Docker E2E

After building a local controlled image, run the explicit release harness:

```console
docker build --tag ai-github-reviewer:controlled .
python3.12 tests/docker_controlled_e2e.py --image ai-github-reviewer:controlled
```

The harness runs the image's real CLI against local fake GitHub and fake DeepSeek
services. It does not contact real services and is not part of default pytest. It
verifies GET-only GitHub access, the absence of GitHub Authorization, Tool Calling
history, disabled thinking, final-only stdout, and the canonical Review format.

## Continuous Integration

The workflow at `.github/workflows/ci.yml` uses Python 3.12 and runs `pip check`,
pytest, Ruff lint, and Ruff format checks. It requires no secrets and performs no real
API calls. The workflow does not run the controlled Docker E2E or a live E2E.

## Manual Live E2E Checklist

Run this checklist only after automated tests, Ruff, `pip check`, the Docker build,
and the controlled E2E all pass:

1. Put a valid DeepSeek key in the local, ignored `.env`.
2. Select one real public Pull Request without writing its URL or personal data to a
   tracked file.
3. Run the CLI once; do not add an automatic retry.
4. Confirm exit status `0` and that stdout contains only the review.
5. Confirm all six headings are unique and correctly ordered.
6. Confirm every Finding follows the required grammar and the Final Assessment is
   allowed.
7. Confirm the output contains no API key.
8. Confirm the GitHub Pull Request state, reviews, and comments are unchanged.

This live E2E has not been executed as part of Slice 10.

## Limitations and Out of Scope

The v0.1.0 scope excludes private repositories; GitHub tokens, Apps, and OAuth;
automatic review publication; comments; code changes or fix commits; merge or close
operations; a web UI; streaming; retries; caching; background work; multiple Pull
Requests; GitHub Enterprise; local repository analysis; Pull Request code execution;
RAG; persistent memory; MCP; multiple agents; provider switching; and multi-model
comparison.

## Release Status

`v0.1.0` is the current stable tag. Public runner work after that tag is development
work for a future release and does not change the package version in this phase.
