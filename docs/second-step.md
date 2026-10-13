# 第二步：Java 主后端启动

任务编号：M0-2。当前状态：**已完成，2026-10-13 编译打包与实际 HTTP 检查通过**。

这一步建立接收请求的 Java 主后端。后续的 Python 调用与基础网页已另行完成，详见 `third-step.md`、`fourth-step.md`，当前下一项为 M0-5 网页展示报告。

## 已实现内容

1. 将原 `Application.java` 占位入口改为可运行的 Spring Boot 应用。
2. 增加 Maven 工程配置，编译并打包为可运行 JAR。
3. 提供 `GET /api/health`，返回 Java 自身运行状态。
4. 提供 Maven Wrapper、Windows 启动脚本和实际 HTTP 检查脚本。
5. 更新进度文档，与本任务代码一起保存本地 Git 提交。

本轮范围不包含 Java 调用 Python、数据库、网页或真实模型接入，原有三应用架构与开发顺序继续沿用。

## 健康检查

打开 `http://127.0.0.1:8080/api/health`，返回 HTTP 200 和以下 JSON：

```json
{
  "status": "ok",
  "service": "server"
}
```

它只证明 Java 主后端可接收请求，不代表 Python、模型或数据源已经接通。Java 没有 `/docs` 交互页面；完整产品页面由后续 React 前端提供。

不存在的路由返回 404，使用 POST 请求健康接口返回 405。

## 环境和依赖

- Spring Boot 固定为 `4.1.1`，只引入 MVC Web 服务所需的 starter。
- Maven Wrapper 固定为 `3.3.4`，自动下载 Maven `3.10.0`，无需全局安装 Maven。
- Maven 下载地址和 SHA-256 校验值保存在 `.mvn/wrapper/maven-wrapper.properties`。
- 源码目标版本为 Java 21，本次使用本机 JDK `25.0.2` 编译和运行。
- 本机需要 JDK 21 或更高版本；已有 `JAVA_HOME` 时使用它，否则启动脚本从 PATH 中的 `javac` 定位 JDK。
- 默认仅监听 `127.0.0.1:8080`。依赖和构建结果不纳入 Git。

版本兼容依据：[Spring Boot 官方系统要求](https://docs.spring.io/spring-boot/system-requirements.html)。Maven 版本来源：[Apache Maven 官方下载页](https://maven.apache.org/download.cgi)；Wrapper 用法见 [官方说明](https://maven.apache.org/tools/wrapper/)。

## 启动和检查

在项目根目录执行：

```powershell
.\scripts\start-server.ps1
```

脚本每次先构建，再运行 `apps/server/target/path-of-market-server.jar`。首次需要联网下载 Maven 和项目依赖；后续使用本机缓存。按 Ctrl+C 停止服务，再重新构建或启动同一工程。

若当前 PowerShell 策略阻止本地脚本，可在单独进程中运行，不修改系统持久策略：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-server.ps1
```

保持服务运行，另开终端执行：

```powershell
.\scripts\check-server.ps1
```

指定端口时，启动与检查分别使用：

```powershell
.\scripts\start-server.ps1 -Port 8081
.\scripts\check-server.ps1 -BaseUrl http://127.0.0.1:8081
```

以上两条在两个终端中分别运行。Python 使用 8000，Java 使用 8080，两者端口不同。

单独构建可以在 `apps/server` 目录执行：

```powershell
.\mvnw.cmd --batch-mode --no-transfer-progress package
```

## 文件分工

| 文件 | 用途 |
| --- | --- |
| `apps/server/pom.xml` | 固定 Spring Boot 版本、Java 目标版本和构建规则 |
| `apps/server/mvnw`、`mvnw.cmd`、`.mvn/wrapper/maven-wrapper.properties` | 使用固定 Maven 版本构建项目 |
| `apps/server/src/main/java/com/pathofmarket/server/Application.java` | 启动 Spring Boot |
| `apps/server/src/main/java/com/pathofmarket/server/controller/HealthController.java` | 接收健康检查请求 |
| `apps/server/src/main/java/com/pathofmarket/server/dto/HealthResponse.java` | 健康检查返回格式 |
| `apps/server/src/main/resources/application.properties` | 应用名、监听地址和默认端口 |
| `scripts/start-server.ps1` | 定位 JDK、构建并启动 Java 服务 |
| `scripts/check-server.ps1` | 从实际 HTTP 检查健康接口和路由边界 |

## 验证结果

- Maven Wrapper 下载、Java 编译、JAR 打包和 Spring Boot 启动通过。
- 两个脚本通过 Windows PowerShell 5.1 语法检查，使用 UTF-8 BOM 与 CRLF。
- 从项目目录之外调用启动和检查脚本通过，中文与空格路径可用。
- 3 次实际 HTTP 检查通过：健康接口返回 200、JSON 类型和约定服务标识；错误路径返回 404；错误方法返回 405。
- 临时工程副本中，初始 Maven Wrapper 缓存为空，测试进程没有 `JAVA_HOME`；启动脚本成功定位 PATH 中已安装的 JDK，下载 Maven、构建并在指定 8081 端口运行，同样的 3 次 HTTP 检查通过。
- 临时验收进程已停止，原项目 Java 保留在默认端口运行。

本任务采用实际 HTTP 验收，没有为固定健康响应额外引入单元测试依赖。

## 后续调用：M0-3 已完成

Java 已可调用 Python 返回演示报告，基础网页也已在 M0-4 完成。连接、超时和校验见 `third-step.md`，网页见 `fourth-step.md`。下一项为 M0-5 网页接入报告。
