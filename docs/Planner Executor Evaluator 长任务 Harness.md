# Planner Executor Evaluator 长任务 Harness

## 第二块目标

第一块已经完成 Tool Runtime 工程化，解决的是工具调用链路的问题：

```text
工具发现
schema 校验
权限检查
diff preview
timeout
retry
结果压缩
JSONL tracing
```




第二块要解决的是长任务执行质量问题。

目标是实现一个轻量级长任务 Harness，让 AI Coding Agent 不只是单次响应用户，而是可以按照以下流程执行较大的工程任务：

```text
用户需求
  |
  v
Planner 生成任务计划和验收标准
  |
  v
Executor 分阶段执行 task
  |
  v
Evaluator 运行测试、检查 diff、生成反馈
  |
  v
失败则反馈给 Executor 修复
  |
  v
生成最终运行报告
```

这部分可以作为项目第二个核心亮点：

```text
从工具调用 Runtime 升级到长任务 Agent Harness。
```

## 参考思想

这块参考的是 Claude Code 和 Agent Harness Engineering 中的工程思路，而不是简单做一个聊天机器人。

核心判断：

```text
真实 AI Coding Agent 的难点不是一次 tool call，而是多步骤任务中如何避免目标漂移、上下文混乱、自评偏乐观和失败不可追踪。
```

因此需要：

```text
结构化任务计划
分阶段执行
客观验证
失败反馈
运行产物记录
最终报告
```

## 当前项目已有基础

当前已经具备：

```text
AgentLoop
ToolRuntime
ToolRegistry
PermissionGate
TraceRecorder
JSONL trace
diff preview
unit tests
```

这些为第二块提供基础：

```text
ToolRuntime 负责单个工具调用的安全和可观测性
长任务 Harness 负责多步骤任务的规划、执行、验证和复盘
```

## 推荐整体架构

计划新增目录：

```text
miniclaudecode/harness/
  __init__.py
  artifacts.py
  planner.py
  executor.py
  evaluator.py
  task_harness.py
  report.py
```

第一阶段先实现：

```text
miniclaudecode/harness/
  __init__.py
  artifacts.py
```

运行产物目录：

```text
.miniclaudecode/
  runs/
    {run_id}/
      request.md
      spec.md
      plan.json
      events.jsonl
      final_report.md
      tasks/
        task-001.md
      evaluator_reports/
        task-001.json
      traces/
        run-trace.jsonl
```

## 第一阶段：ArtifactStore

第一阶段先做 ArtifactStore。

目的：

```text
为每一次长任务运行创建一个独立目录，保存 request、plan、task、evaluator report、events 和 final report。
```

这一步不是为了功能炫技，而是为了后续 Planner、Executor、Evaluator 都有共同的运行产物基础。

## ArtifactStore 执行步骤

### 1. 新增 harness 包

新增：

```text
miniclaudecode/harness/
  __init__.py
  artifacts.py
```

### 2. 定义 RunArtifacts

建议结构：

```python
@dataclass(frozen=True)
class RunArtifacts:
    run_id: str
    root: Path
```

提供路径属性：

```text
request_path
spec_path
plan_path
events_path
final_report_path
tasks_dir
evaluator_reports_dir
traces_dir
```

### 3. 定义 ArtifactStore

建议结构：

```python
class ArtifactStore:
    def __init__(self, base_dir: str | Path = ".miniclaudecode/runs") -> None:
        self.base_dir = Path(base_dir)
```

核心方法：

```text
create_run()
get_run(run_id)
list_runs()
write_request(artifacts, request)
write_spec(artifacts, spec)
write_plan(artifacts, plan)
read_plan(artifacts)
write_task(artifacts, task_id, content)
write_evaluator_report(artifacts, task_id, report)
append_event(artifacts, event)
write_final_report(artifacts, report)
```

### 4. run_id 规则

建议格式：

```text
YYYYMMDD-HHMMSS-短 uuid
```

示例：

```text
20260616-143000-a1b2c3
```

优点：

```text
可读
可按时间排序
冲突概率低
```

### 5. create_run 行为

`create_run()` 应该创建：

```text
.miniclaudecode/runs/{run_id}/
.miniclaudecode/runs/{run_id}/tasks/
.miniclaudecode/runs/{run_id}/evaluator_reports/
.miniclaudecode/runs/{run_id}/traces/
```

然后返回 `RunArtifacts`。

### 6. 写入 request.md

保存用户原始需求。

示例：

```text
帮我实现 session 持久化，并补充测试
```

### 7. 写入 spec.md

保存需求规格说明。

第一版可以手写或由后续 Planner 生成。

### 8. 写入 plan.json

建议结构：

```json
{
  "goal": "实现 session 持久化",
  "tasks": [
    {
      "id": "task-001",
      "title": "新增 SessionStore",
      "acceptance": [
        "可以保存 messages",
        "可以加载 session"
      ]
    }
  ]
}
```

### 9. 写 task 文件

路径：

```text
tasks/task-001.md
```

内容可以包含：

```text
task id
title
acceptance criteria
implementation notes
```

### 10. 写 evaluator report

路径：

```text
evaluator_reports/task-001.json
```

示例：

```json
{
  "task_id": "task-001",
  "status": "passed",
  "checks": [
    {
      "name": "unit_tests",
      "status": "passed"
    }
  ]
}
```

### 11. 追加 events.jsonl

用于记录 harness 级事件。

示例事件：

```json
{"type": "run_created", "timestamp": "2026-06-16T14:30:00Z"}
```

后续可以扩展：

```text
task_started
task_finished
evaluation_started
evaluation_failed
repair_started
run_finished
```

### 12. 写 final_report.md

保存最终运行报告。

可以包含：

```text
任务目标
完成的 tasks
失败和修复记录
测试结果
修改文件摘要
trace 文件位置
```

### 13. list_runs

用于后续 CLI：

```bash
python -m miniclaudecode --list-runs
```

第一版先实现底层方法，不急着接 CLI。

## ArtifactStore 测试计划

新增：

```text
tests/test_harness_artifacts.py
```

测试覆盖：

```text
create_run 创建 run 目录
自动创建 tasks、evaluator_reports、traces
write_request 写入 request.md
write_spec 写入 spec.md
write_plan 和 read_plan 保真读写
write_task 写入 tasks/task-001.md
write_evaluator_report 写入 evaluator_reports/task-001.json
append_event 写 JSONL 且可逐行 json.loads
write_final_report 写入 final_report.md
list_runs 能列出已有 run
```

测试要求：

```text
使用 tempfile.TemporaryDirectory
不要写真实 .miniclaudecode/runs
```

## 第二块后续步骤

ArtifactStore 做完后，推荐顺序：

```text
1. Planner
2. Evaluator
3. Executor
4. TaskHarness
5. Final Report Generator
6. CLI 接入
```

### Planner

输入用户需求，输出：

```text
spec.md
plan.json
tasks 目录下的任务 md 文件
```

重点是把自然语言需求转成结构化 task contract。

### Evaluator

第一版先做确定性检查：

```text
python -m unittest discover
python -m py_compile
git diff --stat
是否新增测试
是否有未提交运行产物
```

不要一开始就做 LLM evaluator。

### Executor

按 task 逐步调用 AgentLoop。

每个 task 注入：

```text
task title
acceptance criteria
当前项目上下文
上一轮 evaluator feedback
```

### TaskHarness

串起来：

```text
create run
write request
planner generate plan
for task in tasks:
  execute task
  evaluate task
  if failed:
    repair
write final report
```

## 面试表达

可以这样说：

```text
第一阶段我实现的是 Tool Runtime，解决工具调用的安全性、稳定性和可观测性。

第二阶段我开始做长任务 Harness，目标是解决 coding agent 在多步骤任务中容易目标漂移、自评偏乐观和失败不可追踪的问题。

我的设计是 Planner Executor Evaluator 架构。Planner 把用户需求转成结构化任务和验收标准，Executor 分阶段执行，Evaluator 用测试、diff 和静态检查给出客观反馈，如果失败再反馈给 Executor 修复，最后生成完整运行报告。
```

简历表达：

```text
设计 Planner Executor Evaluator 长任务 Harness，支持需求规划、分阶段执行、自动验证、失败反馈修复和运行报告生成，使 AI Coding Agent 从单次工具调用升级为可审计、可恢复的长任务执行流程。
```

ArtifactStore 可以单独写：

```text
实现 Harness ArtifactStore，为每次长任务运行持久化 request、plan、task、evaluator report、events 和 final report，为后续任务复盘、失败定位和 session 恢复提供结构化运行产物。
```

## 关键注意事项

### 不要过早做复杂多 agent

第一版不要做真正并行多 agent。

先做：

```text
单进程
结构化角色
确定性 evaluator
可复盘 artifacts
```

### 不要只依赖模型自评

Evaluator 第一版优先使用：

```text
测试
编译
git diff
文件存在性
规则检查
```

模型自评可以后置。

### 每一步都要有产物

长任务 Harness 的核心不是“跑完”，而是每一步都留下可审计产物：

```text
request
plan
task
event
trace
evaluator report
final report
```

### CLI 可以后置

先把底层模块和测试做好，再接 CLI。

推荐顺序：

```text
ArtifactStore -> Planner -> Evaluator -> TaskHarness -> CLI
```

## 当前状态

当前文档只是第二块的设计和第一阶段执行步骤。

下一次实现应从：

```text
miniclaudecode/harness/artifacts.py
tests/test_harness_artifacts.py
```

开始。
