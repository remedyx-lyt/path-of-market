# Path of Market（市场之路）

Path of Market（市场之路）是一个基于大模型的个人财经研究工作台，内部包含研究 Agent。它帮助用户持续积累资料、比较变化，从不同视角展开有来源的分析，并发现和自己研究风格相关的线索。它不是自动交易系统，也不是荐股系统。

第一版做成本地运行的网页应用，通过浏览器使用；功能稳定后再考虑线上部署或桌面客户端。

## 当前状态

截至 2026-10-13，M0-1 Python 研究服务骨架、M0-2 Java 主后端启动、M0-3 Java 调用 Python 均已完成并通过实际 HTTP 检查。Java 可将研究请求交给 Python，并返回演示报告；前端工程仍待实现，整个应用最小闭环尚未完成。

已初始化本地 Git，分支为 `main`。当前没有配置远程地址，代码和提交先保存在本地。

当前下一项为 M0-4 React 页面启动，随后 M0-5 在网页展示演示报告。Python 的演示服务只验证请求与报告格式，尚未接入真实模型、资料或研究 Agent。

## 启动 Python 研究服务

在 PowerShell 中执行：

```powershell
Set-Location 'D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路'
.\scripts\start-agent.ps1
```

服务启动后打开 `http://127.0.0.1:8000/docs`，可以查看接口，并在 `POST /research/mock` 中点击 **Try it out**、**Execute** 发送示例请求。服务根地址也会跳转到接口文档。

另开一个终端检查接口：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-agent.py
```

启动脚本自动定位项目和虚拟环境，第一次缺少环境或依赖时会安装 `apps/agent/requirements.txt`。已有环境需要重装锁定版本时使用 `-InstallDependencies`，开发时可使用 `-Reload`，指定端口用 `-Port 8001`。按 Ctrl+C 停止服务。

详细请求示例、字段限制和验证结果见 `docs/first-step.md`。

## 启动 Java 主后端

在另一个 PowerShell 终端执行：

```powershell
Set-Location 'D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路'
.\scripts\start-server.ps1
```

启动脚本先构建再运行。第一次需要联网，由 Maven Wrapper 下载固定版本 Maven 和项目依赖；本机需要 JDK 21 或更高版本，无需单独安装 Maven。

打开 `http://127.0.0.1:8080/api/health`，应看到 `{"status":"ok","service":"server"}`。这里展示健康检查 JSON，完整操作页面属于后续前端任务。

另开终端检查接口：

```powershell
.\scripts\check-server.ps1
```

默认只监听本机 `127.0.0.1:8080`。启动指定端口用 `-Port 8081`，对应检查用 `-BaseUrl http://127.0.0.1:8081`；按 Ctrl+C 停止服务。同一工程保持一个 Java 实例运行，重新构建前先停止原实例。

Java 健康检查只说明 Java 应用可接收请求；研究调用已在 M0-3 接入。Java 启动基础见 `docs/second-step.md`，研究请求与错误格式见 `docs/third-step.md`。

## 通过 Java 提交演示研究

保持 Python 和 Java 两个服务运行，在另一个终端执行：

```powershell
$researchPayload = @{
    target = '示例公司'
    question = '如何研究它的研发投入变化？'
    userStyle = '关注长期增长和风险验证'
    omens = @('opportunity', 'abyssal_echoes')
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/research/mock' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($researchPayload)) | ConvertTo-Json -Depth 10
```

请求进入 Java 的 `POST /api/research/mock`，再由 Java 调用 Python 的 `/research/mock`。报告仍明确标记为演示，不读取真实资料、不调用模型。

验证整条后端链路及隔离的故障场景：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-research-bridge.py --check-errors
```

默认 Python 地址为 `http://127.0.0.1:8000`，连接超时 3 秒，完整响应等待上限 10 秒。启动 Java 时可用 `-AgentBaseUrl` 和 `-AgentTimeoutMs` 覆盖地址与响应等待上限；完整配置、错误码和验证结果见 `docs/third-step.md`。

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
