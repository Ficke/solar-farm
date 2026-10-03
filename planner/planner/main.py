"""Entry points run by GitHub Actions.

  python -m planner.main plan --site out/site --data out/data
  python -m planner.main recommend --data out/data
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from planner import jackery, telemetry, watttime
from planner.plan import build_plan


def cmd_plan(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    token = watttime.login(os.environ["WATTTIME_USERNAME"], os.environ["WATTTIME_PASSWORD"])
    points = watttime.forecast(token, region=args.region)
    plan = build_plan(points, now, budget_hours=args.budget_hours, region=args.region)
    try:
        plan["index_now"] = watttime.signal_index(token, region=args.region)
    except Exception as e:  # informational only; the device has its own fallback
        print(f"signal-index: skipped ({type(e).__name__}: {e})", file=sys.stderr)
    site = Path(args.site)
    site.mkdir(parents=True, exist_ok=True)
    (site / "plan.json").write_text(json.dumps(plan, separators=(",", ":")))
    print(f"plan: {len(plan['windows'])} windows {plan['windows']} index_now={plan.get('index_now')}")

    email = os.environ.get("JACKERY_EMAIL")
    if email:
        try:
            reading = asyncio.run(
                jackery.read(email, os.environ["JACKERY_PASSWORD"], os.environ.get("JACKERY_SN"), now)
            )
            telemetry.append(Path(args.data) / "telemetry.csv", reading)
            print(f"jackery: battery {reading.battery_pct}% solar {reading.solar_w} W")
        except Exception as e:  # unofficial API: never let it block the plan
            print(f"jackery: telemetry skipped ({type(e).__name__}: {e})", file=sys.stderr)
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    path = Path(args.data) / "telemetry.csv"
    if not path.exists():
        print("No telemetry yet.")
        return 0
    daily = telemetry.daily_solar_wh(telemetry.load(path))
    rec = telemetry.recommend_reserve(daily)
    lines = ["| Day | Solar (Wh) |", "| --- | --- |"]
    lines += [f"| {d} | {round(wh)} |" for d, wh in sorted(daily.items())[-14:]]
    if rec["reserve_pct"] is None:
        summary = "Not enough full days of telemetry yet to recommend a reserve."
    else:
        summary = (
            f"Set the Self-powered reserve to **{rec['reserve_pct']}%**. "
            f"A good solar day over the last {rec['days']} days was about {rec['good_day_wh']} Wh, "
            "and this leaves room for it."
        )
    out = summary + "\n\n" + "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(out)
    print(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="planner")
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("plan")
    pp.add_argument("--site", default="out/site")
    pp.add_argument("--data", default="out/data")
    pp.add_argument("--region", default="CAISO_NORTH")
    pp.add_argument("--budget-hours", type=float, default=4.0)
    pr = sub.add_parser("recommend")
    pr.add_argument("--data", default="out/data")
    pr.add_argument("--out")
    args = p.parse_args(argv)
    return cmd_plan(args) if args.cmd == "plan" else cmd_recommend(args)


if __name__ == "__main__":
    raise SystemExit(main())
