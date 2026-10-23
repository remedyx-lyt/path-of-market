# M1-1：模型接口与研究状态

状态：**已完成，2026-10-23 实际模型调用、浏览器展示及隔离故障检查通过。**

## 本步结果

```text
网页选择“模型分析”并提交研究任务
  → Java POST /api/research/model
    → Python POST /research/model
      → 从根目录 .env 读取模型配置
      → 调用 DeepSeek Chat Completions
      → 校验结构化结果，附加任务状态与证据边界
    → Java 转发，网页展示模型分析
```

当前模型生成的是研究思路、待验证假设和资料需求。本次没有资料搜索、PDF 阅读、行情、RAG 或长期记忆。来源与工具记录由程序保持为空，界面标注“模型分析 · 未检索资料”。真实研究 Agent 的工具循环仍按 M1-2 至 M1-4 继续实现。

原有 `/research/mock` 与 `/api/research/mock` 保留。网页可切换到“演示报告”，无需模型密钥即可检查原有应用骨架。

## 密钥放哪里

项目根目录：

```text
D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路\.env
```

本次已创建本地文件。其他电脑首次配置时，从 `.env.example` 复制；已有 `.env` 时不要覆盖。只需填写模型区的密钥：

```dotenv
DEEPSEEK_API_KEY=在这里填写你自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
LLM_TIMEOUT_SECONDS=60
LLM_MAX_TOKENS=1800
```

配置支持普通 `名称=值`、整行注释和成对单/双引号，不做变量展开或多行值解析。注释放在单独一行。操作系统环境变量优先于 `.env`；如果修改文件后仍使用旧配置，检查同名环境变量。

只有 Python 研究服务读取这些模型设置，不传给浏览器或 Java。每次模型请求重新读取，所以密钥保存后可直接重试，无需为密钥修改而重启服务。`.env` 已被 Git 忽略；`.env.example` 只保留空密钥。

默认使用 DeepSeek 官方接口。本次实际调用验证了 `deepseek-flash`；该模型名称和请求参数来自 [DeepSeek 首次调用文档](https://api-docs.deepseek.com/)，结构化 JSON 约定见 [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。其他供应商需核对模型名称和参数，不能只凭“兼容”就视为已验证。

## 页面操作与启动

按 `sixth-step.md` 启动三个服务，打开 http://127.0.0.1:5173/ 。

1. 选择“模型分析”，填写研究对象和问题，也可先“填入示例”。
2. “研究偏好与预兆”内可修改研究截止日期，默认使用浏览器本地当天日期。
3. 点击“生成模型分析”，等待完成。
4. 查看标题、摘要、章节及资料局限；展开“查看研究任务”，查看截止日期、模型、任务状态和编号。

切换模式、日期或输入会使旧报告失效。生成时禁止重复提交和修改任务，可“取消并清空”。取消只结束浏览器等待，不保证服务端或供应商已停止执行，也不保证未产生 API 用量。

启动和 `check-app.ps1` 仍只调用演示接口，不消耗模型 API 额度。Python `/health` 保留 M0 JSON 契约，其中 `mode: mock` 是原有基础检查标记，不代表模型是否配置或账户是否可用。模型是否实际可调用，以一次成功的模型请求为准。

## 请求与运行状态

模型接口比原有四字段多一个必填日期：

```json
{
  "target": "示例公司",
  "question": "解释研究研发投入变化需要哪些资料，不提供未经证实的数字。",
  "userStyle": "关注长期增长与风险验证",
  "omens": ["opportunity", "abyssal_echoes"],
  "asOfDate": "2026-10-23"
}
```

原有长度与严格类型检查继续使用，日期须为有效 `YYYY-MM-DD`，非法请求在调用模型前返回 422。截止日期表达研究范围，不保证模型掌握该日期的事实。

成功报告包含 `mode: model`、`isMock: false`、`evidenceStatus: not_retrieved`，以及程序附加的 `run`：

- `taskId`：本次任务 UUID。
- `status`：`completed`。
- `states`：`created → calling_model → completed`，记录程序实际经历的阶段。
- `startedAt / finishedAt`：UTC 时间。
- `model / provider`：调用的模型及接口类型。
- `usage`：供应商返回的 token 用量；缺少时不虚构。
- `stopReason`：`model_response_received`。

Python 失败响应记录 `failed`、已经历阶段和错误码。Java 向网页转发允许的错误码与本地文案，不透传上游错误正文。运行状态随本次请求返回，尚无后台任务轮询或数据库保存；页面刷新后的历史保存在 M2 实现。

模型仅能生成标题、摘要和 2 至 6 个章节，其 JSON 由 Pydantic 校验。来源、工具记录、模式、状态和限制说明由程序生成，模型不能通过添加字段把自己标为已查证。用户偏好与预兆本阶段只影响提示中的关注点，后续 M1-4 才验收实际研究策略。

## 等待与错误

| 层 | 模型调用默认上限 | 演示接口 |
| --- | --- | --- |
| Python 完整调用 | 60 秒，可在 `.env` 调低 | 不调用外部模型 |
| Java 等待 Python | 75 秒，`AGENT_MODEL_REQUEST_TIMEOUT` 可配置 | 原有 10 秒 |
| 浏览器完整等待 | 90 秒 | 原有 15 秒 |
| Vite 代理 | 模型路径 100 秒 | 原有 20 秒 |

模型请求不自动重试，避免一次提交因隐藏重试产生重复调用。Python 使用标准库 HTTP 客户端，通过线程执行网络访问，并限制完整响应等待和响应体大小；慢模型请求不会阻塞健康接口。接口地址不跟随重定向，HTTPS 为默认要求，本机隔离测试允许 HTTP 回环地址。

| 错误码 | 含义 |
| --- | --- |
| `MODEL_NOT_CONFIGURED` | 密钥未填写 |
| `MODEL_CONFIG_ERROR` | 配置文件、地址、模型或数值参数有误 |
| `MODEL_AUTH_FAILED` | 密钥验证或账户权限失败 |
| `MODEL_BALANCE_INSUFFICIENT` | 余额或额度不足 |
| `MODEL_RATE_LIMITED` | 频率或额度限制 |
| `MODEL_UNAVAILABLE / MODEL_UPSTREAM_ERROR` | 连接失败或供应商异常 |
| `MODEL_TIMEOUT` | 完整模型调用超时 |
| `MODEL_INVALID_RESPONSE` | 非法 JSON、输出截断、异常章节或额外字段 |

错误只显示受控文案，不输出密钥、Authorization 头或供应商原始错误正文。

## 检查命令与结果

默认隔离检查不使用实际账户：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-model.py
```

需要主动检查实际账户时，保持三个服务运行，执行下列命令；它会实际调用一次模型并消耗 API 额度：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-model.py --live
```

本次实际结果：

- Python 应用导入、请求/报告类型和提示词构造通过；没有新增 Python 或网页依赖。
- 14 组隔离真实 HTTP 检查通过：正常中文任务、研究状态、用量、日期、偏好、无证据边界，以及认证、余额、限流、供应商故障、无效 JSON、截断、伪造来源字段、响应头/正文超时、恢复、缺密钥和配置错误。
- Java 重新编译打包、TypeScript 类型检查与 Vite 生产构建通过。
- 原有 Java/Python 链路 33 次正常/校验请求与 12 次隔离故障请求全部通过。
- Java 模型接口另 6 组检查通过：有效结果、认证错误、未知错误码、异常来源、响应超时和真实 422 日期校验。
- Chrome 浏览器完成一次真实 DeepSeek 调用，网页完整显示模型返回的全部章节、日期、模型与任务状态。
- 另外 6 组浏览器检查覆盖四种宽度、模式切换与实际演示接口、6 种错误提示、日期定位、等待与取消、无页面错误或直连 Python；这些隔离响应不重复消耗实际模型额度。
- 桌面与手机截图已保存并查看；三个默认本机服务保留运行。

## 下一项

M1-2：接入少量真实资料与工具，保留文件标识、披露日期与 PDF 页码等来源；之后 M1-3 再让模型动态选择工具、根据结果补查或结束。
