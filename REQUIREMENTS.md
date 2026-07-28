# AI GitHub Reviewer Requirements

## 1. Document Information

| Field | Value |
| --- | --- |
| Product | AI GitHub Reviewer |
| Target version | v0.1.0 |
| Document type | Product requirements |
| Status | Requirements baseline |
| Interface | Command-line interface (CLI) |
| Agent model | Single agent |

This document defines the product behavior, constraints, quality requirements, and acceptance criteria for AI GitHub Reviewer v0.1.0. It defines what the product MUST do without prescribing a detailed module structure or an implementation sequence.

For the requirements in this document:

- **MUST** and **MUST NOT** identify mandatory behavior.
- **SHOULD** and **SHOULD NOT** identify recommended behavior that may be waived only with a documented product reason.
- **MAY** identifies permitted optional behavior.

### 1.1 Current Repository-Setup Step

The current repository-setup step MUST produce only this requirements document and a concise Python `.gitignore`. Production code, tests, implementation plans, architecture documents, packaging, user documentation, environment files, containers, CI configuration, commits, tags, releases, and GitHub remotes are deliverables for later work and MUST NOT be created during this step.

## 2. Product Overview

AI GitHub Reviewer v0.1.0 is a command-line, single-agent application. A user supplies one standard URL for a public GitHub pull request. The application validates and parses that URL, lets a DeepSeek Chat Completions model request pull request data through a single read-only tool, retrieves the data from the public GitHub REST API, and returns the tool result to the model. DeepSeek then analyzes the supplied pull request metadata and code changes and produces a structured, read-only code review report.

The application MUST NOT submit a review, create a comment, modify code, or perform any other write operation on GitHub.

## 3. Goals

AI GitHub Reviewer v0.1.0 MUST:

1. Accept exactly one supported public GitHub pull request URL through a non-interactive CLI.
2. Retrieve sufficient pull request metadata and changed-file data for a useful review.
3. Require the agent to obtain GitHub data only through the `get_pull_request` tool.
4. Use DeepSeek Chat Completions and tool calling to coordinate data retrieval and review generation.
5. Produce a consistent review focused on actionable, evidence-based risks in the supplied changes.
6. Remain read-only with respect to GitHub.
7. Fail visibly when inputs, configuration, external responses, or tool calls are invalid.
8. Be automatically testable without access to live GitHub or DeepSeek services.

The v0.1.0 release MUST form a minimal end-to-end workflow from a public pull request URL to a structured review printed by the CLI.

## 4. Target Users

The target users are software developers and reviewers who:

- can run a Python command-line application;
- want an initial review of a public GitHub pull request;
- can evaluate model-generated findings before acting on them; and
- do not expect the application to publish or apply any result automatically.

Users MUST remain responsible for validating the report and deciding whether or how to act on it.

## 5. Core User Flow

The complete v0.1.0 user flow MUST be:

1. The user invokes the CLI with one public GitHub pull request URL.
2. The application validates and parses the URL.
3. The application extracts the GitHub owner, repository name, and pull request number and records those values as the authoritative pull request target for the current review session.
4. The agent sends the user's review request and the available tool definition to DeepSeek.
5. DeepSeek calls `get_pull_request` with arguments that exactly match the authoritative target.
6. The agent parses the tool call, validates its schema, and verifies that all three arguments match the authoritative target.
7. The `get_pull_request` tool uses the GitHub REST API to retrieve complete, structured data for that target pull request.
8. The agent appends the successful structured tool result to the Chat Completions message history.
9. DeepSeek analyzes the target pull request changes using that tool result and returns a candidate final review.
10. The agent validates the candidate review against the required structure.
11. The CLI writes only the validated final review to standard output.
12. The application performs no GitHub write operation at any point.

A successful pull request review MUST include at least one successful `get_pull_request` tool call whose result contains the structured data for the authoritative target. If the model returns text without a new tool call before such a result exists, the agent MUST reject the text and raise a clear runtime error. The agent MUST NOT return model text as a successful review unless a real tool result for the target supports it.

The agent MUST support both a single tool-calling round and multiple tool-calling rounds, subject to the configured maximum. A **tool-calling round** is one model response that contains at least one tool call, followed by execution of the valid tool call or calls and addition of the corresponding tool result messages. After at least one successful target tool result exists, a model response with no new tool call is a candidate final response and MUST pass the review format validation in Section 13 before it is returned.

## 6. Supported Pull Request URLs

### 6.1 Accepted Form

v0.1.0 MUST accept only URLs with this logical form:

`https://github.com/{owner}/{repository}/pull/{number}`

The URL MAY have at most one trailing `/`. The parser MUST produce exactly:

- `owner`: the non-empty owner path segment;
- `repository`: the non-empty repository path segment; and
- `pull_number`: a positive integer represented by the final required path segment.

The three parsed values MUST become the authoritative pull request target for the current review session. No model output or GitHub-supplied text MAY replace, override, or redefine that target.

### 6.2 Validation Rules

The URL validator MUST enforce all of the following:

- The scheme MUST be `https`.
- The hostname MUST be exactly `github.com`.
- The URL MUST NOT contain username or password information.
- The URL MUST NOT contain an explicit port, including the default HTTPS port.
- The URL MUST NOT contain a query string.
- The URL MUST NOT contain a fragment.
- The owner segment MUST be present and non-empty.
- The repository segment MUST be present and non-empty.
- The path segment between the repository and number MUST be exactly `pull`.
- The pull request number MUST contain an integer greater than zero.
- The path MUST end immediately after the pull request number or after exactly one trailing `/`.
- No additional path segment, empty or non-empty, MAY follow the optional single trailing `/`.
- At most one pull request URL MAY be supplied.

The validator MUST reject:

- HTTP URLs;
- non-GitHub hostnames and subdomains;
- GitHub Enterprise URLs;
- URLs containing username or password information;
- URLs containing an explicit port;
- URLs containing a query string;
- URLs containing a fragment;
- URLs whose required path segment is not exactly `pull`;
- issue URLs;
- commit URLs;
- repository home-page URLs;
- shortened URLs;
- URLs with a missing owner, repository, or number;
- zero or negative pull request numbers;
- non-integer pull request numbers;
- URLs with more than one trailing slash or any additional path segment after the pull request number;
- multiple pull request inputs.

Invalid URLs MUST be rejected before any GitHub or DeepSeek network request is made.

## 7. Functional Requirements

### 7.1 Review Request

- The application MUST treat the supplied URL as a request to review its authoritative target pull request.
- A successful review MUST include at least one successful `get_pull_request` tool call.
- The successful tool result MUST contain structured data for the authoritative target parsed from the URL.
- The application MUST review only data made available through a validated, successful tool result for that target.
- If the model returns final text before a successful target tool result exists, the application MUST reject it with a clear runtime error.
- The application MUST NOT access or analyze a local Git repository as part of the review.
- The application MUST NOT run, build, import, or otherwise execute pull request code.
- The application MUST NOT claim that it ran code, ran tests, or verified runtime behavior.

### 7.2 Read-Only Operation

- All GitHub HTTP requests MUST use the `GET` method.
- The product MUST NOT expose any tool capable of writing to GitHub.
- The product MUST NOT create a GitHub review or comment.
- The product MUST NOT edit, merge, close, or otherwise mutate a pull request.
- The product MUST NOT modify or commit code.
- The final assessment MUST be report text only and MUST NOT be represented as having been submitted to GitHub.

### 7.3 Result Integrity

- The product MUST preserve the distinction between data returned by GitHub and conclusions generated by the model.
- The product MUST NOT invent files, patches, code locations, test results, or runtime observations.
- The product MUST NOT return model-generated review text as a successful result without a real, complete tool result for the authoritative target.
- The product MUST NOT silently replace an error with a fabricated or partial review.
- The product MUST NOT retry automatically or fabricate a review when a required tool result is absent or invalid.
- When available data is insufficient for a reliable conclusion, the report MUST say so.

## 8. GitHub Data Requirements

### 8.1 Data Source and Access

- Pull request data MUST be obtained from the public GitHub REST API.
- v0.1.0 MUST require only public-repository access.
- The GitHub client MUST NOT require or send a GitHub token.
- The GitHub client MUST perform only read requests.
- GitHub connection, HTTP, rate-limit, response-decoding, and data-validation failures MUST be propagated to the caller.
- The GitHub client MUST NOT retry a failed request automatically.

### 8.2 Pull Request Metadata

The structured tool result MUST contain the following pull request metadata:

| Field | Required meaning |
| --- | --- |
| `title` | Pull request title |
| `body` | Pull request description as returned by GitHub, including an absent or empty value |
| `state` | Pull request state |
| `author` | Pull request author's GitHub identity |
| `base_branch` | Target branch name |
| `head_branch` | Source branch name |
| `created_at` | Pull request creation time |
| `updated_at` | Pull request last-updated time |
| `changed_files` | Count of changed files |
| `additions` | Total additions |
| `deletions` | Total deletions |
| `commits` | Commit count |

The product MUST validate that the GitHub response can supply the required structured metadata. It MUST NOT silently invent a replacement for malformed required data.

### 8.3 Changed Files

For each changed file returned by GitHub, the structured tool result MUST contain:

| Field | Required meaning |
| --- | --- |
| `filename` | Repository-relative file path |
| `status` | GitHub change status |
| `additions` | Added line count |
| `deletions` | Deleted line count |
| `changes` | Total changed line count |
| `patch` | Patch text when, and only when, GitHub returns it |

The GitHub client MUST retrieve all changed-file pages using read-only `GET` requests. It MUST continue pagination until either the number of unique files retrieved equals the metadata `changed_files` value or GitHub explicitly indicates that no next page exists.

When combining pagination results:

- each changed file MUST appear exactly once;
- duplicate file entries, identified by `filename`, MUST be rejected;
- pagination metadata and page contents MUST be mutually consistent;
- the final number of unique files MUST equal the metadata `changed_files` value; and
- an advertised next page after the required file count has already been reached MUST be treated as contradictory pagination data.

If GitHub does not make the complete changed-file list available, indicates contradictory pagination state, returns a duplicate file, or produces a final count that differs from `changed_files`, the application MUST raise a clear data-integrity error. It MUST NOT pass incomplete data to the model or generate a review that appears complete.

The tool result MUST represent the complete changed-file list as a structured collection. If GitHub omits `patch` for a file, the product MUST preserve that absence and MUST NOT construct, infer, or fabricate a diff. Missing patch data MUST NOT by itself cause the application to claim knowledge of changed lines it did not receive.

## 9. Tool Contract

### 9.1 Available Tool

v0.1.0 MUST expose exactly one function tool to the model:

`get_pull_request`

No alias or additional tool MUST be advertised.

### 9.2 Input Contract

The tool arguments MUST have an object as their root and MUST contain exactly these fields:

| Field | Type | Constraint |
| --- | --- | --- |
| `owner` | string | MUST be non-empty |
| `repository` | string | MUST be non-empty |
| `pull_number` | integer | MUST be greater than zero |

All three fields MUST be required. Additional fields MUST be rejected. A non-object root, missing field, wrong type, empty owner or repository, non-positive pull request number, or otherwise invalid argument payload MUST be rejected before tool execution.

The tool schema supplied to DeepSeek MUST express the same required fields, types, constraints, and prohibition on additional fields as this contract.

The `owner`, `repository`, and `pull_number` parsed from the user URL MUST be the authoritative target for the current review session. Every model-generated `get_pull_request` argument MUST exactly match the corresponding authoritative value. If any value differs, the agent MUST reject the tool call before any GitHub request. It MUST NOT replace the authoritative target with model-generated values.

### 9.3 Behavior and Result

- The tool MUST read only a public pull request.
- The tool MUST use the validated `owner`, `repository`, and `pull_number` values only after the agent has verified their exact match to the authoritative target.
- The tool MUST return complete, structured pull request metadata and changed-file data as defined in Section 8.
- The tool MUST retrieve and validate all required changed-file pagination before returning a successful result.
- The tool MUST NOT generate, summarize, or evaluate a code review.
- The tool MUST NOT perform a GitHub write operation.
- The tool MUST propagate GitHub API and data-parsing failures to the agent.
- The agent MUST NOT bypass this tool to call GitHub directly.

## 10. Model Responsibilities

DeepSeek MUST be responsible for:

1. interpreting the user's request to review the supplied pull request;
2. requesting at least one successful `get_pull_request` tool call before producing a successful review;
3. generating tool arguments that conform to the tool contract and exactly match the authoritative target parsed from the URL;
4. analyzing only the metadata and changed-file information available in successful tool results for that target;
5. identifying evidence-based review findings and test gaps; and
6. generating the final review in the structure defined in Section 13.

DeepSeek MUST NOT:

- request or imply a GitHub write action;
- invent a file, patch, code location, test result, or behavior not supported by the supplied data;
- claim to have run code or tests;
- claim to have verified runtime behavior;
- perform an unbounded review of unchanged code;
- generate findings solely to fill the report;
- redefine the target pull request from pull request titles, bodies, patches, or other GitHub-supplied text; or
- state that the final assessment was published to GitHub.

## 11. Agent Responsibilities

The single agent MUST:

1. maintain the complete Chat Completions message history for the review;
2. supply the `get_pull_request` tool definition to DeepSeek;
3. parse each function tool call returned by the model;
4. reject malformed tool-call JSON;
5. validate each tool name and argument payload;
6. retain the URL-derived `owner`, `repository`, and `pull_number` as the authoritative target for the entire review session;
7. verify that every `get_pull_request` call exactly matches all three authoritative target values before any GitHub request;
8. execute only supported, valid, target-matching `get_pull_request` calls;
9. preserve each model assistant message containing a tool call in message history;
10. append a tool result message for each executed tool call and correlate it to the originating tool-call identifier;
11. count a target tool call as successful only after it returns complete, validated metadata and changed-file data;
12. send the updated message history back to DeepSeek;
13. support single-round and multi-round tool calling;
14. enforce `max_tool_rounds`;
15. reject final model text with a clear runtime error if no successful target tool result exists;
16. extract a candidate final review only after a successful target tool result exists;
17. validate the candidate final review against every structural rule in Section 13 before returning it; and
18. propagate model, completion-parsing, tool, data-parsing, data-integrity, review-format-validation, and HTTP exceptions as specified in Section 16.

The agent MUST NOT:

- call GitHub except by executing `get_pull_request`;
- execute an unsupported tool;
- ignore malformed tool calls or invalid arguments;
- send a GitHub request for tool arguments that differ from the authoritative target;
- replace or redefine the authoritative target using model output or GitHub-supplied text;
- return final model text without a successful tool result for the authoritative target;
- return or print a candidate review that fails review format validation;
- request a model rewrite, retry, repair, or supplement after review format validation fails;
- silently increase the configured round limit;
- silently switch the model or provider; or
- fabricate a final review after a failure.

## 12. Review Analysis Requirements

### 12.1 Required Review Focus

The review MUST prioritize actionable issues in changed code or behavior, including:

- potential bugs;
- correctness risks;
- security concerns;
- missing validation;
- error-handling problems;
- compatibility risks;
- concurrency or state-management problems;
- missing or insufficient tests;
- maintainability problems;
- unnecessarily complex code; and
- unclear behavior changes.

### 12.2 Evidence and Scope

- Each finding MUST be supported by the available pull request data.
- Each finding MUST identify a changed file.
- A precise code location SHOULD be used when the patch makes one identifiable.
- File-level or `Unknown` location MUST be used when the patch is absent or insufficient for a more precise location.
- Recommendations MUST be concrete and directly related to the stated issue.
- The review MUST distinguish a confirmed problem from a risk or uncertainty.
- The review MUST stay within the supplied pull request metadata and changed files.
- The review MUST NOT comment on purely personal style preferences.
- The review MUST NOT invent findings when no reliable actionable issue is present.

## 13. Review Output Format

The final review MUST be Markdown and MUST contain all of the following top-level and second-level headings exactly once and in this order:

1. `# Pull Request Review`
2. `## Summary`
3. `## Findings`
4. `## Test Gaps`
5. `## Maintainability`
6. `## Final Assessment`

No required section MAY be omitted.

### 13.1 Summary

`Summary` MUST briefly describe the apparent purpose of the pull request and its overall risk based on the available data. It MUST disclose material data limitations that affect the review.

### 13.2 Findings

Each finding MUST contain all of these labeled fields:

- `Severity`
- `File`
- `Location`
- `Issue`
- `Evidence`
- `Recommendation`

`Severity` MUST be exactly one of:

- `Critical`
- `High`
- `Medium`
- `Low`

`Location` MUST be one of:

- a code location identifiable from the returned patch;
- a file-level location; or
- `Unknown` when the available patch cannot support a more precise location.

If no reliable actionable issue is identified, `Findings` MUST contain this exact statement and MUST NOT contain fabricated findings:

`No actionable issues identified from the available pull request data.`

### 13.3 Test Gaps

`Test Gaps` MUST describe missing or insufficient tests supported by the available pull request data. If the data is insufficient to assess tests, the section MUST explicitly state that limitation.

### 13.4 Maintainability

`Maintainability` MUST describe evidence-based maintainability risks and useful improvement recommendations. If no reliable maintainability issue can be established, the section MUST say so rather than inventing one.

### 13.5 Final Assessment

The `Final Assessment` section MUST contain exactly one of the following values and MUST contain no other content:

- `Approve`
- `Approve with minor comments`
- `Request changes`
- `Insufficient data`

The assessment MUST be consistent with the findings and stated data limitations. It MUST NOT claim that the assessment has been submitted to GitHub.

### 13.6 Final Review Validation

Before treating model output as a successful result, the application MUST perform review format validation and verify all of the following:

1. each of the six required headings appears exactly once;
2. the headings appear in the exact order defined in this section;
3. `Final Assessment` contains exactly one allowed value and no other content;
4. every finding contains all six required labeled fields;
5. every finding uses exactly one of the four allowed severity values;
6. when no finding is present, `Findings` contains the exact no-actionable-issues statement; and
7. no required section is missing.

A candidate review that violates any of these rules MUST cause a clear review format validation error. The application MUST NOT print or return the invalid text as a successful review. It MUST NOT automatically ask the model to rewrite it, retry the request, repair or supplement the text, or fabricate missing content.

## 14. CLI Requirements

### 14.1 Arguments

The CLI MUST provide:

| Argument | Requirement |
| --- | --- |
| `pull_request_url` | One required positional argument containing the supported pull request URL |
| `--max-tool-rounds` | Optional integer with a default value of `8` |

`max_tool_rounds` MUST be an integer greater than or equal to `1`. A non-integer or a value less than `1` MUST be rejected. The application MUST NOT accept multiple pull request URLs in one invocation.

### 14.2 Composition and Execution

For a valid invocation, the CLI MUST:

1. load the DeepSeek and GitHub configuration;
2. create the GitHub HTTP client;
3. create the DeepSeek model client;
4. create the single agent with the configured maximum tool rounds;
5. execute one pull request review; and
6. write the final review to standard output.

### 14.3 Runtime Behavior

- On successful completion, standard output MUST contain only the final review.
- Successful completion MUST return exit status `0`.
- The CLI MUST NOT request interactive input.
- The CLI MUST NOT open a browser.
- The CLI MUST NOT print an API key.
- The CLI MUST NOT emit debug logs.
- The CLI MUST NOT automatically retry a failed operation.
- The CLI MUST NOT catch or wrap otherwise unhandled application exceptions.

## 15. Configuration Requirements

### 15.1 Supported Variables

The application MUST support configuration through a `.env` file and the following variable names:

| Variable | Required | Default |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | Yes | None |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | No | `deepseek-v4-flash` |
| `GITHUB_API_BASE_URL` | No | `https://api.github.com` |

The application MUST NOT read `OPENAI_API_KEY` as a substitute for `DEEPSEEK_API_KEY`.

### 15.2 Normalization and Validation

- Leading and trailing whitespace MUST be removed from `DEEPSEEK_API_KEY`.
- A missing, empty, or whitespace-only `DEEPSEEK_API_KEY` MUST raise a clear `ValueError`.
- Leading and trailing whitespace MUST be removed from each base URL and model value.
- Trailing `/` characters MUST be removed from each base URL.
- A missing, empty, or whitespace-only optional variable MUST use its documented default.
- Configuration errors and exception text MUST NOT reveal the API key.

### 15.3 Secret Handling

- `.env` MUST be ignored by Git.
- No real API key MUST be stored in tracked files.
- A later implementation-stage `.env.example` MUST contain variable names and safe placeholders or empty values only.
- The API key MUST NOT appear in logs, standard output, tool results, model prompts, or exception text.

## 16. Error Handling

### 16.1 General Rules

- Failures MUST be visible to the caller and MUST NOT be silently ignored.
- The application MUST NOT fabricate a review when processing fails.
- The application MUST NOT automatically retry.
- The application MUST NOT switch models, providers, or configured API base URLs after a failure.
- The application MUST NOT increase `max_tool_rounds` after the limit is reached.
- The application MUST NOT return a review without a successful `get_pull_request` result for the authoritative target.
- The application MUST NOT automatically retry, rewrite, repair, or supplement an invalid final review.
- Unless this document explicitly requires a validation error produced by the application, underlying model, parsing, tool, and HTTP exceptions MUST propagate without being caught and replaced by a generic application error.

### 16.2 Required Failure Scenarios

The application MUST handle each scenario as follows:

| Scenario | Required behavior |
| --- | --- |
| Pull request URL has an invalid format | Reject before external requests |
| Hostname is not exactly `github.com` | Reject before external requests |
| Pull request number is not a positive integer | Reject before external requests |
| URL contains user information, an explicit port, a query string, a fragment, extra trailing slashes, or an additional path segment | Reject before any GitHub or DeepSeek request |
| GitHub API cannot be reached | Propagate the connection or HTTP-client failure |
| GitHub API returns `404` | Propagate the GitHub HTTP failure; do not fabricate data |
| GitHub API reports rate limiting | Propagate the GitHub HTTP failure; do not retry |
| Pull request response data is invalid | Propagate a data-validation or parsing failure |
| Changed-file pagination is incomplete or contradictory | Raise a clear data-integrity error; do not retry or generate a review |
| Changed-file pages contain a duplicate filename | Raise a clear data-integrity error; do not generate a review |
| Final changed-file count differs from metadata `changed_files` | Raise a clear data-integrity error; do not generate a review |
| `DEEPSEEK_API_KEY` is missing or blank | Raise a clear `ValueError` without exposing a key |
| DeepSeek API fails | Propagate the model-client failure; do not switch models |
| Tool-call arguments contain invalid JSON | Propagate or raise a parsing failure; do not execute the tool |
| Tool-call argument root is not an object | Reject validation; do not execute the tool |
| Tool name is unsupported | Reject the call; do not execute any substitute |
| A required tool argument is missing | Reject validation; do not execute the tool |
| Tool arguments contain an extra field | Reject validation; do not execute the tool |
| Any tool argument differs from the authoritative target | Reject before any GitHub request; do not replace the target or generate a review |
| `max_tool_rounds` is not an integer | Reject before agent execution |
| `max_tool_rounds` is less than `1` | Reject before agent execution |
| Model requests a tool round beyond the configured maximum | Raise a clear limit error; do not call the tool or model again |
| Model returns final text before a successful target tool result exists | Raise a clear runtime error; do not return the text, retry, or fabricate a review |
| Final completion contains no choice | Raise or propagate a completion-parsing failure; do not fabricate review text |
| Candidate final review fails a Section 13 structural rule | Raise a clear review format validation error; do not print, retry, rewrite, repair, supplement, or fabricate output |

## 17. Testing Requirements

### 17.1 Test Tooling and Isolation

- Automated tests MUST use `pytest`.
- Code quality checks MUST use Ruff.
- Automated tests MUST NOT contact the real DeepSeek API.
- Automated tests MUST NOT contact the real GitHub API.
- Every external call MUST be replaced by a mock, fake, or equivalent controlled test double.
- Unit tests MUST be able to run with network access disabled.
- Real end-to-end validation MUST be performed manually outside the automated test suite.
- Tests MUST NOT use `skip` or `xfail` to hide incomplete required behavior.
- No coverage percentage target is required for v0.1.0.

### 17.2 Required Automated Coverage

Automated tests MUST cover at least:

1. accepted URL parsing and extraction;
2. rejection of every unsupported URL category in Section 6;
3. configuration loading, defaults, trimming, and secret validation;
4. GitHub HTTP client request method, request construction, and error propagation;
5. pull request metadata parsing;
6. changed-file parsing with and without a returned patch;
7. the advertised tool schema;
8. tool-call JSON parsing;
9. tool argument root and field validation;
10. supported tool execution;
11. rejection of unsupported tools;
12. construction and preservation of assistant messages containing tool calls;
13. construction and correlation of tool result messages;
14. an agent flow with one tool-calling round;
15. an agent flow with multiple tool-calling rounds;
16. enforcement of the maximum tool-round limit;
17. final review text extraction;
18. handling of a completion with no choice;
19. CLI argument defaults and validation;
20. CLI dependency wiring;
21. successful CLI output and exit status;
22. propagation of model, parsing, tool, data, and HTTP exceptions;
23. proof that input objects are not modified by parsing, validation, message construction, or tool execution;
24. proof that automated tests make no real network requests;
25. rejection before external requests of URLs containing user information, an explicit port, a query string, a fragment, more than one trailing slash, or a path segment after the pull request number;
26. rejection before any HTTP request when `owner`, `repository`, or `pull_number` in a tool call differs from the authoritative target, including proof that the target is not replaced and no review is returned;
27. rejection with a clear runtime error when the model returns text before a successful target tool result exists;
28. successful retrieval and correct duplicate-free merging of multiple changed-file pages using only `GET` requests;
29. data-integrity failure for duplicate filenames, contradictory or incomplete pagination, and a final file count that differs from metadata `changed_files`;
30. acceptance of a compliant final review by review format validation; and
31. rejection of final reviews with a missing or duplicated heading, incorrect heading order, illegal severity, missing finding field, missing exact no-actionable-issues statement when there are no findings, or illegal, multiple, or additional final assessment content.

Tests SHOULD assert externally observable behavior rather than a detailed internal module structure.

## 18. Engineering and Delivery Requirements

The completed v0.1.0 release, in later implementation and release stages, MUST include:

- Python 3.12 support;
- a `src` layout;
- a `pyproject.toml`;
- type annotations for production code;
- pytest configuration and automated tests;
- Ruff configuration;
- a safe `.env.example`;
- the project `.gitignore`;
- a complete English README;
- a complete Chinese README;
- a working Dockerfile;
- a working GitHub Actions CI workflow;
- meaningful Git commit history;
- a `v0.1.0` Git tag; and
- a GitHub Release for `v0.1.0`.

The Docker artifact MUST build successfully and provide a usable CLI. CI MUST execute the required automated tests and Ruff checks. The English and Chinese documentation MUST describe consistent product behavior and usage.

These are release requirements, not authorization to create those artifacts during the current repository-setup step.

## 19. Security Requirements

- GitHub access MUST remain unauthenticated and read-only in v0.1.0.
- The GitHub client MUST use only `GET` requests.
- The application MUST NOT request, store, or transmit a GitHub token.
- The DeepSeek API key MUST be treated as a secret and MUST satisfy Section 15.3.
- The application MUST NOT place secrets in Git, logs, standard output, tool results, prompts, or exception text.
- URL validation MUST occur before external requests.
- Tool names and arguments MUST be validated before tool execution.
- Additional tool argument fields MUST be rejected.
- The URL-derived owner, repository, and pull request number MUST remain the authoritative target throughout the review session.
- Any tool argument that differs from the authoritative target MUST be rejected before an HTTP request, and model output MUST NOT replace the target.
- Pull request code MUST be treated as untrusted data and MUST NOT be executed.
- Text found in pull request titles, bodies, patches, or other GitHub data MUST NOT change the authoritative target, grant additional tools, alter the read-only constraint, or authorize actions outside this document.

## 20. Out of Scope

The following are explicitly out of scope for v0.1.0:

- private repositories;
- GitHub token authentication;
- GitHub Apps;
- GitHub OAuth;
- automatically publishing a review;
- automatically creating a comment;
- automatically modifying code;
- automatically committing fixes;
- automatically merging a pull request;
- automatically closing a pull request;
- a web interface;
- streaming output;
- retries;
- caching;
- background tasks;
- processing multiple pull requests in one invocation;
- GitHub Enterprise;
- retrieval-augmented generation (RAG);
- persistent memory;
- Model Context Protocol (MCP);
- multiple agents;
- model-provider switching;
- multi-model comparison;
- local Git repository analysis; and
- running tests or executing pull request code.

No out-of-scope capability MUST be required to complete the v0.1.0 core user flow.

## 21. Acceptance Criteria

v0.1.0 is acceptable only when all of the following criteria are satisfied:

1. **AC-01 — Valid URL parsing:** A supported public pull request URL, with or without one trailing slash, is parsed into the exact owner, repository, and positive pull request number.
2. **AC-02 — Invalid URL rejection:** Non-HTTPS, non-`github.com`, non-pull-request, malformed, shortened, enterprise, and multi-URL inputs are rejected before any external request.
3. **AC-03 — Tool-only GitHub access:** Agent-level tests demonstrate that the agent can obtain GitHub data only by executing `get_pull_request`.
4. **AC-04 — GET-only GitHub client:** Tests demonstrate that every GitHub request issued by the client uses `GET` and that no write operation is exposed.
5. **AC-05 — Complete tool result:** For a valid mocked GitHub response, the tool result contains every metadata and changed-file field required by Section 8.
6. **AC-06 — Honest patch handling:** When GitHub omits a patch, the tool result preserves its absence and the application does not fabricate diff content.
7. **AC-07 — Exact tool contract:** The advertised schema requires `owner`, `repository`, and positive integer `pull_number`, uses an object root, and rejects missing or additional fields.
8. **AC-08 — Tool result review:** With a valid mocked tool result, DeepSeek interaction can produce a review in the required structure without direct agent access to GitHub.
9. **AC-09 — Required review sections:** Every successful final output contains the six headings in Section 13 exactly once and in the required order.
10. **AC-10 — Finding structure:** Every reported finding has severity, file, location, issue, evidence, and recommendation, and uses only an allowed severity.
11. **AC-11 — No fabricated findings:** When the available data supports no reliable issue, `Findings` contains the required no-issues statement and no invented finding.
12. **AC-12 — Supported assessment:** The final assessment is exactly one allowed value, matches the report, and does not claim to have been published.
13. **AC-13 — Default round limit:** Omitting `--max-tool-rounds` sets the limit to `8`.
14. **AC-14 — Round-limit validation:** Non-integer and less-than-one round limits are rejected, and a request beyond the configured limit fails without an extra tool or model call.
15. **AC-15 — Single- and multi-round agent behavior:** Automated tests verify successful single-round and multi-round tool-calling histories, including correlated tool result messages.
16. **AC-16 — Configuration behavior:** Configuration tests verify documented defaults, whitespace handling, base-URL normalization, and a clear `ValueError` for a missing or blank DeepSeek key.
17. **AC-17 — Secret protection:** `.env` is ignored, no tracked file contains a real key, and automated checks demonstrate that the key is absent from output and failure text.
18. **AC-18 — CLI contract:** A successful mocked review writes only the final review to standard output, exits with status `0`, requests no input, and opens no browser.
19. **AC-19 — Exception propagation:** Tests demonstrate the required propagation of GitHub, DeepSeek, parsing, tool, data-validation, and completion failures without retries or fabricated output.
20. **AC-20 — No-choice completion:** A final completion with no choice fails visibly and does not produce a review.
21. **AC-21 — Immutable inputs:** Tests demonstrate that caller-provided input objects are unchanged after parsing, validation, message construction, and tool execution.
22. **AC-22 — Network-isolated tests:** The complete automated test suite passes with real network access disabled and all external interactions controlled.
23. **AC-23 — Quality checks:** The complete automated test suite passes under pytest and all configured Ruff checks pass without using `skip` or `xfail` to conceal required behavior.
24. **AC-24 — Documentation:** Complete and mutually consistent English and Chinese documentation describes configuration, CLI usage, limitations, read-only behavior, and report interpretation.
25. **AC-25 — Docker:** The release Docker image builds successfully and its CLI can complete a mocked or controlled review workflow.
26. **AC-26 — CI:** The GitHub Actions workflow successfully runs the required pytest and Ruff checks.
27. **AC-27 — Manual public-PR E2E:** A manual end-to-end run against one real public pull request and the configured DeepSeek service completes successfully with all required review sections and no GitHub mutation.
28. **AC-28 — Public, unauthenticated GitHub access:** The end-to-end workflow requires no GitHub token and sends no GitHub authorization credential.
29. **AC-29 — Release history and tag:** The final repository contains meaningful implementation history and a `v0.1.0` tag identifying the accepted release.
30. **AC-30 — GitHub Release:** A GitHub Release for `v0.1.0` exists and corresponds to the accepted tagged version.
31. **AC-31 — Scope compliance:** The accepted release contains none of the out-of-scope capabilities as a requirement of the core flow.
32. **AC-32 — Read-only verification:** Controlled HTTP tests and the manual end-to-end check show that the application does not submit a review, create a comment, or otherwise mutate GitHub state.
33. **AC-33 — Authoritative PR target:** Automated tests demonstrate that URL parsing establishes the authoritative `owner`, `repository`, and `pull_number`; any mismatch in a model tool call is rejected before HTTP access, cannot replace the target, and produces no review.
34. **AC-34 — Tool result required before review:** Automated tests demonstrate that a successful review requires at least one successful `get_pull_request` result containing structured data for the authoritative target and that model text returned earlier causes a clear runtime error without retry or fabricated output.
35. **AC-35 — Exact standard URL components:** Automated tests demonstrate that user information, an explicit port, a query string, a fragment, more than one trailing slash, and any post-number path segment are each rejected before GitHub or DeepSeek access.
36. **AC-36 — Complete changed-file pagination:** Automated tests demonstrate that the client uses only `GET`, follows multiple changed-file pages until the defined stop condition, merges each filename exactly once, and returns a file count equal to metadata `changed_files`.
37. **AC-37 — Changed-file integrity failure:** Automated tests demonstrate that incomplete or contradictory pagination, duplicate filenames, and a final count mismatch each raise a clear data-integrity error without retry, model review generation, or fabricated patch data.
38. **AC-38 — Final review structure validation:** Automated tests demonstrate that a compliant review passes validation and that each missing or duplicated heading, incorrect order, illegal severity, missing finding field, absent required no-issues statement, and illegal, multiple, or additional final assessment content raises a clear format error without printing, retrying, rewriting, repairing, supplementing, or fabricating the review.
