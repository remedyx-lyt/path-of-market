# Git 与后续 GitHub 接入

## 当前状态

- 本地仓库位置：`D:\Learning\AI Lab\Vibe Coding\Path of Market市场之路`。
- 当前主分支：`main`。
- 原有规划和目录骨架已保存为基线提交 `09eb2b1`。
- 本次文档更新作为后续独立提交保存，具体提交标识用 `git log` 查看。
- GitHub 仓库尚未创建；没有配置远程地址，没有推送。

本地 Git 与 GitHub 是两件事。现在保存的提交会保留历史，以后可以一起推送到用户创建的仓库。

## 保存什么

提交源代码、项目 Markdown、依赖清单和锁文件、启动与检查脚本、不含密钥的配置示例，以及必要的设计参考资产。

`.gitignore` 排除：

- `.env` 等真实配置与密钥文件。
- Python 虚拟环境、前端依赖和构建产物。
- Java 构建与工具缓存。
- 上传报告、向量索引、私人研究运行结果和本地数据库。

`storage/uploads/.gitkeep` 和 `storage/vectorstore/.gitkeep` 保留目录结构。`.env.example` 可以提交，但必须只包含空值或明确占位值。

文本换行由 `.gitattributes` 统一；后续启动脚本的换行按 Windows 文件类型处理。

## 每个任务的提交流程

1. 开始前执行 `git status --short`，确认已有改动属于哪个任务。
2. 阅读 `current-state.md`、`task-board.md` 和相关规格。
3. 只完成当前任务，执行相应验证。
4. 更新两个进度文档：写明真实完成内容、验证结果和下一项任务。
5. 用 `git diff` 检查源码和文档，明确选择本任务文件加入暂存区。
6. 用 `git diff --cached` 再核对内容，创建一个范围清楚的提交。
7. 完成后查看状态和最近提交，向用户报告结果。

提交信息示例：

```text
feat(agent): 建立健康检查与演示研究接口
feat(agent): 实现基于真实资料的研究工具循环
feat(server): 接入 Python 研究服务
docs: 更新研究 Agent 验收与下一步
```

未完成但有必要保存的工作应明确写为 `wip:`，文档保持未完成状态。不要为了提交把失败的检查写成通过。

当前使用 `main` 保存准备工作。后续较大任务可以使用对应功能分支，是否创建分支根据任务范围决定。

## 常用查看命令

在项目根目录执行：

```powershell
git status --short
git log --oneline --decorate -10
git diff
git diff --cached
git remote -v
```

## 后续接 GitHub

用户创建仓库并给出实际 URL 后，再配置远程地址和推送。下面是步骤模板，不是已经执行的操作；URL 必须替换成用户实际创建的仓库。

```powershell
git remote add origin <实际仓库URL>
git push -u origin main
```

建议新远程仓库先保持为空，不另外生成 README、许可证或 `.gitignore`，这样可以直接承接已有历史。如果远程已有提交，先读取双方历史后再处理，不直接覆盖远程。
