# Tool Runtime 工程化改造记录

## 改造目标

本次改造的目标是把原本分散在 AgentLoop 中的工具执行逻辑，升级为一个独立的 Tool Runtime。

改造前，AgentLoop 直接负责：

```text
查找工具
权限检查
diff preview
执行工具
拼接 tool_result
```

改造后，AgentLoop 只负责模型调用和对话循环，工具调用统一交给 ToolRuntime：

```text
AgentLoop
  |
  v
ToolRuntime.invoke()
  |
  v
schema 校验 -> 权限检查 -> diff preview -> 超时执行 -> 重试 -> 结果压缩 -> tracing
```

这个变化让项目从“能调用几个工具的 Agent Demo”，升级为“具备中央工具执行管控能力的轻量级 Agent Runtime”。

## 新增能力

### 1. 工具自动发现

新增 `miniclaudecode/runtime/tool_loader.py`。

原来工具注册是硬编码的：

```text
BashTool
FileReadTool
FileWriteTool
FileEditTool
GlobTool
GrepTool
```

现在通过 `discover_tools()` 自动扫描 `miniclaudecode.tools` 包，发现所有继承自 `Tool` 的具体工具类，并自动注册到 `ToolRegistry`。

同时，`ToolRegistry.register()` 增加了重复工具名检测，避免多个工具注册成同一个 name。

价值：

```text
降低工具扩展成本，为后续插件化工具体系打基础。
```

### 2. ToolResult 结构增强

`ToolResult` 从简单的：

```python
output: str
is_error: bool
```

扩展为：

```python
output: str
is_error: bool
error_type: str | None
metadata: dict
```

新增 `error_type` 后，工具错误不再只是布尔值，而可以被分类：

```text
unknown_tool
validation_error
permission_denied
preview_rejected
timeout_error
execution_error
```

新增 `metadata` 后，可以记录压缩、重试、原始输出长度等运行时信息。

价值：

```text
让工具调用结果可分析、可统计、可观测，为 tracing 和运行质量分析提供结构化基础。
```

### 3. 工具运行时属性

在 `Tool` 基类中新增：

```python
timeout_seconds
retryable
is_read_only
```

默认行为：

```text
timeout_seconds = 30
retryable = False
is_read_only = False
```

只读工具被标记为可重试：

```text
read_file
glob
grep
```

写操作和 bash 默认不重试：

```text
bash
write_file
edit_file
```

价值：

```text
将工具的执行策略变成工具自身的元信息，便于 Runtime 统一调度。
```

### 4. Schema 校验

新增 `miniclaudecode/runtime/schema_validator.py`。

在工具执行前，使用 `jsonschema` 校验模型传入的参数是否符合工具的 `input_schema`。

例如 `read_file` 必须传入：

```text
path
```

如果模型漏传参数，会返回：

```text
validation_error
```

价值：

```text
不能完全信任模型输出。schema 校验可以避免非法 tool input 直接进入执行阶段，提高 Agent Runtime 的稳定性。
```

### 5. 结果压缩

新增 `miniclaudecode/runtime/compression.py`。

工具输出过长时，Runtime 会保留头部和尾部，中间插入截断说明：

```text
... output truncated ...
Original length: ...
Showing first ... chars and last ... chars.
```

并在 metadata 中记录：

```text
compressed = True
original_output_chars = 原始长度
```

默认配置：

```text
max_tool_result_chars = 12000
tool_result_head_chars = 8000
tool_result_tail_chars = 4000
```

价值：

```text
防止 grep、bash、read_file 等工具输出过长，撑爆模型上下文窗口。
```

### 6. JSONL Tracing

新增 `miniclaudecode/runtime/tracing.py`。

每次 Agent run 会生成一个 `run_id`，工具调用会写入：

```text
.miniclaudecode/traces/{run_id}.jsonl
```

每条 trace 记录包含：

```text
run_id
turn
tool_call_id
tool_name
status
error_type
duration_ms
input_preview
output_chars
compressed
started_at
ended_at
```

input 只记录摘要，不记录完整大内容，避免日志过大或泄露过多上下文。

价值：

```text
提供可观测性，可以分析 Agent 调用了哪些工具、耗时多少、是否失败、失败类型是什么、输出是否被压缩。
```

### 7. ToolRuntime 中央执行器

新增核心模块：

```text
miniclaudecode/runtime/tool_runtime.py
```

`ToolRuntime.invoke()` 接收模型返回的 tool call：

```python
{
    "id": "...",
    "name": "read_file",
    "input": {"path": "README.md"}
}
```

返回统一的 `ToolExecution`：

```python
ToolExecution(
    tool_use_id="...",
    result=ToolResult(...)
)
```

执行顺序：

```text
1. 查找工具
2. schema 校验
3. 权限检查
4. diff preview
5. 用户确认
6. timeout 执行
7. retry
8. 结果压缩
9. tracing
10. 返回 ToolExecution
```

价值：

```text
工具调用链路被统一收敛到一个运行时模块中，AgentLoop 不再承担执行细节，职责边界更清晰。
```

### 8. 超时和重试

所有工具都可以声明自己的超时时间：

```python
timeout_seconds
```

Runtime 使用 `ThreadPoolExecutor` 做统一 timeout 控制。

如果工具超时，返回：

```text
timeout_error
```

可重试工具在遇到以下错误时会重试一次：

```text
timeout_error
execution_error
```

目前只有只读工具默认可重试，写操作默认不重试，避免重复写文件或重复执行有副作用命令。

价值：

```text
避免单个工具调用卡死整个 Agent Loop，同时避免对有副作用操作进行危险重试。
```

### 9. AgentLoop 变薄

改造前，AgentLoop 中有大量工具执行细节。

改造后，AgentLoop 只做：

```text
调用 Claude API
解析 text 和 tool_use
调用 ToolRuntime
把 tool_result 放回上下文
继续循环
```

工具执行统一变成：

```python
execution = self.tool_runtime.invoke(call, turn=turn, run_id=run_id)
tool_results.append(execution.to_api_result())
```

价值：

```text
核心循环和工具运行时解耦，后续可以独立演进 ToolRuntime、Tracing、权限系统和插件体系。
```

## 改造后的架构

```text
CLI
  |
  v
AgentLoop
  |
  |-- streaming Claude API
  |-- parse tool_use
  |
  v
ToolRuntime
  |
  |-- ToolRegistry
  |-- Schema Validator
  |-- PermissionGate
  |-- Diff Preview
  |-- Timeout and Retry
  |-- Result Compression
  |-- TraceRecorder
  |
  v
tool_result
  |
  v
ConversationContext
```

## 测试覆盖

本次改造后，测试数量增加到：

```text
56 tests
```

覆盖内容包括：

```text
工具自动发现
重复工具名检测
ToolResult metadata
只读工具 retryable 标记
schema 校验
结果压缩
JSONL tracing
unknown tool
permission denied
preview rejected
timeout error
retryable tool retry
AgentLoop 调用 ToolRuntime
```

## 可以怎么写进简历

项目名称建议：

```text
miniClaudeCode: 轻量级 AI Coding Agent Runtime
```

项目描述：

```text
基于 Python 和 Anthropic Messages API 实现轻量级 AI Coding Agent Runtime，支持流式输出、工具调用、权限控制、diff preview、上下文管理和工具调用 tracing。项目围绕 Agent Loop、Tool Runtime、Permission Gate 和 Context Manager 进行模块化设计，复现 AI 编程助手的核心运行机制。
```

本次亮点可以写：

```text
设计并实现 Tool Runtime 中央执行器，将工具发现、JSON Schema 校验、权限门禁、diff preview、超时控制、重试策略、结果压缩和 JSONL tracing 统一收敛到工具调用链路中，提升 AI Agent 执行本地工具时的安全性、稳定性和可观测性。
```

更偏工程化的表达：

```text
将原本散落在 AgentLoop 中的工具执行逻辑重构为独立 ToolRuntime，使 AgentLoop 只负责模型交互和循环控制，工具运行时负责执行策略和可观测性，降低模块耦合并提升扩展性。
```

如果简历 bullet 要短一些，可以写：

```text
实现插件式工具发现和 ToolRuntime 执行管线，支持 schema 校验、权限检查、diff preview、timeout、retry、结果压缩和 JSONL trace。
```

```text
设计结构化 ToolResult，支持 error_type 和 metadata，使工具调用错误可分类、可追踪、可统计。
```

```text
将 AgentLoop 与工具执行解耦，形成 Agent Loop + Tool Runtime + Permission Gate + Context Manager 的轻量级 Agent 架构。
```

## 面试时可以怎么讲

可以这样介绍：

```text
这个项目不是简单调用大模型 API 做聊天，而是实现了一个 AI Coding Agent 的最小运行时。核心是 Agent Loop，模型可以返回 tool_use，系统会执行本地工具并把结果回填给模型继续推理。

后续我把工具调用链路重构成 ToolRuntime，因为真实 Agent 执行本地命令和文件操作时，不能只做 tool.execute。它需要在执行前做 schema 校验和权限检查，写文件前展示 diff preview，执行时要有 timeout 和 retry，执行后还要压缩结果并记录 trace，方便定位失败和分析运行效果。

这部分改造让项目从 demo 变成了一个更工程化的 Agent Runtime 骨架。
```

如果面试官追问为什么要做 tracing，可以回答：

```text
Agent 的行为不是单次函数调用，而是一串模型响应和工具调用。如果没有 trace，很难知道一次任务为什么失败、哪个工具耗时最长、哪个工具输出过长、模型是否传错参数。所以我用 JSONL 记录每次工具调用的 run_id、turn、tool_name、duration、error_type 和 output_chars，后续可以扩展成可视化执行链路或评测报告。
```

如果面试官追问为什么写操作不重试，可以回答：

```text
因为写文件和 bash 命令可能有副作用，重复执行可能造成重复修改或不可逆操作。当前只对 read_file、glob、grep 这类只读工具开启 retry，保持安全边界。
```

## 后续可继续优化

后续可以继续做：

```text
Session 持久化
上下文压缩
Git diff summary
自动测试和 commit message 生成
Trace 可视化
外部插件加载
MCP 工具接入
更细粒度的权限策略
```

其中最推荐的下一步是：

```text
Session 持久化 + Git 工作流闭环
```

这样项目可以继续从 Runtime 骨架走向完整的 AI Coding Workflow。
