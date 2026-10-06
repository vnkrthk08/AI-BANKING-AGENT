"""Priority resolution and decision contract per Spec §6 and §18."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, List, Optional

from kural.nlu.schemas import NLUResult


class PriorityLevel(IntEnum):
    P1_FRAUD = 1
    P2_OPTOUT = 2
    P3_WRONG_PARTY = 3
    P4_WANTS_HUMAN = 4
    P5_BUSY_CALLBACK_CANCEL = 5
    P6_STATE_INTENTS = 6
    P7_QUESTIONS_TRUST = 7
    P8_OFF_TOPIC = 8
    P9_UNKNOWN = 9


INTENT_TO_PRIORITY: dict[str, PriorityLevel] = {
    # P1
    "FRAUD_REPORT": PriorityLevel.P1_FRAUD,
    # P2
    "OPT_OUT": PriorityLevel.P2_OPTOUT,
    # P3
    "WRONG_PARTY": PriorityLevel.P3_WRONG_PARTY,
    "IDENTITY_DENIED": PriorityLevel.P3_WRONG_PARTY,
    # P4
    "WANTS_HUMAN": PriorityLevel.P4_WANTS_HUMAN,
    # P5
    "BUSY": PriorityLevel.P5_BUSY_CALLBACK_CANCEL,
    "CALLBACK_REQUEST": PriorityLevel.P5_BUSY_CALLBACK_CANCEL,
    "CANCEL": PriorityLevel.P5_BUSY_CALLBACK_CANCEL,
    # P6
    "IDENTITY_CONFIRMED": PriorityLevel.P6_STATE_INTENTS,
    "AFFIRM": PriorityLevel.P6_STATE_INTENTS,
    "DENY": PriorityLevel.P6_STATE_INTENTS,
    "DECLINE": PriorityLevel.P6_STATE_INTENTS,
    "QUICK_PLEASE": PriorityLevel.P6_STATE_INTENTS,
    "APP_INSTALLED": PriorityLevel.P6_STATE_INTENTS,
    "APP_NOT_INSTALLED": PriorityLevel.P6_STATE_INTENTS,
    "APP_ALREADY_UPDATED": PriorityLevel.P6_STATE_INTENTS,
    "APP_UPDATE_SUCCESS": PriorityLevel.P6_STATE_INTENTS,
    "APP_UPDATE_ISSUE": PriorityLevel.P6_STATE_INTENTS,
    "GENERAL_APP_ISSUE": PriorityLevel.P6_STATE_INTENTS,
    "ISSUE_RESOLVED_ALREADY": PriorityLevel.P6_STATE_INTENTS,
    "WAIT": PriorityLevel.P6_STATE_INTENTS,
    "UNSURE": PriorityLevel.P6_STATE_INTENTS,
    # P7
    "QUESTION_ABOUT_CALL": PriorityLevel.P7_QUESTIONS_TRUST,
    "QUESTION_ABOUT_AGENT": PriorityLevel.P7_QUESTIONS_TRUST,
    "TRUST_CONCERN": PriorityLevel.P7_QUESTIONS_TRUST,
    # P8
    "OFF_TOPIC": PriorityLevel.P8_OFF_TOPIC,
    # P9
    "UNKNOWN": PriorityLevel.P9_UNKNOWN,
}


@dataclass
class ResolvedPriority:
    primary_intent: str
    secondary_intents: list[str]
    actions_to_execute: list[str]
    is_compound: bool = False
    compound_rule: str | None = None


def resolve_priorities(nlu: NLUResult, sensitive_present: bool = False) -> ResolvedPriority:
    """
    Apply Spec §6 global priority rules and §6.3 compound rules.
    Highest priority intent wins as primary action; others are queued or recorded.
    """
    all_intents = [nlu.primary_intent] + [i for i in nlu.secondary_intents if i != nlu.primary_intent]

    # Check compound rules (§6.3)
    # 1. FRAUD + OPT_OUT
    if "FRAUD_REPORT" in all_intents and "OPT_OUT" in all_intents:
        return ResolvedPriority(
            primary_intent="FRAUD_REPORT",
            secondary_intents=["OPT_OUT"],
            actions_to_execute=["create_case", "record_opt_out"],
            is_compound=True,
            compound_rule="FRAUD_AND_OPT_OUT",
        )

    # 2. OPT_OUT + Help me now / General App Issue
    if "OPT_OUT" in all_intents and any(i in all_intents for i in ["GENERAL_APP_ISSUE", "APP_UPDATE_ISSUE"]):
        return ResolvedPriority(
            primary_intent="OPT_OUT",
            secondary_intents=[i for i in all_intents if i != "OPT_OUT"],
            actions_to_execute=["record_opt_out"],
            is_compound=True,
            compound_rule="OPT_OUT_AND_HELP",
        )

    # 3. BUSY + "tell me quickly" / QUICK_PLEASE
    if "BUSY" in all_intents and "QUICK_PLEASE" in all_intents:
        return ResolvedPriority(
            primary_intent="QUICK_PLEASE",
            secondary_intents=["BUSY"],
            actions_to_execute=[],
            is_compound=True,
            compound_rule="BUSY_AND_QUICK",
        )

    # 4. WANTS_HUMAN + Callback time
    if "WANTS_HUMAN" in all_intents and ("CALLBACK_REQUEST" in all_intents or nlu.entities.time_expression is not None):
        return ResolvedPriority(
            primary_intent="WANTS_HUMAN",
            secondary_intents=["CALLBACK_REQUEST"],
            actions_to_execute=["upsert_callback"],
            is_compound=True,
            compound_rule="HUMAN_WITH_CALLBACK_TIME",
        )

    # Sort by priority rank
    def _rank(intent: str) -> int:
        return INTENT_TO_PRIORITY.get(intent, PriorityLevel.P9_UNKNOWN).value

    sorted_intents = sorted(all_intents, key=_rank)
    primary = sorted_intents[0]
    secondaries = sorted_intents[1:]

    actions: list[str] = []
    if primary == "FRAUD_REPORT":
        actions.append("create_case")
    elif primary == "OPT_OUT":
        actions.append("record_opt_out")
    elif primary == "WRONG_PARTY":
        actions.append("flag_wrong_number")

    return ResolvedPriority(
        primary_intent=primary,
        secondary_intents=secondaries,
        actions_to_execute=actions,
        is_compound=len(secondaries) > 0,
    )


def gate_reply_line(line_id: str, tool_result_ok: bool) -> str:
    """
    Reply gating per Spec §18:
    Success lines (S-CB-DONE, S-CB-MOVED, S-CB-CANCELLED, S-OPTOUT-01, S-FRAUD-03)
    may only be chosen when matching tool returned ok; otherwise S-ACTION-FAIL.
    """
    gated_lines = {
        "S-CB-DONE",
        "S-CB-MOVED",
        "S-CB-CANCELLED",
        "S-OPTOUT-01",
        "S-FRAUD-03",
    }
    if line_id in gated_lines and not tool_result_ok:
        return "S-ACTION-FAIL"
    return line_id
