# Agent 核心设计依据与决策

更新：2026-10-25。用户明确要求核心组成部分参考成熟 Agent 和官方实践。本文件区分参考事实、产品选择和实际实现；不是将某一项目的所有细节称为统一行业标准。

## 参考依据

2026-10-25新增M2-7：直接使用[MCP官方Python SDK](https://github.com/modelcontextprotocol/python-sdk) 2.3.0连接[Exa官方公开MCP](https://exa.ai/docs/get-started/exa-mcp)与[官方Fetch参考服务](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) 2026.10.24。前者用Streamable HTTP搜索，后者用固定模块stdio读取分页正文；SDK做协商、工具发现、调用与关闭。本应用额外适配只读白名单、截止日/未知日期、发现与全文阅读分离、字符游标与快照hash、原有JSONL/checkpoint、网页page=null引用校验。采用成熟协议与参考服务，未引入整套第三方Agent循环。实现/限制/测试见[MCP交接](m2-7-public-web-mcp.md)。F8范围与容量是本产品资料任务适配，见[年报年限](f8-history-window.md)。

| 一手资料 | 本次核对内容 | 本项目如何使用 |
| --- | --- | --- |
| [Pi 工具工厂](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/index.ts) | 可组合的工具集合；默认编码工具与只读工具集合分开 | 工具统一注册，根据任务选取可用集合 |
| [Pi read](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts) | 工具名称、用途、参数与执行；返回上限和继续读取位置 | PDF 按页读，显式 `truncated` / `nextOffset`，避免整本灌入上下文 |
| [Pi Agent Loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts) | 模型请求工具，程序执行并回传，继续循环；截断参数不能直接执行 | M1-3 据此实现模型与工具交替、工具调用 ID 配对、停止和预算 |
| [Pi SessionManager](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts) | 会话头、条目 ID / parentId、追加存储、分支上下文与压缩记录 | 采用 JSONL 会话事件和分支上下文方向，按阶段实施 |
| [Claude Code 官方架构说明](https://code.claude.com/docs/en/how-claude-code-works) | 取上下文→行动→验证的循环；会话消息/工具结果保存为 JSONL；上下文压缩 | 交叉核对工具、会话、恢复与上下文管理的共同机制 |
| [Pi Compaction](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md) | 对历史做摘要并保留近期消息 | M2-5 的摘要不能丢失关键数字、引用和未解决问题 |
| [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) | 原生 `tools`、`assistant.tool_calls`、`role=tool` / `tool_call_id`、结束原因与用量 | M1-3 已实现原始 ID 配对、截断参数拒绝与累计用量，不用文本关键词模拟工具调用 |

以上为 2026-10-23 查阅的一手资料；链接指向上游当前分支，后续实施相应模块时重新核对。本轮 Python 工具代码为本项目实现，没有复制或打包 Pi 源码，也没有把 Pi 安装为运行依赖。

## 已采用：工具定义与执行分离

M1-2 已实现 `ToolDefinition`、`ResearchTools` 和 Provider / DocumentStore 分层：

1. 定义包含工具名称、用途与 JSON Schema 参数；Pydantic 校验必填字段、类型、日期、页码和多余字段。
2. 执行器只分派已注册工具，工具结果包含调用 ID、名称、状态、时间、数据或错误。
3. CLI、Python HTTP 与 M1-3 模型循环共用底层执行器；主模型只看到三个组合入口。
4. 返回资料保持来源与页码，长页面分段继续读；文档内容按证据处理，不作为系统指令。

JSON Schema 参数、工具请求/结果配对、循环与有界上下文是广泛采用的机制。财经工具名称、错误码、日期筛选和返回字段是我们的业务约定，不声称是 Pi 或所有供应商的标准。底层 `callId` 是执行器记录 ID；M1-3 已另保留模型返回的原始 `tool_call_id`，满足 API 工具消息配对。

## M1-3 当时实现的循环与业务适配（历史快照；当前状态见文末与 current-state.md）

- `services/agent_runner.py` 参照 Pi 的模型→工具→结果回传循环，使用 DeepSeek 原生工具消息；只执行注册的工具，拒绝截断参数。模型选择动作，程序负责边界、数据与来源。
- 模型入口是 `find_documents`、`read_document`、`get_market_data` 三个；底层有七个工具。参考 Pi 的可组合工具集合，按财经任务组合下载/分页/查读，不照搬四个编码工具名称，也不开放任意 Shell。
- `read_document(full)` 内部用确定工作流连续分批读原文，每批成功校验才增加覆盖；主模型收到有页码要点，需要时回查。它是工具里的阅读子流程，不是自动历史 compaction。
- 阅读缓存校验 PDF/批次/问题/提示词/模型键，保留 `originRunId`。它只复用同一资料处理结果，不存用户会话，不代替 M2 JSONL SessionStore。
- 默认补查截止日当年最新已披露定期报告并强制其文字处理完成，避免年份混淆。通读是选定资料的可提取文字，不宣称图片/OCR 理解。
- `RunLimits` 有轮数、调用、时间、token 和字符边界；累计 token 在下一调用前检查，可有最后一次请求超出，不宣称精确金额硬上限。最终报告做引用/覆盖校验，再做一次文字与指标/资料范围复核，后者不是独立事实审计。
- `research_jobs.py` 事件带父关系，任务最多八个、一次一个运行；Java 提供短请求创建/查询/取消，网页轮询。当前仍是进程内事件和任务，无 JSONL 落盘、当前分支重建或重启恢复。
- 用户要求的行情提前实现：固定 Provider、同源不复权/后复权、确定性计算、真实数据图表。参考 [AKShare 腾讯行情适配](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_hist_tx.py) 的数据适配和口径处理方式；本项目独立实现与测试，未复制/打包其代码或宣称端点完全相同。

调用关系、实际案例、预算和代码导读见 `m1-3-agent.md`；M1-4 再验收预兆策略对实际研究动作的影响。

## 统一资料阅读规则：默认通读，搜索辅助

用户要求：进入本次研究的选定原始资料应完整阅读，适用于年报、季报、公告、研报、网页正文等，不只适用于年报。系统尽量自动发现与获取原文；搜索引擎摘要、标题与关键词片段用于筛选和回查，不代替全文证据。

M1-2 已实现 PDF 连续批量阅读：`read_document_batch` 从第一页开始，按字符与页数预算返回连续原文，`nextCursor` 精确接续，不跳过未命中关键词的页面。单页 `read_document` 和 `search_document` 保留供后续重点复查。网页与其他格式在各自 Provider 任务中实现相同的完整正文和分段契约。

M1-3 Runner 已区分发现、下载/解析、原文返回与 `processedPages` / `processedCharacters`。解析全本不等于模型读完，模型自称“已读”也不能替代程序记录。正文分批进入模型，每批保留要点、事实、证据与缺口，经过格式/页码校验后记覆盖；最终核对选定文档和当前年度要求。缓存复用有原处理来源。

空文本/扫描页、图表未识别、付费权限、正文获取失败，以及达到累计时间/费用预算，均应记录具体未完成范围。读完文本不代表图片内容也被理解；OCR/视觉能力扩展前明确这一点。资料不全时输出缺口，不用搜索摘要补成“全读”。通读针对纳入研究的原始资料，不要求下载所有搜索候选。

## 采用方向：JSONL 会话与当前分支

会话存储选用用户要求的 JSONL 追加方案；不是只能用这种格式才能称为 Agent。它与研究报告、画像数据库、PDF 缓存各有职责。

目标结构：一个 session 对应一个 JSONL 文件，首行是带版本、会话 ID、创建时间和研究工作区标识的会话头；后续每行是一个事件，至少包含 `id`、`parentId`、`type`、`timestamp`、`sessionId`、`runId`。消息记录角色和内容，工具记录工具调用 ID、名称、参数与结果/证据入口。使用量与配置变化记录为专门事件。

- 用户消息、模型消息、工具执行开始/结束在产生时追加，不能等整份报告完成才一起写。
- 写入由单一会话写入器串行处理并 flush；定义崩溃尾行处理、重复事件去重和锁机制。追加写不自动保证磁盘永不损坏。
- 回退/新分支追加指向所选父节点的新事件；不覆盖旧行。上下文从当前节点沿 `parentId` 回到根，其他分支仍在存储中，不混进当前模型请求。
- 摘要追加 compaction 事件并保留被替代范围、证据入口和关键研究状态，不覆盖原文；消息/工具请求与结果保持合法配对。
- 恢复运行时区分已完成、失败与中途未确认的工具动作。读取可复用，未来可能有副作用的工具不能在恢复时盲目重放。
- 事件只保存应用可见消息、动作、证据和状态；不要求记录模型私有内部推理。

职责仍保持 Java 管业务持久化：Python Runner 产生规范事件，Java SessionStore 按会话串行追加 JSONL，并管理当前分支与查询接口。业务数据库可保存报告/画像/索引，不与 Python 同时维护第二份独立会话真相。具体事件传输、提交确认和失败行为在持久化任务中一起验收。

| 阶段 | 具体交付 | 当前状态 |
| --- | --- | --- |
| M1-2 | 独立工具声明、参数校验与执行记录 | 已实现；工具返回值不是完整会话存储 |
| M1-3 | 运行内消息/事件结构、原始工具调用 ID、上下文与动态循环 | 已实现进程内父关系事件/工具协议；完整消息/结果逐条落盘、确认协议仍在 M2-1 |
| M2-1 | Java SessionStore 逐条 JSONL 落盘、研究记录、重载与尾行恢复 | 已实现（2026-10-24）：会话头 + `event`/`message`/`context_edit`/`report`/`run_state` 条目，`parentId` 单链；去重、残行、重启索引与快照还原；分支与从会话恢复上下文待 M2-4，见 `m2-1-sessions.md` |
| M2-5 | 当前分支选择/重建、摘要事件、检查点与任务恢复 | 2026-10-25已接入结构化历史摘要、近期完整工具组、原记录回查、摘要UI和恢复；真实模型语义质量待验收，见`m2-5-context-compaction.md` |
| M2-2 | 单用户跨研究记忆、确认偏好与可管理候选 | 2026-10-25已接入经历/主题观察、原话候选、确认偏好注入、工具与UI管理；真实模型个性化效果待使用观察，见`m2-2-user-memory.md` |

## 编码工具如何对应财经工作台

| Pi 能力 | 本项目需要的对应能力 | 实施安排 |
| --- | --- | --- |
| read | 读原报告、研究资料与笔记 | M1-2 已有 `read_document`；更多格式在 M2-3 |
| write | 保存研究笔记、报告与生成文件 | 缓存写入由程序执行；面向模型的笔记写入随 M2-1 / 报告组件增加 |
| edit | 修改研究草稿和假设，保留版本 | M2-1 记录与 M2-6 长报告章节；原始证据保留 |
| bash / 执行 | 运行计算、数据整理和图表程序 | 先做 M2-8 可验证的数值工具、M2-4 图表组件；需要通用代码执行时限定研究工作区、资源和结果协议 |

不会把四个名字原样复制就视为财经 Agent 完成。公开报告发现、PDF 解析、行情 Provider、数值口径和引用是本场景必须补齐的工具。若后续引入通用执行器，应单独说明用途、借鉴实现和验收，不能把网页研究服务变成全机器随意执行命令的接口。

## 报告与侧边聊天的关联（产品适配，待实现）

用户已确认未来增加可开合的侧边聊天，保留报告主区并继续追问、补查与调整。这是我们的产品设计，参考现有会话/上下文机制，不声称侧栏布局是 Pi 的实现。

报告是带版本的研究产物，会话是消息与工具事件序列；二者通过 `reportId` / `reportVersion` / `sessionId` / `runId` 关联。上下文构建器使用当前报告、选中片段、相关来源、截止日期及当前分支历史。追问、工具补查与修改均沿用同一 Runner；修改生成报告新版本，保留历史与证据。JSONL 分支节点与报告版本是不同对象，不能将每条聊天消息等同于一个报告版本。

本轮只确认规划，落实在 M2-1 的保存与关联、M2-4 的侧栏问答/补查、M2-6 的报告修改/差异；M1-3 先预留必要运行与消息标识。具体界面与交互按实现任务再参考成熟产品核对。

## 2026-10-24：直接复用金融研究 Skill 与表图/视觉

用户进一步要求“能用的原版尽量保留”。已按 Apache-2.0 保留 Anthropic `financial-services` 固定版本的16个相关 Skill/36个原始文件，附许可证、来源清单和哈希；本项目适配另放 `apps/agent/skills/company-financial-research/`，没有修改上游原件或自动运行其中脚本。

`research_skills.py` 每次实际加载本项目基本规则和原版财报解读参考，其他原版文件由 `read_research_skill` 白名单分页读取。原版中的工具环境、固定页数/图数、评级、付费数据或逐任务确认不改变本应用授权与行为；保留库不等于所有功能已可执行。采用 Skill→工具→确定性计算→表图/报告的分工，不把大段新规则硬塞成唯一系统提示词。

依据 [DeepSeek 官方 Vision](https://api-docs.deepseek.com/guides/vision/)，新增 `inspect_document_pages`；实际 PNG 输入使用 `content` 数组的 `image_url`，视觉请求不附带整页提取文字。渲染器只接收受控文档ID/页码，渲染成功与视觉模型处理成功分别记录；原始数值再与本页文本/单位核对，未核对金额不画图。局部视觉检查不能代替全本图片理解或独立审计。

完整联调暴露财务底稿随多次补查重复进入上下文；`AgentRunner.context` 已改为旧结果的有限有来源投影加一份当前底稿。完整记录仍保留，可回查；这是基本上下文投影，没有宣称完成 M2 自动 compaction/分支/会话恢复。细节、来源与学习入口见 `financial-research-skill.md`。

## 2026-10-24：代码整理、token 用量与 M1-4 预兆策略

依据 [DeepSeek KV 缓存说明](https://api-docs.deepseek.com/guides/kv_cache)、[定价](https://api-docs.deepseek.com/quick_start/pricing) 与 [Chat Completion 参数](https://api-docs.deepseek.com/api/create-chat-completion)：缓存默认开启，只有与先前请求**开头完全相同**的部分计为命中；`deepseek-flash` 命中价格约为未命中的 1/50；`usage` 返回 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`；`tool_choice` 支持 `none`。据此采用：

| 机制 | 做法 | 理由与边界 |
| --- | --- | --- |
| 用量记账 | `model_client.usage_counts` 保留命中/未命中字段，任务与网页显示命中率 | 以前只记总数，无法判断真实费用 |
| 稳定前缀 | 主循环开头固定为 系统规则+Skill → 原版财报方法 → Skill 目录 → 预兆规格 → 任务；历史投影只取决于消息本身；当前底稿和剩余轮数放在末尾 | 每轮只有新增内容计未命中 |
| 写作沿用研究前缀 | 写作阶段不再替换系统提示，写作规则作为最后一条消息追加，并发送同一组工具定义、`tool_choice=none`、JSON 模式；供应商拒绝时自动退回不带工具的旧方式 | 工具定义也属于提示开头；不带工具的写作请求会整段未命中。组合未见官方限制但也未明示支持，故保留回退 |
| 阅读笔记与问题无关 | `READ_SYSTEM` 改为通读要点，缓存键不含问题；旧键（含问题）仍可查到并转存新键 | 同一份年报换问题不再整本重读；仍是模型对原文的完整阅读，记录原运行 ID，不是会话记忆 |
| 不重复回传 | 已通读资料再次 full 只返回覆盖与提示，不再整批回传笔记 | 笔记此前已在上下文中 |
| 更少轮次 | `read_document` page 模式支持 `pages` 一次1至5页；提示允许同一轮并行调用互不依赖的工具 | 逐页一轮会让整段上下文反复计入 |
| 精简底稿 | 每轮底稿去掉逐项证据（页码/原值仍在程序与最终报告中），图表菜单只给 id/标题/主题 | 实际案例每轮约 21k→12k 字符 |
| 复核免重写 | 复核无需修改时只回 `{"unchanged":true}` | 省去整篇报告的重复输出（输出单价最高） |
| 方法计划 | 方法参考固定顺序、放在任务之前；同一任务的计划结果缓存复用 | 跨研究也能命中前缀 |
| 写作单独等待上限（真实验收后补） | `ModelSettings.report_timeout_seconds`（`LLM_REPORT_TIMEOUT_SECONDS`，默认 180，60–600）只用于写作与复核；研究轮次仍是 60 秒 | 真实案例中单次写作输出 1.27 万 token、耗时 69 秒，原来统一 60 秒上限会让整个任务失败；整体仍受 20 分钟任务预算约束 |
| 机械格式由程序整理（真实验收后补） | `normalize_report()`：引用完全相同的去重并截到 schema 上限（章节 12、图节点 3）、去掉定性图层级多余字段、预兆自评列表截到 12；同一图表被多个章节引用时保留第一次出现。均记录事件（`report_normalized`、`figure_duplicates_removed`） | 真实案例中这类机械超限每次都触发整篇重写（每次约 1 万输出 token、50 秒），连续 3 次即中止；整理不改动正文。章节数超过 12 会删掉正文，仍退回模型，并在写作要求中写明合计上限 |
| 接近上下文上限时收尾写作（真实验收后补） | 每轮决策前计算上下文长度，超过 `max_context_characters - context_reserve_characters`（真实验收时 160000 − 32000 字符；之后按用户要求上限翻倍为 320000）时发出 `context_wrapup`，不再让模型选工具，直接用已有证据写作；报告局限注明提前结束取证 | 参照 [Pi Compaction](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md) 的触发方式 `contextTokens > contextWindow - reserveTokens`（默认预留 16384 token，2026-10-24 核对）。Pi 触发后做历史摘要；本项目的摘要压缩按 M2-5 实施，现阶段先保证有完整报告而非越限后只留部分结果 |
| 写作分两步：正文与数据表（2026-10-24 补） | `compose()` 写正文与图表选择；`add_tables()` 用相同上下文前缀单独生成数据表，逐张校验、坏表丢弃并记原因；复核不带表、完成后挂回，复核出错保留原报告 | 一次输出 3–5 万字符、深层嵌套的 JSON 在真实运行中多次写坏，每次整篇重写。分步后每步输出更短、失败只影响该步；属于长文生成常见的分阶段做法，本项目分章续写仍按 M2-6 实施。模型输出的机械偏差（字段放错层、数值未加引号、页码列表等）由程序整理并记录事件，结构性损坏才重写 |
| 过程可见的事件（M2-9） | 阶段、工具、模型、计划、写作逐节事件；写作与数据表两步流式输出并识别章节标题；前端时间线 | 参照 learn-claude-code s01/s02/s05 与 DeepSeek 流式文档（见 `m2-9-activity.md`）。计划完成状态未让模型勾选（未加 TodoWrite 类工具），用程序维护的阶段表示进度 |
| 工具消息投影（本机会话补） | `self.messages` 保留完整工具结果；`ToolView` 为每条工具消息一次性生成主循环投影和“较早回查摘录”两个版本，按 `tool_call_id` 缓存；回查原文按结构识别（单页 `text` 或 `pages` 列表） | 与 [Pi Agent Loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts) 的 `transformContext` / `convertToLlm` 思路一致（完整的 AgentMessage 记录与每次请求时发给模型的消息分开，2026-10-24 核对）；Pi 每次请求重新转换，这里把投影按消息缓存以免每轮重新解析，只在进程内，不写会话文件；投影仍只取决于消息本身，改动前后发给模型的消息逐字节一致。顺带修正：通读笔记的 `facts.text` 曾被字符串匹配误判为回查原文 |

预兆（M1-4）沿用 `report-omens.md`：它是研究策略配置，不是独立模型。规格结构化在 `app/core/omens.py`，进入方法计划（专属检查与 Skill）、主循环上下文（资料偏好、工具提示、能力缺口）、写作要求（章节 `omens` 标记与 `omenCoverage`）和程序自检。程序只能核对结构与关键要素，内容是否充分由模型自评并经复核，`covered` 明确限定为“现有工具与已读资料范围内”。新闻/政策/行业历史等需要 M2-7 公开信息工具的资料一律列为 `capabilityGaps`。

不选预兆时也按问题意图选 Skill（`select_methods`），并把 Skill 目录交给主循环模型按需读取；按需读取记录在 `methodUsage.onDemandReads`。方法计划失败不再中止研究，记录 `plan_failed` 并在报告局限中注明。

## 后续核心改动的固定流程（沿用）

2026-10-24 后续补充：检查实际旧报告发现只有原版earnings-analysis默认注入，模型没有读取更详细原版；不能把保留16个文件等同于充分使用。新增按任务选择原版方法→完整阅读→模型形成研究主线/证据/图表建议→按实际取证调整→方法计划参与报告复核的内部流程，保留完整读取长度/哈希与计划。方法内容直接参考已许可的Anthropic公司研究、图表、财报workflow、质量检查和观点验证；没有引入另一套Agent框架，也不照搬固定图数/审批约定。

新增extract_report_data逻辑工具，按已通读资料的原页文字建立可核对数值，复用现有PDF/来源边界。模型在章节中选有效图表ID或提供有引用的定性图；程序负责金额/占比计算与安全绘制。用户最新要求是不机械每节凑图，选择权保留给模型，基础数据校验和来源规则由程序保证。方法模型复核不是独立事实审计。实现与原版使用审计见 `methods-and-section-figures.md`。

先查成熟实现或官方文档 → 记录采用机制与本项目适配 → 实现一个明确任务 → 用正常、缺资料、异常/恢复案例验收 → 更新本文件与任务板。尽量使用成熟库完成通用工作；业务 Provider、来源规则和金融证据口径保留为本项目职责。

## 2026-10-24：阅读恢复、失败诊断与渲染环境修复

本轮重新核对 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 对 `max_tokens`、`finish_reason=length`、用量和截断 JSON 的说明，以及 [Pi Agent Loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts) 的 `executePreparedToolCall` / `createErrorToolResult`：工具执行错误形成工具结果，模型可以据此继续；不把每个工具异常都上升为整次 Agent 失败。上述是参考机制；批次游标、预算数值与财经覆盖规则是本项目适配。

采用独立阅读输出预算，长度异常或连续格式失败时缩小失败输入并从原游标继续；只在笔记通过结构/页码校验后增加已处理覆盖。暂时连接故障同位置重试；失败仍可交回 Agent 补读；密钥/余额等全局问题和总预算仍停止。没有添加新的逻辑工具：增强 `read_document(full)` 与工具异常边界。

失败事件包含结束原因、错误码、输出上限、用量与耗时，逐次格式错误只存字段/错误类型，不回显资料全文；旧记录没有的字段不补造。方法计划请求提供实际 schema，唯一短参考路径可确定性展开；不把方法计划失败写成“已形成计划”。

PDF 渲染按 [pypdfium2 官方 API](https://pypdfium2.readthedocs.io/en/stable/python_api.html) 的渲染/`to_pil` 与非线程安全说明，放在单独可终止的进程里；沿用 PNG 大小、尺寸、页码与缓存校验，消除 Poppler 对服务 PATH 的依赖。图片渲染、模型视觉处理、财务列序语义核验仍是不同层次。

JSONL 已实现主循环消息/事件/报告保存与重启查看；仍没有重启后自动接续、分支上下文恢复或所有辅助模型调用的完整原始消息保存。SessionStore 的去重集合只在写盘成功后更新；校验失败/IO 失败不能把未写入的条目标成已保存。
# 2026-10-24 补充：调用预算与接续

## 2026-10-25实测补充：长任务恢复与局部修复

五/十年真实材料暴露的恢复修正继续沿用已有Pi父链/摘要、检查点和原生工具消息协议，没有替换Agent框架。3500token摘要改成固定长度累计合并，截断缩短重试；原消息/笔记/精确底稿保留。这是本项目预算适配，不把600–900字称为行业统一标准。真实天齐5块摘要400,595→129,812字符后完成后续。

复核采用M2-4已有的“模型提修改、程序校验合并”方向，输出短文字补丁；章节编号错误时仅用全报告逐字且唯一的oldText定位，不做含糊语义替换，引用/图表/结构继续校验。保存复核输入hash与原回复，恢复可本地重校验已付费结果；十年表格alsoFrom适配12个来源页并从原回复恢复合格表。最终天齐接续恢复2表和原复核，新增模型调用0次。未匹配金额、模糊表格与外部资料未读仍明确保留，不把任务完成当独立金融审计。

依据 [Pi session-format](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md) 当前父链、[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 的执行状态检查点，补充 Python 原子执行检查点与旧 JSONL 迁移恢复。Java 继续保存追加会话；新运行通过 continuation 条目关联旧运行，旧结果不改。取证预算与写作预留分开；本地回查不消耗模型调用额度。随后按用户要求接入 F17 大纲、逐节校验保存、摘要；成功章节不因后续失败作废，report_draft也逐条落盘。摘要只接收完整正文，避免与取证历史叠加超限；账户类错误不无限重试。代码、边界与验证见 [调用预算与接续](budget-and-continuation.md)。M2-5 上下文摘要压缩仍待做，分节写作未额外收费重生成报告验收。

## 2026-10-24：M2-4报告对话和版本

再次核对上述Pi会话格式的`parentId`/当前叶节点与agent-loop的`transformContext`、`convertToLlm`，以及[DeepSeek原生工具协议](https://api-docs.deepseek.com/guides/tool_calls/)。采用同会话追加请求、消息、工具结果与报告版本；从用户选中的节点回溯，其他分支不进入对话。运行记录与每次模型输入分开：输入为选定报告、实际通读笔记和该父链的问答，原始工具消息另存。当前尚无compaction，不能把投影说成长期记忆或摘要压缩。

## 2026-10-25：M2-5按需压缩，优先报告后的多轮追问

用户明确报告本身是持久产物，主要需要后续多轮对话压缩。按需触发，短聊天不增加摘要调用；长研究复用保护入口，完整原文阅读子调用不摘要替换。报告、最新问题、来源覆盖/方法计划和准确底稿独立注入，不让摘要模型改写正式数据。

重新核对[Pi compaction说明](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md)与[源码](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/compaction/compaction.ts)：接近窗口减预留量时触发，保留近期消息、完整工具请求/结果组，合并此前摘要与新历史并追加摘要边界。核对[Claude Code官方架构](https://code.claude.com/docs/en/how-claude-code-works)：先清理较早工具输出再摘要，并避免大工具输出造成连续压缩。采用既有ToolView精简→结构化旧历史摘要→近期消息的分层，设置有限重试/分块/每轮次数，原消息只追加不删除。

同时通过OpenAI官方文档搜索/读取核对[Codex compaction指南](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide#compaction)：Responses `/compact`生成用于后续请求的`encrypted_content`。本项目仍是DeepSeek，不把这套原生端点或不透明状态硬接到兼容Chat协议；参考继续执行的机制，使用普通JSON研究摘要，没有添加OpenAI依赖/密钥，也不声称与原生压缩等价。

业务适配：`ContextSummary`保留目标、约束、已完成、决定、未解决项和实际已读引用；新增`recall_research_context`按本分支来源/批次或章节取回保存的原记录。摘要引用与缩减量校验后才采用；不能只验证JSON格式就称事实正确。精确财务值仍从原页与底稿查，摘要不能提高阅读覆盖或抹去冲突。当前32万上限与预留量沿用程序字符预算，不冒称模型精确token窗口。

`compaction`节点追加摘要及firstKeptEntryId、原消息范围哈希；检查点保存原消息ID映射，跨轮沿当前父链复用。不重序列化聊天导致边界错位；无检查点降级也只读所选父链。27项隔离服务集成验证压缩→继续答复/调用工具→JSONL降级→重启恢复，原报告和阅读覆盖不变；11项新增单测与前端摘要检查通过，真实模型调用0次。真实摘要的语义保留质量仍待使用验收；详情及代码入口见[M2-5交接](m2-5-context-compaction.md)。下一项M2-2，未实施。

版本用程序合并经过引用校验的章节补丁，不让模型重写覆盖旧报告；修订继承原图表/数据表，明确未重新整体审计。请求先落盘、以requestId去重，有限重试与失败检查点沿用现有预算和恢复机制。本轮不新增逻辑工具，复用六个工具；21项隔离集成通过，未新增真实模型账户调用。学习入口、采用边界和验收详见[m2-4-report-discussion.md](m2-4-report-discussion.md)。

## 2026-10-25：M2-2单用户跨研究记忆

用户以自己为唯一用户，希望从近几天研究的公司/问题积累研究兴趣与偏好；本轮按此完成记忆，下一项MCP，之后才准备GitHub展示。

核对[Claude Code memory官方说明](https://code.claude.com/docs/en/memory)的跨会话持久笔记、索引/详情分开和用户可编辑；通过OpenAI官方文档搜索并读取[个性化记忆示例](https://developers.openai.com/cookbook/examples/agents_sdk/context_personalization#techniques-covered)，参考状态保存、相关记忆注入、工具记录候选、合并去重和移除。另核对[LangChain memory概念](https://docs.langchain.com/oss/python/concepts/memory)的短期状态/长期画像及条目集合取舍。本项目仍为DeepSeek+既有Runner，不复制供应商内置记忆、不训练模型、不引入整套SDK或向量数据库；Pi式JSONL继续负责会话父链，独立画像由Java保存。

选择：成功研究/追问自动聚合为可追溯经历，最近30次问题按关键词形成主题观察；观察含默认模板，只能说明近期任务涉及，不能推断持仓或风险承受力。用户直接保存或确认的偏好参与方法计划及缓存键、研究/写作/聊天上下文；本次用户问题、风格、截止日优先。模型可在正常工具循环调用`remember_user_memory`提出候选，Python/Java都核对当前用户逐字原话；确认前不注入为长期偏好。`recall_user_memory`跨独立研究回查历史问题，不把旧报告结论当新财务证据。

Java `ResearchMemoryStore`保存在已忽略的`sessions/memory/user.json`，临时文件刷盘替换、revision防旧页覆盖、48条有效条目限制及最多256个拒绝指纹；用户可编辑/移除/关闭/忽略某对象的经历。读写失败保留原文件，Python按本次任务降级，不拖垮研究。读取画像时只解析用户请求与状态行，避免重复解析原文/模型消息/完整报告。当前报告各分支的问题仍由当前父链决定；记忆读取排除当前root，避免通过全局观察混入兄弟分支。用户确认的全局偏好按其本来作用域跨会话参考。

验证：118项Python单测、20项真实记忆HTTP、32项隔离研究聊天/压缩/恢复、前端契约和实际浏览器确认/修改/刷新/开关/来源检查通过，本轮真实模型调用0次。真实DeepSeek提出建议的质量与对报告的个性化效果仍待使用观察；实现入口/边界见[M2-2交接](m2-2-user-memory.md)。

## 2026-10-25：报告研究与侧栏聊天的上下文边界

工作台后续更新：沿用已核对的[DeepSeek流式输出](https://api-docs.deepseek.com/api/create-chat-completion)与项目既有`model_client._stream_payload`回调，不新增另一套工具循环。逐段仅展示JSON中answer字段完整字符，标为未校验草稿，失败撤回；最终格式/引用校验和JSONL追加仍是正式回复边界。新增本次来源基线随检查点保存，防止上一轮资料冒充再次补查。恢复同一问题沿用基线，新问题重新设置；机制适配与39项专项/34项隔离检查见[工作台交接](workbench-layout.md)。

重新核对[Pi agent-loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)：运行记录保留AgentMessage，调用边界才转换为模型输入；当前源码还提供prepareRequest/prepareNextTurn等准备点。采用的是“持久记录与每次输入分离”的机制，不宣称本项目直接运行了Pi。原有父链与完整工具请求/结果配对继续使用。

实际适配：已完成报告是独立产物，聊天第一次进入时按可靠消息ID保留聊天父链，原研究流水、年报笔记、精确底稿另存可回查；报告投影只重复正文，不重复整份日线/表图/旧草稿。单独提供补查新笔记和日期资格；收尾只留未读搜索目录，避免摘要数字冒充新成果。用户要求补查且存在有效新资料时，回复至少引用新增来源；该检查证明实际阅读与引用关联，不等于自动证明所有文字事实。

预算预留与下一请求估算是本项目的业务策略，仍维持100万token/72调用/900秒；取证接近边界先用已读证据答复并说明缺口，而非提高预算或无限重试。最多两次格式/引用修正、保存具体诊断；无日期网页仍不合格。真实旧追问复用已读记录，2次调用完成，详见[修复记录](discussion-budget-repair.md)。


## 2026-10-25：明确补查与原生工具选择

实际追问失败不是搜索为空，而是auto允许模型连续三次直接回答；答后反复校验缺证据不能替代工具执行。核对[DeepSeek原生工具选择](https://api-docs.deepseek.com/api/create-chat-completion/)：指定函数在关闭thinking时可用；本项目原客户端已关闭。采用标准named tool_choice：显式补查先检索，有候选再读，关键词/来源仍由模型选。无新证据时不让文字解释冒充成功，站点失败则换词/候选，原预算与真实引用条件保留。

补查决策只传提要、目录、本轮工具结果及已读笔记；未读搜索摘要数字不送进答案生成。沿用Pi式assistant/tool消息循环、JSONL、当前分支与检查点，不用一条提示词假装约束已落实。DeepSeek[独立Search/Fetch API](https://api-docs.deepseek.com/guides/search/)确实可联网，本项目当前仍是Exa/Fetch MCP，未接原生搜索。真实两轮与最终逐来源核验、具体文件入口和边界见[补查修复交接](discussion-search-repair.md)。

## 2026-10-26：结构化财务报表（AKShare）与引用只到资料

用户决定两件事：引用不再要求精确到页；财务数字接 AKShare 直接用，不与年报比对，年报负责经营细节、业务结构、产能、风险和管理层表述。

- 来源核对：AKShare 1.19.3 文档的 `stock_profit_sheet_by_report_em` / `stock_balance_sheet_by_report_em` / `stock_cash_flow_sheet_by_report_em`（akshare.akfamily.xyz），本机实测天齐锂业字段：`REPORT_DATE`、`NOTICE_DATE`、`OPERATE_INCOME`、`PARENT_NETPROFIT`、`DEDUCT_PARENT_NETPROFIT`、`OPERATE_COST`、`RESEARCH_EXPENSE`、`TOTAL_ASSETS`、`TOTAL_LIABILITIES`、`TOTAL_PARENT_EQUITY`、`MONETARYFUNDS`、`ACCOUNTS_RECE`、`INVENTORY`、`NETCASH_OPERATE`。只用这个库，不复制其源码；依赖固定在 `requirements.txt`。
- 通用机制：工具定义与执行分离（沿用 Pi 风格的 `ToolDefinition` 注册表），第三方失败转成受控 `ToolError`，不外泄堆栈。
- 本项目选择：由程序在首份资料通读后自动调用一次，不放进模型工具列表——数据只属于本次研究主公司（底稿不区分公司），也避免改变工具定义导致前缀缓存失效。按 `NOTICE_DATE` 过滤到研究截止日；按“证券+日期”缓存原始行（`storage/documents/financial-db/`，不提交）。同一指标有结构化数时直接用它；没有（失败、北交所、研发投入等）才用年报原文取数。
- 局限（写入报告）：数据库可能是后续更正/重述后的数值；产能、产销、客户集中度、分业务收入不在三大报表里。
- 引用：`check_citation` 只核对来源是否本次取得并读完；`loosen_page` 把对不上的页码去掉、保留来源，用于正文、定性图、数据表、分节写作和报告追问。不存在或未读完的来源仍不通过。表格数字无页码时 `check_table` 在整份资料或结构化数值内核对，核对不上的格子照旧标 `*`，不删表。

追加（同日）：分业务收入改用 AKShare `stock_zygc_em`（主营构成，按行业/产品/地区的收入、成本、毛利率；1.19.3 实测列：报告日期、分类类型、主营构成、主营收入、毛利率等）。该接口没有披露日期，套用同一报告期利润表的 `NOTICE_DATE` 过滤研究截止日；只有年报与中报期。“其中:”开头是上一项的子项，计入会重复（山东黄金实测行业合计达营收141%），程序剔除。某维度某期有结构化数据时整期只用它，不与年报抽取的分项混合（两边分项名称不同，无法逐项对齐）；主营构成取不到不影响三大报表，记缺口后仍走年报抽取。
