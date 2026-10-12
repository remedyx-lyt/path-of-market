# Path of Market（市场之路）

Path of Market（市场之路）是一个个人金融研究操作台。它不是自动交易系统，也不是荐股系统。它的目标是帮助用户建立市场认知、整理研究资料、追踪变化，并发现和自己研究风格相关的线索。

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

## 开发顺序

1. 项目骨架。
2. Java 主后端 hello world。
3. 前端 hello world。
4. 前后端联通。
5. Python Agent 服务 hello world。
6. Java 主后端调用 Python Agent 服务。
7. LLM API 联通。
8. 深研室 v0。
9. 数据库存储研究报告。
10. 用户画像。
11. 板块地图。
12. 文档上传 + RAG。
13. 追猎者 v1。
14. 锐眼 v1。
