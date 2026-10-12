# Path of Market（市场之路）

Path of Market（市场之路）是一个基于大模型的个人财经研究工作台，内部包含研究 Agent。它帮助用户持续积累资料、比较变化，从不同视角展开有来源的分析，并发现和自己研究风格相关的线索。它不是自动交易系统，也不是荐股系统。

第一版做成本地运行的网页应用，通过浏览器使用；功能稳定后再考虑线上部署或桌面客户端。

## 当前状态

截至 2026-10-12，项目处于规划和目录骨架阶段。Python、Java 入口仍是占位文件，前端尚未建立可运行工程。Python 虚拟环境和基础依赖已准备，但没有实现服务接口。

已初始化本地 Git，分支为 `main`。GitHub 仓库尚未创建，也没有配置远程地址。

当前等待用户明确要求执行第一步；本轮只更新文档和保存 Git 记录。第一步的范围见 `docs/first-step.md`。

## 第一版功能

- 用户画像：投资风格、观察池、关注板块、风险偏好。
- 板块地图：产业链、核心公司、关键指标、催化因素、主要风险。
- 深研室：公司研究、行业研究、研报整合、反方检查。
- 追猎者：追踪公司、板块、公告、新闻和市场变化。
- 锐眼：识别和用户个人风格相关的重要变化。
- 研究日志：保存报告、假设、来源和后续问题。

## 推荐技术栈

- 前端：React + Vite + TypeScript。
- 主后端：Java + Spring Boot，负责接口、业务管理、数据库、用户画像和研究记录。
- Agent 服务：Python + FastAPI，负责 LLM、RAG、文档解析、工具调用和 Agent 工作流。
- 数据库：先用 SQLite 或 PostgreSQL，后续以 PostgreSQL 为主。
- 大语言模型：先用 DeepSeek API，后续预留其他模型供应商。
- 数据来源：上传文件、搜索工具、免费或低成本行情 API。

以上是现有技术路线。Agent 编排库尚未确定；第一步建立服务和数据格式，后续再为真实研究循环选择 SDK 或编排实现。

## 应用分层

- `apps/web`：前端操作台，负责页面、表单、报告展示和用户交互。
- `apps/server`：Java 主后端，负责主要 API、数据库、权限、任务管理和调用 Agent 服务。
- `apps/agent`：Python Agent 服务，负责深研室、锐眼、追猎者、RAG、数据工具和模型调用。

## 项目协作记忆

- `docs/architecture.md`：架构说明。
- `docs/current-state.md`：当前进度。
- `docs/task-board.md`：任务板。
- `docs/dev-workflow.md`：AI 协作开发工作流。
- `docs/handoff-prompt.md`：新聊天框交接提示词。
- `docs/skill-plan.md`：项目开发 Skill 规划。
- `docs/design-style.md`：前端设计风格。
- `docs/report-omens.md`：深研室研究报告预兆设计。
- `docs/first-step.md`：第一步的范围、数据格式和验收标准。
- `docs/git-workflow.md`：本地版本保存与后续接入 GitHub。
- `docs/data-sources.md`：候选数据来源与 Data Provider 边界。

## 开发顺序

1. **M0：Python 服务骨架。** 提供 `/health` 和 `/research/mock`，确定请求与结构化报告的格式，补齐启动说明。
2. **M1：真实研究 Agent v0。** 接入模型和少量真实资料工具，验证模型选择工具、读取结果、补查或结束的研究循环。
3. **M2：Java 与网页工作台。** Java 调用 Python，网页选择研究对象、问题和预兆，展示报告、来源与运行记录。
4. **M3：研究积累与特色功能。** 保存研究记录和画像，逐步实现板块地图、追猎者、锐眼及更多检索能力。

每个里程碑继续拆成小任务；完成一个任务后核查结果、更新进度文档并提交 Git。具体状态以 `docs/current-state.md` 和 `docs/task-board.md` 为准。

## Agent 的实现要求

真实研究 Agent 必须由模型根据目标和工具结果决定研究动作。运行记录要能展示：实际调用的工具、资料来源、补查行为，以及完成或停止的原因。

Mock 报告只用于验证服务接口，不代表已完成 Agent。不能把固定的提示词切换或定时查询本身当成真实 Agent 的验收结果。
