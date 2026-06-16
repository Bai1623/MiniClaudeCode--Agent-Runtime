# 蒸馏笔记：从 50 万行到 800 行

## 蒸馏方法论

### 第一步：理解原始架构

通过以下资源理解 Claude Code 的架构：

1. **claw-code 项目** (instructkr/claw-code)
   - Python 移植工作区，提供了原版的模块映射
   - `reference_data/tools_snapshot.json` 列出了 100+ 工具模块
   - `reference_data/commands_snapshot.json` 列出了 150+ 命令
   - 28 个子系统的 JSON 描述文件

2. **公开架构文档**
   - Anthropic 官方的 Harness Design 文档
   - 社区的架构分析文章

3. **参考蒸馏项目**
   - ClaudeLite (davidweidawang/ClaudeLite)
   - cc-mini (e10nMa2k/cc-mini) - 800 行复现

### 第二步：识别核心 vs 外围

将原版的 28 个子系统分为"核心"和"外围"：

**核心（必须保留）**：
- Agent Loop 循环机制
- Tool 接口和注册
- 基础权限检查
- 消息/上下文管理
- 系统提示构建
- CLI 入口

**外围（可以去掉）**：
- assistant, bootstrap, bridge, buddy
- components, coordinator, entrypoints
- hooks, keybindings, memdir, migrations
- moreright, native_ts, outputStyles
- plugins, remote, schemas, screens
- server, services, skills, state
- types, upstreamproxy, utils, vim, voice

### 第三步：精简工具集

原版 100+ 工具模块（涵盖 26 种工具类型）：
- AgentTool (20 个模块) -> 去掉（SubAgent 机制）
- BashTool (17 个模块) -> 精简为 1 个文件
- FileReadTool (5 个模块) -> 精简为 1 个文件
- FileWriteTool (3 个模块) -> 精简为 1 个文件
- FileEditTool (6 个模块) -> 精简为 1 个文件
- GlobTool (3 个模块) -> 精简为 1 个文件
- GrepTool (3 个模块) -> 精简为 1 个文件
- 其余 19 种工具 -> 全部去掉

### 第四步：精简权限模型

原版 5 层 -> 保留 2 层：
- 工具自检：每个工具的 `check_permissions()` 方法
- 模式检查：ask/auto/plan 三种模式

去掉的 3 层在企业级使用中很重要，但对理解架构不是必需的。

## 代码行数统计

| 文件 | 行数 | 职责 |
|------|------|------|
| agent_loop.py | ~140 | 核心循环 |
| tools/base.py | ~85 | 工具基类+注册 |
| tools/bash_tool.py | ~80 | Bash 执行 |
| tools/file_read.py | ~55 | 文件读取 |
| tools/file_write.py | ~42 | 文件写入 |
| tools/file_edit.py | ~68 | 文件编辑 |
| tools/glob_tool.py | ~55 | 文件搜索 |
| tools/grep_tool.py | ~82 | 内容搜索 |
| permissions.py | ~72 | 权限管理 |
| context.py | ~72 | 上下文管理 |
| system_prompt.py | ~52 | 系统提示 |
| config.py | ~32 | 配置 |
| cli.py | ~110 | CLI 入口 |
| **总计** | **~945** | |

## 核心发现

1. **Agent Loop 是一切的基础** -- 理解了 "prompt -> API -> tool_use -> execute -> loop"
   这个循环，就理解了 Claude Code 80% 的行为

2. **工具接口设计精妙** -- name + description + input_schema 三要素足以让 LLM
   准确调用工具，不需要复杂的路由逻辑

3. **权限是可插拔的** -- 原版的 5 层权限模型虽然复杂，但每一层都是独立的，
   可以按需添加或移除

4. **上下文管理决定了"记忆力"** -- 原版的压缩和持久化让 Claude Code 看起来
   "记得"项目上下文，本质上是精心管理的消息列表
