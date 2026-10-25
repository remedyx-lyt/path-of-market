"""文字与视觉分别记账；扫描页确实查看后才算资料阅读完成。"""


def reading_complete(coverage):
    return bool(coverage and (coverage.get("textComplete") or coverage.get("readingComplete")))


def update_reading_complete(coverage):
    if coverage.get("unit") == "segment":
        return
    covered = set(coverage.get("processedPages", []))
    scanned = set(coverage.get("emptyTextPages", []))
    visual = set(coverage.get("visuallyProcessedPages", []))
    coverage["readingComplete"] = (coverage.get("nextCursor") is None and len(covered) == coverage.get("pageCount", 0)
                                    and bool(covered) and scanned <= visual)


def page_read(coverage, page):
    return bool(coverage and page in coverage.get("processedPages", [])
                and (page not in coverage.get("emptyTextPages", []) or page in coverage.get("visuallyProcessedPages", [])))
