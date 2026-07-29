# AI GitHub Reviewer Implementation Plan

## 1. Plan Information

| Field | Value |
| --- | --- |
| Product | AI GitHub Reviewer |
| Target release | v0.1.0 |
| Plan status | Proposed for incremental approval |
| Runtime | Python 3.12 |
| Interface | Non-interactive command-line interface |
| Agent model | One agent with one read-only tool |
| Requirements baseline | `9dde6e5 docs: define AI GitHub Reviewer requirements` |

This document defines an implementation sequence for the approved requirements baseline. It does not change the requirements, contain production code, or claim that any implementation or test has been completed. Each slice is intended to be reviewed, tested, and committed independently before the next slice begins.

The implementation will remain a minimal closed loop: parse one public GitHub pull request URL, obtain complete pull request data through `get_pull_request`, ask DeepSeek to review that data, validate the final Markdown structure, and print the validated review. GitHub remains read-only throughout.

## 2. Requirements Baseline

The sole product baseline is `REQUIREMENTS.md` at commit `9dde6e5`. Implementation decisions in this plan are subordinate to that document.

The implementation must preserve these invariants:

- exactly one standard public GitHub pull request URL per invocation;
- an immutable, URL-derived authoritative pull request target;
- exactly one advertised tool, `get_pull_request`;
- public GitHub REST API access with `GET` only and no GitHub token;
- complete changed-file pagination and integrity validation;
- DeepSeek OpenAI-compatible Chat Completions with thinking disabled;
- at least one successful target tool result before a review can succeed;
- deterministic validation of the required final review structure;
- no automatic retry, model fallback, repair, or partial-result output;
- no real external calls in automated tests; and
- no capability listed in the requirements' Out of Scope section.

Work on a slice must stop if it would require changing the requirements. Any such issue must be returned for requirements review rather than resolved by silently expanding the implementation.

## 3. Architecture Overview

The application will use a small layered design:

1. The CLI loads configuration and validates CLI arguments.
2. The URL parser converts the user URL into an immutable authoritative target.
3. The CLI creates the GitHub client, DeepSeek model client, and single agent.
4. The agent sends system and user messages plus the one tool definition to DeepSeek.
5. The agent parses and validates every tool call, including exact comparison with the authoritative target.
6. The GitHub client fetches metadata and the complete changed-file collection using read-only requests.
7. Domain parsers validate external JSON and construct immutable domain values.
8. Message helpers serialize the complete tool result into a new tool result message.
9. The agent continues single-round or multi-round tool calling within the configured limit.
10. Once a successful target tool result exists and the model returns no new tool call, the agent extracts a candidate review.
11. The review validator checks the deterministic Markdown contract.
12. Only a valid review is returned to the CLI and printed to standard output.

Dependency direction will point inward toward domain values and contracts. The domain data layer will not depend on HTTP, the model SDK, or the CLI. The agent will depend on narrow GitHub and model-client interfaces so tests can use controlled fakes without network access.

No component other than the GitHub client will issue GitHub HTTP requests. No component will expose a GitHub write operation.

## 4. Dependency Strategy

### 4.1 Runtime Dependencies

| Dependency | Purpose | Constraint |
| --- | --- | --- |
| Python 3.12 | Runtime and standard-library facilities | The package metadata will require Python 3.12 |
| OpenAI Python SDK | DeepSeek OpenAI-compatible Chat Completions and tool calls | Configure the DeepSeek base URL and disable SDK retries |
| `httpx` | Public GitHub REST API client | Use a normal client with no retry transport |
| `python-dotenv` | Optional `.env` loading | Existing process environment values take precedence |

The standard library will provide `argparse`, URL parsing, JSON parsing, immutable data classes, collections, and type definitions. The application will not directly depend on Pydantic, a GitHub SDK, a web framework, or an agent framework.

### 4.2 Development Dependencies

| Dependency | Purpose |
| --- | --- |
| `pytest` | Automated unit and integration-style tests with controlled doubles |
| Ruff | Formatting-independent linting and import/style checks |

`pyproject.toml` will contain package metadata, dependency declarations, pytest settings, and Ruff settings. Version ranges will be explicit and compatible with Python 3.12. Dependency installation will occur only during an approved implementation slice.

### 4.3 Excluded Dependencies

FastAPI, Pydantic as a direct application dependency, Typer, Click, GitHub SDKs, LangChain, LangGraph, CrewAI, AutoGen, MCP SDKs, databases, and web frameworks are unnecessary for the required behavior and will not be added. `argparse` is sufficient for the two CLI arguments. Small explicit validators are sufficient for the fixed external data contracts.

## 5. Proposed Repository Structure

The completed v0.1.0 repository is expected to have this minimal structure:

```text
.
├── .env.example
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── Dockerfile
├── IMPLEMENTATION_PLAN.md
├── README.md
├── README.zh-CN.md
├── REQUIREMENTS.md
├── pyproject.toml
├── src/
│   └── ai_github_reviewer/
│       ├── __init__.py
│       ├── agent.py
│       ├── cli.py
│       ├── config.py
│       ├── github_client.py
│       ├── github_url.py
│       ├── messages.py
│       ├── model_client.py
│       ├── pull_request.py
│       ├── review_validation.py
│       ├── tool_calls.py
│       └── tool_schema.py
└── tests/
    ├── conftest.py
    ├── docker_controlled_e2e.py
    ├── test_agent.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_github_client.py
    ├── test_github_url.py
    ├── test_messages.py
    ├── test_model_client.py
    ├── test_pull_request.py
    ├── test_review_validation.py
    ├── test_tool_calls.py
    └── test_tool_schema.py
```

`review_validation.py` owns the canonical Finding grammar and validates Finding filenames against the changed files supplied by the agent; no additional parsing module is required. `tests/conftest.py` provides the always-on unit-test network boundary. `tests/docker_controlled_e2e.py` is an explicitly invoked release-validation harness and is not collected by the default pytest suite.

No separate utilities package, service layer, persistence layer, plugin system, or framework-specific structure is planned. A new module may be proposed only if a later approved requirement cannot be represented cleanly by these responsibilities.

## 6. Module Responsibilities

| Module | Single responsibility |
| --- | --- |
| `__init__.py` | Declare the package and release version without importing side-effecting components |
| `config.py` | Load, normalize, and validate DeepSeek and GitHub configuration |
| `github_url.py` | Parse one supported URL and return an authoritative pull request target |
| `pull_request.py` | Define immutable pull request domain values and validate GitHub response data into them |
| `github_client.py` | Perform the two kinds of read-only GitHub requests and enforce changed-file pagination integrity |
| `tool_schema.py` | Provide the sole `get_pull_request` function-tool schema |
| `tool_calls.py` | Parse and strictly validate tool calls, bind them to the authoritative target, and dispatch the supported tool |
| `messages.py` | Construct the canonical read-only system prompt plus new user, assistant tool-call, and correlated tool result messages without mutation |
| `model_client.py` | Adapt the OpenAI Python SDK to the required DeepSeek Chat Completions behavior |
| `review_validation.py` | Parse the canonical Finding grammar and validate the full Markdown contract against the current changed-filename set |
| `agent.py` | Own message history, strictly validate the round limit, retain the most recent complete target result, and coordinate the bounded loop |
| `cli.py` | Parse CLI arguments, wire dependencies, execute one review, and print only the final review |
| `tests/conftest.py` | Install an automatically enabled global guard that makes unexpected real socket or network access fail |
| `tests/docker_controlled_e2e.py` | Run the release-only controlled Docker workflow against local fake GitHub and DeepSeek HTTP services |

Each test module will correspond to the production responsibility with the same stem. Cross-component behavior will be tested at the narrowest useful boundary; `test_agent.py` and `test_cli.py` will use fakes rather than real network clients.

## 7. Core Data Structures

All domain values will be conceptually immutable. Frozen data classes and tuples are the preferred representation because they are available in the standard library, make mutation failures visible, and can be compared directly in tests.

### 7.1 Pull Request Target

The authoritative target contains:

- `owner`: non-empty string;
- `repository`: non-empty string; and
- `pull_number`: positive integer, with booleans rejected as integers.

It is created exactly once from the validated user URL. The agent retains the same value for the entire session. Model output and GitHub content cannot create a replacement target.

### 7.2 Pull Request Metadata

The metadata value contains every field required by Requirements Section 8:

- `title`;
- `body`, preserving an absent value without inventing text;
- `state`;
- `author`;
- `base_branch`;
- `head_branch`;
- `created_at`;
- `updated_at`;
- `changed_files`;
- `additions`;
- `deletions`; and
- `commits`.

Required strings will be type-checked. Required counts will be non-negative integers and will reject booleans. The parser will preserve the API's timestamp text after validating the required type. It will not normalize content in a way that changes the GitHub data.

### 7.3 Changed File

Each changed-file value contains:

- `filename`;
- `status`;
- `additions`;
- `deletions`;
- `changes`; and
- optional `patch`.

`filename` and `status` must be strings. Counts must be non-negative integers and must reject booleans. Internally, a missing patch will be represented as an explicit absence, not an empty or fabricated diff. When serialized for the model, the `patch` key will be omitted when GitHub omitted it.

### 7.4 Complete Pull Request Tool Result

The complete result contains:

- one validated metadata value; and
- an immutable tuple of all unique changed-file values.

Construction succeeds only when the changed-file tuple length exactly equals metadata `changed_files` and pagination integrity has passed. No partial-result variant will be exposed to the agent.

During an agent run, the current result snapshot is the most recent successful, complete, integrity-validated result returned for the authoritative target. A later successful call for the same target replaces the prior snapshot. A later failed call fails the entire run and cannot fall back to an older snapshot.

### 7.5 Parsed Tool Call

The parsed tool call contains:

- the model-provided tool-call identifier;
- the exact tool name; and
- a newly constructed, validated target value derived from the argument payload.

The parsed target must equal the authoritative session target before execution. The original JSON string, SDK response object, argument mapping, and message list will not be modified.

### 7.6 Configuration

Configuration will also be immutable and contain:

- trimmed `deepseek_api_key`;
- normalized `deepseek_base_url`;
- trimmed `deepseek_model`; and
- normalized `github_api_base_url`.

The key will be excluded from representations intended for logs or error text.

### 7.7 Serialization and Input Immutability

Parsers will read from external mappings and sequences but build fresh domain objects. They will not remove keys, rewrite nested mappings, append to caller lists, or reuse mutable collections in returned values.

Tool-result serialization will build a new JSON-compatible mapping from the immutable result and encode it as JSON for the tool message. Metadata and every changed file will be represented structurally. Missing patch data will remain absent. Serialization will never include the DeepSeek key or add inferred GitHub data.

Message construction will copy relevant values into new message mappings. The agent will start from a new message-history list and append newly created messages, leaving caller-owned inputs unchanged.

### 7.8 Agent Execution State

The agent's session state contains the immutable authoritative target, the configured tool-round limit, the current round count, and an optional current complete-result snapshot. The snapshot begins absent and is replaced only by a successful, fully validated target result.

`max_tool_rounds` must be a true integer and must reject `bool`, strings, floating-point values, `None`, and integers below `1`. The value is validated without coercion at the agent construction or run boundary before the first model or tool call.

## 8. Key Design Decisions

### 8.1 URL Parsing

`github_url.py` will use the standard library URL parser and validate the original parsed components before constructing a target:

1. The scheme must equal `https`.
2. The hostname must equal `github.com` exactly.
3. Username and password components must both be absent.
4. The parsed URL must contain no explicit port, including `443`. Presence is checked independently of the normalized hostname.
5. Query and fragment components must be absent. The original URL text will also be checked for literal `?` or `#` delimiters so an explicitly empty query or fragment cannot disappear through parser normalization.
6. The path must match exactly four required semantic segments: owner, repository, `pull`, and the number.
7. The path may end immediately after the number or contain exactly one trailing slash.
8. Empty required segments, extra segments, and repeated trailing slashes are rejected.
9. The number must contain decimal digits and convert to an integer greater than zero.

Validation completes before constructing any HTTP or model request. The parser returns a new immutable target and does not mutate the URL input.

### 8.2 Authoritative Pull Request Target

The CLI will parse the URL before creating the agent. That target is passed explicitly to the agent and remains the sole authority for the session.

For every model tool call:

1. JSON and schema validation occur first.
2. A new target is constructed from the validated arguments.
3. The new target is compared field-for-field with the authoritative target.
4. Any owner, repository, or pull-number mismatch raises a clear application error before dispatch.
5. All tool calls in one assistant message are validated before any of them can cause HTTP traffic, preventing a mixed valid/invalid batch from causing partial access.

The agent never assigns model-generated values back to its authoritative target. Pull request titles, bodies, patches, and all other GitHub data are review inputs only.

### 8.3 GitHub HTTP Requests

`github_client.py` will use an injected `httpx` client to make:

- one metadata request to the public pull request endpoint for the authoritative owner, repository, and number; and
- one or more files requests to that pull request's changed-files endpoint.

The endpoint families are the GitHub REST pull request resource and its files resource. The files request will use the maximum supported page size to minimize calls without changing pagination correctness.

Every request will:

- use `GET`;
- use the normalized configured API base URL;
- omit GitHub credentials and the `Authorization` header;
- use no retry transport or retry loop;
- disable automatic HTTP redirect following;
- call the HTTP client's status check so HTTP failures propagate; and
- validate decoded JSON before constructing domain values.

Connection failures, timeouts, redirect responses, status errors including `404` and rate limiting, and low-level response decoding errors will propagate unchanged. Application-owned data validation errors will identify the invalid response category without fabricating missing fields. A pagination `next` URL is validated as described below before it can become a request target.

### 8.4 Changed Files Pagination

Pagination will use GitHub's `Link` response header as exposed by `httpx` response link metadata. The implementation will never guess the next page number.

The algorithm is:

1. Fetch and validate metadata first to obtain `changed_files`.
2. If `changed_files` is zero, construct an empty complete collection without requesting a files page.
3. Otherwise request the first files page with a fixed maximum page size.
4. Validate that each page body is a list and validate every file before merging the page.
5. Track filenames in a set and normalized visited page URLs in a second set.
6. Raise a changed-file integrity error immediately for a duplicate filename, an invalid page body, or a total greater than metadata `changed_files`.
7. Read only the `next` relation from the response's parsed `Link` header metadata.
8. If the unique count equals `changed_files`, require that no `next` relation remains. A remaining `next` link is contradictory pagination and fails without another request.
9. If the unique count is below `changed_files`, require a `next` relation. Its absence means the list is incomplete and fails.
10. Reject an empty page that advertises another page as contradictory progress.
11. Resolve a relative `next` reference against the current response URL with the standard-library URL resolver, then parse and normalize the resolved URL with the standard URL parser.
12. Enforce a same origin rule: the resolved scheme and complete authority must exactly equal the configured GitHub API base URL. A scheme, host, or explicit-port difference fails.
13. Require absent username, password, and fragment components.
14. Require the normalized path to remain exactly the current authoritative target's Pull Request files endpoint. A different repository, pull request number, metadata endpoint, or any non-files endpoint fails.
15. Parse the query as pagination data only. Permit only the expected `page` and `per_page` parameters with valid positive integer values, no duplicate keys, and no value that changes resource identity.
16. Require the normalized next URL to differ from the current response URL and every previously visited page URL.
17. Complete all next-URL checks before sending the request. Any failure raises a changed-file integrity error and sends no next-page request.
18. Follow only the validated next URL and repeat without retrying or following redirects.
19. Return a complete immutable result only when the unique count exactly matches metadata and there is no contradictory next page.

Any HTTP failure during pagination propagates unchanged. Duplicate, incomplete, cyclic, excessive, contradictory, cross-origin, or resource-changing pagination data raises an application-owned integrity error. The agent never receives or reviews a partial collection. Patch absence remains absence on every page.

### 8.5 Tool Schema

`tool_schema.py` will expose one OpenAI-compatible function tool named `get_pull_request`. Its conceptual JSON Schema has:

| Property | Schema requirement |
| --- | --- |
| Root | `object` |
| `owner` | non-empty `string` |
| `repository` | non-empty `string` |
| `pull_number` | `integer` with minimum `1` |
| Required | all three properties |
| Additional properties | `false` |

No other function tool or alias will be advertised. Tests will compare the complete schema contract rather than only checking the tool name.

### 8.6 Tool Call Parsing and Execution

`tool_calls.py` will:

1. retain the tool-call identifier required for result correlation;
2. reject an empty or unsupported tool name;
3. parse the argument text with the standard JSON parser;
4. reject invalid JSON and a root value that is not an object;
5. require exactly the three allowed keys;
6. reject missing or extra keys;
7. enforce strict string and integer types, treating booleans as invalid integers;
8. reject blank owner or repository and pull numbers below one;
9. construct a new parsed tool-call value;
10. compare its target exactly with the authoritative target;
11. dispatch only `get_pull_request` to the GitHub client; and
12. construct a new correlated tool result message from the complete result.

Parsing, validation, target comparison, dispatch, and message construction will not modify the original SDK object, JSON text, mapping, or message history.

### 8.7 DeepSeek Model Client

`model_client.py` will wrap the OpenAI Python SDK configured for DeepSeek:

- `DEEPSEEK_API_KEY` supplies the API key;
- `DEEPSEEK_BASE_URL` supplies the OpenAI-compatible base URL;
- `DEEPSEEK_MODEL` selects the model, defaulting to `deepseek-v4-flash`;
- SDK automatic retries are disabled explicitly;
- each Chat Completions request receives the message history and the single tool definition;
- each request disables thinking with `extra_body={"thinking": {"type": "disabled"}}`;
- the adapter returns the first choice's assistant message in a form the agent can preserve; and
- a completion with no choice raises a clear completion-parsing error.

The adapter will not fall back to another model, alter the configured base URL, retry, log the key, or catch and wrap SDK API exceptions.

### 8.8 Agent Loop

The system message will define the read-only review purpose, the untrusted-data boundary, the single tool, the required review structure, the canonical Finding format from Section 8.9, and the prohibition on claims about running code or publishing to GitHub. The user message will identify the authoritative target as the requested review subject without allowing model text to redefine it.

The loop will operate as follows:

1. Strictly validate `max_tool_rounds` before building messages or invoking any dependency. Accept only an integer other than `bool` with a value of at least `1`; do not coerce values.
2. Build a fresh history containing system and user messages and initialize the current complete-result snapshot as absent.
3. Send the history and tool definition to the model client.
4. Reject a response with no completion choice through the model-client contract.
5. If the assistant message has tool calls, treat the response as one tool-calling round.
6. Before executing any call, verify that another round is allowed and validate every call in the assistant message.
7. If the requested round would exceed `max_tool_rounds`, raise a clear limit error without executing a tool or calling the model again.
8. Append a newly constructed representation of the complete assistant tool-call message.
9. Execute each validated call and append its correlated tool result message. After each successful same-target call returns complete, integrity-validated data, replace the current snapshot with that most recent successful Tool Result.
10. If any later tool call fails, fail the entire agent run. Do not use or return a review based on an older successful snapshot.
11. Call the model again with the expanded history, supporting both one and multiple tool rounds.
12. If a response has no new tool call, reject its text unless the current snapshot proves that at least one target call succeeded.
13. Extract non-empty candidate review text from the assistant message.
14. Pass both the candidate and the current snapshot's complete changed filename set to deterministic review validation.
15. Return the candidate only after its structure and every Finding filename validate against that most recent snapshot.

Model content accompanying tool calls is not treated as a final review. A tool-calling round is counted once per assistant response containing one or more tool calls. The default limit is eight. The agent does not retry, ask for a rewrite, repair messages, fall back to an earlier Tool Result, or fabricate a result after any failure.

### 8.9 Review Format Validation

`review_validation.py` will accept the candidate Markdown plus the complete changed filename set from the most recent successful authoritative-target Tool Result. It will perform deterministic line- and section-based validation only. The system prompt will require the same canonical grammar.

When Findings exist, each block must have this canonical Markdown form:

```markdown
### Finding 1

- Severity: High
- File: src/example.py
- Location: line 10
- Issue: non-empty text
- Evidence: non-empty text
- Recommendation: non-empty text
```

The validator will verify:

1. `# Pull Request Review` and the five required `##` headings each occur exactly once.
2. The six headings occur in the required order and no required section is absent.
3. Every Finding heading is exactly `### Finding N`, where `N` starts at `1` and increases consecutively by one.
4. The next `### Finding N` heading is the only delimiter between multiple Finding blocks.
5. Each Finding contains each of `Severity`, `File`, `Location`, `Issue`, `Evidence`, and `Recommendation` exactly once and in that order.
6. Every field uses the exact `- Label: value` single-line form, and the value after the colon is non-empty.
7. Every severity is exactly `Critical`, `High`, `Medium`, or `Low`.
8. Every `File` value exactly equals one changed filename from the supplied most recent complete result.
9. An empty File, a directory name, a filename not returned by GitHub, a fabricated path, or multiple filenames combined in one field fails the exact-match check.
10. When no Finding exists, the Findings section contains no `### Finding N` heading and, apart from surrounding whitespace, contains only `No actionable issues identified from the available pull request data.`
11. A no-Finding report requires no filename match.
12. The Final Assessment section, after surrounding whitespace is removed, contains exactly one allowed value and nothing else.

Malformed, duplicated, missing, misnumbered, out-of-order, or filename-mismatched structure raises a clear review format or review contract validation error. The validator will not modify the candidate, request a model rewrite, retry, insert missing text, or output a partial result. Filename validation checks file identity only; it will not attempt to prove that Issue, Evidence, or Recommendation text is semantically true, that runtime behavior was verified, or that every possible issue was found.

### 8.10 Configuration

`config.py` will load `.env` values without overriding values already present in the process environment. It will read only the documented variable names.

Normalization will:

- trim the DeepSeek API key and raise a clear `ValueError` if it is missing or blank;
- trim base URLs and remove trailing slashes;
- trim the model name;
- apply defaults when optional values are absent or blank;
- never read `OPENAI_API_KEY` as a substitute; and
- avoid including the API key in object representations or error text.

The defaults remain:

- DeepSeek base URL: `https://api.deepseek.com`;
- DeepSeek model: `deepseek-v4-flash`; and
- GitHub API base URL: `https://api.github.com`.

### 8.11 CLI

`cli.py` will use `argparse` and provide:

- one required positional `pull_request_url`; and
- optional `--max-tool-rounds`, parsed as an integer and defaulting to `8`.

Values below one are rejected before agent execution. Normal argument errors use `argparse`'s normal nonzero behavior. For a valid invocation, the CLI loads configuration, parses the authoritative target, creates the HTTP and model clients, creates the agent, runs one review, and prints the returned review once.

Successful execution writes only the final review to standard output and exits with status zero. The CLI adds no prompt, progress output, debug logging, or browser action. Application and external exceptions are not caught or wrapped, and no automatic retry occurs.

## 9. Error and Exception Strategy

The implementation may use a small number of focused application exceptions, primarily `ValueError` or `RuntimeError` subclasses. A large exception hierarchy is unnecessary.

| Category | Source and behavior | Handling boundary |
| --- | --- | --- |
| Invalid URL | Application detects an unsupported component or path | Raise before any GitHub or DeepSeek request |
| Invalid configuration | Application detects a missing key or invalid normalized value | Raise a clear error; never include the key |
| GitHub connection, timeout, or HTTP error | `httpx` | Propagate the original exception unchanged |
| GitHub response decoding error | HTTP/JSON layer | Propagate the original decoding exception |
| GitHub data validation error | Application detects missing fields or wrong types | Raise a clear data-validation error |
| Changed-file integrity error | Application detects duplicate, incomplete, cyclic, excessive, contradictory, cross-origin, or resource-changing pagination | Raise before an invalid next request; expose no partial result |
| Invalid tool-call JSON | Standard JSON parser | Propagate or surface the parsing error; do not dispatch |
| Invalid tool arguments | Application detects root, key, value, or strict-type violations | Raise before dispatch |
| Unsupported tool | Application detects a tool name other than `get_pull_request` | Raise before dispatch |
| Authoritative target mismatch | Application compares a valid parsed call with the session target | Raise before any HTTP request |
| Invalid `max_tool_rounds` | Agent receives a bool, non-integer, `None`, or integer below one | Raise before the first model or tool call; do not coerce |
| Missing successful tool result | Model returns final text too early | Raise a clear runtime error |
| Maximum tool rounds exceeded | Model requests another tool round after the limit | Raise before tool execution or another model call |
| DeepSeek API error | OpenAI SDK | Propagate unchanged |
| Completion has no choice | Model-client adapter detects an empty choice list | Raise a clear completion-parsing error |
| Invalid final review format | Deterministic validator detects canonical grammar, Finding sequence, field, filename, or final-assessment violations | Raise a clear contract error; do not print or repair |

The CLI will not catch or wrap these errors. `argparse` remains responsible only for its own CLI syntax failures. Tests will assert both the error category and the absence of forbidden follow-on calls.

## 10. Security and Trust Boundaries

The main trust boundaries are the CLI input, environment, GitHub HTTP responses, and DeepSeek responses.

- Pull request title, body, filenames, patch text, and all other GitHub values are untrusted review data.
- Untrusted data cannot change the authoritative target, add tools, alter the tool schema, authorize GitHub writes, request code execution, or modify the system prompt.
- The system prompt will explicitly state that PR content is data rather than instructions and that the application is read-only.
- Target matching, strict tool validation, HTTP method selection, pagination integrity, and review validation are enforced in program logic. They do not rely on model compliance.
- Only `github_client.py` can issue GitHub requests, and its public operations use `GET` only.
- No GitHub token or `Authorization` header is accepted or generated.
- A Link header is untrusted input. A next URL must pass same-origin, authority, endpoint, pagination-query, and visited-URL checks before a request, and redirects remain disabled.
- The DeepSeek key is loaded only for the model client and is never placed in messages, tool results, logs, standard output, or error text.
- Pull request code is never cloned, imported, built, tested, or executed.
- A target mismatch fails before any HTTP request, even when another call in the same assistant message appears valid.
- Invalid or incomplete tool results never reach the model as successful review data.
- A Finding File is accepted only when it exactly matches a changed filename from the most recent complete target result; PR text cannot authorize a fabricated or combined path.
- Invalid model output never reaches standard output as a successful review.

Tests will verify enforcement at the program boundary rather than treating prompt text as the security mechanism.

## 11. Testing Strategy

### 11.1 Automated Test Principles

- Use pytest for all automated tests.
- Run Ruff against production and test files.
- Replace the DeepSeek client and GitHub transport with deterministic fakes or mocks.
- Load an autouse fixture from `tests/conftest.py` that fails any unexpected real socket or network attempt.
- Do not use real API keys, public pull requests, live GitHub, or live DeepSeek in automated tests.
- Do not disable the global network fixture in individual tests.
- Do not use `skip` or `xfail` to conceal required behavior.
- Keep test inputs local and synthetic.
- Assert observable behavior and contracts instead of incidental private structure.

The global fixture will use pytest monkeypatching and standard-library socket boundaries rather than adding `pytest-socket`. It will be active by default for the complete suite and raise an immediate, explicit test failure on an attempted real connection. `httpx.MockTransport`, mocked OpenAI clients, and in-memory fakes do not open sockets and remain usable. Slice 1 will include a self-test that attempts a standard-library connection and proves the guard blocks it. Real-network validation is never placed in pytest.

### 11.2 Coverage by Concern

| Concern | Test approach |
| --- | --- |
| URL parser | Table-driven valid and invalid cases for every component rule, including explicit port, user information, empty query/fragment delimiters, repeated slash, and extra path |
| Configuration | Controlled environment and `.env` fixtures; assert defaults, precedence, trimming, missing-key error, and secret absence |
| Domain parsing | Synthetic mappings for every field, wrong types, booleans as counts, missing fields, optional body, optional patch, and immutable outputs |
| GET-only GitHub | Inject a recording `httpx` transport and assert every request method is `GET` |
| No GitHub authorization | Assert every recorded request lacks `Authorization` and no configuration field accepts a token |
| HTTP propagation | Configure the transport to raise connection errors or return failing statuses; assert unchanged propagation and one attempt |
| Link pagination | Supply same-origin absolute and relative `next` links; assert standard URL resolution, exact authoritative files endpoint, pagination-only query, ordering, and final merge |
| Pagination trust boundary | Reject changed scheme, host, explicit port, userinfo, fragment, repository, PR number, endpoint, non-pagination query, current URL, and visited URL; assert no invalid next request and no redirect |
| Pagination integrity | Test duplicate filenames, repeated links, empty page with next, next link after expected count, missing next before expected count, and count overflow/mismatch |
| Tool schema | Assert object root, exact properties, all required fields, minimum one, and no additional properties |
| Tool calls | Test malformed JSON, non-object roots, missing/extra fields, strict types, unsupported names, IDs, and input immutability |
| Target binding | Vary owner, repository, and number individually and assert zero HTTP requests and no review |
| Messages | Assert assistant tool-call preservation, tool-call ID correlation, JSON serialization, omitted missing patch, and no mutation |
| Model client | Mock the OpenAI SDK and assert model, base configuration, tools, messages, disabled thinking, zero retries, no fallback, and no-choice handling |
| Agent history | Script single- and multi-round responses, compare history, and prove two successful results with different file sets leave only the most recent successful snapshot authoritative |
| Agent limits | Accept `1` and `8`; reject `0`, `-1`, `True`, `False`, `"8"`, `8.0`, and `None` before any dependency call; also test the first round beyond the valid limit |
| Tool-result prerequisite | Return final text before any successful target result and assert a runtime error with no output or retry |
| Review validation | Test canonical Finding numbering, exact field order and single-line values, valid changed filename, unknown filename, directory, combined filenames, empty File, no-Finding form, and every other malformed structure independently |
| CLI | Replace all dependencies, invoke arguments, assert default eight, dependency wiring, final-only standard output, status zero, and exception propagation |
| Input immutability | Deep-copy mutable fixtures before calls and compare them afterward across parsers, message builders, tool execution, and agent runs |
| Global network block | Prove a real socket attempt fails while `httpx.MockTransport`, mocked OpenAI clients, and in-memory fakes continue to work |

The complete automated suite must pass with network access unavailable. The test suite will not assert a coverage percentage, but every Requirements Section 17 category and AC-01 through AC-38 will have an explicit test or release verification.

### 11.3 Manual Versus Automated Validation

Automated tests prove deterministic application behavior with controlled external responses. One real public pull request end-to-end run is reserved for the release stage and remains outside pytest. Its purpose is compatibility validation, not a replacement for isolated tests.

### 11.4 Controlled Docker Workflow

The release-only `tests/docker_controlled_e2e.py` harness will run the built image's real console script against local standard-library HTTP services that emulate GitHub and DeepSeek. It is invoked explicitly, is not part of the default pytest suite, and does not require Docker in normal unit-test environments. Section 14 defines its full workflow and assertions.

## 12. Implementation Slices

### Slice 1 — Project Scaffolding and Configuration

**Objective**

Establish Python 3.12 packaging, development tooling, immutable configuration loading, and a testable package base.

**Files to create or modify**

- Create `pyproject.toml`.
- Create `.env.example`.
- Create `src/ai_github_reviewer/__init__.py`.
- Create `src/ai_github_reviewer/config.py`.
- Create `tests/conftest.py`.
- Create `tests/test_config.py`.

**Behavior implemented**

- Package metadata and runtime/development dependencies.
- Python 3.12 requirement.
- pytest and Ruff configuration.
- `.env` loading without process-environment override.
- exact variable names, defaults, trimming, base-URL normalization, and key validation.
- immutable configuration with secret-safe errors and representations.
- An autouse, standard-library-based network guard for every pytest test, without a new plugin dependency.

The console entry point will be activated in Slice 9, when a functioning CLI exists, rather than pointing packaging metadata at an incomplete module.

**Tests added**

- Required key present, missing, empty, and whitespace-only cases.
- Optional values absent, blank, padded, and explicitly set.
- Base URL trailing-slash removal.
- `OPENAI_API_KEY` is not used.
- Existing process environment takes precedence over `.env`.
- Key does not appear in errors or safe representations.
- A network-guard self-test proves an attempted real socket connection fails immediately.
- A controlled in-memory fake proves the guard does not prevent tests that use no real socket.

**Commands to validate**

- Run pytest for `tests/test_config.py`, including the network-guard self-test with `tests/conftest.py` active.
- Run Ruff against `src/ai_github_reviewer/config.py`, `tests/conftest.py`, and `tests/test_config.py`.
- Run package metadata validation available from the selected build backend.

**Acceptance Criteria covered**

- AC-16, AC-17, AC-22, and the scaffolding and network-isolation portions of AC-23.

**Explicit non-goals**

- No URL parser, GitHub client, model client, agent, CLI execution, documentation, Docker, or CI.

**Expected Git commit boundary**

- One commit after configuration tests and Ruff pass, proposed message: `chore: scaffold project configuration`.

### Slice 2 — Pull Request URL Parsing

**Objective**

Create the immutable authoritative target and strictly parse the only supported URL form before external access.

**Files to create or modify**

- Create `src/ai_github_reviewer/pull_request.py` with the target value only.
- Create `src/ai_github_reviewer/github_url.py`.
- Create `tests/test_github_url.py`.

**Behavior implemented**

- Standard-library parsing.
- Exact scheme, hostname, authority, port, query, fragment, path, trailing-slash, and positive-number rules.
- Construction of a new immutable authoritative target.
- Rejection before any external request is possible.

**Tests added**

- Accepted URL with and without one trailing slash.
- Extraction of owner, repository, and positive number.
- Every unsupported URL category, including user information, explicit `443`, query, fragment, enterprise, non-pull paths, missing segments, repeated trailing slashes, extra paths, and multiple CLI URL inputs at the later CLI boundary.
- Original input remains unchanged.

**Commands to validate**

- Run pytest for `tests/test_github_url.py`.
- Run Ruff against the new source and test files.

**Acceptance Criteria covered**

- AC-01, AC-02, AC-21, AC-33 target construction, and AC-35.

**Explicit non-goals**

- No HTTP, tool calling, model messages, or CLI wiring.

**Expected Git commit boundary**

- One commit after all URL cases pass, proposed message: `feat: parse GitHub pull request URLs`.

### Slice 3 — Pull Request Data Models and Parsing

**Objective**

Represent and validate metadata, changed files, and a complete tool result without mutating GitHub response objects.

**Files to create or modify**

- Extend `src/ai_github_reviewer/pull_request.py`.
- Create `tests/test_pull_request.py`.

**Behavior implemented**

- Immutable metadata, changed-file, and complete-result values.
- Validation of every Requirements Section 8 field and strict numeric types.
- Optional body handling.
- Missing patch representation and serialization policy.
- Complete-result count invariant.
- Fresh object construction from external mappings.

**Tests added**

- Valid metadata and file parsing.
- Missing and wrong-typed fields.
- Non-negative counts and boolean rejection.
- Body absent or empty.
- Patch present, absent, and empty as actually returned.
- Complete count match and mismatch.
- Caller inputs unchanged.

**Commands to validate**

- Run pytest for `tests/test_pull_request.py`.
- Run Ruff against the modified source and test files.

**Acceptance Criteria covered**

- AC-05, AC-06, AC-21, and data-validation portions of AC-19.

**Explicit non-goals**

- No network requests, pagination traversal, tool schema, or review generation.

**Expected Git commit boundary**

- One commit after domain parsing tests pass, proposed message: `feat: model pull request data`.

### Slice 4 — GitHub Read-Only Client

**Objective**

Fetch target metadata and all changed-file pages through public, unauthenticated, GET-only GitHub REST calls.

**Files to create or modify**

- Create `src/ai_github_reviewer/github_client.py`.
- Create `tests/test_github_client.py`.
- Modify `tests/test_pull_request.py` only if shared complete-result boundary cases require it.

**Behavior implemented**

- Metadata and files endpoint requests.
- No token or Authorization header.
- No retry.
- HTTP and connection exception propagation.
- Same-origin Link-header next-page resolution and authoritative files-endpoint validation.
- Redirect following disabled.
- Duplicate, cycle, empty-progress, overflow, missing-next, extra-next, and final-count checks.
- Complete-result construction only after integrity succeeds.

**Tests added**

- Recorded methods are all `GET`.
- Headers contain no Authorization.
- Correct endpoint inputs and normalized base URL.
- One page, multiple pages, and zero files.
- Valid same-origin absolute and relative Link next URLs are resolved and followed without page guessing.
- Changed scheme, host, explicit port, userinfo, fragment, repository, PR number, endpoint, and non-pagination query are rejected before a next-page request.
- Current-page and previously visited next URLs are rejected as loops.
- Every invalid next URL records no next-page request, no redirect, and no partial result.
- Every integrity failure produces no partial result.
- `404`, rate limit, connection, decoding, and malformed-data behavior.
- Each failure causes one attempt per reached page and no retry.
- The global network guard remains enabled while `httpx.MockTransport` supplies every response.

**Commands to validate**

- Run pytest for `tests/test_github_client.py` and `tests/test_pull_request.py`.
- Confirm the autouse network guard is active for the GitHub-client tests and is never locally disabled.
- Run Ruff against the GitHub and domain modules and tests.

**Acceptance Criteria covered**

- AC-04, AC-05, AC-06, AC-19, AC-22, AC-28, AC-32, AC-36, and AC-37.

**Explicit non-goals**

- No GitHub authentication, writes, cache, retry, model access, or agent loop.

**Expected Git commit boundary**

- One commit after all mocked pagination and HTTP tests pass, proposed message: `feat: fetch public pull request data`.

### Slice 5 — Tool Schema and Tool-Call Parsing

**Objective**

Expose exactly one strict tool and enforce schema, tool name, arguments, authoritative-target equality, and read-only dispatch.

**Files to create or modify**

- Create `src/ai_github_reviewer/tool_schema.py`.
- Create `src/ai_github_reviewer/tool_calls.py`.
- Create `tests/test_tool_schema.py`.
- Create `tests/test_tool_calls.py`.

**Behavior implemented**

- Exact `get_pull_request` JSON Schema.
- JSON parsing and object-root validation.
- Required and additional-field enforcement.
- Strict types and positive number validation.
- Unsupported-tool rejection.
- Immutable parsed tool call with identifier.
- Exact authoritative-target comparison before HTTP dispatch.
- Dispatch only to the injected GitHub client.

**Tests added**

- Full schema comparison.
- Invalid JSON and every root/type/key error.
- Unknown tool.
- Owner, repository, and number mismatches independently.
- Batch prevalidation prevents all HTTP when any call mismatches.
- Matching dispatch returns the controlled complete result.
- Argument, message, and target inputs remain unchanged.

**Commands to validate**

- Run pytest for the two tool test modules.
- Run Ruff against the new modules and tests.

**Acceptance Criteria covered**

- AC-03, AC-07, AC-19, AC-21, AC-32, and AC-33.

**Explicit non-goals**

- No model SDK request, message-history loop, or final review validation.

**Expected Git commit boundary**

- One commit after schema and dispatch tests pass, proposed message: `feat: validate pull request tool calls`.

### Slice 6 — DeepSeek Messages and Model Client

**Objective**

Construct immutable Chat Completions messages and provide a no-retry DeepSeek adapter through the OpenAI Python SDK.

**Files to create or modify**

- Create `src/ai_github_reviewer/messages.py`.
- Create `src/ai_github_reviewer/model_client.py`.
- Create `tests/test_messages.py`.
- Create `tests/test_model_client.py`.

**Behavior implemented**

- System and user messages with read-only and untrusted-data boundaries.
- Assistant tool-call message preservation.
- Correlated tool result messages.
- Complete result JSON serialization with omitted missing patches.
- DeepSeek base URL, model, key, tools, and message forwarding.
- Thinking disabled on every request.
- SDK retries disabled and errors propagated.
- First-choice extraction and no-choice error.

**Tests added**

- Exact message roles, ordering fields, and correlation IDs.
- Original messages and result objects remain unchanged.
- Serialized metadata and all files; absent patch is not invented.
- Mock SDK receives tools and disabled-thinking body.
- Configured model/base/key are used without fallback.
- API errors propagate and no-choice completions fail.
- No retry call is made.
- The mocked OpenAI client runs with the global network guard active and opens no socket.

**Commands to validate**

- Run pytest for `tests/test_messages.py` and `tests/test_model_client.py`.
- Confirm the autouse network guard remains enabled for all model-client tests.
- Run Ruff against the new modules and tests.

**Acceptance Criteria covered**

- AC-05, AC-06, AC-08 adapter foundation, AC-17, AC-19, AC-20, AC-21, and AC-22.

**Explicit non-goals**

- No agent loop, review-format validation, CLI, or live DeepSeek request.

**Expected Git commit boundary**

- One commit after mocked SDK and message tests pass, proposed message: `feat: integrate DeepSeek chat completions`.

### Slice 7 — Review Format Validation

**Objective**

Validate the deterministic final Markdown contract without judging natural-language correctness.

**Files to create or modify**

- Create `src/ai_github_reviewer/review_validation.py`.
- Create `tests/test_review_validation.py`.

**Behavior implemented**

- Unique required headings and exact ordering.
- Required sections.
- Canonical `### Finding N` blocks with consecutive numbering from one.
- Six single-line fields, each exactly once and in the required order.
- Exact changed filename matching against the supplied complete result.
- Findings/no-findings exclusive branch.
- Severity enumeration.
- Exact and exclusive no-actionable-issues sentence when no Finding exists.
- Exactly one allowed Final Assessment with no additional content.
- Clear error without repair, rewrite, retry, or partial output.

**Tests added**

- One compliant canonical report with one Finding and one with multiple consecutively numbered Findings.
- One compliant no-findings report.
- Missing, duplicated, and misordered headings.
- Missing, duplicate, or misordered finding labels; skipped or repeated Finding numbers; and empty or multiline field values.
- Illegal severity.
- Valid changed filename plus unknown filename, directory name, combined filenames, fabricated path, and empty File.
- No-Finding form requires no filename match and rejects any Finding heading or additional Findings text.
- Illegal, multiple, or additional Final Assessment content.
- Candidate input remains unchanged.

**Commands to validate**

- Run pytest for `tests/test_review_validation.py`.
- Run Ruff against the validator and tests.

**Acceptance Criteria covered**

- AC-09, AC-10, AC-11, AC-12, AC-19 format failures, AC-21, and AC-38, including canonical grammar and changed-filename validation.

**Explicit non-goals**

- No semantic truth scoring, model rewrite, content improvement, or model invocation.

**Expected Git commit boundary**

- One commit after every valid and invalid structure case passes, proposed message: `feat: validate review output`.

### Slice 8 — Agent Loop

**Objective**

Coordinate bounded single- and multi-round tool calling while enforcing the target-result prerequisite and final validation.

**Files to create or modify**

- Create `src/ai_github_reviewer/agent.py`.
- Create `tests/test_agent.py`.
- Modify `src/ai_github_reviewer/messages.py` or its tests only if agent integration exposes a missing message contract.

**Behavior implemented**

- Strict agent-boundary validation of `max_tool_rounds` before any model or tool call, with no type coercion and explicit bool rejection.
- Fresh system/user history.
- System prompt requirement for canonical `### Finding N` output.
- Tool definition on every model request.
- Complete assistant and tool result history.
- Prevalidation of all calls in a tool round.
- One or multiple tool rounds.
- Default-injected or configured maximum enforcement.
- At least one complete authoritative-target result before accepting final text.
- Replacement of the current snapshot after each later successful same-target Tool Call.
- Whole-run failure after a later Tool Call failure, with no fallback to an earlier snapshot.
- Candidate extraction and validation against the most recent successful result's changed filename set.
- Direct propagation of model, tool, HTTP, data, integrity, limit, prerequisite, and format errors.

**Tests added**

- Single-round success.
- Multiple-round success and exact histories.
- Multiple tool calls in one assistant response.
- Two successful same-target calls with different file collections; the final review passes only for the most recent collection.
- A later failed call after an earlier success fails the run and cannot produce a review from the older result.
- Model text before a successful result.
- Tool failure before success and after prior success.
- Target mismatch causes zero HTTP calls.
- Agent accepts `1` and `8` and rejects `0`, `-1`, `True`, `False`, `"8"`, `8.0`, and `None` before any model or tool call.
- The first tool-calling round beyond a valid limit fails.
- No model call beyond the limit.
- Content accompanying a tool call is not treated as final.
- A canonical candidate with a current changed filename is returned unchanged; stale or unknown filenames and other invalid candidates are not returned.
- Caller messages and fixtures remain unchanged.
- The global network guard remains active while agent dependencies are in-memory fakes.

**Commands to validate**

- Run pytest for `tests/test_agent.py` plus tool, message, and review-validator tests.
- Confirm the autouse network guard remains enabled for all agent tests.
- Run Ruff against all implemented source and tests.

**Acceptance Criteria covered**

- AC-03, AC-08, AC-09 through AC-15, AC-19 through AC-22, AC-33, AC-34, and AC-38.

**Explicit non-goals**

- No CLI parsing, real network use, retries, multi-agent coordination, streaming, or persistence.

**Expected Git commit boundary**

- One commit after all scripted agent flows pass, proposed message: `feat: implement review agent loop`.

### Slice 9 — CLI Integration

**Objective**

Provide the final non-interactive command, dependency wiring, exit behavior, and final-only standard output.

**Files to create or modify**

- Create `src/ai_github_reviewer/cli.py`.
- Create `tests/test_cli.py`.
- Modify `pyproject.toml` to activate the console script.

**Behavior implemented**

- Required URL positional argument.
- Optional integer `--max-tool-rounds` with default eight and minimum one.
- CLI rejection of non-integer text through `argparse`, while passing valid integers unchanged to the independently validating agent.
- Configuration and authoritative-target creation.
- HTTP client, model client, and agent construction.
- One review execution.
- One final review print and successful zero exit.
- No debug output, interactive input, browser action, exception wrapper, or retry.

**Tests added**

- Argument presence, default, explicit value, non-integer, and below-one cases.
- One URL only.
- Dependency construction receives the expected normalized configuration and target.
- Successful output is exactly the review plus normal terminal newline.
- No extra standard output.
- Application and external exceptions propagate.
- No real network or API key is required.
- The global network guard remains active for CLI dependency-wiring tests.

**Commands to validate**

- Run pytest for `tests/test_cli.py`.
- Run the complete pytest suite with network disabled.
- Confirm the autouse network guard is enabled and cannot be bypassed by CLI tests.
- Run Ruff against all source and tests.
- Invoke CLI help as a non-network smoke check.

**Acceptance Criteria covered**

- AC-13, AC-14, AC-16, AC-18, AC-19, AC-22, and the executable portion of AC-23.

**Explicit non-goals**

- No interactive mode, browser launch, streaming, automatic retry, or release artifacts.

**Expected Git commit boundary**

- One commit after CLI and complete isolated tests pass, proposed message: `feat: add AI GitHub Reviewer CLI`.

### Slice 10 — Documentation and Delivery

**Objective**

Complete user documentation, container and CI delivery, full verification, manual end-to-end validation, and the approved v0.1.0 release.

**Files to create or modify**

- Create `README.md`.
- Create `README.zh-CN.md`.
- Create `Dockerfile`.
- Create `.github/workflows/ci.yml`.
- Create `tests/docker_controlled_e2e.py`.
- Modify only existing delivery metadata if required for the accepted package.

**Behavior implemented**

- Consistent English and Chinese setup, configuration, usage, report, limitation, and security documentation.
- Safe Docker image that runs the CLI.
- GitHub Actions execution of pytest and Ruff on Python 3.12.
- No secret embedded in image, documentation, or workflow.
- Release-only controlled workflow using local fake GitHub and DeepSeek HTTP services and the image's real console script.
- Release readiness for a GitHub remote, `v0.1.0` tag, and GitHub Release after explicit approval.

**Tests added**

- No new behavioral tests unless delivery validation reveals an uncovered requirement.
- Docker build and `--help` or startup smoke test.
- Explicit controlled Docker review workflow with one Tool Call, a complete Tool Result, and a canonical final Finding.
- Assertions for final-only stdout, GET-only GitHub access, no Authorization header, tool schema, disabled thinking, and no GitHub writes.
- CI-equivalent full pytest and Ruff run.
- Dependency consistency check with `pip check`.
- Manual live E2E outside pytest.

**Commands to validate**

- Run the complete pytest suite with network disabled.
- Run Ruff against the repository's Python files.
- Run `pip check`.
- Build the Docker image and run a controlled non-secret smoke check.
- Run `tests/docker_controlled_e2e.py` explicitly outside pytest and verify the complete controlled workflow.
- Validate English and Chinese documentation against the accepted CLI.
- Run the manual E2E procedure in Section 14.
- Confirm a clean worktree before release operations.

**Acceptance Criteria covered**

- AC-17, AC-22 through AC-32, including AC-25's complete controlled container workflow, plus final verification of all earlier criteria.

**Explicit non-goals**

- No production mock server, private repositories, authentication, GitHub writes, web UI, streaming, retry, caching, background work, multiple PRs, enterprise support, local-repository analysis, code execution, RAG, memory, MCP, multiple agents, or provider switching.

**Expected Git commit boundary**

- One commit after documentation, Docker, CI, and all release checks pass, proposed message: `docs: prepare v0.1.0 release`. Remote configuration, tag creation, and GitHub Release occur only after explicit approval and do not change that commit.

## 13. Requirements Traceability

| Acceptance criterion | Implementation slice | Primary test area | Final verification |
| --- | --- | --- | --- |
| AC-01 | Slice 2 | `test_github_url.py` accepted cases | Parsed target equals all three expected values |
| AC-02 | Slice 2 | `test_github_url.py` invalid table | Every unsupported category fails before external calls |
| AC-03 | Slices 5 and 8 | `test_tool_calls.py`, `test_agent.py` | Agent GitHub access occurs only through tool dispatch |
| AC-04 | Slice 4 | `test_github_client.py` recording transport | All recorded GitHub methods are `GET` |
| AC-05 | Slices 3, 4, and 6 | Domain, client, and serialization tests | Complete metadata and file fields reach the tool result |
| AC-06 | Slices 3, 4, and 6 | Missing-patch cases | Missing patch remains absent through model serialization |
| AC-07 | Slice 5 | `test_tool_schema.py`, `test_tool_calls.py` | Exact schema and strict argument rejection pass |
| AC-08 | Slices 6 and 8 | Model adapter and agent success flow | Controlled tool result produces a structured candidate |
| AC-09 | Slices 7 and 8 | Required-heading validator cases | Successful output contains all headings once in order |
| AC-10 | Slice 7 | Canonical Finding and filename cases | Consecutive `### Finding N` blocks have ordered fields, allowed severity, and a File from the current result |
| AC-11 | Slices 7 and 8 | Exclusive no-Finding report and agent flow | Exact no-issues statement is the only Findings content and requires no filename match |
| AC-12 | Slice 7 | Final Assessment cases | Exactly one allowed value and no extra content passes |
| AC-13 | Slices 8 and 9 | Agent strict-value and CLI default cases | Omitted CLI option supplies integer eight and the agent independently accepts it |
| AC-14 | Slices 8 and 9 | Agent type/minimum matrix, CLI invalid values, and loop-limit cases | Bool, non-integers, and values below one fail before calls; the first excess round makes no follow-on call |
| AC-15 | Slice 8 | Single- and multi-round histories | Correlated histories match expected order |
| AC-16 | Slices 1 and 9 | Configuration and CLI wiring tests | Defaults, normalization, and missing-key behavior pass |
| AC-17 | Slices 1, 6, and 10 | Secret scanning and controlled errors | Key is absent from tracked content, output, messages, and errors |
| AC-18 | Slice 9 | CLI success case | Standard output contains only final review and status is zero |
| AC-19 | Slices 1–9 | Failure tests including next-URL trust, strict limits, and review contracts | Required exceptions propagate with no retry, fallback, repair, or fabricated output |
| AC-20 | Slice 6 | Empty-choice completion | Clear completion error and no review |
| AC-21 | Slices 2, 3, 5–8 | Deep-copy immutability assertions | Every caller-owned fixture remains equal after invocation |
| AC-22 | Slices 1, 4, 6, and 8–10 | Autouse network-guard self-test and complete suite | Full pytest suite passes with `tests/conftest.py` active and every unexpected socket attempt fails |
| AC-23 | Slices 1, 9, and 10 | Network-isolated complete pytest and Ruff runs | Both tools pass with the global guard enabled and without skip, xfail, or local guard disabling |
| AC-24 | Slice 10 | Documentation review | English and Chinese behavior and usage remain consistent |
| AC-25 | Slice 10 | Docker build, smoke check, and `docker_controlled_e2e.py` | Image builds and its real CLI completes a full controlled GitHub/DeepSeek review workflow |
| AC-26 | Slice 10 | CI-equivalent local run and workflow run | Workflow runs pytest and Ruff successfully |
| AC-27 | Slice 10 | Manual E2E checklist | One public PR produces the complete validated review |
| AC-28 | Slices 4 and 10 | Header assertions and manual E2E | No token configuration or GitHub authorization credential |
| AC-29 | Slice 10 | Git history and tag inspection | Meaningful slice commits and accepted `v0.1.0` tag exist |
| AC-30 | Slice 10 | Release inspection | GitHub Release points to the accepted tag |
| AC-31 | All slices | Scope review per slice and release audit | No out-of-scope capability is required or exposed |
| AC-32 | Slices 4, 5, and 10 | GET-only tests and manual observation | No review, comment, or mutation request is sent |
| AC-33 | Slices 2, 5, and 8 | Target construction and mismatch cases | Each mismatch fails before HTTP and cannot replace target |
| AC-34 | Slice 8 | Early-final-response cases | No successful target result causes runtime failure and no output |
| AC-35 | Slice 2 | Exact URL component table | Every forbidden authority, suffix, query, and fragment fails early |
| AC-36 | Slice 4 | Same-origin absolute/relative Link response sequences | Validated authoritative-files pages merge once and count equals metadata |
| AC-37 | Slice 4 | Data and next-URL integrity matrix | Duplicate, incomplete, cyclic, cross-origin, resource-changing, and contradictory data fail before invalid access |
| AC-38 | Slices 7 and 8 | Canonical format, latest-result filename, and agent-boundary matrix | Only a canonical review whose Files belong to the most recent successful result reaches the CLI |

Every acceptance criterion is mapped to at least one implementation slice, an automated test area or release check, and a concrete final verification.

## 14. Manual End-to-End Validation

Release validation contains two separate workflows. The controlled Docker workflow proves the built artifact against local deterministic services. The live workflow then checks compatibility with one real public pull request. Neither workflow is part of pytest.

### 14.1 Controlled Docker Workflow

The explicitly invoked `tests/docker_controlled_e2e.py` harness will:

1. Use only the Python standard library to start local controlled HTTP services for a fake GitHub metadata/files API and a fake DeepSeek Chat Completions API.
2. Make the GitHub service return valid metadata and at least one changed file, using either a single page or a verifiable same-origin pagination sequence.
3. Make the DeepSeek service return a target-matching `get_pull_request` Tool Call on the first completion and a canonical final Review on the second completion.
4. Ensure the canonical Finding uses the exact changed filename returned by the GitHub service.
5. Start the final built image's real console script with a fictional but structurally valid public GitHub pull request URL.
6. Point `GITHUB_API_BASE_URL` and `DEEPSEEK_BASE_URL` to the host-controlled services and supply a fake, non-sensitive DeepSeek key.
7. Use `host.docker.internal` when Docker Desktop provides it; on Linux, add an explicit `host-gateway` mapping so the container can reach only the intended host services.
8. Assert container exit status zero and standard output containing only the complete validated Review.
9. Assert the six required headings, canonical Finding numbering and fields, allowed severity, exact changed filename, and final assessment.
10. Assert that the GitHub mock received only `GET`, received no `Authorization` header, and received no review, comment, or other write request.
11. Assert that DeepSeek received the single Tool Schema, thinking disabled, the assistant/tool message sequence, and the complete Tool Result before returning the final Review.
12. Shut down both services and all container/process resources even when an assertion fails.

The harness never contacts real GitHub or DeepSeek, is not collected by default pytest, and does not require Docker in ordinary unit-test environments. A Docker `--help` or startup smoke check remains required but cannot replace this controlled workflow.

### 14.2 Live Public Pull Request Validation

The live run occurs only after the automated suite, Ruff, dependency checks, Docker smoke check, and controlled Docker workflow pass.

The release operator will:

1. Use a local, ignored `.env` with a valid DeepSeek key and the documented defaults or approved endpoint values.
2. Select one real public pull request without recording its URL or user data in tracked files.
3. Record the pull request's visible state before the run.
4. Invoke the installed CLI once with the standard public pull request URL.
5. Confirm exit status zero and confirm standard output contains only the review.
6. Confirm all six headings occur exactly once and in order.
7. Confirm Findings follows either the complete finding-field form or the exact no-issues form.
8. Confirm Final Assessment is one allowed value with no additional content.
9. Confirm no API key appears in output.
10. Confirm the pull request state, reviews, and comments were not changed by the application.
11. Record only the pass/fail checklist and non-sensitive environment/version information needed for release approval.

The live run will not be placed in pytest, automatically retried, or used to execute pull request code. A failure blocks release and is diagnosed without fabricating a successful result.

## 15. Delivery and Release Plan

Release work begins only after Slices 1–9 are approved and their tests pass.

1. Complete both READMEs with consistent commands, configuration, output contract, failure behavior, and limitations.
2. Build a minimal Python 3.12 Docker image without embedding `.env` or secrets.
3. Add GitHub Actions to install the project and run pytest and Ruff.
4. Run the complete network-isolated automated suite with the global guard active, then run Ruff and `pip check`.
5. Build and smoke-test the Docker image.
6. Run the complete controlled Docker workflow against local fake GitHub and DeepSeek services.
7. Perform the live public-pull-request E2E checklist.
8. Review the complete Git history and confirm each accepted slice has a meaningful commit boundary.
9. Create or configure a GitHub remote only with explicit authorization.
10. Push only with explicit authorization and after confirming the intended target.
11. Create the annotated or lightweight `v0.1.0` tag only after final acceptance.
12. Create the GitHub Release from that exact tag with release notes that do not expose secrets or personal data.
13. Verify the tag and Release correspond to the accepted commit.

Remote creation, push, tag, and Release are release-stage external actions. This plan does not authorize or perform them.

## 16. Out of Scope

v0.1.0 will not implement:

- private repositories;
- GitHub Token authentication;
- GitHub Apps;
- GitHub OAuth;
- automatic review publication;
- automatic comments;
- automatic code modification;
- automatic fix commits;
- pull request merge or close;
- a web UI;
- streaming;
- automatic retries;
- caching;
- background tasks;
- multiple pull requests per invocation;
- GitHub Enterprise;
- local repository analysis;
- running, building, importing, testing, or executing pull request code;
- RAG;
- persistent memory;
- MCP;
- multiple agents;
- provider switching; or
- multi-model comparison.

No slice may add an abstraction intended solely for one of these excluded capabilities.

The local HTTP services in `tests/docker_controlled_e2e.py` are release-test fixtures only. They are not production background services, product endpoints, or a web UI.

## 17. Plan Completion Criteria

This implementation plan is ready for approval when:

1. all 17 required top-level sections are present;
2. every proposed module has one stated responsibility;
3. the core immutable data values and serialization policy are defined;
4. URL, target binding, GitHub access, trusted pagination, tool parsing, DeepSeek, latest-result agent state, canonical review validation, and CLI decisions are explicit;
5. errors are classified as application-owned or directly propagated;
6. the trust boundaries are enforceable outside the prompt;
7. guarded pytest, controlled Docker validation, and live manual E2E are clearly separated;
8. all ten slices include objective, files, behavior, tests, validation commands, AC coverage, non-goals, and a commit boundary;
9. AC-01 through AC-38 each map to implementation, test, and final verification;
10. release work preserves explicit approval boundaries for remote, push, tag, and Release; and
11. no production code, test code, configuration, dependency installation, or out-of-scope capability is created during this planning step.

Implementation may begin only after this plan is reviewed and the next slice is explicitly authorized.
