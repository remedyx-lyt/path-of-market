"""资料完整阅读与按页回查（AgentRunner 的一部分）。

拥有的运行状态：sources（来源）、coverage（文字覆盖）、notes（每份资料的分批阅读记录）。
规则不变：选定资料先 mode=full 连续分批读完，page/search 只用于复查；阅读失败的批次不计入覆盖。
"""

import asyncio
import json

from app.core.agent_prompts import LEGACY_READ_SYSTEM, READ_SYSTEM
from app.core.config import ModelServiceError
from app.schemas.agent import AgentReadArguments, ReadingNote
from app.services.model_json import DerivedCache, ask_json, stable_key, validation_problems
from app.services.runtime import now
from app.tools.contracts import ToolError

# 阅读笔记的提示版本；修改 READ_SYSTEM 或阅读任务结构时递增，使旧缓存自然失效。
READING_VERSION = 2


class ReadingMixin:
    def source(self, metadata):
        identifier = metadata["documentId"]
        if identifier not in self.sources:
            self.sources[identifier] = {
                "sourceId": identifier,
                "kind": "document",
                "title": metadata["title"],
                "url": metadata["sourceUrl"],
                "publishedAt": metadata["publishedAt"],
                "pageCount": metadata["pageCount"],
                "fiscalYear": metadata["fiscalYear"],
                "reportType": metadata.get("reportType", "annual"),
            }
            self.coverage[identifier] = {
                "sourceId": identifier,
                "pageCount": metadata["pageCount"],
                "returnedCharacters": 0,
                "processedCharacters": 0,
                "processedPages": [],
                "emptyTextPages": [],
                "textComplete": False,
                "batches": 0,
            }
        self.job.sources = list(self.sources.values())
        self.job.coverage = list(self.coverage.values())
        return identifier

    async def read(self, arguments):
        args = AgentReadArguments.model_validate(arguments)
        metadata = await asyncio.to_thread(self.tools.store.metadata, args.document_id)
        if metadata["publishedAt"] > self.job.request.as_of_date.isoformat():
            raise ToolError("AFTER_RESEARCH_CUTOFF", "资料披露时间晚于研究截止日。")
        downloaded = await self.raw_tool("fetch_document", {"documentId": args.document_id})
        identifier = self.source(downloaded["document"])
        if args.mode != "full":
            return await self.lookup(identifier, args)
        if self.coverage[identifier]["textComplete"]:
            # 已通读的资料再次 full：笔记此前已返回过，不重复整批传回主上下文（重复传回只增加 token）。
            await self.financial_summary(identifier)
            await self.detail_data(identifier)
            return {
                "sourceId": identifier,
                "coverage": self.coverage[identifier],
                "cacheHit": True,
                "notesAlreadyProvided": True,
                "noteBatches": len(self.notes[identifier]),
                "instruction": "此资料已完整阅读，阅读要点在之前的工具结果中；需要细节请用 mode=page（可一次多页）或 search。",
            }
        await self.read_all_batches(identifier, metadata, downloaded["document"]["sha256"])
        await self.financial_summary(identifier)
        await self.detail_data(identifier)
        return {
            "sourceId": identifier,
            "notes": self.notes[identifier],
            "coverage": self.coverage[identifier],
            "financialData": self.financial_data(),
            "businessData": self.business_data(),
            "limitations": ["文字与视觉覆盖分别记录；未列出的图片尚未理解。"],
        }

    async def lookup(self, identifier, args):
        if not self.coverage[identifier]["textComplete"]:
            raise ToolError(
                "FULL_READ_REQUIRED", "此资料尚未完成通读。请使用 mode=full，程序会从上次成功处理的位置接续；单页或关键词不能替代。"
            )
        if args.mode == "search":
            if not args.query.strip():
                raise ToolError("INVALID_TOOL_ARGUMENTS", "关键词回查需要 query。")
            return await self.raw_tool("search_document", {"documentId": identifier, "query": args.query})
        pages = list(dict.fromkeys(args.pages)) or [args.page]
        results = [await self.raw_tool("read_document", {"documentId": identifier, "page": page}) for page in pages]
        if len(results) == 1:
            return results[0]
        return {"sourceId": identifier, "pages": results}

    async def read_all_batches(self, identifier, metadata, file_sha256):
        # 失败后的补读从已处理游标接续；不把先前只返回但模型失败的批次算成已读。
        cursor = self.coverage[identifier].get("nextCursor", {"startPage": 1, "offset": 0})
        self.notes.setdefault(identifier, [])
        cache = DerivedCache(self.tools.store.root / "reading-notes", "note")
        # 缩批只重读失败游标，成功范围不回退；沿用缩小后的批量，避免下一批再次撞上同一上限。
        max_pages, max_characters, splits, transient_retries = 20, self.limits.read_characters, 0, 0
        while cursor is not None:
            self.check_budget()
            batch = await self.raw_tool(
                "read_document_batch", {"documentId": identifier, **cursor, "maxPages": max_pages, "maxCharacters": max_characters}
            )
            progress = self.coverage[identifier]
            progress["nextCursor"] = cursor
            progress["returnedCharacters"] += sum(len(p["text"]) for p in batch["pages"])
            first, last = batch["pages"][0]["page"], batch["pages"][-1]["page"]
            self.job.emit(
                "reading_batch", f"{metadata['title']}：阅读第 {first}–{last} 页", sourceId=identifier, firstPage=first, lastPage=last
            )
            try:
                note = await self.batch_note(identifier, metadata, batch, cursor, file_sha256, cache)
            except (ModelServiceError, ToolError) as error:
                # 密钥/余额等全局错误不能伪装成资料缺口；只隔离本批的格式、截断与临时调用故障。
                if isinstance(error, ModelServiceError) and error.code not in {
                    "MODEL_INVALID_RESPONSE", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_UPSTREAM_ERROR"
                }:
                    raise
                length = isinstance(error, ModelServiceError) and getattr(error, "finish_reason", None) == "length"
                invalid_note = isinstance(error, ToolError) and error.code == "READING_NOTE_INVALID"
                characters = sum(len(p["text"]) for p in batch["pages"])
                if (length or invalid_note) and characters > 1000:
                    splits += 1
                    max_pages = max(1, len(batch["pages"]) // 2)
                    max_characters = max(1000, min(max_characters // 2, characters // 2))
                    self.job.emit(
                        "reading_batch_split", f"第 {first}–{last} 页阅读记录未完成，缩小批次后从原位置重读",
                        sourceId=identifier, firstPage=first, lastPage=last, nextCursor=cursor,
                        maxPages=max_pages, maxCharacters=max_characters, attempt=splits,
                    )
                    continue
                if isinstance(error, ModelServiceError) and error.code in {
                    "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_UPSTREAM_ERROR"
                } and transient_retries < 1:
                    transient_retries += 1
                    self.job.emit(
                        "reading_batch_retry", f"第 {first}–{last} 页调用暂未完成，从同一位置重试", sourceId=identifier,
                        errorCode=error.code, nextCursor=cursor,
                    )
                    await asyncio.sleep(0.5)
                    continue
                self.job.emit(
                    "reading_batch_failed", f"第 {first}–{last} 页尚未读完，已保留成功范围，可接续补读",
                    sourceId=identifier, firstPage=first, lastPage=last, errorCode=error.code, nextCursor=cursor,
                )
                raise ToolError(
                    "READING_BATCH_FAILED", "本批阅读未完成，未计入已读覆盖；可用 full 从失败位置接续，不必重读已完成范围。",
                    {"sourceId": identifier, "cause": error.code, "nextCursor": cursor, "coverage": progress.copy()},
                ) from None
            self.notes[identifier].append(note.model_dump())
            progress["processedCharacters"] += sum(len(p["text"]) for p in batch["pages"])
            progress["processedPages"] = sorted(set(progress["processedPages"]) | {p["page"] for p in batch["pages"] if p["pageComplete"]})
            progress["emptyTextPages"] = sorted(
                set(progress["emptyTextPages"]) | {p["page"] for p in batch["pages"] if p["textStatus"] != "extracted"}
            )
            progress["batches"] += 1
            cursor = batch["nextCursor"]
            splits, transient_retries = 0, 0
            progress["nextCursor"] = cursor
            progress["textComplete"] = (
                cursor is None and len(progress["processedPages"]) == progress["pageCount"] and not progress["emptyTextPages"]
            )
            self.job.emit(
                "reading_processed",
                f"{metadata['title']}：已处理 {len(progress['processedPages'])}/{progress['pageCount']} 页文本",
                sourceId=identifier,
            )

    async def batch_note(self, identifier, metadata, batch, cursor, file_sha256, cache):
        """一批原文交给模型阅读。笔记与研究问题无关（通读要点），同一文件换问题也能复用，避免整本重读。"""
        allowed = {p["page"] for p in batch["pages"]}
        reading_task = {"sourceId": identifier, "title": metadata["title"], "pages": batch["pages"]}
        messages = [{"role": "system", "content": READ_SYSTEM}, {"role": "user", "content": json.dumps(reading_task, ensure_ascii=False)}]
        # 派生阅读缓存，不是会话持久化：须命中同一原文件、同一批原文、同一模型与提示版本。
        key = stable_key({"messages": messages, "model": self.settings.model, "sha256": file_sha256, "version": READING_VERSION})

        def parse(content):
            note = ReadingNote.model_validate_json(content) if isinstance(content, str) else ReadingNote.model_validate(content)
            if any(not set(fact.pages) <= allowed for fact in note.facts):
                raise ValueError("引用了当前批次之外的物理页码")
            return note

        note, origin = cache.load(key, parse)
        if note is None:
            # 兼容旧缓存：以前的笔记键包含研究问题。同一问题此前读过就直接复用，并转存到新键，避免整本重读。
            legacy_task = {"question": self.job.request.question, **reading_task}
            legacy_key = stable_key(
                {
                    "messages": [
                        {"role": "system", "content": LEGACY_READ_SYSTEM},
                        {"role": "user", "content": json.dumps(legacy_task, ensure_ascii=False)},
                    ],
                    "model": self.settings.model,
                    "sha256": file_sha256,
                }
            )
            note, origin = cache.load(legacy_key, parse)
            if note is not None:
                cache.save(
                    key,
                    note.model_dump(),
                    runId=origin,
                    processedAt=now(),
                    sourceId=identifier,
                    model=self.settings.model,
                    migratedFrom=legacy_key,
                )
        if note is not None:
            self.job.emit("reading_cache_reused", "复用同一原文的已验证阅读记录", sourceId=identifier, originRunId=origin)
            return note
        repair = (
            "上次记录未通过校验。请修正为 summary 字符串、最多8个 facts（每个 text 字符串和 pages 整数数组）、最多6个 gaps 字符串。"
            "只能引用这些物理页码：" + json.dumps(sorted(allowed)) + "。原文中其他引用页码不能当作本批来源。"
        )
        try:
            def invalid(message, error, attempt):
                self.job.emit(
                    "reading_note_invalid", "阅读记录格式需修正：" + "；".join(validation_problems(error)),
                    sourceId=identifier, pages=sorted(allowed), attempt=attempt + 1, problems=validation_problems(error),
                )

            note, _ = await ask_json(lambda m: self.model(m, reading=True), messages, parse, repair, on_invalid=invalid)
        except ValueError:
            # 只修复一次，不能把结构失败当成全文已读；不把验证异常里的原文/堆栈塞入结果。
            raise ToolError(
                "READING_NOTE_INVALID",
                "本批阅读记录未通过校验；继续 full 可接续重试，本批尚未计入覆盖。",
                {"allowedPages": sorted(allowed), "nextCursor": cursor},
            ) from None
        cache.save(key, note.model_dump(), runId=self.job.task_id, processedAt=now(), sourceId=identifier, model=self.settings.model)
        return note
