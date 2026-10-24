# M2-1 会话持久化（JSONL）

2026-10-24。目标：研究的消息、工具结果、过程事件和报告逐条落盘；服务重启后旧研究仍能打开、回放；为侧边聊天（续接上下文）、上下文压缩（compaction 条目）打基础。

## 参考依据

| 来源 | 核对内容（2026-10-24） | 本项目采用 |
| --- | --- | --- |
| [Pi SessionManager](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts) | 一个会话一个 `.jsonl`；首行 `type:"session"` 会话头（version、id、timestamp）；之后每行条目带 `id`、`parentId`、`timestamp`；`appendFileSync` 每条追加；读取时跳过无法解析的行，末尾残行后先补换行；当前分支 = 从最后一条沿 `parentId` 回到根；`compaction`、`context_edit` 等条目类型 | 同样的文件布局、条目链、追加与残行处理；`context_edit` 表示作废的草稿 |
| [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) s10 Task System | 任务状态写到磁盘，重启后可恢复 | 研究任务的结束状态与报告写入会话，重启后还原 |
| 项目设计决策（`agent-design-decisions.md`“采用方向：JSONL 会话与当前分支”） | Java 管业务持久化：Python 产生事件，Java SessionStore 按会话串行追加 | 照此分工实现 |

## 文件格式

`storage/sessions/{sessionId}.jsonl`（不进 Git）。每行一个 JSON：

```text
{"type":"session","version":1,"id":"<sessionId>","runId":"<taskId>","request":{"target":"中际旭创","question":"…"}, …}   ← 会话头
{"type":"event","id":"…","parentId":null,"runId":"…","data":{"type":"phase_changed","phase":"methods",…}}
{"type":"message","id":"…","parentId":"<上一条>","message":{"role":"assistant","tool_calls":[…]}}
{"type":"message","id":"…","parentId":"…","message":{"role":"tool","tool_call_id":"…","content":"<完整工具结果>"}}
{"type":"context_edit","id":"…","parentId":"…","targetId":"<被作废的草稿消息>","replacement":null}
{"type":"report","id":"…","parentId":"…","reportId":"<taskId>","reportVersion":1,"report":{…}}
{"type":"run_state","id":"…","parentId":"…","status":"completed","usage":{…},"modelCalls":21,"error":null}
```

所有条目沿 `parentId` 首尾相接，是一条当前分支；以后侧边聊天的追问、改写可从任一条目分出新分支，旧行不改。

## 数据怎么流动

```text
Python AgentRunner                          Java SessionStore                      网页
 job.emit(...) ──────┐                       POST /internal/sessions/{id}/entries
 messages.append(..) ├─> SessionRecorder ──>  串行追加 + 按 id 去重 + fsync    ──> storage/sessions/*.jsonl
 结束：report/run_state┘   （后台每秒一批，失败保留重试）
                                             GET /api/research/jobs/{taskId}
                                             先问 Python；找不到或 Python 不可用 → 从 JSONL 还原快照 ──> 报告 + 过程回放
                                             GET /api/research/sessions ──> “最近研究”列表
```

- **Python** `SessionRecorder`：任务创建时写会话头；`ResearchJob.emit()` 每条事件同步记一条 `event`；`runner.messages` 换成 `RecordedMessages`，`append` 记 `message`（含完整工具结果），`pop`（作废未通过核查的草稿）记 `context_edit`；结束时记 `report` 与 `run_state`，再把剩余条目提交完。提交在后台按批进行，失败保留重试，不阻塞研究；任务快照 `persistence` 字段显示已提交/未提交数量。
- **Java** `SessionStore`：按会话加锁串行写；按条目 id 去重（Python 重试不会写重复行）；新会话第一条必须是会话头；文件末尾若是写到一半的残行先补换行；写后 `force` 落盘；启动时扫描会话文件建立 `runId → sessionId` 索引。还原快照时，没有 `run_state` 的运行（中途被打断）如实标为 `failed / RESEARCH_INTERRUPTED`。
- **写入接口只在本机**：Java 只监听 127.0.0.1；网页代理只转发 `/api`，`/internal` 不经过网页代理。

## 代码位置

| 位置 | 作用 |
| --- | --- |
| [session_recorder.py](../apps/agent/app/services/session_recorder.py) `SessionRecorder`、`RecordedMessages` | 条目生成、后台提交与重试、消息记录 |
| [research_jobs.py](../apps/agent/app/services/research_jobs.py) `JobStore.start()`、`ResearchJob.emit()`、`snapshot()` | 建记录器、事件入 JSONL、持久化状态 |
| [agent_runner.py](../apps/agent/app/services/agent_runner.py) `__init__`、`persist_outcome()` | 消息记录、结束时写报告与状态 |
| [SessionStore.java](../apps/server/src/main/java/com/pathofmarket/server/session/SessionStore.java) | 追加、去重、残行、读取、还原快照、列表 |
| [SessionController.java](../apps/server/src/main/java/com/pathofmarket/server/controller/SessionController.java) | 写入接口与研究记录接口 |
| [ResearchJobController.java](../apps/server/src/main/java/com/pathofmarket/server/controller/ResearchJobController.java) | 任务查询的 JSONL 回退 |
| [SessionProperties.java](../apps/server/src/main/java/com/pathofmarket/server/config/SessionProperties.java)、`application.properties` | `sessions.dir`（默认 `storage/sessions`，可用 `SESSIONS_DIR` 覆盖） |
| [RecentSessions.tsx](../apps/web/src/features/research-lab/RecentSessions.tsx) | 网页“最近研究” |

## 验证

- Python：`tests/test_sessions.py`（假 SessionStore 接收：会话头在前、`parentId` 首尾相接、消息/事件/报告/结束状态齐全、草稿作废记为 `context_edit`、存储暂不可用时研究照常完成且恢复后补交不重复）。
- Java：`scripts/check-sessions.py`（真实启动 Java：写入、去重、首条须为会话头、id 校验、一行一条、从 JSONL 还原快照、残行后继续追加、中断运行标为中断、最近研究列表、未知任务 404、**Java 重启后重建索引并还原**，共 11 项）；原有 `check-job-bridge.py` 13 项、`check-research-bridge.py` 33 + 12 项通过。
- 真实运行：见任务板 M2-1 行。

## 未做 / 边界

- 2026-10-24 晚已提前实现未完成任务接续：按当前 `parentId` 链重建消息并应用 `context_edit`；Python 执行检查点保存笔记/证据/写作进度，Java JSONL 新增 `continuation` 与 `report_draft` 条目。新运行关联原任务、旧结果不改；逐节正文校验后保存，失败从未完成章节继续。实际范围与验证见 [调用预算与接续](budget-and-continuation.md)。交互式分支/回退、侧边聊天仍随 M2-4 实施。
- 没有 compaction 条目（M2-5）。

2026-10-24最新：M2-4已接入报告侧边追问、六工具补查、正文局部修订版本、前后对照和交互式父链分支。新增followup/chat_turn条目，旧行不改；重启读取与失败证据复用通过隔离集成。上文“随M2-4实施”的交互部分已有基础实现，真实对话效果仍待使用验收；见[m2-4-report-discussion.md](m2-4-report-discussion.md)。
- 研究进行中如果 Java 不可用，条目暂存在 Python 进程内并重试；若 Python 也在此期间退出，未提交的条目会丢失（快照的 `persistence.unsent` 会显示积压）。
- 写入接口没有鉴权（只监听本机）；部署到多人环境前需加鉴权。
