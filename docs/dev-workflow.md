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

2026-10-12 已核对并统一顺序：M0 服务骨架 → M1 真实研究 Agent → M2 Java 与网页 → M3 研究积累与特色功能。

当前功能任务为 M0-1，范围见 `docs/first-step.md`。用户本轮只要求检查、规划、更新文档和保存 Git；功能实现保持待做。用户之后明确要求实施某个任务时，该请求就是本任务的执行依据，不需要重复要求确认。

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
