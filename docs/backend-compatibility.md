# 后端迁移第一阶段 · Web API 与历史数据兼容基线

基准是本地提交 `0c6120b` 的 Spring Boot + FastAPI 实现。后续 Python 后端要接受相同的网页请求、返回前端能解析的结果，并能打开旧版写入的文件。下面的黑盒检查在独立临时目录中运行，实际启动两个服务，使用合成的资料、历史记录和模型回答。

## 复现

在仓库根目录的 PowerShell 运行下列命令。使用项目现有的 Python 虚拟环境、JDK 和 Maven Wrapper。已有可用 JAR 时，重跑可直接执行最后一行。首次安装环境见 [README](../README.md#快速开始)。

```powershell
Push-Location apps/server
try { .\mvnw.cmd --batch-mode --no-transfer-progress package } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Java 构建失败' }
.\apps\agent\.venv\Scripts\python.exe -X utf8 scripts/check-backend-contract.py
```

脚本为每次运行创建临时目录，复制固定样本，在随机回环端口启动服务，完成后清理。JSONL、记忆文件和运行检查点都指向该副本。模型、公告和行情使用测试替身。一次运行包含三次冷启动，共两次重启。公开 HTTP 场景位于 [scenarios.py](../scripts/backend_contract/scenarios.py)，与参考后端的启动代码分开；将来可用同一组请求和断言验证合并后的 FastAPI 服务。

## 12 个公开操作

下表的路径均以 `/api` 开头。`{id}` 是任务的 UUID。研究输入包含 `target`、`question`、可选的 `userStyle` 和 `omens`；模型和 Agent 还接收 `asOfDate`。字段用网页当前发送的驼峰命名。

| 方法与路径 | 输入、成功响应及前端依赖 |
|---|---|
| GET `/api/health` | `200`，`status=ok`、`service=server`。启动脚本据此判断后端就绪。 |
| POST `/api/research/mock` | 研究输入。`200` 演示报告，`mode=mock`、`isMock=true`，含标题、摘要、章节、输入回显，`sources`、`toolCalls` 为空数组。 |
| POST `/api/research/model` | 带截止日的输入。`200` 思路报告，`mode=model`、`isMock=false`、`evidenceStatus=not_retrieved`，保留 `limitations` 和 `run` 的状态序列、任务标识与起止时间。 |
| POST `/api/research/jobs` | 带截止日的输入，可传 `includeMarket`、`includeCurrentPeriod`、`includeFinancials`。`202` 返回新任务快照，`taskId` 用于轮询；已有运行时 `409 RESEARCH_BUSY`。 |
| GET `/api/research/jobs/{id}` | `200` 快照。当前任务从内存读，进程重启后从 JSONL 还原。返回活动、用量、证据覆盖和可空报告。未知任务 `404 RESEARCH_NOT_FOUND`。 |
| DELETE `/api/research/jobs/{id}` | `200` 返回原任务快照，随后轮询最终状态 `cancelled`。已写入的阅读进度可用于接续。 |
| POST `/api/research/jobs/{id}/continue` | 无请求体。`202` 返回新快照，其 `parentTaskId` 指向原任务。原任务仍可查。数据不足以恢复时 `409 RESEARCH_NOT_RESUMABLE`。 |
| POST `/api/research/jobs/{id}/chat` | `message`、`action`（`ask` 或 `revise`）、`parentId`、`requestId`。`202` 返回追问任务。`parentId` 指向选中的会话节点，`requestId` 用于识别重发。 |
| GET `/api/research/jobs/{id}/discussion` | `200` 返回 `sessionId`、`rootTaskId`、`turns` 和 `versions`。保留每次追问的父节点、来源版本和修订后的版本。未知任务返回空响应体的 `404`。 |
| GET `/api/research/sessions` | `limit` 默认 20，限制在 1–100。`200` 返回 `{sessions: [...]}`，按创建时间倒序，列表使用根任务的 `runId`。 |
| GET `/api/research/memory` | 可传 `query`、`limit`、`excludeRoot`。`200` 返回版本、开关、偏好、研究经历、公司及主题观察。记忆检索上限是 30。 |
| POST `/api/research/memory` | 发送读取时的 `revision`、`action` 和动作字段。支持保存、遗忘、开关、忽略或恢复公司。`200` 返回新快照；过期版本 `409 MEMORY_CONFLICT`，非法编辑 `400 INVALID_MEMORY`。 |

网页依赖的任务状态为 `queued / running / completed / partial / failed / cancelled`。轮询读取 `progress`、`events`、`modelCalls`、`coverage` 和 `report`；活动历史还读取 `target`、`phase`、`usage` 与 `parentTaskId`。结束时如 `persistence.unsent` 仍大于零，追问页面会继续等待落盘。完整报告、财务表图、覆盖范围和引用仍须满足现有 [Zod 校验](../apps/web/src/api/researchSchemas.ts)；对话版本与记忆分别见[对话读取](../apps/web/src/api/discussion.ts)和[记忆读取](../apps/web/src/api/memory.ts)。

无效 JSON 的参考响应是 `400`，错误码为 `INVALID_JSON`。请求字段校验失败返回 `422`，`detail` 是含 `loc`、`msg` 和 `type` 的数组。业务错误使用 `{error: {code, message}}`。两个 `404` 的差异，以及追问重发的两种结果，都已纳入回归。

## 固定历史样本与验收

[样本目录](../scripts/backend_contract/fixtures)包含 3 个 v1 会话、1 个 v1 检查点和 1 份已有偏好的记忆文件。样本由测试数据构造。检查点的证据状态来自项目离线模型读取两页合成 PDF 的结果，固定了标识并缩短了测试提示词。

| 情形 | 自动检查的行为 |
|---|---|
| 已完成研究带一次修订 | 通过根任务读取第一版，通过追问任务读取修订版。两版报告、父版本、追问节点和用户回答能够对应。 |
| 中断且仅有活动记录 | 历史可读，状态为 `failed`，错误码为 `RESEARCH_INTERRUPTED`；尝试接续得到 `409`。 |
| 中断且保有旧版检查点 | 恢复已读的两页资料，生成独立的新任务并完成报告。根据工具记录和测试模型调用记录核对没有重读。 |
| 再创建一个任务并取消 | 运行期间第二次创建得到 `409`。资料读完后取消，重启两个服务，再接续到完成；旧任务仍可按原 ID 查询。 |
| 重发同一次追问 | 任务还在内存时返回原追问任务。再次重启后重发返回 `409 RESEARCH_NOT_RESUMABLE`，打开历史仍能读到原回答。两次重发合计没有增加模型调用。 |
| 更新旧记忆 | 旧版偏好可以读取；提交过期修改不会覆盖新值，非法修改不会递增版本。重启后开关及版本仍可读。 |

测试结束逐字节核对 3 份原始 JSONL 和原始检查点。旧会话格式、批量追加、重复事件去重、截断行恢复和记忆候选规则的详细参考见 [check-sessions.py](../scripts/check-sessions.py) 与 [check-memory.py](../scripts/check-memory.py)。这些脚本仍包含旧服务的内部 HTTP 入口，第二阶段可将针对存储行为的断言移到 Python 存储实现。

下一阶段是迁移会话和记忆存储，先在样本副本上验证。当前生产请求仍走 React → Java → Python。本次基线覆盖接口、数据和执行语义，真实供应商输出质量及长时间负载需要单独验证。
