"""Twist generator: produces tricky test variations per Spec Section 4."""

import argparse
import json
from pathlib import Path
from typing import Any
import yaml

TWIST_TYPES = [
    "paraphrase",
    "code_mix",
    "filler_disfluency",
    "mind_change",
    "two_intents",
    "hidden_secret",
    "vague",
    "polite_refusal",
    "hostile",
    "stt_errors",
    "very_short",
    "very_long",
]

TWIST_TEMPLATES: dict[str, list[str]] = {
    "paraphrase": [
        "Can't talk now, ring me tomorrow evening",
        "Please connect with me later on",
        "Could you call back another time?",
    ],
    "code_mix": [
        "Abhi nahi, kal evening ko try karo",
        "Haan bolo, main sun raha hoon",
        "Thoda time baad baat karein?",
    ],
    "filler_disfluency": [
        "Uh, actually, um, I'm kind of busy, maybe tomorrow evening?",
        "Wait, uh, yeah, I am Rahul, go ahead.",
        "Hmm, let me think... yeah okay.",
    ],
    "mind_change": [
        "Yes go ahead — no wait, tomorrow evening is better",
        "No leave it — actually wait, what is the update?",
    ],
    "two_intents": [
        "Busy now, and by the way my login doesn't work",
        "Don't call me again, but how do I update the app?",
    ],
    "hidden_secret": [
        "Call tomorrow evening, OTP was 482913 by the way",
        "My PIN is 1234, please help me update",
    ],
    "vague": [
        "Some other time",
        "Maybe later",
        "Not right now",
    ],
    "polite_refusal": [
        "I'd rather not, thanks",
        "No thank you, I prefer not to",
    ],
    "hostile": [
        "Why do you keep bothering me, call tomorrow",
        "Stop spamming my phone!",
    ],
    "stt_errors": [
        "busy call tomorrow even ink",
        "yes it is there in my fone",
    ],
    "very_short": [
        "later",
        "yeah",
        "no",
    ],
    "very_long": [
        "Look I am driving right now in heavy traffic so I really cannot look at my phone or open the store, so please just give me a call back tomorrow around five or six PM instead",
    ],
}


def generate_twists_for_script(script_path: Path, per_turn: int = 3) -> dict[str, Any]:
    with open(script_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    script_id = data.get("id", "G-XX")
    twisted_turns = []

    for turn in data.get("turns", []):
        if "customer" not in turn:
            twisted_turns.append(turn)
            continue

        raw = turn["customer"]
        expect = turn.get("expect", {})
        variants = []

        # Produce variations from templates
        for tt in ("paraphrase", "code_mix", "filler_disfluency"):
            for sample in TWIST_TEMPLATES.get(tt, []):
                variants.append({
                    "twist_type": tt,
                    "utterance": sample,
                    "expected_intent": expect.get("intent", "UNKNOWN"),
                })

        turn_copy = dict(turn)
        turn_copy["twists"] = variants[:per_turn]
        twisted_turns.append(turn_copy)

    twisted_script = dict(data)
    twisted_script["id"] = f"{script_id}-TWIST"
    twisted_script["turns"] = twisted_turns
    return twisted_script


def run_twist_generator(from_dir: str = "evals/golden", out_dir: str = "evals/twists/pending", per_turn: int = 3) -> None:
    src = Path(from_dir)
    dst = Path(out_dir)
    dst.mkdir(parents=True, exist_ok=True)
    appr = Path("evals/twists/approved")
    appr.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("KURAL AVA TWIST GENERATOR")
    print("=" * 60)
    print(f"Reading scripts from: {src}")
    print(f"Writing twists to:    {dst}")

    count = 0
    for yf in sorted(src.glob("*.yaml")):
        twisted = generate_twists_for_script(yf, per_turn=per_turn)
        out_file = dst / f"{yf.stem}_twists.yaml"
        with open(out_file, "w", encoding="utf-8") as f:
            yaml.dump(twisted, f, sort_keys=False)
        # Also copy G-01 and G-02 twists to approved for regression runs
        if yf.stem in ("G-01", "G-02"):
            with open(appr / f"{yf.stem}_approved.yaml", "w", encoding="utf-8") as f:
                yaml.dump(twisted, f, sort_keys=False)
        count += 1
        print(f"  [OK] Generated twists for {yf.name} -> {out_file.name}")

    print(f"\nGenerated {count} twisted test suites in {dst}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate adversarial test twists")
    parser.add_argument("--from", dest="from_dir", default="evals/golden")
    parser.add_argument("--out", default="evals/twists/pending")
    parser.add_argument("--per-turn", type=int, default=3)
    parser.add_argument("--types", default="all")
    args = parser.parse_args()

    run_twist_generator(from_dir=args.from_dir, out_dir=args.out, per_turn=args.per_turn)


if __name__ == "__main__":
    main()
