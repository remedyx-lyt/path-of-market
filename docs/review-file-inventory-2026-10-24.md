# 文件盘点与检查范围（2026-10-24）

本轮逐文件读取、盘点版本管理中的自有源码、文档、测试、脚本和配置，并做对应静态检查；关键执行链路逐段审阅，历史文档检查需求、进度和冲突。此清单不代表每个分支的业务语义都已经穷尽验证。具体发现、修复与真实验收边界见 [稳定性审查](reliability-review-2026-10-24.md)。

共 200 个自有文本文件（含 34 个目录占位，非占位 166 个）；另有 39 个上游/图片文件按目录和哈希核对。上游 manifest 的 36 个文件哈希通过。

不逐个检查的生成内容：`.git` 内部对象、`.venv`、`node_modules`、`target`、`dist`、PDF/PNG/阅读缓存、私人研究报告和运行日志。失败任务与成功任务的相关 JSONL 单独用于诊断；密钥 `.env` 不回显、不纳入清单。

文件级结果：Python AST、JSON/XML 解析、PowerShell 脚本语法通过；前端类型/构建、Java 编译和相关回归另见审查记录。Markdown 本地链接检查结果见文末。

| 文件 | 行数 | 检查类别 |
| --- | ---: | --- |
| [.env.example](../.env.example) | 25 | 配置/入口 |
| [.gitattributes](../.gitattributes) | 12 | 配置/入口 |
| [.gitignore](../.gitignore) | 50 | 配置/入口 |
| [AGENTS.md](../AGENTS.md) | 11 | 文档/需求 |
| [README.md](../README.md) | 164 | 文档/需求 |
| [apps/agent/app/__init__.py](../apps/agent/app/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/api/__init__.py](../apps/agent/app/api/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/api/routes/.gitkeep](../apps/agent/app/api/routes/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/api/routes/__init__.py](../apps/agent/app/api/routes/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/api/routes/jobs.py](../apps/agent/app/api/routes/jobs.py) | 52 | Python 源码 |
| [apps/agent/app/api/routes/research.py](../apps/agent/app/api/routes/research.py) | 70 | Python 源码 |
| [apps/agent/app/api/routes/tools.py](../apps/agent/app/api/routes/tools.py) | 20 | Python 源码 |
| [apps/agent/app/core/agent_prompts.py](../apps/agent/app/core/agent_prompts.py) | 171 | Python 源码 |
| [apps/agent/app/core/config.py](../apps/agent/app/core/config.py) | 88 | Python 源码 |
| [apps/agent/app/core/omens.py](../apps/agent/app/core/omens.py) | 274 | Python 源码 |
| [apps/agent/app/core/prompts.py](../apps/agent/app/core/prompts.py) | 25 | Python 源码 |
| [apps/agent/app/core/research_skills.py](../apps/agent/app/core/research_skills.py) | 98 | Python 源码 |
| [apps/agent/app/db/session.py](../apps/agent/app/db/session.py) | 1 | Python 源码 |
| [apps/agent/app/main.py](../apps/agent/app/main.py) | 23 | Python 源码 |
| [apps/agent/app/models/.gitkeep](../apps/agent/app/models/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/schemas/.gitkeep](../apps/agent/app/schemas/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/schemas/__init__.py](../apps/agent/app/schemas/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/schemas/agent.py](../apps/agent/app/schemas/agent.py) | 149 | Python 源码 |
| [apps/agent/app/schemas/financial.py](../apps/agent/app/schemas/financial.py) | 100 | Python 源码 |
| [apps/agent/app/schemas/research.py](../apps/agent/app/schemas/research.py) | 125 | Python 源码 |
| [apps/agent/app/services/__init__.py](../apps/agent/app/services/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/services/agent_runner.py](../apps/agent/app/services/agent_runner.py) | 647 | Python 源码 |
| [apps/agent/app/services/data_providers/.gitkeep](../apps/agent/app/services/data_providers/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/services/financial_data.py](../apps/agent/app/services/financial_data.py) | 229 | Python 源码 |
| [apps/agent/app/services/ingestion/.gitkeep](../apps/agent/app/services/ingestion/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/services/llm/.gitkeep](../apps/agent/app/services/llm/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/services/model_client.py](../apps/agent/app/services/model_client.py) | 263 | Python 源码 |
| [apps/agent/app/services/model_json.py](../apps/agent/app/services/model_json.py) | 113 | Python 源码 |
| [apps/agent/app/services/rag/.gitkeep](../apps/agent/app/services/rag/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/services/report_figures.py](../apps/agent/app/services/report_figures.py) | 228 | Python 源码 |
| [apps/agent/app/services/research_jobs.py](../apps/agent/app/services/research_jobs.py) | 107 | Python 源码 |
| [apps/agent/app/services/runner_evidence.py](../apps/agent/app/services/runner_evidence.py) | 258 | Python 源码 |
| [apps/agent/app/services/runner_methods.py](../apps/agent/app/services/runner_methods.py) | 151 | Python 源码 |
| [apps/agent/app/services/runner_omens.py](../apps/agent/app/services/runner_omens.py) | 105 | Python 源码 |
| [apps/agent/app/services/runner_reading.py](../apps/agent/app/services/runner_reading.py) | 236 | Python 源码 |
| [apps/agent/app/services/runner_report.py](../apps/agent/app/services/runner_report.py) | 628 | Python 源码 |
| [apps/agent/app/services/runtime.py](../apps/agent/app/services/runtime.py) | 29 | Python 源码 |
| [apps/agent/app/services/session_recorder.py](../apps/agent/app/services/session_recorder.py) | 141 | Python 源码 |
| [apps/agent/app/services/workflows/.gitkeep](../apps/agent/app/services/workflows/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/services/workflows/__init__.py](../apps/agent/app/services/workflows/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/services/workflows/mock_research.py](../apps/agent/app/services/workflows/mock_research.py) | 44 | Python 源码 |
| [apps/agent/app/tools/.gitkeep](../apps/agent/app/tools/.gitkeep) | 1 | 目录占位 |
| [apps/agent/app/tools/__init__.py](../apps/agent/app/tools/__init__.py) | 1 | Python 源码 |
| [apps/agent/app/tools/cninfo.py](../apps/agent/app/tools/cninfo.py) | 249 | Python 源码 |
| [apps/agent/app/tools/contracts.py](../apps/agent/app/tools/contracts.py) | 79 | Python 源码 |
| [apps/agent/app/tools/documents.py](../apps/agent/app/tools/documents.py) | 271 | Python 源码 |
| [apps/agent/app/tools/market.py](../apps/agent/app/tools/market.py) | 196 | Python 源码 |
| [apps/agent/app/tools/pdf_render_worker.py](../apps/agent/app/tools/pdf_render_worker.py) | 36 | Python 源码 |
| [apps/agent/app/tools/pdf_worker.py](../apps/agent/app/tools/pdf_worker.py) | 35 | Python 源码 |
| [apps/agent/app/tools/registry.py](../apps/agent/app/tools/registry.py) | 151 | Python 源码 |
| [apps/agent/app/tools/visuals.py](../apps/agent/app/tools/visuals.py) | 69 | Python 源码 |
| [apps/agent/requirements.txt](../apps/agent/requirements.txt) | 18 | 配置/入口 |
| [apps/agent/ruff.toml](../apps/agent/ruff.toml) | 8 | 配置/入口 |
| [apps/agent/skills/company-financial-research/SKILL.md](../apps/agent/skills/company-financial-research/SKILL.md) | 38 | 文档/需求 |
| [apps/agent/skills/company-financial-research/references/metrics-and-charts.md](../apps/agent/skills/company-financial-research/references/metrics-and-charts.md) | 35 | 文档/需求 |
| [apps/agent/skills/company-financial-research/references/upstream.md](../apps/agent/skills/company-financial-research/references/upstream.md) | 11 | 文档/需求 |
| [apps/agent/tests/.gitkeep](../apps/agent/tests/.gitkeep) | 1 | 目录占位 |
| [apps/agent/tests/support.py](../apps/agent/tests/support.py) | 194 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_activity.py](../apps/agent/tests/test_activity.py) | 98 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_failure_recovery.py](../apps/agent/tests/test_failure_recovery.py) | 234 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_methods_and_skills.py](../apps/agent/tests/test_methods_and_skills.py) | 116 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_omens.py](../apps/agent/tests/test_omens.py) | 157 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_pdf_rendering.py](../apps/agent/tests/test_pdf_rendering.py) | 57 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_runner_parts.py](../apps/agent/tests/test_runner_parts.py) | 412 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_sessions.py](../apps/agent/tests/test_sessions.py) | 111 | 检查/启动脚本与测试 |
| [apps/agent/tests/test_token_efficiency.py](../apps/agent/tests/test_token_efficiency.py) | 198 | 检查/启动脚本与测试 |
| [apps/server/.mvn/wrapper/maven-wrapper.properties](../apps/server/.mvn/wrapper/maven-wrapper.properties) | 4 | 配置/入口 |
| [apps/server/mvnw](../apps/server/mvnw) | 295 | 配置/入口 |
| [apps/server/mvnw.cmd](../apps/server/mvnw.cmd) | 189 | 配置/入口 |
| [apps/server/pom.xml](../apps/server/pom.xml) | 40 | 配置/入口 |
| [apps/server/src/main/java/com/pathofmarket/server/Application.java](../apps/server/src/main/java/com/pathofmarket/server/Application.java) | 19 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/client/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/client/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/client/AgentJobClient.java](../apps/server/src/main/java/com/pathofmarket/server/client/AgentJobClient.java) | 121 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/client/AgentResearchClient.java](../apps/server/src/main/java/com/pathofmarket/server/client/AgentResearchClient.java) | 188 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/client/AgentServiceException.java](../apps/server/src/main/java/com/pathofmarket/server/client/AgentServiceException.java) | 24 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/config/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/config/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/config/AgentProperties.java](../apps/server/src/main/java/com/pathofmarket/server/config/AgentProperties.java) | 36 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/config/SessionProperties.java](../apps/server/src/main/java/com/pathofmarket/server/config/SessionProperties.java) | 20 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/controller/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/controller/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/controller/ApiExceptionHandler.java](../apps/server/src/main/java/com/pathofmarket/server/controller/ApiExceptionHandler.java) | 25 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/controller/HealthController.java](../apps/server/src/main/java/com/pathofmarket/server/controller/HealthController.java) | 15 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/controller/ResearchController.java](../apps/server/src/main/java/com/pathofmarket/server/controller/ResearchController.java) | 32 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/controller/ResearchJobController.java](../apps/server/src/main/java/com/pathofmarket/server/controller/ResearchJobController.java) | 30 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/controller/SessionController.java](../apps/server/src/main/java/com/pathofmarket/server/controller/SessionController.java) | 44 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/domain/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/domain/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/dto/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/dto/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/dto/ApiErrorResponse.java](../apps/server/src/main/java/com/pathofmarket/server/dto/ApiErrorResponse.java) | 12 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/dto/HealthResponse.java](../apps/server/src/main/java/com/pathofmarket/server/dto/HealthResponse.java) | 5 | Java 源码/配置 |
| [apps/server/src/main/java/com/pathofmarket/server/repository/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/repository/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/service/.gitkeep](../apps/server/src/main/java/com/pathofmarket/server/service/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/java/com/pathofmarket/server/session/SessionStore.java](../apps/server/src/main/java/com/pathofmarket/server/session/SessionStore.java) | 275 | Java 源码/配置 |
| [apps/server/src/main/resources/.gitkeep](../apps/server/src/main/resources/.gitkeep) | 1 | 目录占位 |
| [apps/server/src/main/resources/application.properties](../apps/server/src/main/resources/application.properties) | 14 | Java 源码/配置 |
| [apps/server/src/test/java/com/pathofmarket/server/.gitkeep](../apps/server/src/test/java/com/pathofmarket/server/.gitkeep) | 1 | 目录占位 |
| [apps/web/index.html](../apps/web/index.html) | 14 | 配置/入口 |
| [apps/web/package-lock.json](../apps/web/package-lock.json) | 1296 | 依赖锁文件 |
| [apps/web/package.json](../apps/web/package.json) | 28 | 配置/入口 |
| [apps/web/public/favicon.svg](../apps/web/public/favicon.svg) | 4 | 配置/入口 |
| [apps/web/src/api/.gitkeep](../apps/web/src/api/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/api/research.ts](../apps/web/src/api/research.ts) | 277 | 前端源码 |
| [apps/web/src/api/researchSchemas.ts](../apps/web/src/api/researchSchemas.ts) | 216 | 前端源码 |
| [apps/web/src/app/.gitkeep](../apps/web/src/app/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/app/App.tsx](../apps/web/src/app/App.tsx) | 26 | 前端源码 |
| [apps/web/src/components/.gitkeep](../apps/web/src/components/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/features/deadeye/.gitkeep](../apps/web/src/features/deadeye/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/features/pathfinder/.gitkeep](../apps/web/src/features/pathfinder/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/features/profile/.gitkeep](../apps/web/src/features/profile/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/features/research-lab/.gitkeep](../apps/web/src/features/research-lab/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/features/research-lab/ActivityPanel.tsx](../apps/web/src/features/research-lab/ActivityPanel.tsx) | 116 | 前端源码 |
| [apps/web/src/features/research-lab/BusinessCharts.tsx](../apps/web/src/features/research-lab/BusinessCharts.tsx) | 71 | 前端源码 |
| [apps/web/src/features/research-lab/ChartDataLabels.tsx](../apps/web/src/features/research-lab/ChartDataLabels.tsx) | 45 | 前端源码 |
| [apps/web/src/features/research-lab/FinancialCharts.tsx](../apps/web/src/features/research-lab/FinancialCharts.tsx) | 94 | 前端源码 |
| [apps/web/src/features/research-lab/MarketChart.tsx](../apps/web/src/features/research-lab/MarketChart.tsx) | 48 | 前端源码 |
| [apps/web/src/features/research-lab/RecentSessions.tsx](../apps/web/src/features/research-lab/RecentSessions.tsx) | 24 | 前端源码 |
| [apps/web/src/features/research-lab/ReportText.tsx](../apps/web/src/features/research-lab/ReportText.tsx) | 46 | 前端源码 |
| [apps/web/src/features/research-lab/ResearchPreview.tsx](../apps/web/src/features/research-lab/ResearchPreview.tsx) | 57 | 前端源码 |
| [apps/web/src/features/research-lab/ResearchReport.tsx](../apps/web/src/features/research-lab/ResearchReport.tsx) | 156 | 前端源码 |
| [apps/web/src/features/research-lab/ResearchWorkspace.tsx](../apps/web/src/features/research-lab/ResearchWorkspace.tsx) | 256 | 前端源码 |
| [apps/web/src/features/research-lab/SectionTables.tsx](../apps/web/src/features/research-lab/SectionTables.tsx) | 78 | 前端源码 |
| [apps/web/src/features/research-lab/researchDraft.ts](../apps/web/src/features/research-lab/researchDraft.ts) | 50 | 前端源码 |
| [apps/web/src/features/research-lab/workspaceState.ts](../apps/web/src/features/research-lab/workspaceState.ts) | 104 | 前端源码 |
| [apps/web/src/features/research-log/.gitkeep](../apps/web/src/features/research-log/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/features/sector-map/.gitkeep](../apps/web/src/features/sector-map/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/main.tsx](../apps/web/src/main.tsx) | 10 | 前端源码 |
| [apps/web/src/pages/.gitkeep](../apps/web/src/pages/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/styles/.gitkeep](../apps/web/src/styles/.gitkeep) | 1 | 目录占位 |
| [apps/web/src/styles/global.css](../apps/web/src/styles/global.css) | 309 | 前端源码 |
| [apps/web/src/vite-env.d.ts](../apps/web/src/vite-env.d.ts) | 1 | 前端源码 |
| [apps/web/tsconfig.json](../apps/web/tsconfig.json) | 17 | 配置/入口 |
| [apps/web/vite.config.ts](../apps/web/vite.config.ts) | 27 | 配置/入口 |
| [docs/agent-concepts.md](../docs/agent-concepts.md) | 86 | 文档/需求 |
| [docs/agent-design-decisions.md](../docs/agent-design-decisions.md) | 148 | 文档/需求 |
| [docs/architecture.md](../docs/architecture.md) | 173 | 文档/需求 |
| [docs/current-state.md](../docs/current-state.md) | 141 | 文档/需求 |
| [docs/data-sources.md](../docs/data-sources.md) | 45 | 文档/需求 |
| [docs/design-style.md](../docs/design-style.md) | 104 | 文档/需求 |
| [docs/dev-workflow.md](../docs/dev-workflow.md) | 117 | 文档/需求 |
| [docs/fifth-step.md](../docs/fifth-step.md) | 113 | 文档/需求 |
| [docs/financial-research-skill.md](../docs/financial-research-skill.md) | 99 | 文档/需求 |
| [docs/first-step.md](../docs/first-step.md) | 160 | 文档/需求 |
| [docs/fourth-step.md](../docs/fourth-step.md) | 97 | 文档/需求 |
| [docs/git-workflow.md](../docs/git-workflow.md) | 72 | 文档/需求 |
| [docs/handoff-2026-10-24-m1-4.md](../docs/handoff-2026-10-24-m1-4.md) | 132 | 文档/需求 |
| [docs/handoff-prompt.md](../docs/handoff-prompt.md) | 82 | 文档/需求 |
| [docs/history.md](../docs/history.md) | 256 | 文档/需求 |
| [docs/m1-1-model.md](../docs/m1-1-model.md) | 139 | 文档/需求 |
| [docs/m1-2-tools.md](../docs/m1-2-tools.md) | 97 | 文档/需求 |
| [docs/m1-3-agent.md](../docs/m1-3-agent.md) | 125 | 文档/需求 |
| [docs/m1-4-omens.md](../docs/m1-4-omens.md) | 167 | 文档/需求 |
| [docs/m2-1-sessions.md](../docs/m2-1-sessions.md) | 69 | 文档/需求 |
| [docs/m2-9-activity.md](../docs/m2-9-activity.md) | 62 | 文档/需求 |
| [docs/methods-and-section-figures.md](../docs/methods-and-section-figures.md) | 78 | 文档/需求 |
| [docs/product-plan.md](../docs/product-plan.md) | 90 | 文档/需求 |
| [docs/reliability-review-2026-10-24.md](../docs/reliability-review-2026-10-24.md) | 116 | 文档/需求 |
| [docs/report-omens.md](../docs/report-omens.md) | 425 | 文档/需求 |
| [docs/report-tables.md](../docs/report-tables.md) | 87 | 文档/需求 |
| [docs/requirements-checklist-2026-10-24.md](../docs/requirements-checklist-2026-10-24.md) | 135 | 文档/需求 |
| [docs/research-runtime-plan.md](../docs/research-runtime-plan.md) | 155 | 文档/需求 |
| [docs/review-file-inventory-2026-10-24.md](../docs/review-file-inventory-2026-10-24.md) | 217 | 文档/需求 |
| [docs/second-step.md](../docs/second-step.md) | 106 | 文档/需求 |
| [docs/sixth-step.md](../docs/sixth-step.md) | 176 | 文档/需求 |
| [docs/skill-plan.md](../docs/skill-plan.md) | 71 | 文档/需求 |
| [docs/task-board.md](../docs/task-board.md) | 120 | 文档/需求 |
| [docs/third-step.md](../docs/third-step.md) | 150 | 文档/需求 |
| [infra/.gitkeep](../infra/.gitkeep) | 1 | 目录占位 |
| [run-m1-4-acceptance.cmd](../run-m1-4-acceptance.cmd) | 7 | 配置/入口 |
| [scripts/.gitkeep](../scripts/.gitkeep) | 1 | 目录占位 |
| [scripts/app-common.ps1](../scripts/app-common.ps1) | 107 | 检查/启动脚本与测试 |
| [scripts/check-agent-live.py](../scripts/check-agent-live.py) | 77 | 检查/启动脚本与测试 |
| [scripts/check-agent-loop.py](../scripts/check-agent-loop.py) | 309 | 检查/启动脚本与测试 |
| [scripts/check-agent-web.mjs](../scripts/check-agent-web.mjs) | 116 | 检查/启动脚本与测试 |
| [scripts/check-agent.py](../scripts/check-agent.py) | 82 | 检查/启动脚本与测试 |
| [scripts/check-app.ps1](../scripts/check-app.ps1) | 47 | 检查/启动脚本与测试 |
| [scripts/check-financial-research.py](../scripts/check-financial-research.py) | 160 | 检查/启动脚本与测试 |
| [scripts/check-financial-web.mjs](../scripts/check-financial-web.mjs) | 74 | 检查/启动脚本与测试 |
| [scripts/check-job-bridge.py](../scripts/check-job-bridge.py) | 108 | 检查/启动脚本与测试 |
| [scripts/check-model.py](../scripts/check-model.py) | 196 | 检查/启动脚本与测试 |
| [scripts/check-omens-live.py](../scripts/check-omens-live.py) | 140 | 检查/启动脚本与测试 |
| [scripts/check-recovery-web.mjs](../scripts/check-recovery-web.mjs) | 51 | 检查/启动脚本与测试 |
| [scripts/check-report-figures.py](../scripts/check-report-figures.py) | 204 | 检查/启动脚本与测试 |
| [scripts/check-research-bridge.py](../scripts/check-research-bridge.py) | 273 | 检查/启动脚本与测试 |
| [scripts/check-section-figures-web.mjs](../scripts/check-section-figures-web.mjs) | 83 | 检查/启动脚本与测试 |
| [scripts/check-server.ps1](../scripts/check-server.ps1) | 41 | 检查/启动脚本与测试 |
| [scripts/check-sessions.py](../scripts/check-sessions.py) | 178 | 检查/启动脚本与测试 |
| [scripts/check-tools.py](../scripts/check-tools.py) | 272 | 检查/启动脚本与测试 |
| [scripts/run-agent-example.py](../scripts/run-agent-example.py) | 53 | 检查/启动脚本与测试 |
| [scripts/run-m1-4-acceptance.ps1](../scripts/run-m1-4-acceptance.ps1) | 60 | 检查/启动脚本与测试 |
| [scripts/start-agent.ps1](../scripts/start-agent.ps1) | 61 | 检查/启动脚本与测试 |
| [scripts/start-app.ps1](../scripts/start-app.ps1) | 106 | 检查/启动脚本与测试 |
| [scripts/start-server.ps1](../scripts/start-server.ps1) | 58 | 检查/启动脚本与测试 |
| [scripts/start-web.ps1](../scripts/start-web.ps1) | 34 | 检查/启动脚本与测试 |
| [scripts/stop-app.ps1](../scripts/stop-app.ps1) | 18 | 检查/启动脚本与测试 |
| [scripts/try-report-tools.py](../scripts/try-report-tools.py) | 64 | 检查/启动脚本与测试 |
| [storage/uploads/.gitkeep](../storage/uploads/.gitkeep) | 1 | 目录占位 |
| [storage/vectorstore/.gitkeep](../storage/vectorstore/.gitkeep) | 1 | 目录占位 |

## 静态检查记录

- 语法/哈希异常：0。
- 本地 Markdown 目标缺失：0。
