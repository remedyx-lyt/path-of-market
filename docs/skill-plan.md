# 项目开发 Skill 规划

## 是否可行

可行，但要注意：Skill 不是自动更新的项目数据库。它更像一个“项目开发规范和上手指南”，可以让新聊天框自动知道应该读哪些文档、遵守哪些架构约束、按什么工作流做任务。

真正的最新进度仍然应该放在项目文档里：

- `docs/current-state.md`
- `docs/task-board.md`
- `docs/architecture.md`

Skill 的作用是让 Codex 在你说“用 Path of Market 项目开发 skill 做这个任务”时，自动按固定流程进入项目。

## 建议 Skill 名称

```text
path-of-market-dev
```

## Skill 应该包含什么

`SKILL.md` 里只放精简规则：

- 识别这是 Path of Market（市场之路）项目。
- 默认项目路径。
- 必读文档列表。
- 三应用架构：`web`、`server`、`agent`。
- 单任务开发流程。
- 完成后更新当前进度和任务板。

详细项目资料不放进 Skill，而是继续放在项目 `docs` 里。这样可以避免 Skill 过大，也保证进度只维护一份。

## 使用方式

以后可以这样开新聊天框：

```text
请使用 path-of-market-dev skill。
本次任务：实现 Java 主后端调用 Python Agent 服务的 mock research 接口。
```

理想效果：

- Codex 自动知道先读项目文档。
- Codex 自动知道不要重新设计架构。
- Codex 自动知道只做一个小任务。
- Codex 自动知道做完要更新进度文件。

## 创建时机

建议先完成最小闭环中的 1-2 个任务后再正式创建 Skill。原因是：现在项目还在变，过早把规则写死，可能很快要改。

当前最好的做法：

1. 先用 `docs/handoff-prompt.md` 手动交接。
2. 跑通几个任务，验证工作流。
3. 再创建 `path-of-market-dev` skill。
4. 之后每次新任务直接触发 skill。

