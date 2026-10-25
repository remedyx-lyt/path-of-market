"""经网页代理→Java→Python 实际执行研究；--live 才调用模型账户。"""

import argparse
from datetime import date
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--resume")
    parser.add_argument("--continue-from", help="从已停止任务的检查点继续，创建关联的新任务。")
    parser.add_argument("--target", default="中际旭创")
    parser.add_argument("--question", default="研究最近两年的经营变化，阅读最近两份年报并补充当年已披露的半年报，分析最近约24个月股票价格走势、区间变化、回撤，以及经营与价格之间可能的联系和风险。")
    parser.add_argument("--omens", nargs="*", default=["exalted", "abyssal_echoes"])
    parser.add_argument("--output", type=Path, default=ROOT / "storage/runs/m1-3-zjxc-web-live.json")
    parser.add_argument("--require-financials", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("实际模型检查需显式 --live。")
    target = args.output if args.output.is_absolute() else ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.continue_from:
        code, job = request(args.base_url, "/"+args.continue_from+"/continue", "POST")
        if code != 202:
            raise SystemExit(f"continue failed: {code} {job.get('error', {}).get('code')}")
        task_id = job["taskId"]
    elif args.resume:
        task_id = args.resume
    else:
        code, job = request(args.base_url, "", "POST", {"target": args.target, "question": args.question,
            "asOfDate": args.as_of, "userStyle": "区分事实与假设，核对年份和口径。", "omens": args.omens, "includeMarket": True})
        if code != 202:
            print("create failed", code, job.get("error", {}).get("code"), flush=True)
            raise SystemExit(1)
        task_id = job["taskId"]
    print("taskId", task_id, flush=True)
    last = None
    for _ in range(3000):
        code, job = request(args.base_url, "/" + task_id)
        if code != 200:
            print("poll failed", code, flush=True)
            raise SystemExit(1)
        target.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        if job["progress"] != last:
            print(job["progress"], "| calls", job["modelCalls"], flush=True)
            last = job["progress"]
        if job["status"] not in {"queued", "running"}:
            report = job.get("report") or {}
            print(json.dumps({"status": job["status"], "modelCalls": job["modelCalls"], "usage": job["usage"],
                "coverage": [{"sourceId": c["sourceId"], "processed": len(c["processedPages"]), "total": c["pageCount"], "complete": c["textComplete"]} for c in job["coverage"]],
                "stopReason": report.get("run", {}).get("stopReason"), "error": job.get("error")}, ensure_ascii=False), flush=True)
            if job["status"] == "completed":
                assert report["mode"] == "agent" and report["marketData"]["series"]
                assert report["sources"] and report["toolCalls"] and all(c.get("readingComplete", c["textComplete"]) for c in report["coverage"])
                if args.require_financials:
                    assert report.get('financialData',{}).get('datasets') and report.get('visualReadings') and report.get('researchSkill')
                    assert any(d['id']=='annual' for d in report['financialData']['datasets'])
                print("PASS live web → Java → Python → model/tools → report", flush=True)
                raise SystemExit(0)
            raise SystemExit(1)
        time.sleep(2)
    raise SystemExit("等待上限已到；任务可能仍在运行，可用 --resume 查看。")
