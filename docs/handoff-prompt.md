# 新聊天框交接提示词

## 通用版本

```text
请作为 Path of Market（市场之路）项目的开发助手工作。

项目路径：
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路

请先阅读：
- README.md
- docs/architecture.md
- docs/product-plan.md
- docs/agent-concepts.md
- docs/current-state.md
- docs/task-board.md
- docs/design-style.md（如果本次涉及前端 UI）

项目基本架构：
- apps/web：React + Vite + TypeScript 前端
- apps/server：Java + Spring Boot 主后端
- apps/agent：Python + FastAPI Agent 服务

本次只做一个任务：
【填写任务】

要求：
- 按现有架构继续，不要重新设计。
- 只改和本任务有关的文件。
- 先探索和说明方案，再修改。
- 完成后运行可行的检查。
- 完成后更新 docs/current-state.md 和 docs/task-board.md。
- 如果涉及前端 UI，遵守 docs/design-style.md 的黑白极简工具风格。
```

## 最小闭环任务版本

```text
请作为 Path of Market（市场之路）项目的开发助手工作。

项目路径：
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路

请先阅读 README.md 和 docs 下的核心文档。

当前里程碑是“最小闭环”：
前端 -> Java 主后端 -> Python Agent 服务 -> Java -> 前端。

这次只做一个任务：
【填写：Python Agent hello world / Java Server hello world / Java 调 Python / 前端展示 mock 报告】

不要接真实 LLM，不要做 RAG，不要做数据库。先把链路打通。
完成后更新 docs/current-state.md 和 docs/task-board.md。
```
