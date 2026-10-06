import pytest
from kural.knowledge.script_store import ScriptStore, default_script_store


def test_script_store_contains_required_ids():
    required_ids = [
        "S-OPEN-01", "S-OPEN-01b", "S-OPEN-01n", "S-REASK-ID",
        "S-PURPOSE-01", "S-PURPOSE-01b", "S-REC-01",
        "S-NOTAVAIL-01", "S-WRONG-01", "S-ID-REFUSE-01", "S-ID-REFUSE-END",
        "S-PERM-OK", "S-REASK-PERM", "S-BUSY-PRE", "S-HUMAN-PRE", "S-CB-PRE",
        "S-Q-WHO", "S-Q-AI", "S-Q-WHY", "S-APP-01", "S-UPD-01", "S-UPD-OK",
        "S-ISSUE-01", "S-HUMAN-01", "S-CB-ASK", "S-CB-CONFIRM", "S-CB-DONE",
        "S-CB-MOVED", "S-CB-CANCELLED", "S-OPTOUT-01", "S-FRAUD-01", "S-SENS-01",
        "S-END-OK", "S-FAIL-01", "S-ACTION-FAIL"
    ]
    for script_id in required_ids:
        line = default_script_store.get_line(script_id, first_name="Rahul", spoken_datetime="tomorrow at 5 PM")
        assert line, f"Missing or empty script line for {script_id}"


def test_script_store_contains_no_forbidden_claims():
    violations = default_script_store.validate_content_safety()
    assert not violations, f"Forbidden claims found in script store: {violations}"


def test_script_store_catches_injected_forbidden_claim(tmp_path):
    bad_yaml = tmp_path / "bad_scripts.yaml"
    bad_yaml.write_text(
        """
scripts:
  S-TEST:
    text: "I am a human and your account is safe."
    rephrase: false
"""
    )
    bad_store = ScriptStore(bad_yaml)
    violations = bad_store.validate_content_safety()
    assert len(violations) >= 2
    assert any("i am a human" in v for v in violations)
    assert any("your account is safe" in v for v in violations)
