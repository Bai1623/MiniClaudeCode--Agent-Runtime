# Git Workflow 工程闭环

## 第三块目标

第一块已经完成 Tool Runtime，解决工具调用的安全性、稳定性和可观测性。

第二块已经完成 Planner Executor Evaluator 长任务 Harness，解决长任务的规划、分阶段执行、验证、失败修复和运行产物记录。

第三块要解决的是：

```text
AI Coding Agent 完成代码修改后，如何进入真实工程协作流程。
```

目标是实现 Git Workflow 工程闭环，让 Agent 不只是会改代码，而是能够：

```text
检查工作区状态
识别变更文件
生成 diff 摘要
运行测试并收集结果
生成 commit message
把 Git 结果写入 harness final report
可选执行 commit
```

这块的定位是：

```text
从 Agent 执行闭环升级到工程交付闭环。
```

## 为什么要做这一块

真实开发流程里，改代码只是中间步骤。一个可落地的 coding agent 还需要回答：

```text
改了哪些文件
为什么改
测试是否通过
有没有未跟踪文件
是否污染了用户已有修改
commit message 怎么写
能否审计这次变更
```

如果没有 Git Workflow，Agent 的输出还是偏 demo。

有了 Git Workflow 后，项目可以形成更完整链路：

```text
Tool Runtime
  |
  v
Planner Executor Evaluator Harness
  |
  v
Git Workflow 工程闭环
```

也就是：

```text
安全执行工具 -> 规划并验证长任务 -> 汇总变更并进入版本控制流程
```

## 第三块整体架构

建议新增目录：

```text
miniclaudecode/git_workflow/
  __init__.py
  worktree.py
  diff_summary.py
  test_runner.py
  commit_message.py
  workflow.py
```

建议新增测试：

```text
tests/test_git_workflow_worktree.py
tests/test_git_workflow_diff_summary.py
tests/test_git_workflow_test_runner.py
tests/test_git_workflow_commit_message.py
tests/test_git_workflow_workflow.py
```

第一版不接 GitHub，不开 PR，不 push。

第一版只做本地 Git 闭环：

```text
status
diff
test
summary
commit message
optional commit
report data
```

## 核心模块规划

### 1. WorktreeInspector

文件：

```text
miniclaudecode/git_workflow/worktree.py
```

职责：

```text
读取 git status
读取 git diff --stat
读取 git diff --name-only
识别 changed、untracked、staged 文件
判断工作区是否 dirty
```

建议数据结构：

```python
@dataclass(frozen=True)
class WorktreeStatus:
    branch: str
    changed_files: list[str]
    untracked_files: list[str]
    staged_files: list[str]
    is_dirty: bool
```

核心方法：

```text
get_status()
get_diff_stat()
get_changed_files()
ensure_git_repo()
```

命令：

```text
git status --porcelain=v1 -b
git diff --stat
git diff --name-only
git diff --cached --name-only
```

测试重点：

```text
解析 status porcelain
识别 untracked 文件
识别 modified 文件
识别 staged 文件
非 git repo 返回明确错误
```

### 2. DiffSummary

文件：

```text
miniclaudecode/git_workflow/diff_summary.py
```

职责：

```text
把 git diff 信息转成结构化摘要
```

建议数据结构：

```python
@dataclass(frozen=True)
class FileChange:
    path: str
    change_type: str
    additions: int
    deletions: int

@dataclass(frozen=True)
class DiffSummary:
    files: list[FileChange]
    total_additions: int
    total_deletions: int
```

输入可以来自：

```text
git diff --numstat
```

示例输出：

```text
12  3  miniclaudecode/cli.py
4   0  tests/test_cli.py
```

测试重点：

```text
解析普通文件变更
处理二进制文件
统计总 additions 和 deletions
生成 markdown 摘要
```

### 3. TestRunner

文件：

```text
miniclaudecode/git_workflow/test_runner.py
```

职责：

```text
运行测试命令
记录 returncode
记录 stdout stderr
记录耗时
输出结构化 TestRunResult
```

建议数据结构：

```python
@dataclass(frozen=True)
class TestRunResult:
    command: list[str]
    returncode: int
    duration_ms: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0
```

默认命令：

```text
python -m unittest discover
```

测试重点：

```text
成功命令
失败命令
输出截断
耗时记录
```

### 4. CommitMessageGenerator

文件：

```text
miniclaudecode/git_workflow/commit_message.py
```

职责：

```text
根据 diff summary 和测试结果生成 commit message
```

第一版不用 LLM，采用规则生成。

示例：

```text
Add planner executor evaluator harness

- Add harness planner, executor, evaluator, task harness, and report generator
- Add CLI options for harness runs
- Add tests for harness workflow modules
- Tests: python -m unittest discover passed
```

建议输入：

```text
DiffSummary
TestRunResult
optional user summary
```

测试重点：

```text
有 tests 文件时生成 tests bullet
测试通过时写 passed
测试失败时写 failed
无变更时给出 fallback message
```

### 5. GitWorkflow

文件：

```text
miniclaudecode/git_workflow/workflow.py
```

职责：

```text
串起 status -> diff summary -> tests -> commit message -> optional commit
```

第一版建议只做：

```text
analyze()
```

返回：

```python
@dataclass(frozen=True)
class GitWorkflowReport:
    status: WorktreeStatus
    diff_summary: DiffSummary
    test_result: TestRunResult
    commit_message: str
```

可选后续再做：

```text
commit()
```

不要第一版就自动 commit。自动 commit 需要更严格保护。

测试重点：

```text
mock runner 串联流程
dirty worktree 可以生成 report
clean worktree 也可以生成 report
测试失败时 report 标记 failed
```

## 和第二块 Harness 的衔接

第三块完成后，可以把 GitWorkflow 接入：

```text
FinalReportGenerator
TaskHarness
CLI
```

例如 final report 增加：

```text
## Git Summary

Changed files:
  miniclaudecode/cli.py
  tests/test_cli.py

Diff stat:
  25 insertions
  3 deletions

Tests:
  python -m unittest discover passed

Suggested commit message:
  Add planner executor evaluator harness
```

这样第二块的 final_report.md 就不只是 task 报告，还会变成工程交付报告。

## 推荐实施顺序

### 第一步：WorktreeInspector

先做：

```text
miniclaudecode/git_workflow/__init__.py
miniclaudecode/git_workflow/worktree.py
tests/test_git_workflow_worktree.py
```

原因：

```text
所有 Git Workflow 都依赖工作区状态。
```

### 第二步：DiffSummary

做：

```text
miniclaudecode/git_workflow/diff_summary.py
tests/test_git_workflow_diff_summary.py
```

### 第三步：TestRunner

做：

```text
miniclaudecode/git_workflow/test_runner.py
tests/test_git_workflow_test_runner.py
```

### 第四步：CommitMessageGenerator

做：

```text
miniclaudecode/git_workflow/commit_message.py
tests/test_git_workflow_commit_message.py
```

### 第五步：GitWorkflow

做：

```text
miniclaudecode/git_workflow/workflow.py
tests/test_git_workflow_workflow.py
```

### 第六步：接入 Harness Report

更新：

```text
miniclaudecode/harness/report.py
tests/test_harness_report.py
```

让 final_report.md 可以包含 Git Workflow 摘要。

### 第七步：CLI 接入

新增：

```text
python -m miniclaudecode --git-summary
python -m miniclaudecode --git-commit-message
```

是否做自动 commit 可以后置。

## 安全边界

第三块需要特别注意：

```text
默认不自动 commit
默认不 push
默认不 reset
默认不 checkout 覆盖用户文件
```

如果后续做 commit，必须满足：

```text
测试已运行
展示 diff summary
展示 commit message
用户显式确认
只 commit 当前工作区变更
```

## 面试表达

可以这样介绍：

```text
第一块我做的是 Tool Runtime，解决工具调用的安全性和可观测性。

第二块我做的是 Planner Executor Evaluator 长任务 Harness，解决复杂任务的规划、执行、验证和失败反馈。

第三块我继续做 Git Workflow 工程闭环，目标是让 Agent 的代码修改能够进入真实开发流程。它会检查工作区状态，汇总 diff，运行测试，生成 commit message，并把这些信息写入最终报告。这样 Agent 的输出不是黑盒代码改动，而是可审查、可验证、可提交的工程产物。
```

简历表达：

```text
实现 Git Workflow 工程闭环，支持工作区状态检测、变更摘要、测试执行、commit message 生成和报告集成，使 AI Coding Agent 的代码修改能够进入可审查、可验证的版本控制流程。
```

## 当前进度

第一步 WorktreeInspector 已完成。

已经新增：

```text
miniclaudecode/git_workflow/worktree.py
tests/test_git_workflow_worktree.py
```

能力包括：

```text
读取 git status porcelain
识别 changed、untracked、staged 文件
读取 diff stat
读取 changed files
非 git repo 给出明确错误
```

第二步 DiffSummary 已完成。

已经新增：

```text
miniclaudecode/git_workflow/diff_summary.py
tests/test_git_workflow_diff_summary.py
```

能力包括：

```text
解析 git diff --numstat
输出 FileChange 和 DiffSummary
统计 additions 和 deletions
识别 binary 文件
生成 Markdown diff 摘要
支持 cached diff
```

下一步建议继续做：

```text
miniclaudecode/git_workflow/test_runner.py
tests/test_git_workflow_test_runner.py
```
