"""财务/业务数值证据：原页视觉核对与已通读正文取数（AgentRunner 的一部分）。

拥有的运行状态：financial_points / financial_gaps（财务底稿）、segment_points / business_gaps（业务收入结构）、
visual_readings、extraction_readings，以及避免重复自动取数的 financial_checked / detail_checked。
数值一律由程序按原文与单位核对后才进入底稿；模型只负责读表和选择要看的页。
"""

import asyncio
import json
import re

from app.core.agent_prompts import EXTRACT_SYSTEM, VISION_SYSTEM
from app.schemas.financial import ExtractArguments, ExtractResult, InspectArguments, VisualResult, parse_extraction
from app.services.financial_data import build_financial_data, locate_summary_pages, verified_points
from app.services.model_json import DerivedCache, ask_json, stable_key
from app.services.report_figures import build_business_data, locate_detail_pages, verified_segments
from app.services.runtime import now
from app.tools.contracts import ToolError
from app.tools.documents import write_json

UNIT_PATTERN = re.compile(r"单位\s*[:：]\s*(?:人民币)?(亿元|万元|元)")
# 同一页可能开始母公司报表，模型不可把它与此前合并口径混用。
PARENT_STATEMENT = re.compile(r"2[、．.]\s*母公司资产负债表|4[、．.]\s*母公司利润表")


class EvidenceMixin:
    def financial_data(self):
        return build_financial_data(self.financial_points, self.financial_gaps)

    def business_data(self):
        return build_business_data(self.segment_points, self.financial_data(), self.business_gaps)

    async def extract(self, arguments, *, origin="model_tool"):
        args = ExtractArguments.model_validate(arguments)
        if not self.coverage.get(args.document_id, {}).get("textComplete"):
            raise ToolError("FULL_READING_REQUIRED", "先完整阅读资料，再回查取数；指定页提取不能代替全文阅读。")
        metadata, pages = await asyncio.to_thread(self.tools.store.loaded, args.document_id)
        if metadata["publishedAt"] > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "资料晚于研究截止日。")
        if len(set(args.pages)) != len(args.pages) or any(p > len(pages) for p in args.pages):
            raise ToolError("PAGE_OUT_OF_RANGE", "取数页码重复或超出资料范围。")
        payload, texts, units = [], {}, {}
        for number in args.pages:
            text = PARENT_STATEMENT.split(pages[number - 1]["text"])[0]
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
        return {**record, "financialData": self.financial_data(), "businessData": self.business_data()}

    async def detail_data(self, identifier):
        if not self.job.request.include_financials or identifier in self.detail_checked:
            return
        self.detail_checked.add(identifier)
        metadata, pages = await asyncio.to_thread(self.tools.store.loaded, identifier)
        selected = locate_detail_pages(pages)
        for start in range(0, len(selected), 2):
            try:
                await self.extract({"documentId": identifier, "pages": selected[start : start + 2]}, origin="automatic_detail_extraction")
            except ToolError as error:
                self.business_gaps.append(metadata["title"] + "：" + error.message)
                self.job.emit("data_gap", error.message, sourceId=identifier)

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
        self.job.emit(
            "visual_processed",
            f"已查看 {metadata['title']} 原页 {args.pages}，核对{len(points)}个财务数值",
            sourceId=identifier,
            pages=args.pages,
            originRunId=record["originRunId"],
        )
        return {
            **record,
            "financialData": self.financial_data(),
            "limitations": ["只检查所列图片页；数值匹配不证明所有列序与会计口径都无误，保留来源供核查。"],
        }

    async def financial_summary(self, identifier):
        if not self.job.request.include_financials or identifier in self.financial_checked:
            return
        self.financial_checked.add(identifier)
        metadata, pages = await asyncio.to_thread(self.tools.store.loaded, identifier)
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
