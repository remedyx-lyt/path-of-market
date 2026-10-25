# M2-7：MCP公开搜索与网页通读

2026-10-25。已接入研究与报告后追问的正常工具循环。GitHub展示准备在本项与用户追加的年限/双公司真实验收之后。

## 用法与新增工具

用户仍只提供对象、问题和截止日。模型按问题决定是否补外部资料，无须手工找网页发给它。

| 模型工具 | 作用 | 程序入口 |
| --- | --- | --- |
| `search_public_information` | MCP公开检索，返回候选ID/标题/URL/发布日期/有限摘要；不登记为已读引用 | `app/services/runner_web.py` 的同名方法 |
| `read_web_document` | 对本分支已发现的网页获取完整提取正文、分批交给模型、记录真实覆盖；`full`接续，`search`回查已读快照 | 同上 |

共11个模型逻辑工具；原8个底层PDF/行情工具仍保留，另有2个只读远端MCP工具。MCP是程序连接工具服务的协议，不是再接一个大模型，也不替代现有Agent循环、会话、记忆和引用检查。

调用：React → Java任务代理 → Python AgentRunner.dispatch → WebMixin → PublicWeb → 官方SDK Client → Exa远端Streamable HTTP / 本地官方Fetch stdio → 原文 → 独立阅读笔记模型调用 → 正常写作/图表核查。原文/阅读/工具事件继续进入原有JSONL与执行检查点。

## 参考与复用

- [MCP官方Python SDK](https://github.com/modelcontextprotocol/python-sdk)，固定`mcp==2.3.0`。使用SDK的Client、工具发现、JSON schema参数验证、tools/call与上下文退出；自动协商现代发现/旧版握手，不手写JSON-RPC协议。只适配搜索/Fetch，远端描述不升级成系统指令，无sampling或任意shell。
- [Exa官方MCP说明](https://exa.ai/docs/get-started/exa-mcp)。当前提供无需key的免费限流入口；调用`web_search_advanced_exa`，只发必要公开查询词，带截止日期过滤，程序再过滤有日期的未来结果。不承诺免费额度或可用性永久不变。
- [官方Fetch参考服务](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch)，固定`mcp-server-fetch==2026.10.24`。固定Python模块通过stdio启动，SDK负责生命周期；沿用其robots、公开地址与重定向检查，不开启私网访问。返回`start_index`分页截断标记，继续拉正文；重叠256字校验相邻片段，不一致则拒绝拼接。

## 真实边界

1. 发现、获取、模型阅读分开。摘要不能引用；`fetchComplete`不等于`textComplete`。选中但获取失败的网页仍保留未完成覆盖，不能静默当已读。
2. 一次获取最多10批、每批24000字，超过保留获取游标；每批读取按同一快照hash、模型与提示缓存，成功阅读后立即保存字符游标。恢复优先使用成功部分。
3. 网页分段不是PDF物理页。覆盖`unit=segment`，界面显示已读/已取字符数；最终引用`page=null`。PDF图表/财务底稿路径保留。
4. 发布日期来自搜索元数据，保留`dateStatus`；未知日期不以获取时间充数。正文通读且发布日期不晚于任务截止日才可引用；程序在报告、追问、压缩摘要与前端重复检查。当前网页不是历史存档，不能据此保证其内容与历史时点版本完全一致。
5. 只通读可取得的正文。外链、动态加载区、图片、付费/登录内容不会自动算已读；不绕过站点限制。网页数据表可按实际快照核对数字，仍不等于财务审计。
6. 搜到PDF时要求走已有官方PDF工具；任意第三方PDF导入尚未接入。行业公开资料能补查，不等于F4完整行业研究已验收；一致预期/全市场数据/估值数据库仍未接。

## 配置与检查

默认无需另填key，`.env.example`新增`MCP_WEB_ENABLED`、`MCP_SEARCH_URL`、`MCP_TIMEOUT_SECONDS`。设置`MCP_WEB_ENABLED=false`隐藏两个模型工具；原PDF/行情仍可用。Python `/tools`可查看配置状态，配置不冒充连通成功。实际连接成功/失败显示在活动流。

MCP配置在工具服务初始化时读取，修改后重启Python服务生效；不在运行中的研究里切换连接。全量136项Python检查已通过，另有本轮真实大PDF/特殊标题/缺失年度复查的针对性回归与实际80MB下载解析检查。

程序位置：`app/tools/public_web.py`处理SDK与快照；`app/services/runner_web.py`处理研究阅读；`agent_runner.py`注册/分派；`research_recovery.py`保存分支发现/覆盖；`runner_report.py`、`report_discussion.py`、`context_compaction.py`校验引用。前端`researchSchemas.ts`、`ResearchReport.tsx`、`ActivityPanel.tsx`负责契约、正文覆盖与实际事件。

离线：`python -m unittest tests.test_public_web`，覆盖真实stdio发现/调用、整段获取与阅读、断线接续、未知日期、缓存篡改、工具白名单、关闭开关、完整Agent成稿等13项；`node scripts/check-mcp-web.mjs`7组契约/引用/展示。真实公开MCP：`python scripts/check-mcp.py --live`，实际搜索2条并获取正文成功，模型调用0次。原研究/聊天/压缩/恢复32项隔离HTTP集成通过。
