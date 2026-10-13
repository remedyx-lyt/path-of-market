# 第三步：Java 调用 Python

任务编号：M0-3。当前状态：**已完成，2026-10-13 编译打包、真实链路与隔离故障检查通过**。

## 这一步做出了什么

```text
研究对象、问题、偏好、预兆
  → Java POST /api/research/mock
    → Python POST /research/mock
      → Python 校验输入、生成演示报告
    → Java 返回报告或明确错误
```

Python 的研究逻辑、字段规则和报告格式沿用 M0-1。Java 负责请求入口、服务地址、等待上限和错误处理。网页在 M0-4 / M0-5 接入，真实模型和资料工具在 M1 接入。

## 接口与数据约定

Java 地址：`POST http://127.0.0.1:8080/api/research/mock`。

请求示例：

```json
{
  "target": "示例公司",
  "question": "如何研究它的研发投入变化？",
  "userStyle": "关注长期增长和风险验证",
  "omens": ["opportunity", "abyssal_echoes"]
}
```

Java 用 JSON 树保留原始字段类型，不将数字或布尔转换成字符串，也不丢掉未知字段。研究字段统一由 Python 的 `ResearchRequest` 校验，包括必填、空白、长度、可选默认值和四种预兆。具体规则见 `first-step.md`。

成功时返回 HTTP 200 和 Python 的完整 JSON 报告，包括 `mode: mock`、`isMock: true`、对象、问题、偏好、预兆、标题、摘要、章节，以及为空的 `sources` / `toolCalls`。Java 检查报告的基础结构和演示标记，不自行生成另一份报告。

Python 校验失败时，Java 保留 HTTP 422 和原有 `detail` 数组。输入校验依赖 Python 可用；Python 不可连接时返回服务不可用错误。

## 错误约定

| HTTP 状态 | 内容/错误码 | 含义 |
| --- | --- | --- |
| 400 | `INVALID_JSON` | JSON 无法解析或请求体缺失 |
| 422 | Python 的 `detail` 数组 | 研究字段不符合既有规则 |
| 503 | `AGENT_UNAVAILABLE` | Python 无法连接、连接断开或等待被中断 |
| 504 | `AGENT_TIMEOUT` | 连接或完整响应等待超时 |
| 502 | `AGENT_ERROR` | Python 返回意外状态，包括 5xx 和重定向 |
| 502 | `AGENT_INVALID_RESPONSE` | 返回非 JSON、错误报告结构或错误校验格式 |

Java 管理的错误统一返回以下结构：

```json
{
  "error": {
    "code": "AGENT_UNAVAILABLE",
    "message": "无法连接研究服务，请确认 Python 服务已启动。"
  }
}
```

不会向调用者转发上游内部错误正文。接口只接受 JSON 的 POST 请求；不支持的方法/媒体类型按 Spring MVC 返回 405/415。

## 调用配置

| 配置 | 默认值 | 环境变量 |
| --- | --- | --- |
| `agent.base-url` | `http://127.0.0.1:8000` | `AGENT_BASE_URL` |
| `agent.connect-timeout` | `3s` | `AGENT_CONNECT_TIMEOUT` |
| `agent.request-timeout` | `10s` | `AGENT_REQUEST_TIMEOUT` |

配置在启动时检查：服务地址必须为 HTTP(S)，不含用户信息、查询参数或片段；等待上限至少为 1ms。地址可以有路径前缀，末尾斜线会处理后再追加 `/research/mock`。

等待上限覆盖完整响应，包括响应正文；到达上限会取消等待中的请求。使用 JDK 自带 HTTP 客户端，没有增加新的项目依赖。实现依据：[JDK HTTP 请求超时](https://docs.oracle.com/en/java/javase/21/docs/api/java.net.http/java/net/http/HttpRequest.Builder.html)、[Spring Boot JSON 配置](https://docs.spring.io/spring-boot/reference/features/json.html)。

启动脚本可覆盖地址和完整响应等待上限；只有显式传入参数时才覆盖对应环境配置：

```powershell
.\scripts\start-server.ps1 -AgentBaseUrl http://127.0.0.1:8001 -AgentTimeoutMs 5000
```

这条示例要求 Python 使用对应的 8001 端口。Java 自身端口仍由 `-Port` 控制。

## 启动与提交示例

在项目根目录的两个终端分别运行：

```powershell
.\scripts\start-agent.ps1
```

```powershell
.\scripts\start-server.ps1
```

另开终端，向 Java 提交：

```powershell
$researchPayload = @{
    target = '示例公司'
    question = '如何研究它的研发投入变化？'
    userStyle = '关注长期增长和风险验证'
    omens = @('opportunity', 'abyssal_echoes')
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/research/mock' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($researchPayload)) | ConvertTo-Json -Depth 10
```

浏览器直接打开上述 URL 发出的是 GET，无法提交研究任务。当前可以通过 PowerShell 发送；下一步网页会提供输入框与按钮。

## 检查方法

保持两个服务运行，执行：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-research-bridge.py
```

同时检查故障处理：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\check-research-bridge.py --check-errors
```

指定端口时用 `--server-url` 和 `--agent-url`。故障检查需要已构建的 JAR 和 JDK，会另启动临时 Java 与本地故障模拟服务，使用自动分配的端口，结束后关闭它们；不会停止主服务。检查日志位于 Git 忽略的 `apps/server/target/bridge-checks/`。

## 验证结果

- Java 工程编译、打包、重启通过，默认仍使用 8080；Python 保持 8000。
- 检查脚本向真实服务发出的 33 次 HTTP 请求全部通过。
- 4 组成功请求返回与直接调用 Python 相同的报告：完整中文输入、首尾空白与默认值、全部四个预兆、120 个 Unicode 非 BMP 字符的对象名称。
- 18 类无效研究输入返回 422：空/空白字段、缺字段、错误类型、未知预兆、过长字段、过多预兆、未知字段、null 字段、数组根对象、null 根对象；完整校验内容正确转发。
- 非法/空 JSON 返回 400，错误媒体类型返回 415，错误 HTTP 方法返回 405。
- 12 次隔离故障验收请求通过：上游错误、重定向、非 JSON、错误报告、错误校验、响应头超时、正文超时、断线、422 转发、恢复、连接拒绝和 Java 独立健康检查。
- 临时故障检查实例已关闭，原项目的 Python 与 Java 服务保留运行。
- 在临时工程副本中验证 Windows PowerShell 5.1 启动脚本：项目外启动、显式参数覆盖环境配置、地址末尾斜线和中文研究请求通过；临时进程已关闭。

## 文件分工

- `controller/ResearchController.java`：Java 研究 API 入口。
- `client/AgentResearchClient.java`：向 Python 发送请求，处理完整响应、超时和结果格式。
- `config/AgentProperties.java`：Python 地址和等待上限配置。
- `client/AgentServiceException.java`、`controller/ApiExceptionHandler.java`、`dto/ApiErrorResponse.java`：明确的服务错误和返回格式。
- `Application.java`、`application.properties`：注册并配置调用参数。
- `scripts/start-server.ps1`：新增地址和等待上限选项。
- `scripts/check-research-bridge.py`：真实链路与故障 HTTP 验收，无额外 Python 依赖。

以上 Java 路径均相对于 `apps/server/src/main/java/com/pathofmarket/server/`，配置文件位于 `apps/server/src/main/resources/`。

## 下一项：M0-4

按现有黑白极简设计建立 React + Vite + TypeScript 基础页面，提供研究对象和问题输入。随后 M0-5 让网页调用 Java `/api/research/mock`，展示演示报告、mock 标记和明确错误状态。
