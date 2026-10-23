# M1-2：自动查找与读取真实年报

更新：2026-10-23。工具层已实现并验收；模型自主决定调用顺序、将证据写入网页报告属于下一项 M1-3。

## 这一步做成什么

输入公司简称/代码、报告会计年度与研究截止日期，程序自己去巨潮公开披露网站查找完整年报，下载、缓存并提取每页文字；支持从头到尾分批返回全部原文，以及关键词与单页回查。用户无需先提供 PDF 或链接。所有选定研究资料默认通读，统一规则见 `agent-design-decisions.md`；其他来源逐项接入。

开发验收例是同花顺 2024、2025 年年报，但没有在代码里写死公司、公告 ID 或 PDF 链接。工具支持沪深证券目录查询，本次真实联网还核查了沪市公司的查找路径；不等于已验证全市场所有文档。

## 六个可组合工具

| 名称 | 输入 | 输出与边界 |
| --- | --- | --- |
| `resolve_company` | `company` | 名称、代码、交易所、来源组织 ID；简称有歧义返回候选 |
| `find_documents` | `company, years, asOfDate` | 在线找到完整年报、PDF 地址、所属年度、披露日期和候选版本；排除摘要/英文版；逐年标记缺口 |
| `fetch_document` | `documentId` | 下载已发现的官方 PDF，SHA-256 校验、按页文本索引、页数和空文本页；重复请求复用缓存 |
| `search_document` | `documentId, query, startPage?, limit?` | 关键词命中页面、原文片段、来源，`nextStartPage` 可继续；不是向量 RAG |
| `read_document` | `documentId, page, offset?, limit?` | 原文、物理页码、PDF 页标签、披露日期和页链接；`nextOffset` 可继续 |
| `read_document_batch` | `documentId, startPage?, offset?, maxPages?, maxCharacters?` | 从第一页顺序分批阅读全本，下一游标精确接续；不靠关键词筛掉页面 |

`find_documents` 内部同样可识别公司，不强迫调用者先单独调用 `resolve_company`。输入年度与披露年度不同，例如 2025 年报可能在 2026 年披露；由程序按 `asOfDate` 排除当时尚不可见的文件。一次最多四个会计年度，保留完整修订版候选，每年优先标记截止日前最新披露版本。

工具定义与执行器借鉴 Pi 的结构，见 [核心设计依据](agent-design-decisions.md)。API 不接收任意 URL 或磁盘路径；资料工具不携带模型密钥。

## 学习时从哪里看

路径均相对项目根目录：

| 代码 | 负责什么 | 建议先看 |
| --- | --- | --- |
| `apps/agent/app/tools/registry.py` | 六个工具的名称、说明、参数模型与分派；统一成功/失败记录 | `TOOLS` → `ResearchTools.execute` |
| `apps/agent/app/tools/contracts.py` | 公司、年度、日期、页码、批量游标等输入规则 | `FindArguments` / `BatchReadArguments` |
| `apps/agent/app/tools/cninfo.py` | 访问公开来源，识别公司、查找和筛选年报 | `resolve_company` / `find_documents` |
| `apps/agent/app/tools/documents.py` | 下载缓存、校验、连续通读、关键词与单页阅读 | `fetch` → `read_batch` / `search` / `read` |
| `apps/agent/app/tools/pdf_worker.py` | 在独立进程用 pypdf 提取每页文字 | `extract` |
| `apps/agent/app/api/routes/tools.py` | 开发 HTTP 入口，复用注册表 | `execute_tool` |
| `scripts/try-report-tools.py` | 可运行的联网工具演示，不假装动态 Agent | `main` |
| `scripts/check-tools.py` | 正常与失败案例、全本分批无遗漏、HTTP 检查 | 每个 `test_*` |

```text
现在：CLI / 开发 HTTP → ResearchTools.execute → 参数校验 → Provider / DocumentStore → 带来源的工具结果
下一步：模型提出工具请求 → 同一个执行器 → 结果回给模型 → 继续阅读/复查/完成
```

Pi 的 `read` 在这里体现为文档读取；笔记/报告写入、修改与计算/代码执行的阶段对应见 `agent-design-decisions.md`。本轮六个工具侧重自动获取和完整阅读资料，没有把所有规划工具一次实现。

## 运行与查看

在项目根目录运行（只访问公开资料，不调用模型账户）：

```powershell
.\apps\agent\.venv\Scripts\python.exe .\scripts\try-report-tools.py --company 同花顺 --years 2024 2025 --as-of 2026-10-23 --query 研发投入金额
```

完整工具返回写入 `storage/runs/m1-2-tools.json`。默认公司/年度仅是命令行的可改示例，不是工具实现限制；`--company`、`--years`、`--as-of` 可换输入。

Python 服务重启加载新路由后，可在 http://127.0.0.1:8000/docs 查看“研究工具（开发验收）”：

- `GET /tools`：六个工具的名称、用途、JSON Schema；明确 `modelLoopConnected=false`。
- `POST /tools/execute`：通过同一个注册表校验并执行。HTTP 请求结构错误返回 422；合法工具请求的执行失败返回 `status=failed` 及稳定错误码，便于下一步回传给模型。

请求示例：

```json
{"name":"find_documents","arguments":{"company":"同花顺","years":[2024,2025],"asOfDate":"2026-10-23"}}
```

开发接口用于验收，不增加网页直连 Python 的产品路径。网页仍通过 Java 请求模型分析；当前网页报告仍明确“未检索资料”。下一步由 Python 模型循环使用这些工具，Java 和网页同步接收真实来源与动作。

## 缓存与限制

- `storage/documents/` 保存来源元数据、原 PDF、按页文本；`storage/runs/` 保存验收结果，均已忽略 Git。
- 来源地址来自巨潮实际查询，下载前须先登记文件；不把网站查询结果当成已读取正文。
- 网络请求限制主机、重定向、大小与等待；查询最多六页，每页三十条，达到限制明确 `queryComplete=false`。
- PDF 最大 40 MB / 1000 页，解析在可终止子进程执行，60 秒上限；超限和损坏返回失败，不能伪造证据。
- `read_document` 默认返回最多 6000 字符、最大 12000 字符，超过时有下一偏移；限制是单页单次工具结果，不是最终报告篇幅。
- 物理页从 1 开始，返回 `pageLabel` 辅助核对；印刷页码可能不同。PDF 文本提取不保证复杂表格行列结构，扫描页需 OCR，M2 扩展。
- 本批使用巨潮公开网站端点，不是取得了有稳定服务保证的商业数据 API。网站变化/不可用时返回来源错误，Provider 可替换；目前没有实现第二来源自动兜底。
- 公司目录为当前简称/代码，不宣称历史证券名称和市场身份的完整时点数据库。北交所、港美股和券商付费研报不在本批范围。

## 验收记录

2026-10-23 通过真实联网输入“同花顺”与年度自动发现、下载、解析两份文件：

| 报告 | 披露日期 | 页数 | 实际研发投入金额关键词位置 |
| --- | --- | --- | --- |
| [2024 年报](https://static.cninfo.com.cn/finalpage/2025-02-25/1222627630.PDF) | 2025-02-25 | 138 | PDF 第 19 页 |
| [2025 年报](https://static.cninfo.com.cn/finalpage/2026-03-10/1225002186.PDF) | 2026-03-10 | 137 | PDF 第 21 页 |

此处链接是运行时实际查到的验收记录，不是数据发现逻辑。已检查相关页面文字提取，并渲染两页核对；重复读取复用缓存。

自动检查：`scripts/check-tools.py` 覆盖公司/交易所识别、歧义、年度/摘要/修订/截止日过滤、严格参数、真实 PDF 文本提取、来源与页码、缓存复用、分页、空文本、坏文件与完整性、来源失败、查询上限、注册表、真实 HTTP 请求、全本连续阅读无漏字/漏页、解析超时与索引损坏重建。原 `scripts/check-model.py` 的 14 组隔离检查也通过，未调用真实模型账户。

## 紧接着做 M1-3

将这些工具声明交给模型 → 校验并执行模型提出的工具请求 → 带调用 ID 回传原文/错误 → 模型补查或完成 → 返回真实证据和停止原因。实现运行内消息事件、上下文与步数/累计时间/费用边界，并按既定会话方案预留父节点关系。届时才验收从网页一句研究问题开始的自主研究闭环，不能把本步固定验收脚本称作动态 Agent。
