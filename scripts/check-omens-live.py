"""M1-4 真实验收：经网页代理→Java→Python 依次运行三个研究，比较预兆/问题带来的方法与工具动作差异，并记录 token 与缓存命中。

需要三服务已启动、.env 已配置；显式 --live 才会调用模型账户（会产生费用）。
- A：与上次真实案例完全相同的任务（崇高+深渊回响），用来和上次 647,664 tokens 对比；复用已有阅读缓存。
- B：同一公司、不选预兆、换成竞争/行业问题：验证按问题选 Skill，且阅读笔记跨问题复用（不再整本重读）。
- C：同一公司、远古+机遇：验证不同预兆带来不同的取证动作（更长历史区间、展望/产能回查等）与覆盖自评。
结果写入 storage/runs/m1-4-omens-live.json（每个案例完整任务 JSON + 汇总对比）。
"""

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STYLE = "区分事实与假设，核对年份和口径。"
CASES = {
    "A": {"label": "与上次相同任务（崇高+深渊回响）", "omens": ["exalted", "abyssal_echoes"],
          "question": "研究最近两年的经营变化，阅读最近两份年报并补充当年已披露的半年报，分析最近约24个月股票价格走势、区间变化、回撤，以及经营与价格之间可能的联系和风险。"},
    "B": {"label": "不选预兆，竞争与行业问题", "omens": [],
          "question": "研究公司的竞争格局与所在行业周期：主要竞争优势、客户与产品结构变化，以及这些变化在最近两年财报中的体现。"},
    "C": {"label": "远古+机遇", "omens": ["ancient", "opportunity"],
          "question": "从公司自身发展历程看当前所处阶段，并梳理未来6到24个月可能的变化、催化与验证指标。"},
}
PREVIOUS = {"taskId": "921f4324-577a-4794-abf3-2823d0bab7c8", "totalTokens": 647664, "modelCalls": 24}


def request(base, path, method="GET", body=None):
    req = Request(base.rstrip("/") + "/api/research/jobs" + path, method=method,
                  data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


def action(call):
    args = call.get("arguments") or {}
    detail = {k: args[k] for k in ("years", "reportTypes", "startDate", "endDate", "mode", "page", "pages", "query", "reference") if k in args}
    return {"name": call["name"], "status": call["status"], **detail}


def summarize(case, job):
    report = job.get("report") or {}
    usage = job.get("usage") or {}
    hit, miss = usage.get("prompt_cache_hit_tokens"), usage.get("prompt_cache_miss_tokens")
    methods = report.get("methodUsage") or {}
    return {
        "case": case, "label": CASES[case]["label"], "taskId": job["taskId"], "status": job["status"],
        "stopReason": (report.get("run") or {}).get("stopReason"), "modelCalls": job["modelCalls"], "usage": usage,
        "cacheHitRate": round(hit / (hit + miss), 3) if isinstance(hit, int) and isinstance(miss, int) and hit + miss else None,
        "decisionSteps": (report.get("run") or {}).get("steps"), "reviewOutcome": (report.get("run") or {}).get("reviewOutcome"),
        "methodReferences": [{"reference": r["reference"].split("/skills/")[-1], "selectedBecause": r.get("selectedBecause")}
                             for r in methods.get("references", [])],
        "methodPlanStatus": methods.get("status"), "planCacheReused": methods.get("planCacheReused"),
        "onDemandSkillReads": [r.split("/skills/")[-1] for r in methods.get("onDemandReads", [])],
        "toolActions": [action(c) for c in report.get("toolCalls", [])],
        "readingCacheReused": sum(e["type"] == "reading_cache_reused" for e in job.get("events", [])),
        "omenCoverage": [{k: c[k] for k in ("omen", "covered", "sections", "missingItems", "capabilityGaps", "skillsRead", "planChecks")}
                         for c in report.get("omenCoverage", [])],
    }


def run_case(base, case, as_of, out):
    spec = CASES[case]
    code, job = request(base, "", "POST", {"target": "中际旭创", "question": spec["question"], "asOfDate": as_of, "userStyle": STYLE,
                                           "omens": spec["omens"], "includeMarket": True})
    if code != 202:
        raise SystemExit(f"案例 {case} 创建失败：HTTP {code} {job.get('error', {}).get('code')}")
    task_id, last = job["taskId"], None
    print(f"\n== 案例 {case}：{spec['label']} · taskId {task_id}", flush=True)
    for _ in range(900):
        code, job = request(base, "/" + task_id)
        if code != 200:
            raise SystemExit(f"查询失败：HTTP {code}")
        out[case] = job
        if job["progress"] != last:
            print(" ", job["progress"], "| 模型调用", job["modelCalls"], flush=True)
            last = job["progress"]
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(2)
    raise SystemExit(f"案例 {case} 等待上限已到；任务可能仍在运行。")


def compare(summaries):
    print("\n== 对比", flush=True)
    for s in summaries:
        names = [a["name"] + (f"({a.get('mode')})" if a.get("mode") else "") for a in s["toolActions"]]
        print(f"[{s['case']}] {s['label']}: {s['status']} · {s['modelCalls']} 次调用 · {s['decisionSteps']} 轮 · "
              f"tokens {s['usage'].get('total_tokens')} · 缓存命中 {s['cacheHitRate']} · 阅读缓存复用 {s['readingCacheReused']} 批")
        print("    方法：", ", ".join(r["reference"] for r in s["methodReferences"]))
        print("    工具：", " → ".join(names))
        for c in s["omenCoverage"]:
            print(f"    预兆 {c['omen']}: covered={c['covered']} 章节={c['sections']} 未覆盖={c['missingItems'][:3]}")
    if summaries and summaries[0]["case"] == "A":
        total = summaries[0]["usage"].get("total_tokens")
        print(f"\n案例A 与上次同任务对比：上次 {PREVIOUS['totalTokens']} tokens / {PREVIOUS['modelCalls']} 次调用；本次 {total} tokens / {summaries[0]['modelCalls']} 次调用。")
    signatures = {s["case"]: {(a["name"], a.get("mode"), json.dumps(a.get("pages") or a.get("page")), a.get("query")) for a in s["toolActions"]} for s in summaries}
    if len(signatures) > 1:
        same = all(v == next(iter(signatures.values())) for v in signatures.values())
        print("不同问题/预兆的工具动作完全相同" if same else "不同问题/预兆产生了不同的工具动作（见上）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="确认调用模型账户（会产生费用）")
    parser.add_argument("--cases", default="A,B,C", help="要运行的案例，逗号分隔，默认 A,B,C")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--as-of", default="2026-10-23", help="与上次真实案例相同的研究截止日，以复用资料与阅读缓存")
    parser.add_argument("--output", type=Path, default=ROOT / "storage/runs/m1-4-omens-live.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("真实模型验收需显式 --live。")
    cases = [c.strip().upper() for c in args.cases.split(",") if c.strip()]
    if any(c not in CASES for c in cases):
        parser.error("案例只能是 A、B、C")
    target = args.output if args.output.is_absolute() else ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    jobs, summaries = {}, []
    try:
        for case in cases:
            job = run_case(args.base_url, case, args.as_of, jobs)
            summaries.append(summarize(case, job))
            target.write_text(json.dumps({"previous": PREVIOUS, "summaries": summaries, "jobs": jobs}, ensure_ascii=False, indent=2), encoding="utf-8")
    except URLError:
        raise SystemExit("无法连接网页服务，请先运行 scripts/start-app.ps1。") from None
    compare(summaries)
    print(f"\n结果：{target}")
    ok = all(s["status"] == "completed" for s in summaries) and all(
        len(s["omenCoverage"]) == len(CASES[s["case"]]["omens"]) for s in summaries)
    print("PASS M1-4 真实验收" if ok else "未全部通过：查看上面的状态、停止原因与覆盖情况", flush=True)
    raise SystemExit(0 if ok else 1)
