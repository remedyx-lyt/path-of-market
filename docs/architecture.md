# 架构说明

## 项目定位

Path of Market（市场之路）是一个个人金融研究操作台。它不替用户做投资决策，而是帮助用户建立认知、整理资料、追踪变化、沉淀研究，并发现和个人研究风格相关的线索。

## 总体架构

```text
用户
  -> apps/web 前端操作台
    -> apps/server Java 主后端
      -> apps/agent Python Agent 服务
        -> LLM / RAG / 工具 / 数据源
```

## 三个应用

| 应用 | 技术 | 职责 |
| --- | --- | --- |
| `apps/web` | React + Vite + TypeScript | 页面、表单、按钮、报告展示、用户交互 |
| `apps/server` | Java + Spring Boot | 主 API、数据库、用户画像、研究日志、观察池、任务状态 |
| `apps/agent` | Python + FastAPI | LLM 调用、RAG、文档解析、工具调用、Agent 工作流 |

## 关键原则

- 前端通常只调用 Java 主后端，不直接调用 Python Agent 服务。
- Java 主后端是系统中枢，负责稳定业务和数据持久化。
- Python Agent 服务是智能能力层，负责模型、检索、工具和工作流。
- 数据源必须通过 Data Provider 封装，避免业务逻辑绑定某个网站或 API。
- 每个任务聊天框只做一个小功能，避免一次性大改。

## 第一阶段最小闭环

目标是先打通链路，不做复杂 AI：

```text
前端输入研究对象
  -> Java 接收请求
    -> Java 调 Python mock research 接口
      -> Python 返回假研究报告
    -> Java 转发结果
  -> 前端展示报告
```

验收标准：

- 前端能打开页面。
- Java 主后端能启动并提供 `/api/health`。
- Python Agent 服务能启动并提供 `/health` 和 `/research/mock`。
- 前端点击按钮后，能看到从 Python 返回、经 Java 转发的 mock 研究报告。

