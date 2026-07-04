# miniClaudeCode

## Current Highlights

miniClaudeCode now contains two completed engineering blocks:

1. Tool Runtime
   Centralized tool execution with tool discovery, JSON Schema validation, permission checks, diff preview, timeout, retry, result compression, and JSONL tracing.

2. Planner Executor Evaluator Long Task Harness
   A long-running task harness with ArtifactStore, Planner, Evaluator, Executor, TaskHarness, FinalReportGenerator, and CLI entry points. It supports task planning, staged execution, deterministic evaluation, repair feedback loops, run artifacts, trace colocation, audit summaries, and final reports.

Useful harness commands:

```bash
python -m miniclaudecode --list-runs
python -m miniclaudecode --run-harness "your request"
python -m miniclaudecode --run-harness --harness-task "task one" --harness-task "task two" "your request"
```

Interview positioning:

```text
This project implements a lightweight AI Coding Agent Runtime. The first block focuses on safe and observable tool execution. The second block adds a Planner Executor Evaluator harness so larger coding tasks can be planned, executed in stages, evaluated with deterministic checks, repaired from feedback, and recorded as auditable run artifacts.
```
miniClaudeCode 是一个用于学习 Claude Code 核心架构的最小化 Python 实现。它保留了终端 AI 编程助手最关键的运行链路：用户输入、调用 Claude API、解析 tool_use、执行工具、把工具结果放回上下文，然后继续循环直到得到最终回答。

这个项目不是 Claude Code 的完整替代品，而是一个便于阅读、实验和教学的精简版 agent runtime。

## 项目特点

| 能力 | 说明 |
| --- | --- |
| Agent Loop | 流式调用 Anthropic Messages API，支持边生成边输出和多轮工具调用循环 |
| 工具系统 | 内置 bash、read_file、write_file、edit_file、glob、grep 六个核心工具 |
| 权限控制 | 提供 ask、auto、plan 三种权限模式 |
| Diff 预览 | write_file 和 edit_file 在落盘前生成 unified diff，ask 模式需要确认后才应用 |
| 上下文管理 | 使用内存消息列表保存对话，并在超过限制时截断旧消息 |
| 项目指令 | 启动时会读取当前目录下的 CLAUDE.md 作为项目级指令 |
| 命令行入口 | 支持交互式 REPL，也支持一次性 prompt 调用 |

## 目录结构

```text
miniClaudeCode-dev/
  miniclaudecode/
    __main__.py
    cli.py
    agent_loop.py
    config.py
    context.py
    permissions.py
    system_prompt.py
    runtime/
      tool_runtime.py
      tool_loader.py
      schema_validator.py
      compression.py
      tracing.py
    tools/
      base.py
      bash_tool.py
      file_read.py
      file_write.py
      file_edit.py
      glob_tool.py
      grep_tool.py
  tests/
    test_agent_loop.py
    test_tools.py
  docs/
    architecture.md
    distill_notes.md
  comic/
  requirements.txt
```

## 安装

建议使用 Python 3.11 或更新版本。项目依赖以 `pyproject.toml` 为唯一权威来源；`requirements.txt` 只保留给习惯使用 `pip install -r requirements.txt` 的环境，并委托安装当前包。

```bash
python3 -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS 或 Linux:

```bash
source .venv/bin/activate
.venv/bin/python -m pip install -e ".[dev]"
```

只安装运行依赖也可以使用：

```bash
.venv/bin/python -m pip install -e .
```

运行前需要配置 Anthropic API Key。

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY="你的 API Key"
```

macOS 或 Linux:

```bash
export ANTHROPIC_API_KEY="你的 API Key"
```

## 使用方式

启动交互式 REPL：

```bash
python -m miniclaudecode
```

一次性执行一个 prompt：

```bash
python -m miniclaudecode "帮我查看当前目录有哪些 Python 文件"
```

指定模型、权限模式和最大循环轮数：

```bash
python -m miniclaudecode --model claude-sonnet-4-20250514 --mode ask --max-turns 30
```

指定配置文件：

```bash
python -m miniclaudecode --config miniclaudecode.config.json "查看项目状态"
```

交互模式内置命令：

| 命令 | 作用 |
| --- | --- |
| /tools | 查看当前注册的工具 |
| /mode | 查看当前权限模式 |
| /mode ask | 切换到 ask 模式 |
| /mode auto | 切换到 auto 模式 |
| /mode plan | 切换到 plan 模式 |
| /help | 查看帮助 |
| /quit | 退出 |

## 权限模式

| 模式 | 行为 |
| --- | --- |
| ask | 默认模式。安全命令直接执行，潜在风险 bash 命令会询问用户 |
| auto | 自动执行通过工具自检的操作，适合受控环境下快速实验 |
| plan | 只读模式。bash、write_file、edit_file 会被阻止 |

权限检查分为两层：

1. 工具自检。比如 BashTool 会阻止 rm -rf /、git reset --hard、git push --force 等危险模式。
2. 权限模式检查。根据 ask、auto、plan 决定是否允许继续执行。

## 内置工具

| 工具名 | 文件 | 作用 |
| --- | --- | --- |
| bash | miniclaudecode/tools/bash_tool.py | 执行 shell 命令，最长运行 120 秒，输出最多保留 50000 字符 |
| read_file | miniclaudecode/tools/file_read.py | 读取文本文件，返回带行号的内容，单文件最大 2 MB |
| write_file | miniclaudecode/tools/file_write.py | 写入文件，父目录不存在时会自动创建 |
| edit_file | miniclaudecode/tools/file_edit.py | 使用精确字符串替换编辑文件，old_string 必须唯一，并生成 unified diff |
| glob | miniclaudecode/tools/glob_tool.py | 按 glob 规则搜索文件，最多返回 500 个结果 |
| grep | miniclaudecode/tools/grep_tool.py | 使用正则搜索文件内容，优先调用 ripgrep，缺失时回退到 Python re |

## 核心流程

```text
用户输入
  |
  v
AgentLoop 把消息和工具 schema 发给 Claude API
  |
  v
Claude 返回文本或 tool_use
  |
  v
如果没有 tool_use，输出最终回答并结束
  |
  v
如果有 tool_use，先经过权限检查
  |
  v
执行工具，把 tool_result 追加为新的 user message
  |
  v
继续下一轮 API 调用
```

核心代码位置：

| 文件 | 职责 |
| --- | --- |
| miniclaudecode/cli.py | 命令行参数解析、交互式 REPL、内置命令 |
| miniclaudecode/agent_loop.py | 主 agent loop，负责调用 API、解析工具调用、执行工具并继续循环 |
| miniclaudecode/runtime/tool_runtime.py | Tool Runtime，统一处理工具查找、schema 校验、权限、diff preview、超时、重试、压缩和 tracing |
| miniclaudecode/tools/base.py | Tool 抽象基类、ToolResult、ToolRegistry |
| miniclaudecode/permissions.py | 两层权限检查 |
| miniclaudecode/context.py | 对话消息管理、上下文截断、CLAUDE.md 读取 |
| miniclaudecode/system_prompt.py | 系统提示词拼装 |
| miniclaudecode/config.py | 模型、轮数、权限模式和安全命令配置 |

## 配置

配置现在拆分为 `ModelConfig`、`ToolRuntimeConfig`、`SafetyConfig` 和 `HarnessConfig`。加载优先级为：

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

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| model.model | claude-sonnet-4-20250514 | 默认调用的 Anthropic 模型 |
| model.max_turns | 30 | 单次用户输入最多循环多少轮 |
| model.max_context_messages | 100 | 上下文最多保留多少条消息 |
| tool_runtime.max_output_chars | 50000 | 工具原始输出字符上限 |
| tool_runtime.max_tool_result_chars | 12000 | 返回给模型的工具结果上限 |
| tool_runtime.enabled_tools | [] | 非空时只启用列出的工具 |
| tool_runtime.disabled_tools | [] | 禁用列出的工具 |
| safety.permission_mode | ask | 默认权限模式 |
| safety.allowed_commands | 内置安全命令列表 | ask 模式下可自动执行的命令前缀 |
| safety.denied_patterns | 内置危险模式列表 | 始终拒绝的 bash 命令片段 |
| harness.runs_dir | .miniclaudecode/runs | harness 运行产物目录 |
| harness.max_repair_rounds | 1 | evaluator 失败后的最大修复轮数 |

常用环境变量：

| 环境变量 | 对应配置 |
| --- | --- |
| MINICLAUDECODE_MODEL | model.model |
| MINICLAUDECODE_MAX_TURNS | model.max_turns |
| MINICLAUDECODE_PERMISSION_MODE | safety.permission_mode |
| MINICLAUDECODE_ALLOWED_COMMANDS | safety.allowed_commands，逗号分隔 |
| MINICLAUDECODE_DENIED_PATTERNS | safety.denied_patterns，逗号分隔 |
| MINICLAUDECODE_ENABLED_TOOLS | tool_runtime.enabled_tools，逗号分隔 |
| MINICLAUDECODE_DISABLED_TOOLS | tool_runtime.disabled_tools，逗号分隔 |
| MINICLAUDECODE_HARNESS_RUNS_DIR | harness.runs_dir |
| MINICLAUDECODE_MAX_REPAIR_ROUNDS | harness.max_repair_rounds |

命令行参数会覆盖配置文件和环境变量，例如 `--model`、`--mode`、`--max-turns` 和 `--max-repair-rounds`。

Harness 模式会把 AgentLoop 的 tool trace 写入当前 run 的 `traces/` 目录；`final_report.md` 会汇总 events、tool calls、evaluation checks、repair rounds、git diff 和 test result，方便复盘一次长任务运行。

## 测试

项目使用 unittest，并通过 Makefile 统一本地工程命令。首次开发先安装运行依赖和 dev 工具：

```bash
make install
```

常用命令：

```bash
make test       # unittest
make coverage   # coverage run + threshold report
make lint       # ruff check
make format     # ruff auto-fix + format
make typecheck  # mypy
make build      # python -m build
make check      # lint + typecheck + coverage + build
```

## 开发流程

本项目的代码变更统一遵守以下流程：

1. 从 master 新建功能分支，分支名使用 feature/功能名字。
2. 在功能分支完成修改，并运行 make check。
3. 检查通过后提交代码，合并回 master。
4. 将 master 推送到远程仓库。

测试覆盖范围包括：

1. 默认工具注册和 API schema。
2. BashTool 的执行和危险命令拦截。
3. 文件读取、写入和精确替换。
4. glob 和 grep 搜索。
5. 权限模式行为。
6. 上下文截断。
7. 系统提示词构建。

## 与完整 Claude Code 的区别

| 维度 | miniClaudeCode | 完整 Claude Code |
| --- | --- | --- |
| 目标 | 学习和演示核心架构 | 面向真实工程使用的完整产品 |
| API 调用 | 同步非流式 | 流式优先 |
| 工具数量 | 6 个核心工具 | 更多内置工具和扩展能力 |
| 权限系统 | 2 层简化模型 | 更完整的权限、沙箱、设置和钩子系统 |
| 上下文 | 内存列表和简单截断 | 会话持久化、压缩、记忆和项目上下文 |
| UI | print/input REPL | 更完整的终端交互体验 |

## 开发建议

阅读顺序建议：

1. miniclaudecode/agent_loop.py，先理解主循环。
2. miniclaudecode/tools/base.py，理解工具接口和注册方式。
3. miniclaudecode/tools/bash_tool.py，选择一个具体工具看实现细节。
4. miniclaudecode/permissions.py，理解工具执行前的权限检查。
5. miniclaudecode/context.py，理解消息如何进入 Anthropic API。
6. miniclaudecode/system_prompt.py，理解系统提示词如何把工具和项目指令组织起来。
7. tests/，结合测试确认每个模块的预期行为。

添加新工具时，一般需要：

1. 在 miniclaudecode/tools/ 下新增工具文件。
2. 继承 Tool，实现 name、description、input_schema、execute。
3. 如有需要，实现 check_permissions。
4. 在 ToolRegistry.default 中注册新工具。
5. 在 tests/ 中补充对应测试。

## 注意事项

1. bash 工具使用 shell=True 执行命令，只适合本地学习和受控环境实验。
2. auto 模式会自动执行通过工具自检的操作，使用前应确认当前工作目录没有重要未备份文件。
3. edit_file 只做精确字符串替换，不支持模糊匹配或自动 diff。
4. read_file 默认按文本读取，不处理图片或其他二进制文件。
5. 当前项目提供 pyproject.toml，可通过可编辑安装获得 miniclaudecode 命令。
