"""NLU accuracy checker against the example bank."""

import argparse
import json
import sys
from pathlib import Path

from kural.nlu.classifier import DeterministicKeywordNLU, SubbuClassifier


def run_nlu_check(examples_file: str = "kural/nlu/examples/town_bank_app_update.v1.jsonl") -> int:
    path = Path(examples_file)
    if not path.exists():
        print(f"Error: Examples file {examples_file} not found.")
        return 1

    print("\n" + "=" * 60)
    print("KURAL AVA NLU ACCURACY CHECK")
    print("=" * 60)
    print(f"Loading examples from: {path}")

    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))

    classifier = SubbuClassifier()
    keyword_fallback = DeterministicKeywordNLU()

    total = len(examples)
    correct = 0
    failures = []

    for idx, ex in enumerate(examples, start=1):
        utterance = ex["utterance"]
        expected_intent = (ex.get("out") or ex.get("expected", {})).get("primary_intent")
        state = ex.get("state", "PERMISSION_CHECK")
        allowed = ex.get("allowed_intents", ["AFFIRM", "DENY", "BUSY", "CALLBACK_REQUEST", "UNKNOWN"])

        # Try classifier (which uses LLM or fallback if no key)
        result = classifier.classify(state=state, utterance=utterance, allowed_intents=allowed)
        detected = result.primary_intent

        # If detected matches or alias
        if detected == expected_intent or (expected_intent == "CALLBACK_REQUEST" and detected in ("BUSY", "CALLBACK_REQUEST")):
            correct += 1
        else:
            failures.append((idx, utterance, expected_intent, detected))

    accuracy = correct / total if total > 0 else 0
    print(f"Evaluated: {total} examples")
    print(f"Correct:   {correct}")
    print(f"Accuracy:  {accuracy * 100:.1f}% (Pass mark: >= 90.0%)")

    if failures:
        print("\nSample mismatches:")
        for idx, u, exp, det in failures[:5]:
            print(f"  #{idx} '{u}': expected {exp}, got {det}")

    print("=" * 60 + "\n")
    return 0 if accuracy >= 0.90 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Check NLU accuracy against example bank")
    parser.add_argument("--examples", default="kural/nlu/examples/town_bank_app_update.v1.jsonl")
    args = parser.parse_args()
    code = run_nlu_check(args.examples)
    sys.exit(code)


if __name__ == "__main__":
    main()
