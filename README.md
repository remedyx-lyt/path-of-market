# Path of Market（市场之路）

Path of Market（市场之路）是一个基于大模型的个人财经研究工作台，内部包含研究 Agent。它帮助用户持续积累资料、比较变化，从不同视角展开有来源的分析，并发现和自己研究风格相关的线索。它不是自动交易系统，也不是荐股系统。

第一版做成本地运行的网页应用，通过浏览器使用；功能稳定后再考虑线上部署或桌面客户端。

## 当前状态

截至 2026-10-24，M0 完整应用骨架、M1-1 至 M1-3 已完成。网页经 Java、Python 运行真实研究 Agent：模型选择工具，自动找报告、分批阅读原文、查询股票日线，再返回带引用和阅读覆盖的研究报告、行情图和计算表。

已初始化本地 Git，分支为 `main`。当前没有配置远程地址，代码和提交先保存在本地。

下一项为 M1-4：预兆策略与 Agent 行为验收。模型当前使用三个逻辑工具，底层保留七个可复用工具；详见 [M1-3 使用与代码导读](docs/m1-3-agent.md)。中际旭创案例实际处理三份报告共 649 页可提取文字和约 24 个月的 486 个交易日日线。全文文字处理不等于读懂图像/扫描页。

[查看本机已完成案例](http://127.0.0.1:5173/?task=8fc56014-19be-4acb-9120-8b94556f4e6e) 不会重新调用模型。任务目前只保存在 Python 进程内，重启/淘汰后链接失效；该案例 JSON 已另存 `storage/runs/m1-3-zjxc-web-live.json`，聊天工作区另有 Markdown 备份。会话持久化与侧栏聊天按 M2 推进。

## 自动资料工具（M1-2）

输入公司与年度，程序自己寻找和下载公开年报，不需要先上传 PDF。工具层真实联网验收已通过同花顺两份年报与沪市报告查找；详细入口、六个工具及限制见 [M1-2 说明](docs/m1-2-tools.md)。

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\try-report-tools.py --company 同花顺 --years 2024 2025 --as-of 2026-10-23 --query 研发投入金额
```

此命令分批返回全本文字并演示重点回查，不调用模型账户。结果在 `storage/runs/m1-2-tools.json`；Python `/docs` 也提供底层工具验收接口。CLI 本身不代表模型已处理；网页真实研究的 Runner 会另行调用模型并记录实际处理覆盖。

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

打开 http://127.0.0.1:5173/ ，默认选择“真实研究”，填写问题后提交；它会调用模型与资料/行情工具并消耗模型额度。“模型思路”保留未检索资料的单次分析，“演示报告”可检查固定报告，不消耗模型额度。服务在后台运行，关闭启动终端后仍可使用；电脑重启后需要重新启动。

| 服务 | 端口 | 分工 |
| --- | --- | --- |
| React 网页 | 5173 | 输入与展示 |
| Java 主后端 | 8080 | 接收请求并调用 Python |
| Python 研究服务 | 8000 | 模型、动态工具循环、PDF 阅读、行情计算与进程内任务 |

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

Python 自动管理虚拟环境与依赖，网页按锁文件安装依赖，Java 使用 Maven Wrapper 构建。本机已验证 Python 3.14.3、JDK 25.0.2、Node.js 24.13.1 / npm 11.8.0。演示模式无需模型密钥；真实研究和模型思路需本地 `.env` 配置，当前均无需数据库。

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
- 数据来源：系统自动发现的公开原始资料、补充上传、后续搜索与行情 Provider。

以上是现有技术路线。当前采用独立 HTTP 模型适配与轻量 Runner，按 Pi 循环与 DeepSeek 官方工具协议实现；没有引入完整 Pi 或编排库。来源和采用理由见设计决策文档。

## 应用分层

- `apps/web`：前端操作台，负责页面、表单、报告展示和用户交互。
- `apps/server`：Java 主后端，负责主要 API、数据库、权限、任务管理和调用 Agent 服务。
- `apps/agent`：Python Agent 服务，负责深研室、锐眼、追猎者、RAG、数据工具和模型调用。

## 项目协作记忆

- `docs/architecture.md`：架构说明。
- `docs/research-runtime-plan.md`：研究上下文、工具循环、记忆、长报告、表格图表与阶段安排。
- `AGENTS.md`、`docs/agent-design-decisions.md`：核心机制参考成熟实践、JSONL 会话方向、统一资料通读和学习交接。
- `docs/m1-2-tools.md`：自动查年报、六个工具、连续全本阅读与验收。
- `docs/m1-3-agent.md`：动态研究循环、三个逻辑工具/七个底层工具、股票行情、真实案例与学习入口。
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

2026-10-24 完成 M1-3 交接，并按用户要求提前接入股票日线、行情图和指标表。示例研究截止日为 2026-10-23。通用财务表图、长文分章、会话 JSONL 落盘、上下文摘要与检查点仍待 M2；下一项是 M1-4。统一资料通读与成熟实践依据见 `docs/agent-design-decisions.md`。

每个里程碑继续拆成小任务；完成一个任务后核查结果、更新进度文档并提交 Git。具体状态以 `docs/current-state.md` 和 `docs/task-board.md` 为准。

## Agent 的实现要求

真实研究 Agent 必须由模型根据目标和工具结果决定研究动作。运行记录要能展示：实际调用的工具、资料来源、补查行为，以及完成或停止的原因。

Mock 报告只用于验证服务接口，不代表已完成 Agent。不能把固定的提示词切换或定时查询本身当成真实 Agent 的验收结果。
