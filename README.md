# miniClaudeCode

miniClaudeCode 是一个用 Python 实现的轻量级 AI Coding Agent 工程项目。它不是简单的聊天壳，也不是只包装一次 API 调用，而是围绕真实代码智能体需要的运行时、工具调用、长任务执行、工程验证、Git 闭环和长期记忆做了一套可阅读、可测试、可演示的最小实现。

项目目标是把 Claude Code 类终端编程助手的关键工程链路拆开，用较小代码规模复现核心思想，并在此基础上做工程化增强。

## 项目定位

```text
用户请求
  |
  v
AgentLoop
  |
  v
Tool Runtime
  |
  v
Planner Executor Evaluator Harness
  |
  v
Git Workflow 工程闭环
  |
  v
Memory and Context Engineering
```

当前项目已经形成四个核心工程模块：

| 模块 | 解决的问题 | 产出 |
| --- | --- | --- |
| Tool Runtime | 工具调用如何安全、可观测、可扩展地执行 | 插件式工具发现、schema 校验、权限、diff preview、超时、重试、压缩、tracing |
| Planner Executor Evaluator Harness | 长任务如何拆解、执行、验证和修复 | run artifacts、task plan、evaluator report、final report、repair loop |
| Git Workflow 工程闭环 | 代码改动如何被检查、总结和提交前验证 | worktree inspect、diff summary、test runner、commit message suggestion |
| Memory and Context Engineering | Agent 如何沉淀项目认知并选择上下文 | project memory、file summary、task memory、context builder、context compression |

## 核心亮点

### 1. Tool Runtime

传统教学型 Agent 项目常见做法是把工具硬编码到 registry 里，然后直接执行模型返回的 tool_use。miniClaudeCode 把这一层升级成独立运行时。

| 能力 | 说明 |
| --- | --- |
| 工具自动发现 | 扫描 `miniclaudecode.tools` 包，自动发现所有 `Tool` 子类 |
| 工具名重复检测 | registry 注册时检测重复工具名 |
| JSON Schema 校验 | 执行前校验模型传入参数 |
| 错误类型标准化 | `unknown_tool`、`validation_error`、`permission_denied`、`timeout_error`、`execution_error` 等 |
| 权限检查 | 支持 ask、auto、plan 三种模式 |
| Diff preview | `write_file` 和 `edit_file` 在写入前生成 unified diff |
| 用户确认 | ask 模式下可确认或拒绝写操作 |
| 超时控制 | Runtime 层提供统一超时，bash 工具自身也有 subprocess timeout |
| 重试机制 | 只读工具可配置 retryable |
| 结果压缩 | 长工具输出按 head 和 tail 压缩，避免塞爆上下文 |
| Tracing | 工具调用以 JSONL 事件写入 `.miniclaudecode/traces` |

核心文件：

```text
miniclaudecode/runtime/tool_runtime.py
miniclaudecode/runtime/tool_loader.py
miniclaudecode/runtime/schema_validator.py
miniclaudecode/runtime/compression.py
miniclaudecode/runtime/tracing.py
miniclaudecode/tools/base.py
```

### 2. Planner Executor Evaluator Harness

长任务不能只靠一次 AgentLoop 直接执行。miniClaudeCode 增加了轻量 Harness，把一次需求拆成结构化任务，执行后用确定性检查验证，并在失败时把 evaluator feedback 回传给执行器。

| 能力 | 说明 |
| --- | --- |
| ArtifactStore | 每次 run 创建独立目录 |
| Planner | 生成结构化 plan 和 task markdown |
| Executor | 构造任务 prompt 并调用 AgentLoop 或兼容 runner |
| Evaluator | 运行 `python -m unittest discover`、`python -m compileall`、`git diff --stat` 等确定性检查 |
| Repair loop | 失败后将 evaluator feedback 注入下一轮执行 |
| Final report | 汇总 task、events、tool traces、evaluation checks、repair rounds、Git diff 和测试结果 |
| CLI 接入 | 支持 `--run-harness` 和 `--list-runs` |

运行产物示例：

```text
.miniclaudecode/runs/<run_id>/
  request.md
  spec.md
  plan.json
  events.jsonl
  tasks/
  evaluator_reports/
  traces/
  final_report.md
```

### 3. Git Workflow 工程闭环

代码 Agent 最终必须落到工程交付。miniClaudeCode 增加了 Git Workflow 层，把工作区状态、diff、测试结果和提交信息建议整合成报告。

| 能力 | 说明 |
| --- | --- |
| WorktreeInspector | 读取 branch、changed、staged、untracked、dirty 状态 |
| DiffSummary | 解析 `git diff --numstat`，生成文件级增删统计 |
| TestRunner | 运行测试命令并截断超长输出 |
| CommitMessageGenerator | 根据 diff 和测试结果生成提交信息建议 |
| GitWorkflow | 串联 inspect、diff、test、commit message |
| CLI 接入 | 支持 `--git-summary` 和 `--git-commit-message` |
| Memory 接入 | GitWorkflow report 可转换为 TaskMemory |

### 4. Memory and Context Engineering

Agent 如果每次任务都重新扫描项目，会浪费上下文，也无法复用历史工程判断。miniClaudeCode 增加了文件化长期记忆和上下文选择层。

| 能力 | 说明 |
| --- | --- |
| Memory Records | 定义 `FileSummary`、`ProjectSummary`、`DecisionRecord`、`TaskMemory`、`ContextBundle` |
| MemoryStore | 将记忆写为 Markdown，同时内嵌 JSON 元数据保证结构化读取 |
| ProjectIndex | 扫描 tracked 和未忽略文件，过滤 `.git`、`.env`、虚拟环境和缓存目录 |
| Summarizer | 不依赖 LLM，确定性提取 Python symbol、Markdown heading 和文本预览 |
| ContextBuilder | 根据当前任务关键词选择相关文件摘要、工程决策和历史任务 |
| Context compression | 按字符预算裁剪 task memory、decision 和 file summary |
| CLI 接入 | 支持 memory index、memory context 和 memory list |
| Harness 接入 | Harness 完成后写入 TaskMemory |
| GitWorkflow 接入 | GitWorkflow 分析结果写入 TaskMemory |

运行产物示例：

```text
.miniclaudecode/memory/
  project.md
  files/
  decisions/
  tasks/
  context/
```

## 快速开始

建议使用 Python 3.11 或更新版本。项目依赖以 `pyproject.toml` 为权威来源，`requirements.txt` 保留给习惯使用 `pip install -r requirements.txt` 的环境。

创建虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS 或 Linux:

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

只安装运行依赖：

```bash
python -m pip install -e .
```

配置 Anthropic API Key：

```powershell
$env:ANTHROPIC_API_KEY="你的 API Key"
```

macOS 或 Linux:

```bash
export ANTHROPIC_API_KEY="你的 API Key"
```

## CLI 使用

### 基础 Agent

启动交互式聊天：

```bash
python -m miniclaudecode chat
```

一次性执行 prompt：

```bash
python -m miniclaudecode run "帮我查看当前目录有哪些 Python 文件"
```

查看当前可用工具：

```bash
python -m miniclaudecode tools
```

检查配置、工具和 API Key 状态：

```bash
python -m miniclaudecode doctor
```

兼容旧的 prompt 写法：

```bash
python -m miniclaudecode "帮我查看当前目录有哪些 Python 文件"
```

指定模型、权限模式和最大循环轮数：

```bash
python -m miniclaudecode --model claude-sonnet-4-20250514 --mode ask --max-turns 30 chat
```

指定配置文件：

```bash
python -m miniclaudecode --config miniclaudecode.config.json "查看项目状态"
```

交互模式命令：

| 命令 | 作用 |
| --- | --- |
| `/tools` | 查看当前注册工具 |
| `/mode` | 查看当前权限模式 |
| `/mode ask` | 切换到 ask 模式 |
| `/mode auto` | 切换到 auto 模式 |
| `/mode plan` | 切换到 plan 模式 |
| `/help` | 查看帮助 |
| `/quit` | 退出 |

### Harness

列出历史 run：

```bash
python -m miniclaudecode --list-runs
```

运行长任务 Harness：

```bash
python -m miniclaudecode --run-harness "实现一个新功能"
```

指定多个任务：

```bash
python -m miniclaudecode --run-harness --harness-task "实现核心逻辑" --harness-task "补充测试" "实现一个新功能"
```

### Git Workflow

输出 Git 工程报告：

```bash
python -m miniclaudecode --git-summary
```

跳过测试，只生成 Git 报告：

```bash
python -m miniclaudecode --git-summary --skip-git-tests
```

只输出提交信息建议：

```bash
python -m miniclaudecode --git-commit-message --skip-git-tests
```

### Memory

刷新项目 memory：

```bash
python -m miniclaudecode --memory-index
```

为当前任务构建上下文：

```bash
python -m miniclaudecode --memory-context "优化 ToolRuntime 的错误分类"
```

查看 memory 记录数量：

```bash
python -m miniclaudecode --list-memory
```

推荐演示流程：

```bash
python -m miniclaudecode --memory-index
python -m miniclaudecode --memory-context "优化 ToolRuntime 的错误分类"
python -m miniclaudecode --git-summary --skip-git-tests
python -m miniclaudecode --list-memory
```

## 内置工具

| 工具名 | 作用 |
| --- | --- |
| `bash` | 执行 shell 命令，带危险命令拦截和超时 |
| `read_file` | 读取文本文件并返回带行号内容 |
| `write_file` | 写入文件，支持 diff preview |
| `edit_file` | 精确字符串替换，支持 diff preview |
| `glob` | 按 glob 规则查找文件 |
| `grep` | 搜索文件内容，优先使用 ripgrep |

只读工具具备 retryable 和 read_only 标识，写入和 bash 默认不自动重试。

## 权限模式

| 模式 | 行为 |
| --- | --- |
| ask | 默认模式。危险操作和写操作需要确认 |
| auto | 自动执行通过工具自检的操作 |
| plan | 只读模式，阻止 bash、write_file、edit_file |

ask 模式的交互式确认会展示工具名、目标路径或命令、风险说明和 diff 摘要。用户可以选择：

```text
o / once    允许本次执行
a / always  对同一命令或同一工具目标永久允许
d / deny    拒绝执行
```

权限检查由工具自检、工作区边界和全局权限模式共同决定。

## 配置

配置分为 `ModelConfig`、`ToolRuntimeConfig`、`SafetyConfig` 和 `HarnessConfig`。

加载优先级：

```text
默认值 < JSON 配置文件 < 环境变量 < CLI 参数
```

示例配置文件：

```json
{
  "model": {
    "model": "claude-sonnet-4-20250514",
    "max_turns": 30,
    "max_context_messages": 100
  },
  "tool_runtime": {
    "max_output_chars": 50000,
    "max_tool_result_chars": 12000,
    "tool_result_head_chars": 8000,
    "tool_result_tail_chars": 4000,
    "enabled_tools": [],
    "disabled_tools": []
  },
  "safety": {
    "workspace_root": ".",
    "permission_mode": "ask",
    "allowed_commands": ["ls", "cat", "git status", "git diff", "python3"],
    "denied_patterns": ["rm -rf /", "git reset --hard", "git push --force"]
  },
  "harness": {
    "runs_dir": ".miniclaudecode/runs",
    "max_repair_rounds": 1
  }
}
```

常用环境变量：

| 环境变量 | 对应配置 |
| --- | --- |
| MINICLAUDECODE_MODEL | model.model |
| MINICLAUDECODE_MAX_TURNS | model.max_turns |
| MINICLAUDECODE_WORKSPACE_ROOT | safety.workspace_root |
| MINICLAUDECODE_PERMISSION_MODE | safety.permission_mode |
| MINICLAUDECODE_ALLOWED_COMMANDS | safety.allowed_commands，逗号分隔 |
| MINICLAUDECODE_DENIED_PATTERNS | safety.denied_patterns，逗号分隔 |
| MINICLAUDECODE_ENABLED_TOOLS | tool_runtime.enabled_tools，逗号分隔 |
| MINICLAUDECODE_DISABLED_TOOLS | tool_runtime.disabled_tools，逗号分隔 |
| MINICLAUDECODE_HARNESS_RUNS_DIR | harness.runs_dir |
| MINICLAUDECODE_MAX_REPAIR_ROUNDS | harness.max_repair_rounds |

## 目录结构

```text
miniclaudecode/
  agent_loop.py
  cli.py
  config.py
  context.py
  errors.py
  permissions.py
  workspace.py
  runtime/
  tools/
  harness/
  git_workflow/
  memory/
tests/
docs/
```

重要运行时目录：

```text
.miniclaudecode/
  traces/
  runs/
  memory/
```

## 测试与工程命令

项目使用 unittest，并通过 Makefile 统一本地工程命令。

首次开发建议安装运行依赖和 dev 工具：

```bash
make install
```

常用命令：

```bash
make test
make e2e
make coverage
make lint
make format
make typecheck
make build
make check
```

直接运行 unittest：

```bash
python -m unittest discover
```

测试覆盖范围：

| 测试范围 | 内容 |
| --- | --- |
| tools | bash、file read、file write、edit、glob、grep |
| runtime | discovery、schema validation、timeout、retry、compression、tracing |
| harness | artifacts、planner、executor、evaluator、task harness、final report |
| git workflow | worktree、diff summary、test runner、commit message、workflow |
| memory | records、store、project index、summarizer、context builder |
| cli | product commands、harness、git workflow、memory 命令 |
| e2e | fixture repo 端到端 agent task |

## 开发流程

本项目代码变更建议遵守以下流程：

1. 从 master 新建功能分支，分支名使用 `feature/功能名字`。
2. 在功能分支完成修改，并运行 `make check` 或至少运行 `python -m unittest discover`。
3. 检查通过后提交代码。
4. 合并回 master。
5. 将 master 推送到远程仓库。

## 面试讲法

可以这样介绍项目：

```text
miniClaudeCode 是我实现的轻量级 AI Coding Agent Runtime。它从一个基础 AgentLoop 出发，逐步补齐真实代码智能体需要的四个工程层：工具运行时、长任务 Harness、Git Workflow 工程闭环、长期记忆与上下文压缩。项目重点不是简单调 API，而是围绕工具调用安全性、可观测性、任务拆解验证、代码交付闭环和上下文复用做工程化设计。
```

简历表达可以写：

```text
设计并实现轻量级 AI Coding Agent Runtime，支持插件式工具发现、JSON Schema 校验、权限控制、diff preview、工具 tracing、长任务 Planner Executor Evaluator Harness、Git Workflow 工程闭环以及文件化长期记忆与上下文压缩，提升 Agent 在多轮代码任务中的安全性、可观测性和上下文复用能力。
```

## 和普通 Agent Demo 的区别

| 普通 Demo | miniClaudeCode |
| --- | --- |
| 一次 API 调用加工具执行 | 多轮 AgentLoop 和 ToolRuntime |
| 工具硬编码 | 工具自动发现和 schema 校验 |
| 缺少验证 | Harness 和 GitWorkflow 做确定性检查 |
| 没有产物 | run artifacts、events、traces、final report |
| 没有上下文沉淀 | MemoryStore、ProjectIndex、ContextBuilder |
| 难以解释工程取舍 | 每一块都有文档、测试和可演示命令 |

## 后续可优化方向

当前项目已经具备完整展示闭环，后续更适合做成熟度打磨：

1. 增加 `.miniclaudecode/config.toml`，把上下文长度、测试命令、trace 开关等配置化。
2. 为 memory 命令增加 `--max-context-chars` 和 `--output`。
3. 为 `--git-summary` 增加是否写入 memory 的开关。
4. 增加端到端测试，覆盖 memory-index、memory-context、git-summary、list-memory 的完整链路。
5. 增加一份总架构图文档，专门服务面试讲解。

## 注意事项

1. `bash` 工具会在本地执行命令，只适合受控环境。
2. `auto` 模式会自动执行通过工具自检的操作，使用前应确认当前工作区安全。
3. `.miniclaudecode/` 是运行时产物目录，包含 traces、runs 和 memory。
4. Memory 层只记录摘要和元信息，不保存完整大文件内容。
5. 当前项目提供 `pyproject.toml`，可通过可编辑安装获得 `miniclaudecode` 命令。
