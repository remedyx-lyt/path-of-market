"""报告是可回查的产物，不是每轮重放的研究流水；不删除原始会话或证据。"""
import json
import re


def partial_answer(raw):
    """只解码流式JSON中answer字段的完整字符，不把JSON/转义残片展示为答复。最终仍须完整校验。"""
    match = re.search(r'(?<!\\)"answer"\s*:\s*"', raw)
    if not match:
        return ""
    result, i = [], match.end()
    escapes = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', '"': '"', '\\': '\\', '/': '/'}
    while i < len(raw) and len(result) < 16000:
        char = raw[i]
        if char == '"':
            break
        if char != '\\':
            result.append(char)
            i += 1
            continue
        if i + 1 >= len(raw):
            break
        escape = raw[i + 1]
        if escape == 'u':
            fragment = raw[i:i + 6]
            if len(fragment) != 6:
                break
            try:
                code = int(fragment[2:], 16)
                if 0xD800 <= code <= 0xDBFF:
                    fragment = raw[i:i + 12]
                    if len(fragment) != 12 or fragment[6:8] != '\\u' or not 0xDC00 <= int(fragment[8:], 16) <= 0xDFFF:
                        break
                elif 0xDC00 <= code <= 0xDFFF:
                    break
                result.append(json.loads('"' + fragment + '"'))
            except ValueError:
                break
            i += len(fragment)
        elif escape in escapes:
            result.append(escapes[escape])
            i += 2
        else:
            break
    return ''.join(result)


def select_history(recovery, chain, prefix_length):
    messages, ids = recovery["messages"], recovery.get("messageEntryIds", [])
    if recovery.get("state", {}).get("discussion_context_version") == 1:
        return messages, ids, False
    followups = [e for e in chain if e.get("type") == "followup"]
    if not followups:
        # 第一次围绕已完成报告提问；报告正文和证据另行注入。
        return messages[:prefix_length], ids[:prefix_length], True
    first_run = followups[0]["runId"]
    chat_ids = {e["id"] for e in chain if e.get("type") == "message" and e.get("runId") == first_run}
    start = next((i for i, identifier in enumerate(ids) if identifier in chat_ids), None)
    if start is None or start < prefix_length:
        return messages, ids, False  # 无可靠边界时不猜测，防止丢掉问答或拆开工具组。
    return messages[:prefix_length] + messages[start:], ids[:prefix_length] + ids[start:], True


def report_view(report):
    return {"title": report["title"], "summary": report["summary"], "asOfDate": report.get("asOfDate"),
            "sections": [{"index": i, **{k: section[k] for k in ("heading", "content", "citations", "topics", "omens") if k in section}}
                         for i, section in enumerate(report["sections"])], "limitations": report.get("limitations", []),
            "instruction": "这是正式正文；完整表图/行情序列保存在报告中，不在每轮重复传输。精确底稿见current_research_state，细节按来源/批次回查。"}


def saved_supplement(runner):
    """补查笔记单独提供，失败后恢复也不会只看到旧报告而忽略新资料。"""
    original = {s["sourceId"] for s in runner.base.get("sources", [])}
    records = []
    for sid, source in runner.sources.items():
        if sid in original:
            continue
        notes = runner.notes.get(sid, [])
        from app.schemas.agent import Citation
        ineligible = source["kind"] == "web" and not runner.safe_citation(Citation(sourceId=sid, page=None))
        records.append({"sourceId": sid, "title": source["title"], "kind": source["kind"],
                        "publishedAt": source.get("publishedAt"), "citationEligible": source.get("citationEligible", True),
                        "noteBatches": len(notes), "notes": [] if ineligible else notes[:2],
                        "newInThisFollowup": sid not in (runner.discussion_source_baseline or []),
                        "instruction": "日期/阅读条件不合格，仅列为待核资料，不能据此叙述数字或结论。" if ineligible else "完整笔记按批次回查。"})
    # 详细笔记仍可回查；不以无来源的再总结代替原笔记。
    kept, length = [], 0
    for record in reversed(records):
        count = len(json.dumps(record, ensure_ascii=False))
        if length + count > 18000:
            record = {k: v for k, v in record.items() if k != "notes"}
            record["instruction"] = "完整笔记请用recall_research_context回查。"
        kept.append(record)
        length += len(json.dumps(record, ensure_ascii=False))
    return {"type": "discussion_supplement", "sources": list(reversed(kept)),
            "instruction": "newInThisFollowup区分本次新读与此前对话资料。用户说再查时，旧资料不能冒充本次新增；回答说明增量并引用实际已读且日期合格的新资料。搜索摘要和未知日期网页不是已证实事实。"}


def answer_history(messages, blocked_source_ids=()):
    """收尾不再发现资料，搜索线索只留目录，防止未读摘要数字被写成补查成果。"""
    projected = []
    for message in messages:
        if message.get("role") != "tool":
            projected.append(message)
            continue
        try:
            body = json.loads(message["content"])
        except (ValueError, TypeError):
            projected.append(message)
            continue
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data["results"] = [{k: item[k] for k in ("sourceId", "title", "url", "publishedAt", "format") if k in item}
                               for item in data["results"]]
            data.pop("excludedResults", None)
            data["instruction"] = "仅发现目录，尚未通读的资料只列标题与缺口，不引用摘要数字或据此作结论。"
        if isinstance(data, dict) and data.get("sourceId") in blocked_source_ids:
            data.pop("notes", None)
            data.pop("recalledNotes", None)
            data.pop("matches", None)
            data["instruction"] = "该网页日期/阅读条件不合格，正文事实不能用于本次截止日分析；只列待核来源。"
        projected.append({**message, "content": json.dumps(body, ensure_ascii=False)})
    return projected
