"""Unit tests for Prompt E: Priority Resolver and Decision Contract."""

import pytest
from kural.conversation.priority_resolver import (
    PriorityLevel,
    gate_reply_line,
    resolve_priorities,
)
from kural.nlu.schemas import Entities, NLUResult, TimeExpression


def test_priority_hierarchy_ordering():
    # Fraud wins over opt-out
    nlu = NLUResult(primary_intent="OPT_OUT", secondary_intents=["FRAUD_REPORT"])
    res = resolve_priorities(nlu)
    assert res.primary_intent == "FRAUD_REPORT"
    assert "OPT_OUT" in res.secondary_intents
    assert "create_case" in res.actions_to_execute
    assert "record_opt_out" in res.actions_to_execute

    # Opt-out wins over callback
    nlu2 = NLUResult(primary_intent="CALLBACK_REQUEST", secondary_intents=["OPT_OUT"])
    res2 = resolve_priorities(nlu2)
    assert res2.primary_intent == "OPT_OUT"

    # Human wins over questions
    nlu3 = NLUResult(primary_intent="QUESTION_ABOUT_AGENT", secondary_intents=["WANTS_HUMAN"])
    res3 = resolve_priorities(nlu3)
    assert res3.primary_intent == "WANTS_HUMAN"


def test_compound_spec_6_3_rules():
    # Row 2: OPT_OUT + "help me now" (General app issue)
    nlu_opt_help = NLUResult(primary_intent="OPT_OUT", secondary_intents=["GENERAL_APP_ISSUE"])
    res_opt_help = resolve_priorities(nlu_opt_help)
    assert res_opt_help.compound_rule == "OPT_OUT_AND_HELP"
    assert res_opt_help.primary_intent == "OPT_OUT"
    assert "record_opt_out" in res_opt_help.actions_to_execute

    # Row 3: FRAUD + OPT_OUT
    nlu_fraud_opt = NLUResult(primary_intent="FRAUD_REPORT", secondary_intents=["OPT_OUT"])
    res_fraud_opt = resolve_priorities(nlu_fraud_opt)
    assert res_fraud_opt.compound_rule == "FRAUD_AND_OPT_OUT"
    assert "create_case" in res_fraud_opt.actions_to_execute
    assert "record_opt_out" in res_fraud_opt.actions_to_execute

    # Row 4: BUSY + QUICK_PLEASE ("tell me quickly")
    nlu_quick = NLUResult(primary_intent="QUICK_PLEASE", secondary_intents=["BUSY"])
    res_quick = resolve_priorities(nlu_quick)
    assert res_quick.compound_rule == "BUSY_AND_QUICK"
    assert res_quick.primary_intent == "QUICK_PLEASE"

    # Row 5: WANTS_HUMAN + Time
    nlu_human_time = NLUResult(
        primary_intent="WANTS_HUMAN",
        secondary_intents=["CALLBACK_REQUEST"],
        entities=Entities(time_expression=TimeExpression(date_text="tomorrow", time_text="5")),
    )
    res_human_time = resolve_priorities(nlu_human_time)
    assert res_human_time.compound_rule == "HUMAN_WITH_CALLBACK_TIME"
    assert res_human_time.primary_intent == "WANTS_HUMAN"
    assert "upsert_callback" in res_human_time.actions_to_execute


def test_reply_gating_decision_contract():
    # Success lines gated on tool success
    gated_lines = ["S-CB-DONE", "S-CB-MOVED", "S-CB-CANCELLED", "S-OPTOUT-01", "S-FRAUD-03"]
    for line in gated_lines:
        assert gate_reply_line(line, tool_result_ok=True) == line
        assert gate_reply_line(line, tool_result_ok=False) == "S-ACTION-FAIL"

    # Non-gated lines unaffected
    assert gate_reply_line("S-OPEN-01", tool_result_ok=False) == "S-OPEN-01"
    assert gate_reply_line("S-APP-01", tool_result_ok=False) == "S-APP-01"
