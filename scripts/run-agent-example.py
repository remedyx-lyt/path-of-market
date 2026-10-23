"""真实模型研究验收，会消耗 API 额度；必须显式 --live。"""

import argparse
import asyncio
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/agent"))
from app.core.config import load_model_settings
from app.schemas.agent import AgentResearchRequest
from app.services.agent_runner import AgentRunner
from app.services.research_jobs import ResearchJob
from app.tools.registry import get_research_tools


async def run(args):
    request = AgentResearchRequest(target=args.company, question=args.question, asOfDate=args.as_of,
        userStyle="区分事实和假设，重视经营质量、风险与价格口径。", omens=["exalted", "abyssal_echoes"])
    job = ResearchJob(request)
    original = job.emit

    def emit(kind, message, **details):
        original(kind, message, **details)
        print(message, flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(job.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")

    job.emit = emit
    runner = AgentRunner(job, get_research_tools(), load_model_settings())
    await runner.run()
    args.output.write_text(json.dumps(job.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": job.status, "modelCalls": job.model_calls, "usage": job.usage,
                      "sources": len(job.sources), "coverage": job.coverage,
                      "stopReason": (job.report or {}).get("run", {}).get("stopReason"),
                      "error": job.error}, ensure_ascii=False), flush=True)
    return job.status


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--company", default="中际旭创")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--question", default="研究中际旭创最近两年的经营变化，并分析最近约24个月股票价格行情、趋势、区间变化与回撤。阅读最近两份年报并补充当前年度已披露的半年报，区分经营事实、价格表现、可能联系与风险，不给买卖指令。")
    parser.add_argument("--output", type=Path, default=ROOT / "storage/runs/m1-3-zjxc-live.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("实际模型验收需显式 --live；默认离线检查请运行 check-agent-loop.py。")
    raise SystemExit(0 if asyncio.run(run(args)) == "completed" else 1)
