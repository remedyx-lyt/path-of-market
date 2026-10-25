# M2-5：报告追问的上下文压缩

2026-10-25（Australia/Sydney）。已接入代码、离线与隔离服务验收；没有重生成真实报告，没有调用真实模型账户。

## 为谁解决什么问题

主要场景是报告生成后，在侧栏连续追问、补查和局部修改。聊天越长，每次把全部旧消息重新发给模型越占空间。程序在接近阈值时，把较早历史整理成摘要，保留近期消息，继续回答。短对话不调用摘要模型。

报告生成过程也接入同一个保护入口，长研究历史有需要时才用。**不是把每份年报先摘要一下就算读完，也不是把成品报告压缩成缩水版。** 全文阅读子调用、PDF图片读取和方法阅读仍接收原始材料，不走历史摘要替换。

## 白话调用流程

用户追问 → 取所选父节点的消息与检查点 → 拼好当前报告、最新问题和准确来源/底稿 → 检查长度。

- 空间够：直接回答或调用研究工具。
- 接近阈值：较早历史分块交给摘要模型，整理目标、约束、已完成、决定、未解决问题、证据定位；近期消息保留。
- 摘要格式、引用和缩减幅度合格：记录摘要边界，发送“原系统要求 + 摘要 + 近期历史 + 当前报告/问题/底稿”，继续本轮工具循环。
- 需要旧细节：模型可以调用 `recall_research_context` 读本分支保存的笔记；需要原始金额时仍可 `read_document` 回查原页。

原始聊天、工具结果、PDF、完整笔记、报告版本、图表和阅读覆盖都保留。摘要是帮助模型接着工作的材料，不能当成新的财务证据。

## 参考成熟实现，哪些是自己的适配

| 核对的一手资料 | 采用的机制 | 本项目的适配/边界 |
| --- | --- | --- |
| [Pi compaction说明](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md)、[源码](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/compaction/compaction.ts) | 接近窗口减预留量时触发、近期消息保留、工具请求与结果不能拆、旧摘要与新增历史合并、追加摘要条目 | 沿用Python/Java，使用结构化研究摘要和JSONL边界；不是引入整套Pi依赖 |
| [Claude Code官方架构](https://code.claude.com/docs/en/how-claude-code-works) | 先精简较早工具输出，再摘要历史；不能因大工具结果不断挤满而反复压缩 | 保留既有ToolView投影，增加每轮次数和失败重试边界；不声称复制其内部算法 |
| [Codex官方compaction说明](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide#compaction) | 在后续请求中使用整理后的上下文继续执行 | Codex的Responses `/compact`与不透明`encrypted_content`属于其API机制；本项目仍用DeepSeek，使用普通结构化摘要，没有调用OpenAI原生压缩接口 |

这些是成熟实现的共同方向及不同实现选择，不能把JSONL或某一套字段称为所有Agent强制遵守的统一标准。本次没有复制第三方源码。

## 程序入口与新增工具

| 文件/入口 | 负责什么 |
| --- | --- |
| `apps/agent/app/services/context_compaction.py` / `CompactionMixin.prepare_context` | 长度触发、安全切点、分块迭代摘要、校验、投影与回查 |
| 同文件 `ContextMessages`、`projected_history` | 区分历史和当前任务尾部；摘要只影响模型输入，不改原始消息 |
| `apps/agent/app/services/agent_runner.py` / `model`、`context`、`TOOL_SPECS`、`dispatch` | 每次主循环/聊天/分节写作调用前的公共入口；注册工具；准确来源、覆盖、方法计划与底稿独立注入 |
| `apps/agent/app/services/report_discussion.py` / `prepare_followup`、`reply_context` | 重用当前父链原消息与摘要边界，不重复序列化历史；当前报告、操作和最新问题不参与旧历史压缩 |
| `apps/agent/app/services/runtime.py` / `RunLimits` | 字符预留、近期保留量、分块、摘要次数与输出限制 |
| `apps/agent/app/services/research_recovery.py`、`session_recorder.py` | 检查点保存摘要状态及消息ID；JSONL当前父链恢复；原消息不重复落盘 |
| `apps/server/src/main/java/com/pathofmarket/server/session/SessionStore.java` | 允许追加`compaction`条目；继续由Java保存会话，不新增数据库或改变三服务职责 |
| `apps/web/src/features/research-lab/ActivityPanel.tsx` | 展示整理过程、次数、前后字符数和可展开的摘要；外部文本转义 |

**新增一个模型可调用的逻辑工具：`recall_research_context`（回查研究记录）。** 定义在`agent_runner.py:TOOL_SPECS`，实现为`context_compaction.py:recall_research_context`。逻辑工具从6个增为7个；底层公开数据工具仍为8个，回查不需要网络提供方。

- `kind=reading_notes, sourceId, batch`：返回本分支已经保存的一批完整阅读笔记。批次从0开始，不重新通读、不增加阅读覆盖。
- `kind=report_section, sectionIndex`：返回当前讨论报告的一节正文和引用，章节从0开始，不修改表图。

摘要机制本身由程序自动触发，不是另一个让模型随意调用的工具。精确笔记回查没有独立模型调用，但模型决定调用和随后回答仍计入正常模型用量。

## 持久化与恢复

- 原始`messages`保持完整；摘要只替换发给模型的较早历史投影。
- `compaction`追加`summary`、`firstKeptEntryId`、边界/版本、被覆盖原消息的SHA256，以及是否为恢复记录；旧行不删不改。
- 检查点保存原消息、消息条目ID和同一摘要状态。恢复时校验边界与原消息哈希，不能把另一历史的摘要套进来。
- 有检查点优先重用；没有时只沿用户选择的JSONL父链重建，不取同会话另一个分支的最后摘要。已完成的旧任务可直接开始追问。
- 摘要不是跨报告长期记忆；M2-2用户偏好、研究记忆仍待做。

## 触发与失败边界

默认保留原32万**字符**程序上限、3.2万字符预留；接近28.8万字符才触发，尽量保留近期4.8万字符。不是DeepSeek精确token窗口，也没有更改模型上下文容量。摘要输入每块最多6.4万字符、最多8块；每轮最多4次摘要尝试，每块最多重试1次，输出最多3500 token。摘要调用纳入实际模型次数、用量和时间预算。

只在完整工具请求/结果组边界截取；当前系统要求、原始任务、当前报告、最新追问、机器底稿和准确来源索引在摘要之外。摘要引用必须对应实际来源及已读物理页，整体不超过1万字符，且至少缩小10%并回落到触发线下才采用。引用检查不能证明摘要语义毫无遗漏，所以提供原记录回查。

临时超时/格式错误有限重试，失败保留原历史，同一历史不反复压缩；账户错误正常报错。单份报告/单组输入过大、原消息残缺、分块过多或累计预算用尽仍可能停止，不能承诺无限对话。研究阶段仍保留“无法腾出空间时提前收尾并说明缺口”的兜底，原阅读与图表不清空。

## 验证

- `apps/agent/tests/test_context_compaction.py`：新增11项，覆盖短历史零摘要、真实缩减、原数据不变、整组工具消息、独立阅读不压缩、本地精确回查、超时/错误引用回滚、账户错误、检查点恢复、JSONL边界、二次摘要、不可压缩大报告停止反复尝试。
- `scripts/check-discussion.py`：27项真实Java→FastAPI→脚本模型→实际PDF工具→JSONL隔离集成。新增多轮聊天触发摘要、后续回答/回查、报告与覆盖不变、Java记录摘要与旧消息、无检查点JSONL恢复、双服务重启继续。降低阈值仅用于隔离测试，正式默认值不变。
- `scripts/check-discussion-web.mjs`：读取上述实际HTTP结果，检查前端契约/分支/摘要/字符数/时间线和外部HTML转义；保存隔离页面供浏览器核对。既有8组恢复UI和F9检查继续通过；网页与Java打包通过。
- 真实DeepSeek摘要保留语义的效果尚待使用验收。本轮的脚本模型能验证程序机制和异常边界，不能代替真实模型质量评估。真实模型调用0次。

2026-10-25真实十年报告发现并修复摘要累计膨胀：固定长度合并，截断后缩短重试，不放大原3500token/32万字符上限。12项相关单测通过（新增截断缩写路径）；天齐真实接续5个分块将400,595字符降到129,812字符，随后完成表格/复核，原12节和2,527页覆盖没有重做。原版本的实际压缩失败也保留在活动父链中，不把最终成功写成全程无故障。此处验证缩减、证据/原记录保留与继续执行；摘要语义无遗漏仍不能由JSON/页码校验保证。

M2-2与MCP此后已接入，最新任务见current-state；本说明前面的“0次真实调用”仅指首次离线交付，不能用于本轮真实十年验收。
