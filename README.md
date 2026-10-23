# Path of Market（市场之路）

Path of Market（市场之路）是一个基于大模型的个人财经研究工作台，内部包含研究 Agent。它帮助用户持续积累资料、比较变化，从不同视角展开有来源的分析，并发现和自己研究风格相关的线索。它不是自动交易系统，也不是荐股系统。

第一版做成本地运行的网页应用，通过浏览器使用；功能稳定后再考虑线上部署或桌面客户端。

## 当前状态

截至 2026-10-23，M0 完整应用骨架与 M1-1 模型接口均已完成。网页经 Java、Python 实际调用 DeepSeek 并展示模型分析、研究截止日期和任务状态；原有演示模式保留，整套应用可统一启动、检查和停止。

已初始化本地 Git，分支为 `main`。当前没有配置远程地址，代码和提交先保存在本地。

当前下一项为 M1-2：少量真实资料与工具。当前可生成模型分析，但尚未检索财报、行情或执行研究工具；页面明确标注未检索资料。

## 配置模型密钥

项目根目录 `.env` 中填写 `DEEPSEEK_API_KEY`；本次已创建该本地文件，已有文件不要覆盖。只有 Python 读取密钥，文件已被 Git 忽略。默认 `DEEPSEEK_BASE_URL=https://api.deepseek.com`、`DEEPSEEK_MODEL=deepseek-flash`；保存密钥后可直接重试。完整配置与排查见 [M1-1 说明](docs/m1-1-model.md)。

## 启动、检查、停止整套应用

在 PowerShell 中进入项目目录：

```powershell
Set-Location 'D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路'
```

启动（自动启动三个服务，检查成功后返回）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-app.ps1
```

打开 http://127.0.0.1:5173/ ，默认选择“模型分析”，填写问题后点“生成模型分析”。也可切换“演示报告”检查固定报告，不消耗模型额度。服务在后台运行，关闭启动终端后仍可使用；电脑重启后需要重新启动。

| 服务 | 端口 | 分工 |
| --- | --- | --- |
| React 网页 | 5173 | 输入与展示 |
| Java 主后端 | 8080 | 接收请求并调用 Python |
| Python 研究服务 | 8000 | 执行研究任务，当前返回演示报告 |

检查三服务与完整基础链路（使用演示接口，不调用模型账户）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-app.ps1
```

停止统一入口启动的服务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-app.ps1
```

启动记录和日志在 `.runtime/`，不提交 Git。重复启动会检查现有服务；端口冲突时退出，不接管其他进程。启动失败会清理本次创建的服务并保留日志。详细环境要求、首次安装、错误排查和验收见 [第六步运行说明](docs/sixth-step.md)。

## 单个服务开发与检查

需要分别看日志时，先停止统一入口的应用，再在三个终端分别运行 `scripts/start-agent.ps1`、`scripts/start-server.ps1`、`scripts/start-web.ps1`；在各终端按 Ctrl+C 停止。统一停止脚本不管理单独启动的服务。

Python 自动管理虚拟环境与依赖，网页按锁文件安装依赖，Java 使用 Maven Wrapper 构建。本机已验证 Python 3.14.3、JDK 25.0.2、Node.js 24.13.1 / npm 11.8.0。演示模式无需模型密钥；模型分析需本地 `.env` 配置，当前两种模式均无需数据库。

原有专项检查仍可使用：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-server.ps1
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-research-bridge.py --check-errors
```

网页构建（在 `apps/web` 目录）：`npm.cmd run build`。Python 接口文档：http://127.0.0.1:8000/docs 。各服务参数、接口和原有验收记录见第一步至第五步说明。

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
- `docs/second-step.md`：Java 主后端的启动、健康检查和第二步验收结果。
- `docs/third-step.md`：Java 调用 Python 的接口约定、配置、错误处理和第三步验收结果。
- `docs/fourth-step.md`：React 深研室页面、本地任务预览、启动与第四步验收结果。
- `docs/fifth-step.md`：网页报告调用、完整展示、等待/取消、错误和第五步验收结果。
- `docs/sixth-step.md`：整套应用启动、停止、四项链路检查与错误排查。
- `docs/m1-1-model.md`：模型密钥、真实模型调用、研究状态、证据边界与验收结果。
- `docs/git-workflow.md`：本地版本保存与后续接入 GitHub。
- `docs/data-sources.md`：候选数据来源与 Data Provider 边界。

## 开发顺序

1. **M0：完整应用骨架。** 先做 Python `/health` 和 `/research/mock`，再接 Java 和网页，跑通“输入 → Java → Python → 返回演示报告 → 网页展示”。
2. **M1：真实研究 Agent v0。** 接入模型和少量真实资料工具，验证模型选择工具、读取结果、补查或结束的研究循环。
3. **M2：研究积累与资料完善。** 保存报告、来源、运行记录和画像，完善资料检索与研究展示。
4. **M3：特色功能。** 逐步实现板块地图、追猎者、锐眼和研究 Skill。

2026-10-12 用户已确认恢复原来的最小闭环：先得到能打开、能输入、能展示演示报告的应用骨架，再接真实模型、资料工具和特色功能。应用架构和产品模块沿用原设计。

每个里程碑继续拆成小任务；完成一个任务后核查结果、更新进度文档并提交 Git。具体状态以 `docs/current-state.md` 和 `docs/task-board.md` 为准。

## Agent 的实现要求

真实研究 Agent 必须由模型根据目标和工具结果决定研究动作。运行记录要能展示：实际调用的工具、资料来源、补查行为，以及完成或停止的原因。

Mock 报告只用于验证服务接口，不代表已完成 Agent。不能把固定的提示词切换或定时查询本身当成真实 Agent 的验收结果。
