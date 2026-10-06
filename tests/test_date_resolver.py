"""Unit tests for Prompt F: Date Resolver per Spec §7.2–§7.6 (Rules R1–R24)."""

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from kural.scheduling.resolver import (
    DateResolver,
    ResolveStatus,
    default_date_resolver,
)

IST = ZoneInfo("Asia/Kolkata")
FIXED_CLOCK = datetime(2026, 10, 6, 14, 30, tzinfo=IST)  # Tuesday


@pytest.fixture
def resolver():
    return DateResolver()


@pytest.mark.parametrize(
    ("raw", "expected_status", "expected_iso", "expected_contains"),
    [
        ("Tomorrow at 5", ResolveStatus.RESOLVED, "2026-10-07T17:00:00+05:30", ["Wednesday", "7 October", "5 PM"]),
        ("Tomorrow evening", ResolveStatus.RESOLVED, "2026-10-07T18:00:00+05:30", ["Wednesday", "7 October", "6 PM"]),
        ("Tomorrow morning", ResolveStatus.RESOLVED, "2026-10-07T10:00:00+05:30", ["Wednesday", "7 October", "10 AM"]),
        ("Tomorrow afternoon", ResolveStatus.RESOLVED, "2026-10-07T14:00:00+05:30", ["Wednesday", "7 October", "2 PM"]),
        ("Day after tomorrow after 6", ResolveStatus.RESOLVED, "2026-10-08T18:00:00+05:30", ["Thursday", "8 October", "6 PM"]),
        ("Day after tomorrow morning", ResolveStatus.RESOLVED, "2026-10-08T10:00:00+05:30", ["Thursday", "8 October", "10 AM"]),
        ("Today after 6", ResolveStatus.RESOLVED, "2026-10-06T18:00:00+05:30", ["today", "6 PM"]),
        ("This evening", ResolveStatus.RESOLVED, "2026-10-06T18:00:00+05:30", ["today", "6 PM"]),
        ("Any time tomorrow", ResolveStatus.RESOLVED, "2026-10-07T11:00:00+05:30", ["Wednesday", "7 October", "11 AM"]),
        ("Monday afternoon", ResolveStatus.RESOLVED, "2026-10-12T14:00:00+05:30", ["Monday", "12 October", "2 PM"]),
        ("After 5", ResolveStatus.RESOLVED, "2026-10-06T17:00:00+05:30", ["today", "5 PM"]),
        ("Around 7", ResolveStatus.RESOLVED, "2026-10-06T19:00:00+05:30", ["today", "7 PM"]),
        ("Kal shaam ko", ResolveStatus.RESOLVED, "2026-10-07T18:00:00+05:30", ["Wednesday", "7 October", "6 PM"]),
        ("Parso subah", ResolveStatus.RESOLVED, "2026-10-08T10:00:00+05:30", ["Thursday", "8 October", "10 AM"]),
    ],
)
def test_worked_examples_resolved(resolver, raw, expected_status, expected_iso, expected_contains):
    res = resolver.resolve(raw_expression=raw, clock=FIXED_CLOCK)
    assert res.status == expected_status
    assert res.iso_local == expected_iso
    for sub in expected_contains:
        assert sub.lower() in res.spoken_read_back.lower()


@pytest.mark.parametrize(
    ("raw", "expected_status", "expected_rule"),
    [
        ("Later today", ResolveStatus.NEEDS_CLARIFICATION, "R10"),
        ("Sometime this week", ResolveStatus.NEEDS_CLARIFICATION, "R11"),
        ("Next Saturday", ResolveStatus.NEEDS_CLARIFICATION, "R8"),
        ("Next Monday", ResolveStatus.NEEDS_CLARIFICATION, "R8"),
        ("Next Tuesday", ResolveStatus.NEEDS_CLARIFICATION, "R8"),
        ("At 1", ResolveStatus.PAST, "R12"),
        ("10 PM", ResolveStatus.OUT_OF_POLICY, "R13"),
        ("Tomorrow 5 or Thursday morning", ResolveStatus.MULTIPLE, "R17"),
        ("Next Sunday at 11 AM", ResolveStatus.OUT_OF_POLICY, "R14"),
    ],
)
def test_worked_examples_clarification_and_policy(resolver, raw, expected_status, expected_rule):
    res = resolver.resolve(raw_expression=raw, clock=FIXED_CLOCK)
    assert res.status == expected_status
    assert res.rule == expected_rule
    if expected_status == ResolveStatus.OUT_OF_POLICY and "Sunday" in raw:
        assert "Monday, 12 October, at 11 AM" in res.suggestion


def test_adversarial_ad_cases(resolver):
    # AD-08: Multiple times
    assert resolver.resolve(raw_expression="tomorrow 5 or Thursday morning", clock=FIXED_CLOCK).status == ResolveStatus.MULTIPLE

    # AD-09: Late-night "tomorrow" at 00:30 IST
    late_clock = datetime(2026, 10, 6, 0, 30, tzinfo=IST)
    res_late = resolver.resolve(raw_expression="tomorrow evening", clock=late_clock)
    assert res_late.status == ResolveStatus.NEEDS_CLARIFICATION
    assert res_late.rule == "R16"

    # AD-11: Impossible time
    assert resolver.resolve(raw_expression="at 25 o'clock", clock=FIXED_CLOCK).status == ResolveStatus.UNPARSEABLE
    assert resolver.resolve(raw_expression="31st February", clock=FIXED_CLOCK).status == ResolveStatus.UNPARSEABLE

    # AD-12: Past time today
    assert resolver.resolve(raw_expression="today at 1", clock=FIXED_CLOCK).status == ResolveStatus.PAST

    # AD-13: Ambiguous date "on the 10th"
    res_10th = resolver.resolve(raw_expression="on the 10th after 5", clock=FIXED_CLOCK)
    assert res_10th.status == ResolveStatus.RESOLVED
    assert "Saturday, 10 October" in res_10th.spoken_read_back

    # AD-14: Any time is fine
    res_any = resolver.resolve(raw_expression="any time is fine", clock=FIXED_CLOCK)
    assert res_any.status == ResolveStatus.RESOLVED

    # AD-31: Call me after 9 at 14:30
    res_after_9 = resolver.resolve(raw_expression="call me after 9", clock=FIXED_CLOCK)
    assert res_after_9.status == ResolveStatus.OUT_OF_POLICY
    assert res_after_9.rule == "AD-31"
    assert "Wednesday, 7 October, at 9 AM" in res_after_9.suggestion

    # AD-35: Relative duration
    res_2h = resolver.resolve(raw_expression="in 2 hours", clock=FIXED_CLOCK)
    assert res_2h.status == ResolveStatus.RESOLVED
    assert res_2h.iso_local == "2026-10-06T16:30:00+05:30"

    res_10m = resolver.resolve(raw_expression="in 10 minutes", clock=FIXED_CLOCK)
    assert res_10m.status == ResolveStatus.OUT_OF_POLICY
    assert "3 PM" in res_10m.suggestion

    # AD-44: Past date 2nd October
    assert resolver.resolve(raw_expression="call me on 2nd October", clock=FIXED_CLOCK).status == ResolveStatus.PAST


def test_sunday_clock_case(resolver):
    sunday_clock = datetime(2026, 10, 11, 14, 30, tzinfo=IST)
    # Next Sunday said on Sunday -> +7 days
    res = resolver.resolve(raw_expression="next sunday at 11 AM", clock=sunday_clock)
    assert res.status == ResolveStatus.OUT_OF_POLICY
    assert res.rule == "R14"
    assert "Monday, 19 October, at 11 AM" in res.suggestion
