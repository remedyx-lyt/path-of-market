# 当前进度

更新时间：2026-10-13（Australia/Sydney）。

## 当前状态

本轮任务：用户明确要求继续第二步，完成 M0-2 Java 主后端启动。Spring Boot 编译打包、健康接口、Maven Wrapper、启动脚本和实际 HTTP 检查已通过。前一项 M0-1 Python 演示服务已完成。

**已完成：M0-1、M0-2。下一项功能任务：M0-3 Java 调用 Python。**

目前两个服务独立运行；Java 与 Python 的研究请求连接、网页和真实模型接入仍待实现。

## 已完成的规划与准备

- 项目目录：`D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路`。
- 产品定位：本地网页财经研究工作台，内部包含研究 Agent；用于资料积累、变化比较和不同视角的研究。
- 应用分工：React + Vite + TypeScript 前端、Java Spring Boot 主后端、Python FastAPI 研究服务。
- 主模块：用户画像、板块地图、深研室、追猎者、锐眼、研究日志、数据层。
- 模块命名：`Deadeye / 锐眼`、`Pathfinder / 追猎者`。
- 四个研究预兆及完整研究规格已写入 `report-omens.md`：崇高、远古、机遇、深渊回响。
- 前端设计方向：黑白极简、高对比、大留白、强字体；参考图已保存在 `docs/assets/easy-farm-style-reference.png`。
- 研究 Agent 的动态工具循环和验收要求已写入 `architecture.md`、`agent-concepts.md`、`task-board.md`。
- 实施顺序已确认为 M0 完整应用骨架、M1 真实 Agent、M2 研究积累与资料完善、M3 特色功能。
- M0 内部依次完成 Python 演示服务、Java 启动与调用、网页启动与展示；先用 mock 报告跑通整条链路。
- 创建 `first-step.md`，说明第一步范围、数据格式和验收标准。
- 创建 `second-step.md`，记录 Java 主后端的启动、健康接口和第二步验收结果。
- 创建 `git-workflow.md`，说明本地版本保存和未来 GitHub 接入。
- 下一步实施的依据已明确：`architecture.md` 管职责边界，`task-board.md` 管顺序，`current-state.md` 管实际状态，`first-step.md` 和 `second-step.md` 记录已完成任务的接口与验收。

## 实际代码与环境

| 项目 | 检查结果 |
| --- | --- |
| Python 入口 | FastAPI 应用已实现，注册 `/health`、`/research/mock` 和根路径到 `/docs` 的跳转 |
| 请求与报告 | Pydantic 格式已实现，接收对象、问题、偏好与预兆；严格校验类型、空白和长度 |
| Python 环境 | Python 3.14.3，FastAPI 0.143.0、Pydantic 2.14.1、Uvicorn 0.54.0；直接与间接依赖固定在 `requirements.txt` |
| Python 验证 | 语法、依赖、应用/OpenAPI 和 20 次实际 HTTP 请求检查通过 |
| 启动与检查 | `scripts/start-agent.ps1` 和 `scripts/check-agent.py` 已实现；无需手动激活虚拟环境 |
| Java 入口 | `Application.java` 已实现 Spring Boot 启动，`pom.xml` 固定 Spring Boot 4.1.1，生成可运行 JAR |
| Java 环境 | 本机 JDK 25.0.2；源码目标 Java 21，可使用 JDK 21 或更高版本构建；Maven Wrapper 3.3.4 固定 Maven 3.10.0 并验证下载校验和 |
| Java 接口 | `GET /api/health` 返回 HTTP 200 与 `{"status":"ok","service":"server"}`；只检查 Java 自身 |
| Java 启动与检查 | `scripts/start-server.ps1` 自动构建和启动，`scripts/check-server.ps1` 检查真实 HTTP 接口 |
| Java 与 Python | 尚未实现研究请求转发；下一项 M0-3 接入 |
| 网页 | 只有目录占位，尚无可运行的 React 工程 |
| 模型与工具 | 尚未接入真实模型、文档检索、行情查询或研究循环 |
| 服务运行 | 本次验收时 Python 在 `127.0.0.1:8000`、Java 在 `127.0.0.1:8080` 运行；之后分别用启动脚本重新运行 |

演示报告带 `mode: mock` 和 `isMock: true`，来源与工具调用为空。M0-1、M0-2 完成说明两个服务可独立运行；M0 的研究请求链路、网页及 M1 的真实 Agent 仍未完成。

## M0-1 验收记录

- 用 Windows PowerShell 从项目目录之外运行启动脚本，中文与空格路径可用。
- 空环境副本中自动创建虚拟环境、安装清单依赖并成功提供健康检查和演示报告。
- 健康检查、完整中文输入、字段别名、首尾空白和可选默认值通过。
- 15 类无效请求返回 HTTP 422：空/空白字段、缺少问题、错误类型、未知预兆、过长输入、过多预兆、未知字段。
- `/docs` 与 `/openapi.json` 返回 HTTP 200，服务根地址跳转到 `/docs`。
- 完整请求返回结构化演示报告，不编造资料、行情、工具记录或预兆研究完成情况。

## M0-2 验收记录

- Maven Wrapper 成功下载固定版本 Maven，Spring Boot 工程编译、打包为可运行 JAR 并启动。
- 两个 PowerShell 脚本通过 Windows PowerShell 5.1 语法检查。
- 从项目目录之外运行启动脚本，包含中文和空格的项目路径可用，默认只监听 `127.0.0.1:8080`。
- 3 次实际 HTTP 请求通过：健康接口返回 200 和约定 JSON、不存在的路由返回 404、健康接口的 POST 请求返回 405。
- 在独立工程副本中，从空 Maven Wrapper 缓存开始，并移除该测试进程的 `JAVA_HOME`；脚本从 PATH 找到已安装 JDK、下载 Maven、重新构建并在指定的 `8081` 端口启动，3 次 HTTP 检查通过。
- 临时副本的验收进程已停止；原项目 Java 服务保留运行。
- 本轮没有添加数据库、Python 调用、前端或模型依赖。

## Git 状态

- 已在项目目录初始化本地仓库，分支为 `main`。
- 原有规划与目录骨架已保存为基线提交 `09eb2b1`。
- 架构与验收补充保存在 `6dca578`，恢复原闭环和统一任务依据保存在 `8da7ae5`。
- M0-1 的代码、运行说明和进度更新保存为同一个功能提交，标识以 `git log` 为准。
- M0-2 的 Java 工程、Wrapper、脚本、运行说明和进度更新保存为一个独立功能提交，标识以 `git log` 为准。
- `.gitignore` 排除虚拟环境、密钥文件、构建缓存、上传资料、向量索引、研究运行结果和本地数据库。
- `.env.example`、源代码、项目文档和前端设计参考图纳入版本管理。
- 当前没有配置 remote，保存的是本地 Git 历史，未进行推送。

## 下一步

1. M0-3：Java 调用 Python `/research/mock`，传递输入并返回演示报告，同时处理服务错误。
2. M0-4 / M0-5：启动网页并展示演示报告，完成完整应用骨架。
3. M0-6：补完整应用启动说明，再进入 M1 的真实模型和资料工具。
4. 逐步加入研究记录、用户画像、板块地图、追猎者和锐眼。

## 当前约定

- 项目说明、页面文案和必要注释尽量使用中文；代码标识优先使用英文。
- 已有 React、Java、Python 分工继续作为架构边界。
- 每次只完成一个明确任务；完成情况按实际检查结果记录。
- 用户要求只规划或等待时，只进行当前已授权的工作。
- 每个功能任务完成后及时更新本文件和 `task-board.md`，并保存相应 Git 提交。
- 涉及前端时先读 `design-style.md`。
- M0 演示报告和 M1 真实 Agent 分开验收，不虚构工具执行、来源或预兆覆盖情况。
