# AI GitHub Reviewer

[English](README.md) | 简体中文

AI GitHub Reviewer 是一个单 Agent、只读 Reviewer，同时提供命令行界面和同步的
public Python API。它使用 DeepSeek 的 OpenAI-compatible Chat Completions API 与
唯一严格的 `get_pull_request` 工具审查一个公开 GitHub Pull Request。CLI 输出校验
后的 Markdown；Python API 返回同一 Markdown 与不可变的结构化结果。

## v0.2.0

v0.2.0 通过稳定的 public Python 集成边界，使现有 Review 核心可被复用。

### 新增

- `ReviewerConfig`、`ReviewerRunner` 与 `create_reviewer(...)`。
- Typed `ReviewResult` 与 public Review DTO。
- Public 分类异常契约。
- 通过 `ReviewService` 实现依赖注入。
- 明确且幂等的 `close()` 生命周期。

### 安全边界

- CLI 与 Public Runner 均保持匿名 GitHub REST GET-only。
- 不接受也不支持 GitHub token。
- 两种接口均不能 comment、提交 Review、approve、request changes，也不能修改仓库或
  Pull Request。

### 兼容性

- 现有 CLI 及其行为保持可用。
- v0.2.0 未把 CLI 迁移或替换为 Public Runner。
- 两种接口复用现有 Review 核心；未来 Workbench 集成可以使用 typed result，无需
  解析 Markdown。

## 主要特性

- 严格解析标准 `github.com` Pull Request URL。
- 从用户 URL 得到不可变的 authoritative Pull Request target。
- 对 GitHub API 仅进行未认证的 GET 只读访问。
- 完整取得 Pull Request metadata 和 changed files，并安全处理分页。
- 有明确上限且可配置的 Tool Calling 循环。
- 确定性的最终 Markdown Review 校验。
- 提供具有明确配置和生命周期边界的 typed public runner API。
- CLI 成功时只输出最终结果，不输出进度或调试文本。
- 自动化测试具有全局网络隔离。
- 提供最小 Docker 交付和 GitHub Actions CI。

## 只读与信任模型

AI GitHub Reviewer 是只读工具。该边界同时适用于 CLI 与 Public Runner：两者仅接受
公开 Pull Request，只发送匿名 GitHub REST GET 请求；均不接受 `GITHUB_TOKEN`，也
不提供 GitHub 写操作。

应用不会发布 GitHub Review、创建评论、合并或关闭 Pull Request，也不会以其他
方式写入 GitHub。应用不接受 GitHub token。Pull Request 的 title、body、patch、
filename 和 Tool Result 都是不可信数据。模型不能替换或重新定义 authoritative
target。GitHub 数据只能通过调度 `get_pull_request` 工具取得。

应用不会执行、构建、导入或测试 Pull Request 代码，也不会分析本地仓库。所有结论
只能基于最近一次成功且完整的 Tool Result。

## 环境要求

- Python 3.12 或更高版本。
- 有效的 DeepSeek API key。
- 一个托管在 `github.com` 上的公开 Pull Request。
- 仅在使用容器流程时需要 Docker。

## 安装

创建并激活虚拟环境，然后安装应用：

```console
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

开发和质量检查安装：

```console
python -m pip install -e ".[dev]"
```

不需要也不支持 GitHub token。

## Public Python API

Public API 是同步接口且不会打印 Review。Runner 持有 GitHub 与模型 client，调用方
必须关闭它：

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

`ReviewerConfig` 必须提供 `deepseek_api_key`，默认值为
`deepseek_base_url="https://api.deepseek.com"`、
`deepseek_model="deepseek-v4-flash"`、
`github_api_base_url="https://api.github.com"` 与 `max_tool_rounds=8`。

`ReviewResult` 仅包含以下 public result 字段：

- `target`
- `pull_request`
- `summary`
- `findings`
- `test_gaps`
- `maintainability`
- `assessment`
- `markdown`

每个 `ReviewFinding` 包含 `severity`、`file_path`、`location`、`issue`、`evidence` 与
`recommendation`。API 不会伪造 confidence、metrics、token usage、数字 risk score、
精确 diff position 或自动 comment ID。

根包还导出稳定的配置、无效 Pull Request URL、GitHub retrieval、模型执行、Review
protocol validation 与 close 后使用等异常类型。原始原因通过异常链保留，secret 不会
复制到 public error message。

Public factory 保持与 CLI 相同的匿名 GitHub REST GET-only 边界。它不接受 GitHub
token，也不提供 comment、review、approve、request changes、merge 或其他写操作。

## 配置

将 `.env.example` 复制为已被 Git 忽略的 `.env`，并填写 DeepSeek key：

```console
cp .env.example .env
```

| 变量 | 必需 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | 无 | DeepSeek API 认证。 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` | OpenAI-compatible DeepSeek API base URL。 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-v4-flash` | 用于审查的模型。 |
| `GITHUB_API_BASE_URL` | 否 | `https://api.github.com` | 公开 GitHub REST API base URL。 |

base URL 末尾的 slash 会被规范化。缺失或空白的 `DEEPSEEK_API_KEY` 会导致配置加载
失败。应用不会读取 `OPENAI_API_KEY` 作为 fallback。`.env` 已被 Git 忽略；不要提交
真实 Secret。

## CLI 用法

审查一个 Pull Request：

```console
ai-github-reviewer PULL_REQUEST_URL
```

显式设置 Tool Calling 轮次上限：

```console
ai-github-reviewer PULL_REQUEST_URL --max-tool-rounds 8
```

查看模块帮助：

```console
python -m ai_github_reviewer.cli --help
```

只接受一个 URL。`--max-tool-rounds` 默认为 `8`，最小值为 `1`。成功时退出状态为
`0`，stdout 只包含最终校验通过的 Review。应用异常由 CLI 原样传播，不进行包装。

## 支持的 Pull Request URL

只接受以下标准形式：

```text
https://github.com/OWNER/REPOSITORY/pull/NUMBER
https://github.com/OWNER/REPOSITORY/pull/NUMBER/
```

`NUMBER` 必须是正整数。HTTP、hostname 不精确等于 `github.com`、userinfo、显式
端口、query string、fragment、额外 path、多个 URL、GitHub Enterprise URL 以及
其他 GitHub 资源类型，都会在任何 GitHub 或 DeepSeek 请求前被拒绝。

## Review 格式

成功 Review 必须按以下顺序且仅包含这六个标题：

```text
# Pull Request Review
## Summary
## Findings
## Test Gaps
## Maintainability
## Final Assessment
```

每个 Finding 从 1 开始连续编号，使用 `### Finding N`，并严格按以下字段顺序：

```text
### Finding 1

- Severity: Low
- File: src/example.py
- Location: line 10
- Issue: non-empty text
- Evidence: non-empty text
- Recommendation: non-empty text
```

`Severity` 只能是 `Critical`、`High`、`Medium` 或 `Low`。`File` 必须精确匹配
最近一次成功且完整的 Tool Result 中的 changed filename。没有可靠、可操作的问题时，
Findings 章节只能包含：

```text
No actionable issues identified from the available pull request data.
```

Final Assessment 章节只能包含以下一个值：

```text
Approve
Approve with minor comments
Request changes
Insufficient data
```

应用不会声称该 Review 已发布到 GitHub。

## 失败行为

无效 URL、缺失 API key、GitHub HTTP 或 rate-limit 错误、无效 GitHub response、
不完整 changed-file 数据、无效 Tool Call、target mismatch、Tool 轮次耗尽、模型
completion 错误以及无效最终 Review 都会明确失败。失败时不 retry、不 fallback、不
repair、不 rewrite，也不会输出部分 Review。

## 测试与质量

```console
python -m pip check
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

pytest 使用全局 network guard 阻断真实 socket 连接。默认 pytest 不收集或运行
controlled Docker E2E harness。

## Docker

构建 release image：

```console
docker build --tag ai-github-reviewer:0.2.0 .
```

检查容器 CLI：

```console
docker run --rm ai-github-reviewer:0.2.0 --help
```

审查一个公开 Pull Request：

```console
docker run --rm --env-file .env ai-github-reviewer:0.2.0 https://github.com/OWNER/REPOSITORY/pull/NUMBER
```

Dockerfile 不复制 `.env`，image 中不嵌入 Secret。image 的默认入口是
`ai-github-reviewer`。

## Controlled Docker E2E

构建本地 controlled image 后，显式执行 release harness：

```console
docker build --tag ai-github-reviewer:controlled .
python3.12 tests/docker_controlled_e2e.py --image ai-github-reviewer:controlled
```

harness 使用 image 中的真实 CLI 访问本地 fake GitHub 和 fake DeepSeek 服务，不
接触真实服务，也不属于默认 pytest。它验证 GitHub GET-only、无 GitHub
Authorization、Tool Calling history、disabled thinking、final-only stdout 和
canonical Review 格式。

## 持续集成

`.github/workflows/ci.yml` 中的 workflow 使用 Python 3.12，并执行 `pip check`、
pytest、Ruff lint 和 Ruff format 检查。它不需要 Secret，也不进行真实 API 请求。
workflow 不运行 controlled Docker E2E 或 live E2E。

## Manual Live E2E Checklist

只有在自动化测试、Ruff、`pip check`、Docker build 和 controlled E2E 全部通过后，
才执行以下 checklist：

1. 把有效的 DeepSeek key 放入本地且被忽略的 `.env`。
2. 选择一个真实公开 Pull Request，不把它的 URL 或个人数据写入 tracked file。
3. 只运行一次 CLI，不增加自动 retry。
4. 检查退出状态为 `0`，并且 stdout 只有 Review。
5. 检查六个 heading 唯一且顺序准确。
6. 检查每个 Finding 符合固定 grammar，Final Assessment 是允许值。
7. 检查输出中没有 API key。
8. 检查 GitHub Pull Request 的 state、reviews 和 comments 均未变化。

v0.2.0 Public Runner 已由用户对公开 Pull Request
`openai/openai-python#3357` 完成人工验证：

- Public Runner Real E2E：PASS
- ReviewResult：PASS
- Structured finding：PASS（1 个 finding）
- Assessment：`Approve with minor comments`
- Validated Markdown：PASS
- GitHub write：NONE
- Lifecycle close：PASS

## 限制和范围外事项

v0.2.0 不包含 private repositories；GitHub tokens、Apps 和 OAuth；自动发布
Review；comments；代码修改或 fix commit；merge 或 close；Web UI；streaming；
retries；caching；background work；多个 Pull Requests；GitHub Enterprise；本地
仓库分析；Pull Request 代码执行；RAG；persistent memory；MCP；multiple agents；
provider switching；multi-model comparison。

## 发布状态

当前 package version 为 `0.2.0`，作为 reusable public Python API release 进行发布
准备。tag、push 与 GitHub Release 属于后续独立发布操作。
