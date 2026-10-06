"""Approved script store for Subbu and Town Bank."""

from __future__ import annotations

import pathlib
from typing import Any
import yaml

SCRIPTS_PATH = pathlib.Path(__file__).parent / "content" / "town_bank_scripts.yaml"

FORBIDDEN_PHRASES = (
    "transferred",
    "i checked your account",
    "i am a human",
    "i'm a human",
    "your account is safe",
)


class ScriptStore:
    def __init__(self, yaml_path: pathlib.Path | None = None) -> None:
        self.yaml_path = yaml_path or SCRIPTS_PATH
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.yaml_path.exists():
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                self.data = yaml.safe_load(f) or {}

    @property
    def version(self) -> str:
        return str(self.data.get("version", "1.1"))

    @property
    def bank_name(self) -> str:
        return str(self.data.get("bank_name", "Town Bank"))

    @property
    def persona_name(self) -> str:
        return str(self.data.get("persona_name", "Subbu"))

    def get_line(self, line_id: str, **kwargs: Any) -> str:
        scripts = self.data.get("scripts", {})
        item = scripts.get(line_id)
        if not item:
            return ""
        text = str(item.get("text", ""))
        first_name = kwargs.get("first_name") or kwargs.get("name") or "there"
        kwargs_with_defaults = {"first_name": first_name, **kwargs}
        try:
            return text.format(**kwargs_with_defaults)
        except KeyError:
            return text

    def get(self, line_id: str, default: str = "") -> str:
        line = self.get_line(line_id)
        return line if line else default

    def validate_content_safety(self) -> list[str]:
        """Verify no script contains forbidden claims."""
        violations = []
        for line_id, item in self.data.get("scripts", {}).items():
            text = str(item.get("text", "")).lower()
            for forbidden in FORBIDDEN_PHRASES:
                if forbidden in text:
                    violations.append(f"{line_id}: contains forbidden phrase '{forbidden}'")
            for variant in item.get("variants", []):
                v_text = str(variant).lower()
                for forbidden in FORBIDDEN_PHRASES:
                    if forbidden in v_text:
                        violations.append(f"{line_id} variant: contains forbidden phrase '{forbidden}'")
        return violations


default_script_store = ScriptStore()
