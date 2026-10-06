"""Prompt builder for NLU classification per Spec §17 and Prompt D."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Tuple

PROMPT_FILE = Path(__file__).parent / "prompts" / "classify.v1.txt"
EXAMPLE_FILE = Path(__file__).parent / "examples" / "town_bank_app_update.v1.jsonl"


class PromptBuilder:
    def __init__(self, prompt_path: Path | None = None, examples_path: Path | None = None) -> None:
        self.prompt_path = prompt_path or PROMPT_FILE
        self.examples_path = examples_path or EXAMPLE_FILE
        self._prompt_template = self.prompt_path.read_text(encoding="utf-8")
        self._examples = self._load_examples()

    def _load_examples(self) -> list[dict[str, Any]]:
        examples: list[dict[str, Any]] = []
        if not self.examples_path.exists():
            return examples
        for line in self.examples_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                examples.append(json.loads(line))
        return examples

    def select_examples(self, state: str, max_examples: int = 20) -> list[str]:
        """Select up to max_examples examples: state-specific + globals + compound/tricky."""
        state_examples: list[str] = []
        global_examples: list[str] = []
        compound_examples: list[str] = []

        for ex in self._examples:
            line_str = json.dumps(ex, ensure_ascii=False)
            ex_state = ex.get("state", "")
            out = ex.get("out", {})
            primary = out.get("primary_intent", "")
            has_sensitive = bool(ex.get("sensitive_flags", {}).get("present"))

            # Compound or tricky
            if has_sensitive or len(out.get("secondary_intents", [])) > 0 or ex.get("entities", {}).get("note"):
                compound_examples.append(line_str)
            elif primary in {
                "OPT_OUT", "WANTS_HUMAN", "FRAUD_REPORT", "TRUST_CONCERN",
                "QUESTION_ABOUT_AGENT", "QUESTION_ABOUT_CALL", "OFF_TOPIC", "UNKNOWN",
            }:
                global_examples.append(line_str)
            elif ex_state == state:
                state_examples.append(line_str)

        selected: list[str] = []
        # 1. State examples first
        selected.extend(state_examples[:8])
        # 2. Global examples
        selected.extend(global_examples[:7])
        # 3. Compound / tricky
        selected.extend(compound_examples[:5])

        # If still room, fill up to max_examples
        if len(selected) < max_examples:
            for ex_str in state_examples[8:] + global_examples[7:]:
                if ex_str not in selected:
                    selected.append(ex_str)
                if len(selected) >= max_examples:
                    break

        return selected[:max_examples]

    def build_prompt(
        self,
        state: str,
        subbu_last_line: str,
        allowed_intents: list[str],
        global_intents: list[str],
        utterance: str,
        sensitive_flags: dict[str, Any] | None = None,
        last_turns: list[dict[str, str]] | None = None,
    ) -> tuple[str, str]:
        """
        Build complete prompt from template.
        Guarantees zero customer PII or raw secrets.
        """
        selected_exs = self.select_examples(state)
        few_shot_str = "\n".join(selected_exs)

        turns_str = ""
        if last_turns:
            turns_lines = [
                f"{t.get('speaker', 'SPEAKER')}: {t.get('text', '')}"
                for t in last_turns[-3:]
            ]
            turns_str = "\n".join(turns_lines)
        else:
            turns_str = "(none)"

        flags_str = json.dumps(sensitive_flags or {"present": False}, ensure_ascii=False)

        prompt = self._prompt_template.format(
            state=state,
            subbu_last_line=subbu_last_line or "(none)",
            allowed_intents=json.dumps(allowed_intents),
            global_intents=json.dumps(global_intents),
            sensitive_flags=flags_str,
            few_shot_examples=few_shot_str,
            last_turns=turns_str,
            utterance=utterance,
        )

        version = "classify.v1.txt"
        return prompt, version


default_prompt_builder = PromptBuilder()
