# AI 协作开发工作流

## 聊天框分工

推荐使用一个主规划聊天框和多个任务聊天框：

```text
主规划聊天框：总规划、架构决策、任务拆分、路线调整
任务聊天框：每个只做一个小功能
项目文档：所有聊天框共享的记忆
```

## 新任务聊天框开场模板

以后开新聊天框时，可以直接复制下面这段：

```text
请先阅读这个项目的 README.md 和 docs 下的核心文档：

D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\README.md
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\docs\architecture.md
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\docs\product-plan.md
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\docs\agent-concepts.md
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\docs\current-state.md
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\docs\task-board.md
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\docs\design-style.md（如果本次涉及前端）

项目架构是：
- apps/web：React 前端
- apps/server：Java Spring Boot 主后端
- apps/agent：Python FastAPI Agent 服务

这次只做一个任务：
【在这里写本次任务】

要求：
- 不重新设计架构。
- 不改无关模块。
- 先说明会改哪些文件，再执行。
- 完成后运行可行的检查。
- 完成后更新 docs/current-state.md 和 docs/task-board.md。
- 如果涉及前端 UI，必须遵守 docs/design-style.md。
```

## 单个任务的标准流程

1. 读项目文档。
2. 确认当前任务和验收标准。
3. 查看相关目录和已有代码。
4. 只修改任务相关文件。
5. 运行能运行的检查。
6. 更新 `docs/current-state.md` 和 `docs/task-board.md`。
7. 检查 Git diff，将本任务的代码、必要说明和进度更新保存为一个提交。
8. 在最终回复里说明结果、运行方法、验证情况、提交标识和下一步。

## 当前实施顺序与范围

2026-10-12 用户已确认顺序：M0 完整应用骨架 → M1 真实研究 Agent → M2 研究积累与资料完善 → M3 特色功能。

M0 依次完成 Python 演示服务、Java 调用、网页展示；先看到完整应用，再接真实研究能力。此前把真实 Agent 提到 Java 和网页之前的顺序已修正，三应用架构和原产品逻辑保持不变。

2026-10-13 用户已要求执行第一步，M0-1 已完成。下一项为 M0-2 Java 主后端启动。任务范围和实际状态以任务板和当前进度为准；用户明确要求实施某个任务时，该请求就是本任务的执行依据，不需要重复要求确认。

任务完成要区分准备工作和可运行结果。虚拟环境建立不等于服务启动，mock 接口通过不等于真实 Agent 通过。

## Git 保存

本地仓库已初始化，主分支 `main`；GitHub 尚未创建。每个明确任务完成后及时保存本地提交，后续创建 GitHub 仓库时承接这份历史。

详细流程见 `docs/git-workflow.md`。不要将虚拟环境、密钥、私人上传资料或研究运行结果加入版本库。

## 任务粒度示例

合适的任务：

- 搭建 Python Agent hello world。
- 搭建 Java Server hello world。
- 实现 Java 调 Python mock research 接口。
- 做一个前端 mock 报告页面。
- 接入 DeepSeek 的第一个研究报告生成接口。

不合适的任务：

- 一次性完成整个项目。
- 同时做前端、后端、数据库、RAG、部署。
- 没有验收标准的大范围“优化一下”。

## 共享记忆原则

- `docs/current-state.md` 是最重要的当前进度文件。
- `docs/task-board.md` 是任务队列。
- `docs/architecture.md` 是架构约束。
- 如果新聊天框不知道上下文，先让它读这些文档，不要靠口头补充一大段。

## 实施依据与文档分工

| 文档 | 指导什么 |
| --- | --- |
| `docs/architecture.md` | 职责边界：网页、Java、Python 各自做什么 |
| `docs/task-board.md` | 已确定的任务顺序和下一项任务 |
| `docs/current-state.md` | 实际完成内容、检查结果与待做状态 |
| `docs/first-step.md` | M0-1 的接口、字段、文件范围和验收标准 |
| `README.md` | 项目入口与概要，详细执行以对应任务规格为准 |

当前采用原设计的完整应用最小闭环，并保留新增的接口与验收细节。整理文档不应直接替换既定开发顺序；新的路线想法先说明理由和影响，再按用户确定的方向同步任务板。
