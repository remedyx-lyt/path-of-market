# 新聊天框交接提示词

## 通用版本

```text
请作为 Path of Market（市场之路）项目的开发助手工作。

项目路径：
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路

请先阅读：
- AGENTS.md（核心设计参考、资料通读与学习交接约定）
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
- docs/m1-2-tools.md（已完成的六个资料工具、自动发现、全本连续读取）
- docs/m1-3-agent.md（当前动态循环、三个模型工具/七个底层工具、行情图表与学习入口）
- docs/methods-and-section-figures.md（当前六个逻辑工具/八个底层工具、原版方法实际处理、模型自主选图、独立写作与复核）
- docs/financial-research-skill.md（前次五个模型工具/八个底层工具、16个原版金融Skill与实际加载、原页视觉、同比/财务图表和边界）
- docs/agent-design-decisions.md（Pi/官方实践、JSONL 会话与分阶段状态）
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

截至 2026-10-24，M0-1 至 M0-6、M1-1 至 M1-3 及用户优先补充的财务研究Skill/表图/视觉均已完成；下一项M1-4。网页默认真实研究，完整PDF文字分批处理、来源/覆盖、当年报告补充、行情计算与图表已接。最新状态以financial-research-skill.md和current-state.md为准；本地.env已配置，不输出或提交密钥。
用户优先补充已完成：16个Anthropic原版金融Skill/36个许可文件保留；当前六个逻辑工具/八个底层工具，新增extract_report_data。按任务完整处理相关原版方法并形成可调整计划，模型主动选择业务/研发/财务/定性图，分阶段写作与复核。最新案例921f4324-577a-4794-abf3-2823d0bab7c8，storage/runs/section-figures-live.json；见methods-and-section-figures.md/current-state.md。
当前任务和父关系事件只在 Python 进程内，PDF/阅读/视觉缓存不是会话记忆。JSONL 追加、ID/parentId 与当前分支仍是 M2 会话方向。会话落盘、恢复/自动压缩、侧栏聊天、通用表图与长报告仍待做；核心更新说明用途与代码位置供用户学习。
M1 的真实 Agent 任务必须单独验证模型选择工具、依据结果补查或结束；不虚构来源或工具记录。

完成后运行对应检查，更新 docs/current-state.md 和 docs/task-board.md，检查 Git diff 并提交本任务改动。
```
