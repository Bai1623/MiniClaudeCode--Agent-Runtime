# Memory and Context Engineering 长期记忆与上下文压缩层

## 第四块目标

前三块已经完成：

```text
Tool Runtime
Planner Executor Evaluator 长任务 Harness
Git Workflow 工程闭环
```

第四块要解决的是：

```text
AI Coding Agent 在长任务、多轮开发、多文件项目中如何沉淀上下文、复用项目认知、减少重复扫描，并控制上下文窗口成本。
```

目标是实现一个轻量、文件化、可测试的 Memory and Context Engineering 层，让 Agent 不只是每次临时读取代码，而是能够形成项目级记忆。

## 为什么做这一块

基础 Agent 项目常见问题：

```text
每次任务都重新扫描项目
历史工程决策无法沉淀
文件摘要无法复用
长任务 final report 和后续任务之间没有连接
上下文构建依赖人工选择文件
上下文过长时缺少压缩策略
```

第四块的价值是把 Agent 从一次性执行器升级为有项目连续性的工程助手。

## 和前三块的关系

```text
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

前三块解决执行、验证和交付。

第四块解决记忆、上下文选择和长期维护。

## 设计原则

第一版坚持：

```text
文件化存储，不先引入数据库
确定性摘要，不依赖复杂向量检索
可测试，可审计，可手动查看
不自动覆盖用户内容
只记录摘要和元信息，不记录敏感完整内容
先支持本项目结构，再保留扩展空间
```

不做：

```text
不引入向量数据库
不做复杂 embedding 检索
不做自动上传远程服务
不把完整大文件塞进 memory
不把 memory 当聊天记录堆积
```

## 目录规划

新增代码目录：

```text
miniclaudecode/memory/
  __init__.py
  records.py
  store.py
  project_index.py
  summarizer.py
  context_builder.py
```

新增测试：

```text
tests/test_memory_store.py
tests/test_memory_project_index.py
tests/test_memory_summarizer.py
tests/test_memory_context_builder.py
```

运行时产物目录：

```text
.miniclaudecode/memory/
  project.md
  files/
  decisions/
  tasks/
  context/
```

示例：

```text
.miniclaudecode/memory/project.md
.miniclaudecode/memory/files/miniclaudecode_git_workflow_workflow.py.md
.miniclaudecode/memory/decisions/2026-06-22-tool-runtime.md
.miniclaudecode/memory/tasks/run-20260622-001.md
.miniclaudecode/memory/context/latest.md
```

## 核心数据结构

### FileSummary

职责：

```text
记录单个文件的摘要和缓存有效性信息
```

建议字段：

```python
@dataclass(frozen=True)
class FileSummary:
    path: str
    sha256: str
    size_bytes: int
    updated_at: str
    language: str
    symbols: list[str]
    summary: str
```

### ProjectSummary

职责：

```text
记录项目整体结构、核心模块和当前能力地图
```

建议字段：

```python
@dataclass(frozen=True)
class ProjectSummary:
    name: str
    updated_at: str
    modules: list[str]
    capabilities: list[str]
    entrypoints: list[str]
    test_commands: list[str]
```

### DecisionRecord

职责：

```text
记录工程决策和取舍，方便后续任务复用历史判断
```

建议字段：

```python
@dataclass(frozen=True)
class DecisionRecord:
    id: str
    title: str
    date: str
    context: str
    decision: str
    consequences: list[str]
```

### TaskMemory

职责：

```text
记录一次任务的目标、变更、测试结果和最终结论
```

建议字段：

```python
@dataclass(frozen=True)
class TaskMemory:
    id: str
    goal: str
    changed_files: list[str]
    tests: list[str]
    result: str
    summary: str
```

### ContextBundle

职责：

```text
为当前任务构建可投喂给 AgentLoop 的上下文包
```

建议字段：

```python
@dataclass(frozen=True)
class ContextBundle:
    task: str
    project_summary: str
    file_summaries: list[FileSummary]
    decisions: list[DecisionRecord]
    task_memories: list[TaskMemory]
```

## 模块设计

### 1. MemoryStore

文件：

```text
miniclaudecode/memory/store.py
```

职责：

```text
管理 .miniclaudecode/memory 目录
读写 project.md
读写 file summary
读写 decision record
读写 task memory
列出已有 memory 记录
保证目录自动创建
```

核心方法：

```text
ensure_dirs()
write_project_summary()
read_project_summary()
write_file_summary()
read_file_summary()
list_file_summaries()
write_decision()
list_decisions()
write_task_memory()
list_task_memories()
```

测试重点：

```text
使用 tempfile.TemporaryDirectory
不写真实 .miniclaudecode/memory
自动创建目录
写入和读取内容保真
list 方法能稳定排序
```

### 2. ProjectIndex

文件：

```text
miniclaudecode/memory/project_index.py
```

职责：

```text
扫描项目文件
过滤 .git、__pycache__、.miniclaudecode、虚拟环境
识别源码、测试、文档、配置文件
计算 sha256、size、mtime
判断文件摘要是否过期
```

核心方法：

```text
scan()
get_tracked_files()
compute_file_fingerprint()
is_summary_stale()
```

测试重点：

```text
能过滤无关目录
能识别 py、md、toml、json
hash 变化后 stale=True
hash 不变 stale=False
```

### 3. Summarizer

文件：

```text
miniclaudecode/memory/summarizer.py
```

职责：

```text
生成确定性文件摘要
第一版不调用 LLM
Python 文件提取 class 和 def
Markdown 文件提取标题
其他文本文件给出大小和前几行摘要
```

核心方法：

```text
summarize_file(path)
summarize_python(content)
summarize_markdown(content)
summarize_text(content)
```

测试重点：

```text
Python 能提取 class 和 def
Markdown 能提取标题
长文本会截断
二进制或不可读文件返回明确摘要
```

### 4. ContextBuilder

文件：

```text
miniclaudecode/memory/context_builder.py
```

职责：

```text
根据当前任务选择相关 memory
构建上下文包
限制最大字符数
优先保留项目摘要、相关文件摘要、近期任务和关键决策
```

核心方法：

```text
build(task: str, max_chars: int = 12000) -> ContextBundle
render(bundle: ContextBundle) -> str
```

选择策略第一版：

```text
任务关键词命中文件路径或摘要
优先最近 task memory
优先包含 architecture、runtime、harness、git、memory 等关键词的 decision
超过 max_chars 时按优先级截断
```

测试重点：

```text
能选择相关 file summary
能包含 project summary
能限制最大字符数
能稳定渲染 Markdown
```

## 执行步骤

### 第一步：新增 memory 包和 records

新增：

```text
miniclaudecode/memory/__init__.py
miniclaudecode/memory/records.py
tests/test_memory_records.py
```

完成：

```text
定义 FileSummary
定义 ProjectSummary
定义 DecisionRecord
定义 TaskMemory
定义 ContextBundle
提供 to_dict 和 from_dict
```

### 第二步：实现 MemoryStore

新增：

```text
miniclaudecode/memory/store.py
tests/test_memory_store.py
```

完成：

```text
目录自动创建
project.md 读写
files summary 读写
decisions 读写
tasks 读写
list 方法
```

### 第三步：实现 ProjectIndex

新增：

```text
miniclaudecode/memory/project_index.py
tests/test_memory_project_index.py
```

完成：

```text
扫描项目文件
过滤无关目录
计算 sha256
判断 stale
返回结构化文件信息
```

### 第四步：实现 Summarizer

新增：

```text
miniclaudecode/memory/summarizer.py
tests/test_memory_summarizer.py
```

完成：

```text
Python 摘要
Markdown 摘要
普通文本摘要
不可读文件摘要
```

### 第五步：实现 ContextBuilder

新增：

```text
miniclaudecode/memory/context_builder.py
tests/test_memory_context_builder.py
```

完成：

```text
根据任务关键词选择 memory
构建 ContextBundle
渲染 Markdown 上下文
限制最大字符数
```

### 第六步：接入 Harness 和 GitWorkflow

更新：

```text
miniclaudecode/harness/report.py
miniclaudecode/harness/task_harness.py
miniclaudecode/git_workflow/workflow.py
```

完成：

```text
Harness 完成后写 TaskMemory
GitWorkflow report 可生成 TaskMemory
final_report.md 记录 memory 写入路径
```

第一版可以只做可选接入，不影响现有调用。

### 第七步：CLI 接入

更新：

```text
miniclaudecode/cli.py
tests/test_cli.py
```

新增命令：

```text
python -m miniclaudecode --memory-index
python -m miniclaudecode --memory-context "当前任务"
python -m miniclaudecode --list-memory
```

能力：

```text
刷新项目文件摘要
输出当前任务相关上下文
列出已有 memory
```

## 测试计划

总测试要求：

```text
所有 memory 测试使用 tempfile.TemporaryDirectory
不写真实 .miniclaudecode/memory
不依赖真实 Anthropic API
不依赖网络
不引入不可控时间，必要时注入 now
```

测试文件：

```text
tests/test_memory_records.py
tests/test_memory_store.py
tests/test_memory_project_index.py
tests/test_memory_summarizer.py
tests/test_memory_context_builder.py
```

回归测试：

```text
python -m unittest discover
```

## 安全边界

```text
默认不记录完整大文件内容
默认不记录 .env
默认跳过 .git
默认跳过 .miniclaudecode/traces 中的长 trace
默认不上传 memory
默认不删除 memory
```

后续如果加入清理能力，必须明确用户确认。

## 面试表达

可以这样介绍：

```text
第四块我做的是 Memory and Context Engineering。传统 Agent 项目往往每次任务都重新扫描代码，或者把大量文件直接塞进上下文，成本高且容易遗漏。我实现了一个轻量记忆层，对项目结构、文件摘要、工程决策和历史任务进行持久化管理，并通过 ContextBuilder 为当前任务选择相关上下文。这样 Agent 在长任务开发中可以复用已有认知，减少重复扫描，提高任务连续性和上下文利用效率。
```

简历表达：

```text
设计并实现 Memory and Context Engineering 层，支持项目索引、文件摘要缓存、工程决策记录、任务记忆沉淀和上下文构建，使 Agent 在长任务、多轮开发中能够复用历史上下文并降低重复扫描成本。
```

## 当前状态

第四块当前处于规划阶段。

下一步从：

```text
miniclaudecode/memory/__init__.py
miniclaudecode/memory/records.py
tests/test_memory_records.py
```

开始。
