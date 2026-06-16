# miniClaudeCode 架构详解

## 从 Claude Code 到 miniClaudeCode：蒸馏之路

### Claude Code 原版架构

Claude Code 是 Anthropic 构建的终端 AI 编程助手。它不是一个"带代码插件的聊天机器人"，
而是一个完整的 **Agent Runtime（智能体运行时）**。

原版架构包含以下核心层：

```
┌──────────────────────────────────────────────────────────────┐
│                      Terminal UI (Ink/React)                  │
├──────────────────────────────────────────────────────────────┤
│                       CLI Layer (20+ commands)                │
├──────────────────────────────────────────────────────────────┤
│                     Agent Loop (SSE streaming)                │
├──────────────────┬──────────────┬────────────────────────────┤
│  Tool System     │  Permission  │  Context Management        │
│  26+ tools       │  5 layers    │  Sessions + Compaction      │
│  + MCP extension │  + Hooks     │  + CLAUDE.md + Memory       │
├──────────────────┴──────────────┴────────────────────────────┤
│  SubAgent/Task    │  Teams/tmux  │  Bootstrap Graph           │
├───────────────────┴──────────────┴───────────────────────────┤
│                    Anthropic API (Claude model)               │
└──────────────────────────────────────────────────────────────┘
```

### miniClaudeCode 精简架构

```
┌──────────────────────────────────────────────────────────────┐
│                      Simple REPL (print/input)                │
├──────────────────────────────────────────────────────────────┤
│                     CLI Layer (3 commands)                     │
├──────────────────────────────────────────────────────────────┤
│                     Agent Loop (synchronous)                  │
├──────────────────┬──────────────┬────────────────────────────┤
│  Tool System     │  Permission  │  Context Management        │
│  6 core tools    │  2 layers    │  Message list + truncation  │
├──────────────────┴──────────────┴────────────────────────────┤
│                    Anthropic API (Claude model)               │
└──────────────────────────────────────────────────────────────┘
```

## 四大核心模块详解

### 1. Agent Loop（智能体循环）

**文件**: `agent_loop.py`

这是整个系统的"灵魂"。Agent Loop 的工作方式：

```
while True:
    response = call_claude_api(messages, tools)

    if response 只有文本:
        输出文本，结束循环
        break

    if response 包含 tool_use:
        for each tool_call in response:
            权限检查(tool_call)
            result = 执行工具(tool_call)
            追加result到消息历史
        continue  # 继续下一轮循环
```

**原版差异**：
- 原版使用 SSE（Server-Sent Events）流式接收，逐 token 渲染
- 原版支持一次 API 调用返回多个并行 tool_use blocks
- miniClaudeCode 使用同步调用，顺序执行工具

### 2. Tool System（工具系统）

**文件**: `tools/base.py` + 6 个工具文件

每个工具实现相同的接口：

```python
class Tool(ABC):
    name: str              # 工具名称（给 API 的标识）
    description: str       # 描述（LLM 用来决定何时调用）
    input_schema: dict     # JSON Schema（参数验证）

    def check_permissions(params) -> str | None   # 权限自检
    def execute(params) -> ToolResult              # 实际执行
```

**原版对照**：
- 原版用 Zod 做 schema 验证，miniClaudeCode 依赖 API 端验证
- 原版每个工具还有 UI renderer（Ink React 组件），miniClaudeCode 去掉了
- 原版通过 MCP 服务器可以动态加载更多工具

### 3. Permission System（权限系统）

**文件**: `permissions.py`

原版 5 层权限模型：

```
Layer 1: tool.checkPermissions()     -- 工具自身检查（如 Bash 检查危险命令）
Layer 2: Settings allowlist/denylist -- 配置文件中的 glob 模式
Layer 3: Sandbox policy              -- 沙箱路径/命令/网络限制
Layer 4: Permission mode             -- ask/auto/plan 模式
Layer 5: Hook overrides              -- PreToolUse 钩子可以拦截/修改
```

miniClaudeCode 精简为 2 层：

```
Layer 1: tool.check_permissions()    -- 工具自检（保留）
Layer 2: Permission mode             -- ask/auto/plan 模式（保留）
```

去掉了 Settings allowlist、Sandbox、Hooks 三层，因为它们主要服务于
企业级安全和高度定制化场景，对理解核心架构不是必需的。

### 4. Context Management（上下文管理）

**文件**: `context.py` + `system_prompt.py`

原版的上下文管理非常复杂：
- 会话持久化到 `~/.claude/sessions/`
- 接近上下文窗口限制时自动"压缩"（summarize old messages）
- CLAUDE.md 注入项目级指令
- 自动记忆文件跨会话积累
- Transcript 存储支持回放

miniClaudeCode 保留了：
- 消息列表管理
- 简单截断（丢弃最旧消息，保留第一条）
- CLAUDE.md 加载

## 蒸馏比例

| 指标 | Claude Code | miniClaudeCode | 压缩比 |
|------|-------------|----------------|--------|
| 代码行数 | ~500,000 | ~800 | 625:1 |
| 工具数量 | 26+ | 6 | 4:1 |
| 子系统数 | 28 | 4 | 7:1 |
| 权限层数 | 5 | 2 | 2.5:1 |
| CLI 命令 | 20+ | 3 | 7:1 |

## 学习路径建议

1. **从 `agent_loop.py` 开始** -- 理解 Agent Loop 是如何驱动一切的
2. **看 `tools/base.py`** -- 理解工具接口设计
3. **看任意一个工具** -- 如 `bash_tool.py`，理解工具实现
4. **看 `permissions.py`** -- 理解安全模型
5. **看 `context.py`** -- 理解对话管理
6. **看 `system_prompt.py`** -- 理解系统提示如何组装
7. **运行它** -- `python -m miniclaudecode`，实际体验 Agent Loop
