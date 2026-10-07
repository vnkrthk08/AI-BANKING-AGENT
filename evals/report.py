"""Evaluation reporter and pass-mark gatekeeper per Spec Section 5."""

import sys
from pathlib import Path
from evals.runner import SuiteReport


def print_summary(report: SuiteReport) -> None:
    print("\n" + "=" * 70)
    print(f"KURAL AVA EVALUATION REPORT -- SUITE: {report.suite_name.upper()}")
    print("=" * 70)
    print(f"Run Timestamp:           {report.run_timestamp}")
    print(f"Calls Evaluated:         {report.total_calls} (Passed: {report.passed_calls}, Failed: {report.total_calls - report.passed_calls})")
    print(f"Total Turns:             {report.total_turns} (Correct: {report.correct_turns})")
    print(f"Intent Accuracy:         {report.intent_accuracy * 100:.1f}% (Pass mark: >= 95.0%)")
    print(f"Resolver Accuracy:       {report.resolver_accuracy * 100:.1f}% (Pass mark: 100.0%)")
    print(f"Unapproved Statements:   {report.unapproved_statements} (Pass mark: 0)")
    print(f"Sensitive Leakage:       {report.sensitive_leakage} (Pass mark: 0)")
    print(f"False Call Endings:      {report.false_call_endings} (Pass mark: 0)")
    print("-" * 70)

    for s in report.scripts:
        status_icon = "PASS" if s.passed else "FAIL"
        print(f"[{status_icon}] {s.script_id}: {s.title}")
        if not s.passed:
            for err in s.final_errors:
                print(f"    -> ERROR: {err}")

    print("=" * 70)
    overall_status = "PASSED ALL GATES" if report.passed else "FAILED GATES"
    print(f"OVERALL STATUS: {overall_status}")
    print("=" * 70 + "\n")


def generate_report(report: SuiteReport, output_dir: str = "evals/reports") -> Path:
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_file = out_path / "latest.md"

    md = [
        f"# KURAL AVA Evaluation Report — {report.suite_name.upper()}",
        f"**Run at:** `{report.run_timestamp}`\n",
        "## Summary Metrics",
        "| Metric | Target | Result | Status |",
        "|---|---|---|---|",
        f"| Calls Passed | 100% | {report.passed_calls}/{report.total_calls} | {'PASS' if report.passed_calls == report.total_calls else 'FAIL'} |",
        f"| Intent Accuracy | >= 95.0% | {report.intent_accuracy * 100:.1f}% | {'PASS' if report.intent_accuracy >= 0.95 else 'FAIL'} |",
        f"| Resolver Accuracy | 100.0% | {report.resolver_accuracy * 100:.1f}% | {'PASS' if report.resolver_accuracy == 1.0 else 'FAIL'} |",
        f"| Sensitive Leakage | 0 | {report.sensitive_leakage} | {'PASS' if report.sensitive_leakage == 0 else 'FAIL'} |",
        f"| Unapproved Statements | 0 | {report.unapproved_statements} | {'PASS' if report.unapproved_statements == 0 else 'FAIL'} |",
        f"| False Call Endings | 0 | {report.false_call_endings} | {'PASS' if report.false_call_endings == 0 else 'FAIL'} |",
        "\n## Detailed Script Results\n",
    ]

    for s in report.scripts:
        md.append(f"### {s.script_id}: {s.title} — {'PASS' if s.passed else 'FAIL'}")
        md.append(f"- Outcome: `{s.outcome}`")
        md.append(f"- Cases Created: `{s.cases_created}`, Callbacks Created: `{s.callbacks_created}`")
        if s.final_errors:
            md.append("- Errors:")
            for err in s.final_errors:
                md.append(f"  - `{err}`")
        md.append("")

    report_file.write_text("\n".join(md), encoding="utf-8")
    return report_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Report gatekeeper")
    parser.add_argument("--run", default="latest")
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args()
    report_file = Path("evals/reports/latest.md")
    if not report_file.exists():
        print("No evaluation report found. Run `python -m evals.run` first.")
        sys.exit(1)
    content = report_file.read_text(encoding="utf-8")
    try:
        print(content)
    except UnicodeEncodeError:
        print(content.encode("ascii", errors="replace").decode("ascii"))
    if args.gate and "FAIL" in content:
        print("\nGATE FAILED: One or more pass marks failed.")
        sys.exit(1)
    print("\nGATE PASSED.")
    sys.exit(0)
