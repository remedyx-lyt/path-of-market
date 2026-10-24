"""报告写作、程序核查、复核与最终报告结构（AgentRunner 的一部分）。

validate_content 是确定性的程序核查（来源/页码/覆盖/图表 ID/主题），不是独立财务审计。
"""

import json

from app.core.agent_prompts import REPORT_RULES, REVIEW_SYSTEM
from app.core.config import ModelServiceError
from app.schemas.agent import AgentContent
from app.services.report_figures import plan_section_figures
from app.services.runtime import now

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
            for node in visual.get("nodes") or []:
                if isinstance(node, dict) and isinstance(node.get("citations"), list):
                    count = len(node["citations"])
                    node["citations"] = unique_citations(node["citations"], 3)
                    if len(node["citations"]) < count:
                        fixes.append(f"第{i + 1}节定性图节点引用去重/截至3条（原{count}条）")
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
    def check_citation(self, citation):
        source = self.sources.get(citation.source_id)
        return source is not None and (
            source["kind"] != "document"
            or citation.page is not None
            and citation.page in self.coverage[citation.source_id]["processedPages"]
        )

    def require_evidence(self, ok, retry_message, gap):
        """证据是否到位。正常取证中不到位就退回让模型补；收尾写作时已不能再取证，改为记入局限，不宣称完成。"""
        if ok:
            return
        if not self.context_wrapup:
            raise ValueError(retry_message)
        if gap not in self.wrapup_gaps:
            self.wrapup_gaps.append(gap)

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
        unread = [c for c in self.coverage.values() if not c["textComplete"]]
        self.require_evidence(
            self.coverage and not unread,
            "选定报告尚未完整处理可提取文字，请继续 full 阅读或明确停止缺口",
            "以下资料未读完：" + "、".join(f"{self.sources[c['sourceId']]['title']}（已处理 {len(c['processedPages'])}/{c['pageCount']} 页）" for c in unread),
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
        self.require_evidence(
            not current or self.coverage.get(current["documentId"], {}).get("textComplete"),
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
        if self.job.request.include_financials:
            if chart_ids and not any(s.chart_ids for s in content.sections):
                raise ValueError("已取得财务绘图数据，请主动选择支持论点的chartIds，不能全部闲置。")
            if business_ids and not any(s.business_ids for s in content.sections):
                raise ValueError("已取得业务收入结构，请主动选择相关businessIds；不能仅展示财务总览。")
        used, repeated = set(), []
        for section in content.sections:
            if not set(section.chart_ids) <= chart_ids or not set(section.business_ids) <= business_ids:
                raise ValueError("所选图表ID必须来自实际底稿。")
            # 同一图表只放一次：保留第一次出现的章节，后面章节的重复引用由程序去掉，不为这条机械规则整篇重写。
            repeated += [i for i in section.chart_ids + section.business_ids if i in used]
            section.chart_ids = [i for i in section.chart_ids if i not in used]
            section.business_ids = [i for i in section.business_ids if i not in used]
            used |= set(section.chart_ids + section.business_ids)
            if section.visual and not all(self.check_citation(c) for node in section.visual.nodes for c in node.citations):
                raise ValueError("定性图节点也须引用实际已读来源和页码。")
        self.validate_omens(content)
        if repeated:
            self.job.emit(
                "figure_duplicates_removed", f"同一图表已放在前面章节，去掉后面 {len(repeated)} 处重复引用", removed=repeated
            )
        return content

    def review_payload(self, content):
        return {
            "candidate": content.model_dump(by_alias=True),
            "asOfDate": self.job.request.as_of_date.isoformat(),
            "discoveredDocuments": [
                {k: d.get(k) for k in ("documentId", "title", "fiscalYear", "reportType", "publishedAt", "preferred")}
                for d in self.discovered.values()
            ],
            "processedSources": list(self.sources.values()),
            "coverage": [
                {
                    "sourceId": c["sourceId"],
                    "pageCount": c["pageCount"],
                    "processedPageCount": len(c["processedPages"]),
                    "emptyTextPages": c["emptyTextPages"],
                    "textComplete": c["textComplete"],
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

    async def review(self, content):
        self.job.emit("report_review", "核对报告文字、资料范围与行情计算口径")
        message = await self.model(
            [
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": json.dumps(self.review_payload(content), ensure_ascii=False)},
            ],
            report=True,
        )
        try:
            unchanged = json.loads(message.get("content") or "{}") == {"unchanged": True}
        except ValueError:
            unchanged = False
        # 无需修改时复核只回一个标记，省去整篇报告的重复输出；有修改则重新做全部程序核查。
        revised = content if unchanged else self.validate_content(message)
        if self.method_usage:
            # 计划失败时保留 plan_failed，不能因为复核过就显示为“已计划并复核”。
            self.method_usage["reviewed"] = True
            if self.method_usage["status"] != "plan_failed":
                self.method_usage["status"] = "planned_and_reviewed"
        self.review_outcome = "unchanged" if unchanged else "revised"
        return revised

    async def compose(self):
        self.job.emit("report_drafting", "根据已有证据和所选方法撰写图文报告")
        # 保持与研究循环相同的系统提示和历史前缀，DeepSeek 前缀缓存可命中；写作规则作为最后一条用户消息追加。
        messages = self.context()
        messages.append(
            {
                "role": "user",
                "content": REPORT_RULES
                + "\n\n"
                + self.omen_writing_instruction()
                + "\n取证阶段已结束。现在按完整报告JSON格式写作，自主选择有用的实际图表ID与有来源的定性图；不要返回ready。",
            }
        )
        try:
            return await self.model(messages, tool_specs=self.declarations(), report=True, write_only=True)
        except ModelServiceError as error:
            if error.code not in {"MODEL_UPSTREAM_ERROR", "MODEL_INVALID_RESPONSE"}:
                raise
            # 供应商若不接受“工具定义 + 禁止调用 + JSON”的组合，退回旧方式（不带工具），只是少了缓存命中。
            self.job.emit("report_drafting_fallback", "写作请求改用不带工具定义的方式重试")
            return await self.model(messages, report=True)

    def report(self, content=None, reason="research_completed"):
        partial = reason != "research_completed"
        if content is None:
            sections = [
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
                "summary": "研究已停止，以下仅保留实际完成范围与资料。",
                "sections": sections,
            }
        else:
            content = content.model_dump(by_alias=True)
        limitations = [
            "PDF全文文字与局部原页视觉检查分别记录；未列出的图片/扫描页未进行视觉理解，取数校验不等于独立审计。",
            "会话和任务目前保存在运行进程内，重启后不能恢复；持久化按 M2 实施。",
        ]
        if self.market_data:
            limitations += self.market_data["limitations"]
        if self.current_period_gap:
            limitations.append(self.current_period_gap)
        limitations += ["未解决的来源冲突：" + c for c in self.conflicts()]
        if self.context_wrapup:
            limitations.append("上下文接近上限，提前结束取证；报告只基于此前已取得的证据，未继续补查的问题见正文说明。")
            limitations += ["提前结束取证，未完成：" + gap for gap in self.wrapup_gaps]
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
