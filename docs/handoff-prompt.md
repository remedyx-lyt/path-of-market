# 新聊天框交接提示词

## 通用版本

```text
请作为 Path of Market（市场之路）项目的开发助手工作。

项目路径：
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路

请先阅读：
- README.md
- docs/architecture.md
- docs/research-runtime-plan.md（运行架构、长报告与表图要求）
- docs/product-plan.md
- docs/agent-concepts.md
- docs/current-state.md
- docs/task-board.md
- docs/first-step.md（如果本次是 M0-1）
- docs/git-workflow.md
- docs/sixth-step.md（整套应用运行与检查）
- docs/m1-1-model.md（本地模型配置、真实调用与研究状态）
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
- 检查改动，将本任务的代码和相关文档保存为 Git 提交，并报告提交标识。
- 功能任务是否实施，以用户当前明确请求为准；只规划时保持待做。
- 如果涉及前端 UI，遵守 docs/design-style.md 的黑白极简工具风格。
```

## 第一阶段任务版本

```text
请作为 Path of Market（市场之路）项目的开发助手工作。

项目路径：
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路

请先阅读 README.md 和 docs 下的核心文档。

实施顺序：
M0 完整应用骨架 -> M1 真实研究 Agent -> M2 研究积累与资料完善 -> M3 特色功能。
M0 内部顺序：Python 演示接口 -> Java 启动与调用 -> 网页输入与展示。
完整骨架可用后再接真实模型和资料工具。

本次任务由用户填写；用户明确要求实施后执行：
【填写任务编号和目标】

如果本次任务是 M0-1：
先读 docs/first-step.md，只实现 Python 健康检查、mock 研究接口和启动说明。
不要接真实 LLM、资料检索、数据库、Java 或前端。
如果用户本次只要求检查或规划，不进行业务实现。

截至 2026-10-23，M0-1 至 M0-6、M1-1 均已完成，网页已通过 Java/Python 实际调用 DeepSeek，模型分析明确未检索资料；当前下一项为 M1-2。本地 `.env` 已配置，读取和检查时不要输出或提交密钥。
正式研究报告的表格、图表、长文分章与上下文/检查点要求已补进计划，仍按 M1-2 → M1-3 → M1-4 → M2 顺序逐项实施。
M1 的真实 Agent 任务必须单独验证模型选择工具、依据结果补查或结束；不虚构来源或工具记录。

完成后运行对应检查，更新 docs/current-state.md 和 docs/task-board.md，检查 Git diff 并提交本任务改动。
```
