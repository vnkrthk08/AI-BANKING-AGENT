"""CLI entry point for running golden call evaluations."""

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from evals.report import generate_report, print_summary
from evals.runner import GoldenRunner

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


def main() -> None:
    parser = argparse.ArgumentParser(description="KURAL AVA Evaluation Suite Runner")
    parser.add_argument("--suite", choices=["golden", "twists", "all"], default="golden")
    parser.add_argument("--clock", type=str, default="2026-10-06T14:30:00+05:30")
    parser.add_argument("--faults", type=str, default="")
    parser.add_argument("--filter", type=str, default="")
    parser.add_argument("--gate", action="store_true", help="Exit code 1 if any pass mark fails")
    args = parser.parse_args()

    clock = datetime.fromisoformat(args.clock)
    faults = [f.strip() for f in args.faults.split(",") if f.strip()]
    if args.faults == "all":
        faults = ["llm_timeout"]

    scripts_dir = "evals/golden" if args.suite in ("golden", "all") else "evals/twists/approved"
    runner = GoldenRunner(scripts_dir=scripts_dir, fixed_clock=clock, faults=faults)
    report = runner.run_suite(suite_filter=args.filter or None)

    print_summary(report)
    generate_report(report)

    if args.gate and not report.passed:
        print("Gate check: FAILED")
        sys.exit(1)
    elif args.gate:
        print("Gate check: PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
