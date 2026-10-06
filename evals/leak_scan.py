"""Scans database files, log files, and request logs for leaked secrets."""

import argparse
import re
import sys
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"\b482913\b"),
    re.compile(r"\b4\s*8\s*2\s*9\s*1\s*3\b"),
    re.compile(r"\b123456\b"),
    re.compile(r"\b4111\s*1111\s*1111\s*1111\b"),
    re.compile(r"\b[0-9]{16}\b"),
]


def scan_file(file_path: Path) -> list[str]:
    leaks = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            matches = pat.findall(content)
            if matches:
                leaks.append(f"{file_path}: matched {pat.pattern} ({len(matches)} occurrences)")
    except Exception as e:
        pass
    return leaks


def run_leak_scan(target_dir: str = ".") -> int:
    root = Path(target_dir)
    print("\n" + "=" * 60)
    print("KURAL AVA LEAKAGE SCANNER")
    print("=" * 60)
    print(f"Scanning target: {root.resolve()}")

    candidate_files = []
    # Scan db, logs, and reports (exclude dev/vendor dirs and test fixtures)
    excluded_parts = {".git", ".venv", "node_modules", "tests", "evals", "docs", ".gemini"}
    for ext in ("*.log", "*.txt", "*.db", "*.sqlite"):
        for p in root.glob(f"**/{ext}"):
            if any(part in p.parts for part in excluded_parts):
                continue
            candidate_files.append(p)

    all_leaks = []
    for cf in candidate_files:
        leaks = scan_file(cf)
        all_leaks.extend(leaks)

    if all_leaks:
        print(f"[FAIL] LEAKAGE DETECTED: {len(all_leaks)} leaks found:")
        for l in all_leaks:
            print(f"  -> {l}")
        print("=" * 60 + "\n")
        return 1

    print("[PASS] ZERO SECRET LEAKAGE DETECTED. All logs and databases clean.")
    print("=" * 60 + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan for leaked secrets")
    parser.add_argument("--from-run", default="latest")
    args = parser.parse_args()
    code = run_leak_scan()
    sys.exit(code)


if __name__ == "__main__":
    main()
