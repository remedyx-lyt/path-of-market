"""报告写作、程序核查、复核与最终报告结构（AgentRunner 的一部分）。

validate_content 是确定性的程序核查（来源/页码/覆盖/图表 ID/主题），不是独立财务审计。
"""

import json
import re

from app.core.agent_prompts import REVIEW_SYSTEM, TABLE_RULES
from app.core.config import ModelServiceError
from app.schemas.agent import AgentContent, Citation, SectionTable
from app.services.model_json import escape_inner_quotes
from app.services.report_figures import check_table, dominant_share, plan_section_figures
from app.services.runtime import now
from app.services.reading_coverage import reading_complete, page_read
from app.tools.documents import write_json

BASIC_TOPICS = {"business", "performance", "profitability", "cashflow", "balance_sheet", "research", "risks"}


def unique_citations(citations, limit):
    """完全相同的引用去重后保留前 limit 条；非列表原样返回，交给 schema 报错。"""
    if not isinstance(citations, list):
        return citations
    seen, kept = set(), []
    for c in citations:
        key = json.dumps(c, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            kept.append(c)
    return kept[:limit]


OPERATING_WORDS = ("产能", "产量", "销量", "库存")


def operating_table_present(tables, located):
    """是否已有产能/产销表：标题或列名含产能/产量/销量/库存，且引用了程序定位到的经营数据页。只引用同一页的其他表不算。"""
    return any(
        any(w in table.title + "".join(table.columns) for w in OPERATING_WORDS)
        and located & {(c.source_id, c.page) for row in table.rows for c in [row, *row.also_from]}
        for table in tables
    )


def normalize_table(table, index, fixes):
    """表格的机械整理。真实验收中最常见：把行名列的表头（期间/项目）也写进 columns，列数比每行格子多 1。

    能确定意图的就整理；整理后行列仍对不上的表去掉（记录说明），不让一张表拖累整篇报告重写。
    """
    if not isinstance(table, dict):
        return table
    columns, rows = table.get("columns"), table.get("rows")
    if not (isinstance(columns, list) and isinstance(rows, list) and rows and all(isinstance(r, dict) and isinstance(r.get("cells"), list) for r in rows)):
        return table
    title = str(table.get("title", ""))[:20]
    if {len(r["cells"]) for r in rows} == {len(columns) - 1} and len(columns) > 1 and not table.get("labelHeader"):
        table["labelHeader"], table["columns"] = str(columns[0])[:30], columns[1:]
        if isinstance(table.get("chartColumns"), list):
            table["chartColumns"] = [c - 1 for c in table["chartColumns"] if isinstance(c, int) and c >= 1]
            if not table["chartColumns"]:
                table["chart"] = "none"
        fixes.append(f"第{index + 1}节表格「{title}」把行名表头“{table['labelHeader']}”移出数据列")
    for row in rows:
        # 真实运行中模型常把数字直接写成数值（2376）而不是字符串，按原样转成文字，不改数值。
        row["cells"] = [cell if isinstance(cell, str) else "" if cell is None else str(cell) for cell in row["cells"]]
        if not isinstance(row.get("label"), str) and row.get("label") is not None:
            row["label"] = str(row["label"])
        for key in ("chart", "chartColumns"):  # 真实运行中模型把画图设置写进了行里
            if key in row:
                value = row.pop(key)
                table.setdefault(key, value)
    if isinstance(table.get("chartColumns"), list) and len(table["chartColumns"]) > 4:
        fixes.append(f"第{index + 1}节表格「{title}」画图列截至4列（原{len(table['chartColumns'])}列）")
        table["chartColumns"] = table["chartColumns"][:4]
    requested = table.get("chartColumns", [])
    mapped = []
    for column in requested if isinstance(requested, list) else []:
        if isinstance(column, str) and column.strip().isdigit():
            column = int(column.strip())
        elif isinstance(column, str):
            hits = [i for i, name in enumerate(table["columns"]) if name == column.strip()]
            column = hits[0] if len(hits) == 1 else None
        if type(column) is int and 0 <= column < len(table["columns"]) and column not in mapped:
            mapped.append(column)
    if mapped != requested or table.get("chart", "none") != "none" and not mapped:
        fixes.append(f"第{index + 1}节表格「{title}」修正画图列；无法确定的图取消，保留数据表")
        table["chartColumns"] = mapped
        if not mapped:
            table["chart"] = "none"
    for row in rows:
        pages = row.pop("pages", None)  # 真实运行中模型把来源写成页码列表：第一页作 page，其余并入 alsoFrom
        if isinstance(pages, list) and pages and row.get("page") is None:
            row["page"] = pages[0]
            row["alsoFrom"] = (row.get("alsoFrom") or []) + [{"sourceId": row.get("sourceId"), "page": p} for p in pages[1:4]]
    coerced = [row for row in rows if isinstance(row.get("page"), str) and row["page"].strip().isdigit()]
    for row in coerced:
        row["page"] = int(row["page"].strip())
    if coerced:
        fixes.append(f"第{index + 1}节表格「{title}」页码由文字改为数字（{len(coerced)}行）")
    if any(len(r["cells"]) != len(table["columns"]) for r in rows):
        fixes.append(f"第{index + 1}节表格「{title}」行列数对不上，已去掉")
        return None
    return table


MAX_SECTIONS = 12

# 预兆名称不进报告正文（用户要求）。括号或冒号前的名称直接去掉；句中的换成对应视角的普通说法。
OMEN_NAMES = {"崇高预兆": "深入理解", "远古预兆": "历史对照", "机遇预兆": "未来变化", "深渊回响预兆": "风险与反方", "深渊回响": "风险与反方"}
OMEN_PATTERN = "|".join(sorted(map(re.escape, OMEN_NAMES), key=len, reverse=True))


def strip_omen_names(text):
    text = re.sub(rf"[（(]\s*(?:{OMEN_PATTERN})(?:视角)?\s*[)）]", "", text)
    text = re.sub(rf"(?:{OMEN_PATTERN})(?:视角)?\s*[：:·]\s*", "", text)
    return re.sub(OMEN_PATTERN, lambda m: OMEN_NAMES[m.group(0)], text)


def merge_extra_sections(data, fixes):
    """超过 12 节时把多出的章节并入第 12 节：标题保留为小标题、正文全保留，引用/图表/表格合并到 schema 上限。

    真实验收中两个预兆常让报告写到 13–14 节，每次都整篇重写；合并只改变分节，不删正文。
    """
    sections = data.get("sections")
    if not isinstance(sections, list) or len(sections) <= MAX_SECTIONS or not all(isinstance(s, dict) for s in sections):
        return
    keep, extra = sections[: MAX_SECTIONS - 1], sections[MAX_SECTIONS - 1 :]
    merged = {
        "heading": str(extra[0].get("heading", ""))[:120],
        "content": "\n\n".join(f"【{s.get('heading', '')}】\n{s.get('content', '')}" for s in extra)[:10000],
        "citations": [c for s in extra for c in s.get("citations") or []],
        "topics": list(dict.fromkeys(t for s in extra for t in s.get("topics") or [])),
        "omens": list(dict.fromkeys(o for s in extra for o in s.get("omens") or [])),
        "chartIds": list(dict.fromkeys(c for s in extra for c in s.get("chartIds") or []))[:8],
        "businessIds": list(dict.fromkeys(b for s in extra for b in s.get("businessIds") or []))[:6],
        "tables": [t for s in extra for t in s.get("tables") or []][:3],
        "visual": next((s.get("visual") for s in extra if s.get("visual")), None),
    }
    data["sections"] = keep + [merged]
    fixes.append(f"章节超过{MAX_SECTIONS}节（{len(sections)}节），最后{len(extra)}节合并为一节，正文与小标题保留")


def normalize_report(raw):
    """写作结果的机械格式整理：引用去重并截到 schema 上限、去掉定性图层级的多余字段、预兆自评列表截到上限。

    这些超限不影响正文内容，整篇重写代价高（每次上万输出 token）；章节数超限等会删掉正文的情况不在这里处理。
    返回 (整理后的 JSON 文本, 整理说明列表)；无法解析时原样返回，交给 schema 报错。
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw, []
    if not isinstance(data, dict):
        return raw, []
    fixes = []
    if "sections" not in data and isinstance(data.get("candidate"), dict) and "sections" in data["candidate"]:
        # 复核时模型曾把报告包在输入里的 candidate 字段中返回。
        data = data["candidate"]
        fixes.append("报告外层多包了一层 candidate，已去掉")
    merge_extra_sections(data, fixes)
    named = 0
    for holder, key in [(data, "title"), (data, "summary")] + [(s, k) for s in data.get("sections") or [] if isinstance(s, dict) for k in ("heading", "content")]:
        if isinstance(holder.get(key), str) and re.search(OMEN_PATTERN, holder[key]):
            holder[key], named = strip_omen_names(holder[key]), named + 1
    if named:
        fixes.append(f"{named} 处正文/标题出现预兆名称，已改为普通说法")
    for i, section in enumerate(data.get("sections") or []):
        if not isinstance(section, dict):
            continue
        before = section.get("citations")
        section["citations"] = unique_citations(before, 12) if before is not None else []
        if isinstance(before, list) and len(section["citations"]) < len(before):
            fixes.append(f"第{i + 1}节引用去重/截至12条（原{len(before)}条）")
        visual = section.get("visual")
        if isinstance(visual, dict):
            extra = sorted(set(visual) - {"kind", "title", "nodes"})
            for key in extra:
                visual.pop(key)
            if extra:
                fixes.append(f"第{i + 1}节定性图去掉多余字段 {extra}")
            nodes = visual.get("nodes")
            if isinstance(nodes, list):
                cited = [n for n in nodes if not (isinstance(n, dict) and n.get("citations") == [])]
                if len(cited) < len(nodes):
                    # 定性图每个节点须有来源；没有来源的节点去掉，剩不足 2 个则不放这张图。
                    fixes.append(f"第{i + 1}节定性图去掉 {len(nodes) - len(cited)} 个无来源节点")
                    visual["nodes"] = nodes = cited
                if len(nodes) < 2:
                    section["visual"] = None
                    fixes.append(f"第{i + 1}节定性图有效节点不足 2 个，未放入")
            for node in (section["visual"] or {}).get("nodes") or []:
                if isinstance(node, dict) and isinstance(node.get("citations"), list):
                    count = len(node["citations"])
                    node["citations"] = unique_citations(node["citations"], 3)
                    if len(node["citations"]) < count:
                        fixes.append(f"第{i + 1}节定性图节点引用去重/截至3条（原{count}条）")
        if isinstance(section.get("tables"), list):
            section["tables"] = [t for t in (normalize_table(t, i, fixes) for t in section["tables"]) if t is not None]
    for entry in data.get("omenCoverage") or []:
        if isinstance(entry, dict):
            for key in ("addressed", "missingItems"):
                if isinstance(entry.get(key), list) and len(entry[key]) > 12:
                    fixes.append(f"预兆自评 {key} 截至12条（原{len(entry[key])}条）")
                    entry[key] = entry[key][:12]
    return (json.dumps(data, ensure_ascii=False), fixes) if fixes else (raw, [])


def strip_quotes(business):
    """业务数据传给模型时去掉逐字引文等核查字段；原始证据保留在运行状态和最终报告中。"""
    return {
        **business,
        "datasets": [
            {
                **d,
                "rows": [
                    {**r, "items": [{k: v for k, v in p.items() if k not in {"quote", "publishedAt", "verification"}} for p in r["items"]]}
                    for r in d["rows"]
                ],
            }
            for d in business["datasets"]
        ],
    }


def compact_financial(data):
    """财务底稿的模型视图：数值、同比与图表菜单；逐项证据（页码/原值）留在程序里，不必每轮重发。"""
    return {
        "datasets": [
            {
                "id": d["id"],
                "label": d["label"],
                "rows": [{"periodLabel": r["periodLabel"], "values": r["values"], "yoy": r["yoy"]} for r in d["rows"]],
            }
            for d in data["datasets"]
        ],
        "charts": [{"id": c["id"], "title": c["title"], "topic": c["topic"]} for c in data["charts"]],
        "labels": data.get("labels", {}),
        "gaps": data["gaps"],
        "method": data["method"],
    }


class ReportMixin:
    def pending_materials(self):
        """必须补读的原文，独立于可以明确注明缺失的补充指标。"""
        pending = {}
        for sid, document in self.required_annual.items():
            if not reading_complete(self.coverage.get(sid)):
                pending[sid] = {'sourceId': sid, 'tool': 'read_document', 'title': document['title']}
        for sid, coverage in self.coverage.items():
            if not reading_complete(coverage):
                pending[sid] = {'sourceId': sid, 'tool': 'read_web_document' if self.sources[sid]['kind'] == 'web' else 'read_document',
                                'unreadImagePages': sorted(set(coverage.get('emptyTextPages', []))-set(coverage.get('visuallyProcessedPages', [])))}
        return list(pending.values())

    def pending_evidence(self):
        """写作前的确定性门槛；模型说ready不能替代实际阅读覆盖。"""
        pending, gaps = self.pending_materials(), []
        if pending:
            gaps.append('必须先full补读以下资料；成功文字批次不会重读，无文本页由程序视觉补读：'+json.dumps(pending, ensure_ascii=False))
        if self.job.request.include_financials and self.annual_context()['count'] >= 5 and not self.history_checked:
            gaps.append('先find_documents查主公司的完整五/十年年报范围。')
        if self.job.request.include_current_period and not self.current_period_checked:
            gaps.append('尚未查找当年最新已披露定期报告，请find_documents。')
        if self.required_current and not reading_complete(self.coverage.get(self.required_current['documentId'])):
            gaps.append('最新定期报告尚未读完：'+self.required_current['documentId'])
        if self.job.request.include_market and self.market_data is None:
            gaps.append('必须先get_market_data取得本次行情。')
        if not self.sources:
            gaps.append('尚无已取得的资料来源。')
        return gaps

    def check_citation(self, citation):
        source = self.sources.get(citation.source_id)
        if source and source["kind"] == "web":
            return (citation.page is None and bool(source.get("publishedAt"))
                    and source["publishedAt"] <= self.job.request.as_of_date.isoformat()
                    and source.get("citationEligible") is True
                    and self.coverage.get(citation.source_id, {}).get("textComplete") is True)
        return source is not None and (
            source["kind"] != "document"
            or citation.page is not None
            and page_read(self.coverage.get(citation.source_id), citation.page)
        )

    def require_evidence(self, ok, retry_message, gap):
        """证据是否到位。正常取证中不到位就退回让模型补；收尾写作时已不能再取证，改为记入局限，不宣称完成。"""
        if ok:
            return
        if not self.context_wrapup:
            raise ValueError(retry_message)
        if gap not in self.wrapup_gaps:
            self.wrapup_gaps.append(gap)

    def place_required_figures(self, content):
        """必做图由程序兜底：资产负债图（含负债）、非单一业务的收入结构图。模型漏放时补到对应主题章节，不为此整篇重写。"""
        placed = {i for s in content.sections for i in s.chart_ids + s.business_ids}

        def section_for(topic, field, limit):
            fitting = [s for s in content.sections if len(getattr(s, field)) < limit]
            return next((s for s in fitting if topic in s.topics), fitting[0] if fitting else None)

        added = []
        balance = [c["id"] for c in self.financial_data()["charts"] if {"totalLiabilities", "liabilityRatio"} & set(c["keys"])]
        if balance and not placed & set(balance) and (section := section_for("balance_sheet", "chart_ids", 8)):
            section.chart_ids.append(balance[0])
            added.append(balance[0])
        datasets = [d for d in self.business_data()["datasets"] if dominant_share(d) < 90]
        for dimension in dict.fromkeys(d["dimension"] for d in datasets):
            ids = [d["id"] for d in datasets if d["dimension"] == dimension]
            if not placed & set(ids) and (section := section_for("business", "business_ids", 6)):
                section.business_ids.append(ids[0])
                added.append(ids[0])
        if added:
            self.job.emit("required_figures_placed", "必做图表由程序补放到对应章节：" + "、".join(added), added=added)

    def validate_content(self, message):
        raw, fixes = normalize_report(message["content"])
        content = AgentContent.model_validate_json(raw)
        if fixes:
            self.job.emit("report_normalized", "程序整理了报告格式：" + "；".join(fixes)[:300], fixes=fixes)
        if self.job.request.include_financials:
            missing = BASIC_TOPICS - {t for s in content.sections for t in s.topics}
            if missing:
                raise ValueError("基本研究主题缺少：" + ",".join(sorted(missing)) + "；补充分析或明确资料缺口，并标记topics。")
        if not self.sources:
            raise ValueError("尚未取得证据")
        self.require_evidence(not self.job.request.include_financials or self.annual_context()["count"] <= 2 or self.history_checked,
                              "尚未完成主公司的五/十年完整年报范围查询，请先find_documents。",
                              "未完成主公司的五/十年完整年报范围查询。")
        unread = [c for c in self.coverage.values() if not reading_complete(c)]
        self.require_evidence(
            self.coverage and not unread,
            "选定报告尚未完整处理可提取文字，请继续 full 阅读或明确停止缺口",
            "以下资料未读完：" + "、".join(f"{self.sources[c['sourceId']]['title']}（已处理 {len(c['processedPages'])}/{c['pageCount']} {'段' if c.get('unit') == 'segment' else '页'}）" for c in unread),
        )
        self.require_evidence(
            not (self.job.request.include_market and self.market_data is None), "本任务要求行情分析，尚未取得行情", "本任务要求的行情分析未取得行情数据。"
        )
        self.require_evidence(
            not (self.job.request.include_current_period and not self.current_period_checked),
            "尚未查找截止年度最新已披露的定期报告",
            "未查找截止年度最新已披露的定期报告。",
        )
        current = self.required_current
        unread_annual = [d for sid, d in self.required_annual.items() if not reading_complete(self.coverage.get(sid))]
        self.require_evidence(not unread_annual,
                              "本次年报范围尚未完成，请full通读：" + "、".join(d["documentId"] for d in unread_annual),
                              "本次年报范围未读完：" + "、".join(d["title"] for d in unread_annual))
        self.require_evidence(
            not current or reading_complete(self.coverage.get(current["documentId"])),
            f"当年最新已披露报告尚未通读，请以 mode=full 阅读 {current['documentId']}：{current['title']}" if current else "",
            f"当年最新已披露报告未通读：{current['title']}" if current else "",
        )
        citations = [c for section in content.sections for c in section.citations]
        if not citations:
            raise ValueError("最终章节需要引用实际来源")
        if not all(self.check_citation(c) for c in citations):
            raise ValueError("引用必须指向本次实际处理的来源和页码")
        chart_ids = {c["id"] for c in self.financial_data()["charts"]}
        business_ids = {d["id"] for d in self.business_data()["datasets"]}
        if self.job.request.include_financials and chart_ids and not any(s.chart_ids for s in content.sections):
            raise ValueError("已取得财务绘图数据，请主动选择支持论点的chartIds，不能全部闲置。")
        used, repeated, unknown = set(), [], []
        for section in content.sections:
            # 底稿里没有的图表 ID 由程序去掉（真实运行中出现过自拟 ID），不为此整篇重写。
            unknown += [i for i in section.chart_ids if i not in chart_ids] + [i for i in section.business_ids if i not in business_ids]
            section.chart_ids = [i for i in section.chart_ids if i in chart_ids]
            section.business_ids = [i for i in section.business_ids if i in business_ids]
            # 同一图表只放一次：保留第一次出现的章节，后面章节的重复引用由程序去掉，不为这条机械规则整篇重写。
            repeated += [i for i in section.chart_ids + section.business_ids if i in used]
            section.chart_ids = [i for i in section.chart_ids if i not in used]
            section.business_ids = [i for i in section.business_ids if i not in used]
            used |= set(section.chart_ids + section.business_ids)
            if section.visual and not all(self.check_citation(c) for node in section.visual.nodes for c in node.citations):
                raise ValueError("定性图节点也须引用实际已读来源和页码。")
            if not all(
                self.check_citation(c) for t in section.tables for row in t.rows for c in [Citation(sourceId=row.source_id, page=row.page), *row.also_from]
            ):
                raise ValueError("tables 每行须引用本次实际处理的来源和页码（sourceId、page）。")
        self.place_required_figures(content)
        self.validate_omens(content)
        if unknown:
            self.job.emit("unknown_figures_removed", "去掉底稿中不存在的图表 ID：" + "、".join(unknown)[:200], removed=unknown)
        if repeated:
            self.job.emit(
                "figure_duplicates_removed", f"同一图表已放在前面章节，去掉后面 {len(repeated)} 处重复引用", removed=repeated
            )
        return content

    def review_payload(self, content):
        return {
            # 数据表已由程序逐格核对，复核只看正文与图表；带上十几张表会让复核整篇重写超出输出上限。
            "candidate": content.model_dump(by_alias=True, exclude={"sections": {"__all__": {"tables"}}}),
            "asOfDate": self.job.request.as_of_date.isoformat(),
            "discoveredDocuments": [
                {k: d.get(k) for k in ("documentId", "title", "fiscalYear", "reportType", "publishedAt", "preferred")}
                for d in self.discovered.values()
            ],
            "processedSources": list(self.sources.values()),
            "coverage": [
                {
                    "sourceId": c["sourceId"],
                    "unit": c.get("unit", "page"),
                    "pageCount": c["pageCount"],
                    "processedPageCount": len(c["processedPages"]),
                    "emptyTextPages": c["emptyTextPages"],
                    "textComplete": c["textComplete"],
                    "readingComplete": reading_complete(c),
                    "visuallyProcessedPages": c.get("visuallyProcessedPages", []),
                }
                for c in self.coverage.values()
            ],
            "financialData": compact_financial(self.financial_data()),
            "visualReadings": [
                {"sourceId": r["sourceId"], "pages": r["pages"], "observations": [o["summary"] for o in r["observations"]]}
                for r in self.visual_readings
            ],
            "businessData": strip_quotes(self.business_data()),
            "methodPlan": (self.method_usage or {}).get("plan"),
            "omens": self.omen_review_payload(),
            "market": {k: v for k, v in (self.market_data or {}).items() if k != "series"},
        }

    def apply_review_changes(self, content, body):
        """精确匹配的局部补丁；歧义、重复和截断不能覆盖原稿。"""
        if set(body) - {"changes", "summary"} or not isinstance(body.get("changes"), list) or len(body["changes"]) > 24:
            raise ValueError("复核仅允许changes数组与可选summary")
        candidate = content.model_dump(by_alias=True)
        for patch in body["changes"]:
            if not isinstance(patch, dict) or set(patch) - {"sectionIndex", "field", "oldText", "newText"}:
                raise ValueError("复核补丁字段无效")
            index, field = patch.get("sectionIndex"), patch.get("field", "content")
            old, new = patch.get("oldText"), patch.get("newText")
            if (type(index) is not int or not 0 <= index < len(candidate["sections"]) or field not in {"heading", "content"}
                    or not isinstance(old, str) or not old or len(old) > 5000 or not isinstance(new, str) or len(new) > 6000):
                raise ValueError("复核补丁序号/字段/文字长度无效")
            text = candidate["sections"][index][field]
            if text.count(old) != 1:
                raise ValueError("复核oldText须在当前章节逐字且唯一匹配")
            candidate["sections"][index][field] = text.replace(old, new, 1)
        if "summary" in body:
            candidate["summary"] = body["summary"]
        return self.validate_content({"content": json.dumps(candidate, ensure_ascii=False)})

    async def review(self, content):
        self.enter_phase("review", "阶段：复核报告")
        self.job.emit("report_review", "核对报告文字、资料范围与行情计算口径")
        messages = [
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {"role": "user", "content": json.dumps(self.review_payload(content), ensure_ascii=False)},
                ]
        outcome, revised = "discarded", content
        for attempt in range(2):
            try:
                message = await self.model(messages, report=True)
                write_json(self.tools.store.root / "review-replies" / f"{self.job.task_id}-{self.job.model_calls}.json", {"reply": message.get("content")})
                body = json.loads(message.get("content") or "{}")
                if body == {"unchanged": True}:
                    outcome = "unchanged"
                else:
                    candidate = self.apply_review_changes(content, body) if isinstance(body, dict) and "changes" in body else self.validate_content(message)
                    if len(candidate.sections) != len(content.sections):
                        raise ValueError("复核改变了章节数量，无法对应原有数据表")
                    for before, after in zip(content.sections, candidate.sections):
                        after.tables = before.tables
                    outcome, revised = "revised", candidate
                break
            except (ModelServiceError, ValueError) as error:
                if isinstance(error, ModelServiceError) and error.code not in {"MODEL_UPSTREAM_ERROR", "MODEL_INVALID_RESPONSE", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE"}:
                    raise
                detail = error.message if isinstance(error, ModelServiceError) else str(error)[:300]
                if attempt == 0:
                    self.job.emit("review_retry", "复核未完成：仅重试局部修改，不重写正文", reason=detail)
                    messages = messages + [{"role": "user", "content": '上一条未通过：'+detail+'。只输出一个JSON对象：无需修改用{"unchanged":true}，有问题用changes精确文字补丁。不要重写整个报告。'}]
                else:
                    self.job.emit("review_discarded", "复核未完成，保留已通过程序核查的原稿，可仅重试复核：" + detail)
        if self.method_usage and outcome != "discarded":
            # 计划失败时保留 plan_failed，不能因为复核过就显示为“已计划并复核”。
            self.method_usage["reviewed"] = True
            if self.method_usage["status"] != "plan_failed":
                self.method_usage["status"] = "planned_and_reviewed"
        self.review_outcome = outcome
        return revised

    def parse_tables(self, raw, section_count):
        """解析数据表回复：每张表单独整理与校验，不合格的去掉并记下原因，不影响其他表和正文。返回 [(章节序号, SectionTable)]。"""
        write_json(self.tools.store.root / "table-replies" / f"{self.job.task_id}-{self.job.model_calls}.json", {"reply": raw})
        try:
            body = json.loads(raw or "")
        except ValueError:
            try:
                body = json.loads(escape_inner_quotes(raw or ""))
            except ValueError:
                self.job.emit("tables_dropped", "数据表回复不是有效 JSON，本次未加入表格")
                return []
        items = body.get("tables") if isinstance(body, dict) else None
        accepted, reasons = [], []
        for item in items if isinstance(items, list) else []:
            title = str(item.get("title", ""))[:20] if isinstance(item, dict) else ""
            section = item.pop("section", None) if isinstance(item, dict) else None
            if isinstance(section, str) and section.strip().isdigit():
                section = int(section)
            if not isinstance(section, int) or not 0 <= section < section_count:
                reasons.append(f"「{title}」章节序号无效")
                continue
            item = normalize_table(item, section, [])
            if item is None:
                reasons.append(f"「{title}」行列数对不上")
                continue
            try:
                table = SectionTable.model_validate(item)
            except ValueError as error:
                problems = error.errors() if hasattr(error, "errors") else []
                reasons.append(f"「{title}」" + ("；".join(".".join(map(str, e["loc"])) + " " + e["msg"] for e in problems[:2]) or str(error)[:80]))
                continue
            bad = [c for row in table.rows for c in [Citation(sourceId=row.source_id, page=row.page), *row.also_from] if not self.check_citation(c)]
            if bad:
                reasons.append(f"「{title}」来源页不是本次已读页：{bad[0].source_id} 第{bad[0].page}页")
                continue
            accepted.append((section, table))
        if reasons:
            self.job.emit("tables_dropped", f"{len(reasons)} 张表不合格已去掉：" + "；".join(reasons)[:400], reasons=reasons)
        return accepted

    async def add_tables(self, content):
        """写作第二步：为已通过核查的正文补数据表（一次写出整篇带表格的长 JSON 容易出错，真实验收中多次因此重写）。

        与研究阶段共用上下文前缀；必做的产能/产销表缺失时补要一次，仍缺则记入局限，不让表格拖累整篇报告。
        """
        operating = self.operating_pages()
        located = {(sid, p) for sid, pages in operating.items() for p in pages}
        request = TABLE_RULES + "\n章节：" + json.dumps(
            [{"section": i, "heading": s.heading, "topics": s.topics} for i, s in enumerate(content.sections)], ensure_ascii=False
        )
        if operating:
            request += "\n必做的产能/产销数据页：" + json.dumps([{"sourceId": sid, "pages": p} for sid, p in operating.items()], ensure_ascii=False)
        self.enter_phase("tables", "阶段：根据原文整理数据表")
        tables = []
        for attempt in range(2):
            self.job.emit("table_drafting", "根据已读原文整理数据表" if attempt == 0 else "补做必做的产能/产销表")
            messages = self.context() + [{"role": "user", "content": request}]
            try:
                message = await self.model(
                    messages, tool_specs=self.declarations(), report=True, write_only=True, on_text=self.text_watcher("title", "table_section", "正在整理表")
                )
            except ModelServiceError as error:
                if error.code not in {"MODEL_UPSTREAM_ERROR", "MODEL_INVALID_RESPONSE"}:
                    raise
                try:  # 与正文写作相同的回退：不带工具定义重试一次
                    message = await self.model(messages, report=True)
                except ModelServiceError as retry_error:
                    if retry_error.code not in {"MODEL_UPSTREAM_ERROR", "MODEL_INVALID_RESPONSE"}:
                        raise
                    self.job.emit("tables_dropped", "数据表生成失败：" + retry_error.message)
                    break
            tables += self.parse_tables(message.get("content"), len(content.sections))
            if not located or operating_table_present([t for _, t in tables], located):
                break
            request += "\n上一次没有列出产能/产量/销量/库存表；这次只输出这张必做表。"
        for section, table in tables:
            if len(content.sections[section].tables) < 3:
                content.sections[section].tables.append(table)
        if located and not operating_table_present([t for s in content.sections for t in s.tables], located):
            pages = "；".join(f"{self.sources[sid]['title']}第{'、'.join(map(str, p))}页" for sid, p in operating.items())
            self.table_gaps.append(f"资料中有产能/产量/销量/库存数据（{pages}），但本次未能生成对应数据表。")
        return content

    def enter_phase(self, phase, message):
        if self.job.phase != phase:
            self.job.set_phase(phase, message)

    def text_watcher(self, key, event_type, label):
        """流式输出时，从已收到的文字里找出新写完的字段值（章节标题、表名），逐个发事件：活动流显示“正在写：××”。"""
        pattern = re.compile(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"')
        state = {"text": "", "pos": 0, "count": 0}

        def on_text(delta):
            state["text"] += delta
            for match in pattern.finditer(state["text"], state["pos"]):
                state["pos"] = match.end()
                try:
                    title = json.loads('"' + match.group(1) + '"')
                except ValueError:
                    title = match.group(1)
                self.job.emit(event_type, f"{label}：{title}", index=state["count"], title=title)
                state["count"] += 1

        return on_text

    def report(self, content=None, reason="research_completed"):
        partial = reason != "research_completed"
        if content is None:
            saved_sections = (self.writing_state or {}).get("sections", [])
            sections = list(saved_sections) + [
                {
                    "heading": "本次完成的工作",
                    "content": f"执行 {self.steps} 轮研究动作，模型调用 {self.job.model_calls} 次。请结合来源与阅读覆盖查看已完成范围。",
                    "citations": [],
                },
                {
                    "heading": "未完成与停止原因",
                    "content": f"停止原因：{reason}。保留已获取的来源、行情和阅读覆盖；未完成完整报告，不应视作最终研究结论。",
                    "citations": [],
                },
            ]
            for identifier, notes in self.notes.items():
                if notes:
                    sections.append(
                        {
                            "heading": self.sources[identifier]["title"] + "：已读部分记录",
                            "content": "\n".join(n["summary"] for n in notes),
                            "citations": [],
                        }
                    )
            content = {
                "title": self.job.request.target + "研究（未完成）",
                "summary": f"研究已停止，已保存{len(saved_sections)}节正文；可从未完成部分继续。以下仅保留实际完成范围与资料。",
                "sections": sections,
            }
        else:
            content = content.model_dump(by_alias=True)
            for table in (t for s in content["sections"] for t in s.get("tables", [])):
                for row in table["rows"]:
                    if self.sources.get(row["sourceId"], {}).get("kind") != "document":
                        row["page"] = None  # 行情等非文件来源没有页码，避免网页显示无意义的“第1页”
                table["verification"] = check_table(table, self.page_text)
        limitations = [
            "PDF全文文字与局部原页视觉检查分别记录；未列出的图片/扫描页未进行视觉理解，取数校验不等于独立审计。",
            "已提交的会话记录可在服务重启后查看；运行中的任务尚不能在重启后自动接续。" if self.job.recorder
            else "本次未启用会话存储，记录仅保留在运行进程内。",
        ]
        if any(s["kind"] == "web" for s in self.sources.values()):
            limitations.append("公开网页仅通读本次MCP提取的正文快照，不包含自动跟读外链、图片识别、动态加载或付费内容；检索日期不等于发布日期。")
            limitations += [f"网页发布日期未知，未作为截止日事实引用：{s['title']}" for s in self.sources.values()
                            if s["kind"] == "web" and not s.get("publishedAt")]
        if self.market_data:
            limitations += self.market_data["limitations"]
        if self.current_period_gap:
            limitations.append(self.current_period_gap)
        if self.history_gap:
            limitations.append(self.history_gap)
        limitations += ["未解决的来源冲突：" + c for c in self.conflicts()]
        if self.context_wrapup:
            limitations.append("上下文接近上限，提前结束取证；报告只基于此前已取得的证据，未继续补查的问题见正文说明。")
            limitations += ["提前结束取证，未完成：" + gap for gap in self.wrapup_gaps]
        limitations += self.table_gaps
        if self.method_usage and self.method_usage["status"] == "plan_failed":
            limitations.append("本次方法计划未通过格式校验，研究按已加载的基础方法进行。")
        if partial:
            limitations.insert(0, "本次研究未完成：" + reason)
        financial_data, business_data = self.financial_data(), self.business_data()
        usage = self.job.usage
        return {
            **self.job.request.model_dump(mode="json", by_alias=True),
            **content,
            "mode": "agent",
            "isMock": False,
            "evidenceStatus": "partial" if partial else "retrieved",
            "sources": list(self.sources.values()),
            "toolCalls": self.job.tool_calls,
            "coverage": list(self.coverage.values()),
            "annualHistory": self.annual_context(),
            "marketData": self.market_data,
            "financialData": financial_data if self.job.request.include_financials or self.financial_points else None,
            "visualReadings": self.visual_readings,
            "researchSkill": {k: self.skill[k] for k in ["name", "version", "upstream"]},
            "businessData": business_data,
            "extractionReadings": self.extraction_readings,
            "methodUsage": self.method_usage,
            "omenCoverage": self.omen_coverage(content if not partial else None),
            "figurePlan": plan_section_figures(content["sections"], financial_data, business_data),
            "limitations": limitations,
            "run": {
                "taskId": self.job.task_id,
                "sessionId": self.job.session_id,
                "status": "partial" if partial else "completed",
                "startedAt": self.job.started_at,
                "finishedAt": now(),
                "stopReason": reason,
                "model": self.settings.model,
                "modelCalls": self.job.model_calls,
                "usage": usage,
                "steps": self.steps,
                "reviewOutcome": getattr(self, "review_outcome", None),
            },
        }
