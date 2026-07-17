# 工程化变更记录

记录时间：2026-07-17

本文档汇总当前项目近期围绕“从教学 Demo 走向可上线工程”的主要改动，方便后续审计、复盘、交接和继续规划。

## 总览

本轮工程化改造重点覆盖以下方向：

- 配置体系从纯 `dataclass` 默认值升级为可落地的分层配置。
- 工具执行从分散调用升级为统一 runtime，补齐 tracing、权限、重试、超时和结果压缩。
- harness 从“能跑任务”升级为“能审计任务”，每次 run 都有独立 trace 和最终报告。
- 工具系统引入 manifest、能力标签、读写权限、启用/禁用列表和配置注入。
- CLI 从教学 REPL 扩展为更明确的产品入口。
- 上下文超限策略从直接截断升级为摘要压缩。
- 加入 workspace 路径安全策略，限制 agent 文件和 bash 能力边界。
- 增加 Makefile、CI、lint、format、coverage、build、E2E 测试入口。
- ask 权限交互升级为更可理解的审批体验，展示原因、目标、风险和 diff 摘要。

## 配置体系

原始 `Config` 主要依赖 dataclass 默认值，适合教学，但不适合真实部署。当前已拆分并支持多来源覆盖：

- `ModelConfig`：模型、温度、最大 token 等模型相关配置。
- `ToolRuntimeConfig`：工具执行超时、重试、结果压缩、trace 等运行时配置。
- `SafetyConfig`：权限模式、危险命令策略、workspace root 等安全配置。
- `HarnessConfig`：harness 输出目录、最大轮次、repair 策略等测试运行配置。

配置优先级已收敛为：

1. 代码默认值
2. JSON 配置文件
3. 环境变量
4. CLI 显式覆盖

同时补充了 `MINICLAUDECODE_WORKSPACE_ROOT` 等环境变量入口，使部署环境可以不改代码完成配置注入。

## 安装与项目入口

README、`requirements.txt`、`pyproject.toml` 中的安装方式已做收敛，避免多个入口互相冲突。

当前推荐以 `pyproject.toml` 作为权威依赖来源，通过统一的开发命令执行安装、测试、lint、build 等操作。

## Tool Runtime

新增统一工具运行层，将原本散落在 agent loop 和 tool 内部的横切能力集中处理：

- 工具参数校验。
- 权限检查。
- workspace 路径校验。
- bash 风险识别。
- 超时控制。
- 失败重试。
- 工具结果压缩。
- trace 记录。
- ask 模式审批。

这样 agent loop 不再直接承担工具生命周期细节，后续扩展工具、插拔权限策略和接入审计系统会更容易。

## Trace 与 Harness 审计

原先 `TraceRecorder` 默认写入 `.miniclaudecode/traces`，而 harness 自己也有独立 `traces_dir`，两者割裂。

当前已改为每次 harness run 将 agent trace 写入对应 run 目录，使一次任务的关键信息可以集中审计：

- tool call
- evaluation
- repair round
- git diff
- test result
- final report

最终报告能够关联任务执行过程中的工具调用、评估、修复和验证结果，项目从“能跑”进一步变为“能复盘”。

## 工具插件生命周期

工具加载从“扫描包并直接实例化”升级为更接近可扩展 runtime 的结构。

当前工具系统支持：

- tool manifest
- 工具版本
- 能力标签
- 读写权限声明
- 只读工具识别
- 配置注入
- 启用列表
- 禁用列表

这为后续第三方工具、权限面板、工具市场、工具审计和按环境裁剪能力打下基础。

## 工程命令与 CI

新增统一工程命令入口，降低“本机能跑但 CI 不一致”的风险。

主要命令包括：

- `make test`
- `make e2e`
- `make coverage`
- `make lint`
- `make format`
- `make typecheck`
- `make build`
- `make check`

同时增加 GitHub Actions 工作流，用 CI 跑 lint、typecheck、测试和构建，避免只依赖本地 `.venv` 状态。

## Agent Loop 解耦

`AgentLoop` 已从直接绑定具体 client、输出、tracer 和 tool 执行细节中拆出来。

当前支持：

- 注入 LLM client。
- 注入输出处理。
- 注入 tracer。
- 注入 tool runtime。
- 返回结构化 `AgentRunResult`。
- 为 harness run 指定独立 trace 目录。

这让 agent loop 更容易测试，也方便未来接入不同模型、不同 UI、不同执行后端。

## Workspace 沙箱与路径安全

新增 `WorkspacePolicy`，统一约束文件工具和 bash 的 workspace 边界。

当前策略包括：

- 文件 read/write/edit/glob/grep 必须落在授权 workspace 内。
- 相对路径以 workspace root 解析。
- 禁止绝对路径访问。
- 禁止 `~` 家目录访问。
- 禁止 `..` 越权路径。
- bash cwd 必须位于 workspace 内。
- bash 命令做基础词法安全检查，阻断明显越权路径、家目录、父目录和命令替换模式。

这属于上线前必须具备的 P0 能力，目标是让 agent 只能读写授权目录。

## 上下文摘要压缩

原本上下文超过阈值后会直接丢弃旧消息，真实编码任务中容易丢掉关键约束、决策和历史修复原因。

当前已改为：

- 超阈值时压缩旧 conversation。
- 将摘要写入 `<conversation_summary>` block。
- 保留近期消息。
- summarizer 会跳过已有 summary block，避免摘要套摘要。
- tool call 和 tool result 会转换为可读摘要片段。

这样长任务中旧上下文不会简单消失，而是以更低 token 成本继续参与决策。

## CLI 产品化

CLI 从偏教学 REPL 扩展为更明确的产品入口，同时保留旧的直接 prompt 兼容模式。

当前新增或强化的命令包括：

- `chat`：交互式对话入口。
- `run`：执行单次任务。
- `tools`：查看可用工具。
- `doctor`：检查本地环境、配置和依赖状态。

这些命令覆盖真实使用中最常见的少量场景，避免一次性引入过多子命令导致维护成本升高。

## E2E 测试

除单元测试外，新增 fixture repo 和端到端任务测试，提高上线信心。

E2E 覆盖场景包括：

- 读取代码。
- 修改文件。
- 运行测试。
- 生成报告。
- 拒绝危险命令。

该测试层用于验证 agent 在真实项目目录中的行为，而不是只验证单个函数。

## 交互式权限体验

ask 模式从简单 yes/no 升级为更接近真实产品的权限确认体验。

当前权限确认会展示：

- 工具名。
- 目标路径或命令。
- 询问原因。
- 命令风险。
- diff 摘要。
- 完整 diff 预览。
- 允许一次。
- 永久允许同类操作。
- 拒绝。

同时保留旧的 boolean callback 兼容逻辑，避免测试和外部调用方被一次性破坏。

## 主要提交记录

| Commit | 内容 |
| --- | --- |
| `4381959` | Engineer layered configuration loading |
| `f28cac8` | Add harness trace audit and tool manifests |
| `36b7bc3` | Add CI and engineering check targets |
| `aa1989d` | Decouple agent loop client and output |
| `5dfbe57` | Add workspace path policy |
| `ad40338` | Summarize old conversation context |
| `5592f47` | Add product CLI commands |
| `ce5e471` | Improve ask permissions and add e2e tests |

## 已验证项

最近一轮完整验证包括：

- `make lint typecheck coverage`
- `make e2e`
- `python3 -m uv run python -m build`

最近确认结果：

- lint 通过。
- typecheck 通过。
- 单元测试与覆盖率流程通过。
- E2E 测试通过。
- build 通过。
- 当前测试规模约 224 个测试用例。

## 当前未纳入提交的本地产物

当前工作区存在一些本地生成产物，未作为工程代码提交：

- `output/`
- `tmp/`
- `uv.lock`

其中 `output/` 和 `tmp/` 主要来自简历 PDF 处理过程，`uv.lock` 来自本地 `uv` 命令执行。是否纳入版本管理需要后续单独决策。

## 后续建议

后续如果继续向真实上线推进，建议优先考虑：

- 为 bash 引入更强的 OS 级隔离，而不只依赖词法和路径策略。
- 将 ask 模式的永久允许规则持久化，并支持用户查看和撤销。
- 增加真实模型调用的 smoke test，但默认在 CI 中通过环境变量关闭。
- 增加发布流程，例如版本号、changelog、package publish dry-run。
- 扩展 harness 报告为结构化 JSON，方便后续接入 Web UI 或 CI artifact。
- 对 workspace policy 增加更多攻击用例测试，例如 symlink、硬链接、shell glob、环境变量展开和复杂重定向。
