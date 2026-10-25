"""财务/业务数值证据：原页视觉核对与已通读正文取数（AgentRunner 的一部分）。

拥有的运行状态：financial_points / financial_gaps（财务底稿）、segment_points / business_gaps（业务收入结构）、
visual_readings、extraction_readings，以及避免重复自动取数的 financial_checked / detail_checked。
数值一律由程序按原文与单位核对后才进入底稿；模型只负责读表和选择要看的页。
"""

import asyncio
import json
import re

from app.core.agent_prompts import EXTRACT_SYSTEM, VISION_SYSTEM
from app.core.research_history import history_count
from app.schemas.financial import ExtractArguments, ExtractResult, InspectArguments, VisualResult, parse_extraction
from app.services.financial_data import build_financial_data, locate_summary_pages, verified_points
from app.services.model_json import DerivedCache, ask_json, stable_key
from app.services.report_figures import build_business_data, locate_detail_pages, locate_operating_pages, verified_segments
from app.services.runtime import now
from app.services.reading_coverage import reading_complete, update_reading_complete
from app.tools.contracts import ToolError
from app.tools.documents import write_json

UNIT_PATTERN = re.compile(r"单位\s*[:：]\s*(?:人民币)?(亿元|万元|元)")
# 财务报告中的报表与附注标题，用来判断一段文字属于合并口径还是母公司口径。
STATEMENT_HEADING = re.compile(
    r"\d+\s*[、．.]\s*(?:合并|母公司)(?:资产负债表|利润表|现金流量表|所有者权益变动表)|合并财务报表项目注释|母公司财务报表主要项目注释"
    r"|[一二三四五六七八九十]+\s*[、．.]\s*公司基本情况"  # 报表之后的通用附注章节，回到默认（合并）口径
)


def consolidated_text(pages, number):
    """只保留合并口径的文字。母公司报表常跨页：页首沿用前面最近一个标题的口径，页内遇到新标题再切换。

    例：年报第92页合并资产负债表结尾之后是“2、母公司资产负债表”，第93–94页上半部分仍是母公司报表；
    若不按跨页口径过滤，母公司的“负债合计”会被当成合并总负债。
    """
    parent = False
    for entry in reversed(pages[: number - 1]):
        hits = STATEMENT_HEADING.findall(entry["text"])
        if hits:
            parent = "母公司" in hits[-1]
            break
    text, kept, start = pages[number - 1]["text"], [], 0
    for match in STATEMENT_HEADING.finditer(text):
        if not parent:
            kept.append(text[start : match.start()])
        parent, start = "母公司" in match.group(0), match.start()
    if not parent:
        kept.append(text[start:])
    return "".join(kept)


class EvidenceMixin:
    def financial_data(self):
        result = build_financial_data(self.financial_points, self.financial_gaps, history_years=max(3, history_count(self.job.request)))
        # 旧 JSONL 只保存了展示的近3年原值，最早一年的同比基数可能未在展示行里。
        # 保留旧报告已计算的同比，绝不由同比反推基数；原值或来源有变则重新计算。
        saved = getattr(self, "restored_financial", None) or {}
        old_rows = {(d["id"], r["year"]): r for d in saved.get("datasets", []) for r in d["rows"]}
        for dataset in result["datasets"]:
            for row in dataset["rows"]:
                old = old_rows.get((dataset["id"], row["year"]))
                if old and old["values"] == row["values"] and old["evidence"] == row["evidence"]:
                    for metric, growth in row["yoy"].items():
                        if growth["reason"] == "缺少上年同期间数据" and metric in old["yoy"]:
                            row["yoy"][metric] = old["yoy"][metric].copy()
        return result

    def business_data(self):
        return build_business_data(self.segment_points, self.financial_data(), self.business_gaps, history_years=max(3, history_count(self.job.request)))

    def document_pages(self, identifier):
        """已下载资料的逐页文字（只读本地缓存，每份资料加载一次）；取不到时为空，相应核对视为未找到。"""
        if identifier not in self.document_cache:
            try:
                self.document_cache[identifier] = self.tools.store.loaded(identifier)[1]
            except ToolError:
                self.document_cache[identifier] = []
        return self.document_cache[identifier]

    def page_text(self, identifier, page):
        """核对表格数字用的原文。PDF 有页码取该页，无页码取整份资料；结构化报表取本次入底稿的数值。"""
        kind = self.sources.get(identifier, {}).get("kind")
        if kind == "database":
            return " ".join(p["rawValue"] for p in self.financial_points if p["sourceId"] == identifier)
        if kind == "web":
            progress = self.coverage.get(identifier, {})
            if page is None and progress.get("textComplete"):
                snapshot = self.tools.public_web.load(identifier, progress.get("snapshotSha256"))
                if snapshot and snapshot["sha256"] == progress.get("snapshotSha256"):
                    return snapshot["text"]
            return ""
        if page is None:
            return "\n".join(p["text"] for p in self.document_pages(identifier)) if kind == "document" else ""
        pages = self.document_pages(identifier)
        return pages[page - 1]["text"] if 0 < page <= len(pages) else ""

    def operating_pages(self):
        """已通读资料中产能/产量/销量/库存表所在页：{sourceId: [页码]}。写作时这是必做内容，研究中提示模型回查。"""
        return {
            sid: pages
            for sid, c in self.coverage.items()
            if reading_complete(c) and self.sources.get(sid, {}).get("kind") == "document" and (pages := locate_operating_pages(self.document_pages(sid)))
        }

    async def extract(self, arguments, *, origin="model_tool"):
        args = ExtractArguments.model_validate(arguments)
        if not reading_complete(self.coverage.get(args.document_id)):
            raise ToolError("FULL_READING_REQUIRED", "先完整阅读资料，再回查取数；指定页提取不能代替全文阅读。")
        metadata, pages = await asyncio.to_thread(self.tools.store.loaded, args.document_id)
        if metadata["publishedAt"] > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "资料晚于研究截止日。")
        if len(set(args.pages)) != len(args.pages) or any(p > len(pages) for p in args.pages):
            raise ToolError("PAGE_OUT_OF_RANGE", "取数页码重复或超出资料范围。")
        payload, texts, units = [], {}, {}
        for number in args.pages:
            text = consolidated_text(pages, number)
            texts[number] = text
            for prior in reversed(pages[max(0, number - 4) : number]):
                candidate = text if prior["page"] == number else prior["text"]
                hit = UNIT_PATTERN.search(candidate)
                if hit:
                    units[number] = {"unit": hit[1], "page": prior["page"], "quote": hit[0]}
                    break
            payload.append({"page": number, "text": text, "unitContext": units.get(number)})
        task = {"document": {k: metadata[k] for k in ["documentId", "fiscalYear", "reportType"]}, "focus": args.focus, "pages": payload}
        key = stable_key({"task": task, "system": EXTRACT_SYSTEM, "model": self.settings.model, "baseUrl": self.settings.base_url})
        cache = DerivedCache(self.tools.store.root / "data-notes", "result")
        parsed, origin_run = cache.load(key, ExtractResult.model_validate)
        if parsed is None:

            def record_invalid(message, error, attempt):
                write_json(
                    self.tools.store.root / "data-errors" / f"{key}-{attempt}.json",
                    {"response": message.get("content"), "error": str(error)[:1200], "runId": self.job.task_id},
                )

            messages = [{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": json.dumps(task, ensure_ascii=False)}]
            repair = lambda error: (
                "按financialPoints、segmentPoints、gaps结构修正，不推算，quote只保留含指标行与数值的短连续原文。格式问题："
                + str(error)[:700]
            )
            try:
                parsed, _ = await ask_json(self.model, messages, parse_extraction, repair, on_invalid=record_invalid)
            except ValueError:
                raise ToolError("DATA_EXTRACTION_INVALID", "正文取数未通过格式校验，未计入底稿。") from None
            cache.save(key, parsed.model_dump(by_alias=True), runId=self.job.task_id)
        # 文本路径必须提供逐字引文；旧视觉路径不受此约束。
        missing = [p for p in parsed.financial_points if not p.quote]
        parsed.financial_points = [p for p in parsed.financial_points if p.quote]
        points, gaps = verified_points(parsed, metadata, texts, units)
        segments, segment_gaps = verified_segments(parsed, metadata, texts)
        self.financial_points += points
        self.financial_gaps += gaps
        self.segment_points += segments
        self.business_gaps += segment_gaps + parsed.gaps
        if missing:
            self.financial_gaps.append("正文取数缺少连续原文引文的数值已排除。")
        record = {
            "sourceId": args.document_id,
            "pages": sorted(args.pages),
            "origin": origin,
            "cacheReused": origin_run is not None,
            "originRunId": origin_run or self.job.task_id,
            "verifiedPointCount": len(points),
            "segmentPointCount": len(segments),
        }
        self.extraction_readings.append(record)
        self.job.emit("data_extracted", f"正文取数完成：{len(points)}个财务值、{len(segments)}个业务收入值", **record)
        self.checkpoint()
        return {**record, "financialData": self.financial_data(), "businessData": self.business_data()}

    async def detail_data(self, identifier):
        if not self.job.request.include_financials or identifier in self.detail_checked:
            return
        metadata, pages = await asyncio.to_thread(self.tools.store.loaded, identifier)
        selected = locate_detail_pages(pages)
        for start in range(0, len(selected), 2):
            try:
                await self.extract({"documentId": identifier, "pages": selected[start : start + 2]}, origin="automatic_detail_extraction")
            except ToolError as error:
                self.business_gaps.append(metadata["title"] + "：" + error.message)
                self.job.emit("data_gap", error.message, sourceId=identifier)
        self.detail_checked.add(identifier)
        self.checkpoint()

    async def inspect(self, arguments, *, origin="model_tool"):
        args = InspectArguments.model_validate(arguments)
        metadata = await asyncio.to_thread(self.tools.store.metadata, args.document_id)
        if metadata["publishedAt"] > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "资料晚于研究截止日。")
        if self.uses_real_provider and self.settings.model not in self.settings.vision_models:
            raise ToolError(
                "VISION_MODEL_UNSUPPORTED", "当前配置模型未声明图片能力，请使用支持视觉输入的模型或配置 DEEPSEEK_VISION_MODELS。"
            )
        existing = {(r["sourceId"], p) for r in self.visual_readings for p in r["pages"]}
        if len(existing | {(args.document_id, p) for p in args.pages}) > self.limits.max_visual_pages:
            raise ToolError("VISUAL_PAGE_BUDGET", "本轮视觉页面预算已达上限，保留已检查范围。")
        downloaded = await self.raw_tool("fetch_document", {"documentId": args.document_id})
        identifier = self.source(downloaded["document"])
        rendered = await self.raw_tool("render_document_pages", args.model_dump(by_alias=True))
        task = {
            "document": rendered["document"],
            "focus": args.focus,
            "pages": [{k: v for k, v in p.items() if k not in {"imageDataUrl", "text"}} for p in rendered["pages"]],
        }
        key = stable_key({"task": task, "system": VISION_SYSTEM, "model": self.settings.model, "baseUrl": self.settings.base_url})
        cache = DerivedCache(self.tools.store.root / "visual-notes", "result")

        def parse(content):
            candidate = VisualResult.model_validate_json(content) if isinstance(content, str) else VisualResult.model_validate(content)
            if {o.page for o in candidate.observations} != set(args.pages) or any(
                p.page not in args.pages for p in candidate.financial_points
            ):
                raise ValueError("视觉结果引用了未提供的页码或遗漏输入页")
            return candidate

        parsed, origin_run = cache.load(key, parse)
        if parsed is None:
            parts = [{"type": "text", "text": json.dumps(task, ensure_ascii=False)}]
            for page in rendered["pages"]:
                parts.extend(
                    [
                        {"type": "text", "text": f"以下为PDF物理第{page['page']}页"},
                        {"type": "image_url", "image_url": {"url": page["imageDataUrl"], "detail": "high"}},
                    ]
                )
            messages = [{"role": "system", "content": VISION_SYSTEM}, {"role": "user", "content": parts}]
            try:
                parsed, _ = await ask_json(
                    lambda m: self.model(m, visual=True), messages, parse, "请严格按JSON结构和输入物理页码修正；未看清数值可省略。"
                )
            except ValueError:
                raise ToolError("VISUAL_RESULT_INVALID", "原页视觉结果未通过格式/页码校验，未计入已理解范围。") from None
            cache.save(key, parsed.model_dump(by_alias=True), runId=self.job.task_id, processedAt=now())
        points, gaps = verified_points(parsed, rendered["document"], {p["page"]: p["text"] for p in rendered["pages"]})
        for point in points:
            point["verificationOrigin"] = origin
        self.financial_points.extend(points)
        self.financial_gaps.extend(gaps)
        record = {
            "sourceId": identifier,
            "pages": sorted(args.pages),
            "origin": origin,
            "model": self.settings.model,
            "processedAt": now(),
            "cacheReused": origin_run is not None,
            "originRunId": origin_run or self.job.task_id,
            "observations": [o.model_dump() for o in parsed.observations],
            "verifiedPointCount": len(points),
            "imageHashes": [p["imageSha256"] for p in rendered["pages"]],
        }
        self.visual_readings.append(record)
        progress = self.coverage[identifier]
        was_complete = reading_complete(progress)
        progress['visuallyProcessedPages'] = sorted(set(progress.get('visuallyProcessedPages', [])) | set(args.pages))
        update_reading_complete(progress)
        if not was_complete and reading_complete(progress):
            self.financial_checked.discard(identifier)
            self.detail_checked.discard(identifier)  # 原先因扫描页未读而失败的取数，补读后可继续。
        self.job.emit(
            "visual_processed",
            f"已查看 {metadata['title']} 原页 {args.pages}，核对{len(points)}个财务数值",
            sourceId=identifier,
            pages=args.pages,
            originRunId=record["originRunId"],
        )
        self.checkpoint()
        return {
            **record,
            "financialData": self.financial_data(),
            "limitations": ["只检查所列图片页；数值匹配不证明所有列序与会计口径都无误，保留来源供核查。"],
        }

    async def database_financials(self):
        """结构化财务报表（AKShare）：主公司每次研究只取一次，作财务底稿主来源。失败只记缺口，仍走年报原页取数。"""
        if not self.job.request.include_financials or self.database_info is not None:
            return
        if getattr(self.tools, "statement_provider", None) is None:
            self.database_info = {"status": "disabled"}
            return
        as_of = self.job.request.as_of_date
        arguments = {"company": self.job.request.target, "startYear": as_of.year - max(3, history_count(self.job.request)),
                     "endYear": as_of.year, "asOfDate": as_of.isoformat()}
        self.job.emit("financial_database_started", "AKShare 取结构化财务报表：" + self.job.request.target)
        try:
            data = await asyncio.wait_for(self.raw_tool("get_financial_statements", arguments), 240)
        except (ToolError, TimeoutError) as error:
            message = error.message if isinstance(error, ToolError) else "AKShare 取数超时"
            self.database_info = {"status": "failed", "message": message}
            self.financial_gaps.append(message + "；财务数字改由年报原文取数。")
            self.job.emit("financial_database_failed", message + "，改用年报原文取数")
            self.checkpoint()
            return
        identifier = "akshare-" + data["company"]["code"]
        self.sources[identifier] = {
            "sourceId": identifier,
            "kind": "database",
            "title": data["company"]["name"] + "三大财务报表（" + data["provider"] + "）",
            "url": data["sourceUrl"],
            "publishedAt": data["latestNoticeDate"],
            "retrievedAt": data["retrievedAt"],
        }
        self.job.sources = list(self.sources.values())
        self.financial_points += [
            {**p, "sourceId": identifier, "page": None, "quote": "", "verification": "akshare_structured", "verificationOrigin": "financial_database"}
            for p in data["points"]
        ]
        self.database_info = {"status": "completed", "sourceId": identifier, **{k: v for k, v in data.items() if k != "points"}}
        self.job.emit("financial_database_finished", f"结构化财务报表取得 {len(data['periods'])} 个报告期、{len(data['points'])} 个数值",
                      sourceId=identifier, cacheReused=data["cacheReused"])
        self.checkpoint()

    def database_covers(self, metadata):
        """结构化报表是否已有这份报告所属期间的营业收入（有则不必再视觉读主要会计数据页）。"""
        period = {"annual": "annual", "interim": "h1", "q1": "q1", "q3": "q3"}.get(metadata.get("reportType", "annual"))
        return any(p.get("verificationOrigin") == "financial_database" and p["metric"] == "revenue"
                   and p["year"] == metadata["fiscalYear"] and p["period"] == period for p in self.financial_points)

    async def financial_summary(self, identifier):
        if not self.job.request.include_financials or identifier in self.financial_checked:
            return
        self.financial_checked.add(identifier)
        await self.database_financials()
        metadata, pages = await asyncio.to_thread(self.tools.store.loaded, identifier)
        if self.database_covers(metadata):
            self.job.emit("financial_summary_skipped", metadata["title"] + "：主要财务数已由结构化报表提供，不再视觉读取会计数据页", sourceId=identifier)
            return
        selected = locate_summary_pages(pages)
        if not selected:
            self.financial_gaps.append(metadata["title"] + "：未定位主要会计数据页，尚无自动结构化财务取数。")
            return
        try:
            await self.inspect(
                {
                    "documentId": identifier,
                    "pages": selected,
                    "focus": "检查主要会计数据表，提取当前及比较年度的实际值，核对表头年份/单位。",
                },
                origin="automatic_financial_summary",
            )
        except ToolError as error:
            self.financial_gaps.append(metadata["title"] + "：" + error.message)
            self.job.emit("visual_gap", error.message, sourceId=identifier)
