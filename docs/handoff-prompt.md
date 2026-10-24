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
- docs/handoff-2026-10-24-m1-4.md（最新交接：本轮改动清单、未提交/未在本机验证的状态、下一步顺序）
- docs/m1-4-omens.md（最新：Runner 拆分、token 优化、按问题/预兆选 Skill、M1-4 预兆策略与验收命令）
- docs/methods-and-section-figures.md（六个逻辑工具/八个底层工具、原版方法实际处理、模型自主选图、独立写作与复核）
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

截至 2026-10-24，M0/M1 功能链路以及 M2-9 活动流、M2-1 会话保存已实现。当前是早期研究 Agent 原型，不把功能完成等同于稳定产品。先读 current-state.md、task-board.md、reliability-review-2026-10-24.md，再定本轮具体范围。
本轮已修 F13 阅读独立预算/缩批接续、F14 调用失败诊断、F15 方法 schema 与诊断、F18 项目内 PDF 渲染；84 项 Python 与相关协议/会话检查通过，未重跑天齐真实付费报告。下一项 F16 表格容错与核验状态，然后 F17 按节生成恢复、多公司冷启动验收；之后再做默认问题、侧栏聊天、压缩、记忆与搜索。
当前六个逻辑工具/八个底层工具；16 个 Anthropic 原版金融 Skill/36 个许可文件保留。新增能力优先参考成熟 Agent / 官方协议，核心变更说明用途、代码位置与实际验证范围。
JSONL 已保存主循环消息、活动事件、报告和结束状态，可重启后查看；尚不能重启后自动接着跑，辅助子调用原始上下文也未全量保留。PDF/阅读/视觉缓存与会话记忆区分。模型密钥在本地 .env，不输出或提交；避免无必要的付费报告重生成。
M1 的真实 Agent 任务必须单独验证模型选择工具、依据结果补查或结束；不虚构来源或工具记录。

完成后运行对应检查，更新 docs/current-state.md 和 docs/task-board.md，检查 Git diff 并提交本任务改动。
```
