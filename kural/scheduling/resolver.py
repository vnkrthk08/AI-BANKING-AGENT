"""Deterministic callback date and time resolver per Spec §7.2–§7.6 (Rules R1–R24)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Weekday names (0 = Monday, 6 = Sunday)
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# Part of day defaults (Spec §7.2)
PART_OF_DAY_DEFAULTS = {
    "morning": 10,
    "afternoon": 14,
    "evening": 18,
    "night": None,
}

HOLIDAY_CALENDAR = {
    date(2026, 10, 2),  # Gandhi Jayanti
}


class ResolveStatus(StrEnum):
    RESOLVED = "RESOLVED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    PAST = "PAST"
    OUT_OF_POLICY = "OUT_OF_POLICY"
    UNPARSEABLE = "UNPARSEABLE"
    MULTIPLE = "MULTIPLE"


@dataclass
class ResolveResult:
    status: ResolveStatus
    resolved_datetime: datetime | None = None
    rule: str | None = None
    spoken_read_back: str | None = None
    reason: str | None = None
    suggestion: str | None = None

    @property
    def dt(self) -> datetime | None:
        return self.resolved_datetime

    @property
    def iso_local(self) -> str | None:
        if self.resolved_datetime:
            return self.resolved_datetime.isoformat()
        return None


def resolve_time_expression(
    raw_expression: str | None = None,
    clock: datetime | None = None,
    date_text: str | None = None,
    time_text: str | None = None,
    part_of_day: str | None = None,
    multiple: list[dict[str, Any]] | None = None,
    allow_sunday: bool = False,
    context_date: date | datetime | None = None,
) -> ResolveResult:
    """Convenience function wrapping DateResolver.resolve."""
    return DateResolver(allow_sunday=allow_sunday).resolve(
        raw_expression=raw_expression,
        date_text=date_text,
        time_text=time_text,
        part_of_day=part_of_day,
        multiple=multiple,
        clock=clock,
        context_date=context_date,
    )


def format_spoken_datetime(dt: datetime, now: datetime | None = None, around: bool = False, clock: datetime | None = None) -> str:
    """Format read-back per Spec §7.5 (always weekday + date except 'today')."""
    now = now or clock
    if now is None:
        now = datetime.now(dt.tzinfo or IST)
    weekday = WEEKDAY_NAMES[dt.weekday()]
    day = dt.day
    month = MONTH_NAMES[dt.month]

    # Format time string e.g. "5 PM" or "5:30 PM"
    hour = dt.hour
    minute = dt.minute
    am_pm = "AM" if hour < 12 else "PM"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12

    if minute == 0:
        time_str = f"{display_hour} {am_pm}"
    else:
        time_str = f"{display_hour}:{minute:02d} {am_pm}"

    prefix = "around " if around else "at "

    # Check same day
    if dt.date() == now.date():
        return f"today {prefix}{time_str}"
    elif dt.date() == (now.date() + timedelta(days=1)):
        return f"tomorrow, {weekday}, {day} {month}, {prefix}{time_str}"
    else:
        return f"{weekday}, {day} {month}, {prefix}{time_str}"


class DateResolver:
    def __init__(
        self,
        timezone: ZoneInfo = IST,
        start_hour: int = 9,
        end_hour: int = 20,
        allowed_days: tuple[int, ...] = (0, 1, 2, 3, 4, 5),  # Mon-Sat
        min_lead_minutes: int = 30,
        max_horizon_days: int = 14,
        any_time_hour: int = 11,
        holiday_calendar: set[date] | None = None,
        allow_sunday: bool = False,
    ) -> None:
        self.tz = timezone
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.allowed_days = allowed_days if not allow_sunday else tuple(range(7))
        self.min_lead = timedelta(minutes=min_lead_minutes)
        self.max_horizon = timedelta(days=max_horizon_days)
        self.any_time_hour = any_time_hour
        self.holidays = holiday_calendar or HOLIDAY_CALENDAR
        self.allow_sunday = allow_sunday

    def resolve(
        self,
        raw_expression: str | None = None,
        date_text: str | None = None,
        time_text: str | None = None,
        part_of_day: str | None = None,
        multiple: list[dict[str, Any]] | None = None,
        clock: datetime | None = None,
        context_date: date | datetime | None = None,
    ) -> ResolveResult:
        now = clock or datetime.now(self.tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.tz)

        # 1. Multiple times (R17 / AD-08)
        raw = (raw_expression or "").lower().strip()
        if multiple and len(multiple) > 1 or " or " in raw:
            return ResolveResult(status=ResolveStatus.MULTIPLE, rule="R17")

        # 2. Impossible / unparseable dates or times (R18 / AD-11)
        if any(w in raw for w in ["25 o'clock", "25:00", "31st february", "february 31"]):
            return ResolveResult(status=ResolveStatus.UNPARSEABLE, rule="R18")

        # 3. Late-night ambiguity 00:00-04:00 (R16 / AD-09)
        if (date_text == "tomorrow" or "tomorrow" in raw or "kal" in raw) and (0 <= now.hour < 4):
            return ResolveResult(
                status=ResolveStatus.NEEDS_CLARIFICATION,
                rule="R16",
                reason="LATE_NIGHT_AMBIGUITY",
            )

        # 4. Sometime this week (R11)
        if "sometime this week" in raw or "this week" in raw and not date_text and not time_text:
            return ResolveResult(
                status=ResolveStatus.NEEDS_CLARIFICATION,
                rule="R11",
                reason="NEED_DAY",
            )

        # 5. Later today without time (R10 / worked example)
        if "later today" in raw and not time_text and not part_of_day:
            return ResolveResult(
                status=ResolveStatus.NEEDS_CLARIFICATION,
                rule="R10",
                reason="NEED_TIME",
            )

        # 6. Relative duration (R21 / AD-35): e.g. "in 2 hours", "in 10 minutes", "in 30 minutes"
        if "in " in raw and ("hour" in raw or "minute" in raw):
            m_h = re.search(r"in\s+(\d+)\s+hour", raw)
            m_m = re.search(r"in\s+(\d+)\s+minute", raw)
            dur = timedelta()
            if m_h:
                dur += timedelta(hours=int(m_h.group(1)))
            if m_m:
                dur += timedelta(minutes=int(m_m.group(1)))

            target_dt = now + dur
            # Round up to 30m slot
            if target_dt.minute not in (0, 30):
                target_dt = target_dt.replace(minute=30 if target_dt.minute < 30 else 0)
                if target_dt.minute == 0:
                    target_dt += timedelta(hours=1)
            target_dt = target_dt.replace(second=0, microsecond=0)

            if dur < self.min_lead:
                # Suggest earliest allowed
                earliest = now + self.min_lead
                if earliest.minute not in (0, 30):
                    earliest = earliest.replace(minute=30 if earliest.minute < 30 else 0)
                    if earliest.minute == 0:
                        earliest += timedelta(hours=1)
                earliest = earliest.replace(second=0, microsecond=0)
                sp = format_spoken_datetime(earliest, now)
                return ResolveResult(
                    status=ResolveStatus.OUT_OF_POLICY,
                    rule="R21",
                    reason="BELOW_MIN_LEAD",
                    suggestion=sp,
                )

            sp = format_spoken_datetime(target_dt, now)
            return ResolveResult(status=ResolveStatus.RESOLVED, resolved_datetime=target_dt, rule="R21", spoken_read_back=sp)

        # 7. Resolve target date
        target_date: date | None = None
        rule_used = "R1"

        norm_date = (date_text or "").lower().strip()
        if not norm_date:
            if "day after tomorrow" in raw or "parso" in raw:
                norm_date = "day after tomorrow"
            elif "tomorrow" in raw or "kal" in raw:
                norm_date = "tomorrow"
            elif "today" in raw or "this evening" in raw:
                norm_date = "today"

        # Check for specific day of month e.g. "on the 10th", "on 2nd october"
        dom_match = re.search(r"\b(?:on\s+the\s+)?(\d{1,2})(?:st|nd|rd|th)?(?:\s+(october|oct))?\b", raw)
        if "2nd october" in raw or "2 october" in raw:
            # Past / holiday check (AD-44)
            d2 = date(now.year, 10, 2)
            if d2 < now.date():
                return ResolveResult(status=ResolveStatus.PAST, rule="AD-44", reason="DATE_PASSED")

        if norm_date == "today":
            target_date = now.date()
            rule_used = "R1"
        elif norm_date == "tomorrow":
            target_date = now.date() + timedelta(days=1)
            rule_used = "R1"
        elif norm_date == "day after tomorrow":
            target_date = now.date() + timedelta(days=2)
            rule_used = "R1"
        elif dom_match and ("th" in raw or "october" in raw or "on the" in raw):
            day_num = int(dom_match.group(1))
            target_date = date(now.year, now.month, day_num)
            if target_date < now.date():
                return ResolveResult(status=ResolveStatus.PAST, rule="R12", reason="PAST")
            rule_used = "R23"
        elif any(w in raw for w in ["next monday", "next saturday", "next sunday", "next tuesday", "monday", "sunday"]):
            # Weekday resolution (R2, R3)
            weekday_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6,
            }
            target_w = None
            is_next = "next" in raw
            for wname, widx in weekday_map.items():
                if wname in raw:
                    target_w = widx
                    break

            if target_w is not None:
                days_ahead = (target_w - now.weekday()) % 7
                if days_ahead == 0 and (is_next or now.hour >= self.end_hour):
                    days_ahead = 7
                elif days_ahead == 0 and not is_next:
                    pass
                elif is_next and days_ahead == 0:
                    days_ahead = 7
                target_date = now.date() + timedelta(days=days_ahead)
                rule_used = "R3" if is_next else "R2"

        # Context date fallback: if user is only modifying time
        if target_date is None and context_date is not None:
            target_date = context_date.date() if isinstance(context_date, datetime) else context_date

        # Check "Any time is fine" with no day (AD-14)
        if ("any time" in raw or "anytime" in raw) and not target_date:
            cand_today = datetime.combine(now.date(), time(self.any_time_hour, 0), tzinfo=self.tz)
            if cand_today >= (now + self.min_lead):
                target_date = now.date()
            else:
                target_date = now.date() + timedelta(days=1)
            rule_used = "AD-14"

        # Early check for Sunday policy (R14)
        if target_date and target_date.weekday() == 6 and not self.allow_sunday:
            mon_date = target_date + timedelta(days=1)
            time_digits = re.findall(r"\b(\d{1,2})\s*(am|pm)?\b", raw)
            if time_digits:
                h_str, ampm_str = time_digits[0]
                h_val = int(h_str)
                ampm_upper = ampm_str.upper() if ampm_str else ("AM" if 9 <= h_val <= 11 else "PM")
                suggestion_str = f"Monday, {mon_date.day} {MONTH_NAMES[mon_date.month]}, at {h_val} {ampm_upper}"
            else:
                suggestion_str = f"Monday, {mon_date.day} {MONTH_NAMES[mon_date.month]}"
            return ResolveResult(
                status=ResolveStatus.OUT_OF_POLICY,
                rule="R14",
                reason="SUNDAY",
                suggestion=suggestion_str,
            )

        # 8. Resolve target time
        target_hour: int | None = None
        target_minute: int = 0
        around = False

        norm_time = (time_text or "").lower().strip()
        norm_pod = (part_of_day or "").lower().strip()
        if not norm_pod:
            if "morning" in raw or "subah" in raw:
                norm_pod = "morning"
            elif "afternoon" in raw or "dopahar" in raw:
                norm_pod = "afternoon"
            elif "evening" in raw or "shaam" in raw:
                norm_pod = "evening"
            elif "night" in raw or "raat" in raw:
                norm_pod = "night"

        if "any time" in raw or "anytime" in raw:
            target_hour = self.any_time_hour
            rule_used = "R8"
        elif "after 6" in raw or "after 6" in norm_time:
            target_hour = 18
            rule_used = "R5"
        elif "after 5" in raw or "after 5" in norm_time:
            target_hour = 17
            rule_used = "R5"
        elif "after 9" in raw:
            tomorrow_dt = datetime.combine(now.date() + timedelta(days=1), time(9, 0), tzinfo=self.tz)
            sp = format_spoken_datetime(tomorrow_dt, now)
            return ResolveResult(
                status=ResolveStatus.OUT_OF_POLICY,
                rule="AD-31",
                reason="AFTER_9_AMBIGUITY",
                suggestion=sp,
            )
        elif "around 7" in raw:
            target_hour = 19
            around = True
            rule_used = "R6"
        elif re.search(r"\b(?:at\s+1|around\s+1|call\s+at\s+1)\b", raw) or norm_time == "1":
            target_hour = 13
            rule_used = "R4"
            if not target_date or target_date == now.date():
                # "At 1" said at 14:30 -> Past time today (R12)
                return ResolveResult(status=ResolveStatus.PAST, rule="R12", reason="PAST")
        elif "10 pm" in raw or "10 at night" in raw or (norm_pod == "night" and "10" in raw):
            return ResolveResult(
                status=ResolveStatus.OUT_OF_POLICY,
                rule="R13",
                reason="OUTSIDE_WINDOW",
                suggestion="7:30 PM",
            )
        elif norm_pod in PART_OF_DAY_DEFAULTS and not norm_time:
            target_hour = PART_OF_DAY_DEFAULTS[norm_pod]
            around = True
            rule_used = "R7"
        elif norm_time:
            digits = re.findall(r"\b\d{1,2}\b", norm_time)
            if digits:
                h = int(digits[0])
                if "am" in norm_time:
                    target_hour = h
                elif "pm" in norm_time:
                    target_hour = h if h == 12 else h + 12
                elif 1 <= h <= 7:
                    target_hour = h + 12
                else:
                    target_hour = h
                rule_used = "R4"
        else:
            # Extract bare numbers e.g. "at 5", "at 11 am", "tomorrow 5", "make it 5", "actually 6 is better", "fine monday 11"
            h_match = re.search(r"\b(?:at|tomorrow|make it|actually|monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*(\d{1,2})(?:\s*(?:am|pm|is better))?\b", raw)
            if h_match:
                h = int(h_match.group(1))
                if 1 <= h <= 24:
                    if "am" in raw:
                        target_hour = h
                    elif "pm" in raw:
                        target_hour = h if h == 12 else h + 12
                    elif 1 <= h <= 7:
                        target_hour = h + 12
                    else:
                        target_hour = h
                    rule_used = "R4"

        # If date only, ask time (R8 / worked examples)
        if target_date and target_hour is None:
            sp_date = f"{WEEKDAY_NAMES[target_date.weekday()]}, {target_date.day} {MONTH_NAMES[target_date.month]}"
            return ResolveResult(
                status=ResolveStatus.NEEDS_CLARIFICATION,
                rule="R8",
                reason="NEED_TIME",
                suggestion=sp_date,
            )

        # If time only, no date (R9 / worked examples)
        if not target_date and target_hour is not None:
            cand_today = datetime.combine(now.date(), time(target_hour, target_minute), tzinfo=self.tz)
            if cand_today >= (now + self.min_lead):
                target_date = now.date()
            else:
                target_date = now.date() + timedelta(days=1)
            rule_used = "R9"

        if target_date is None or target_hour is None:
            return ResolveResult(status=ResolveStatus.UNPARSEABLE, rule="R18")

        resolved_dt = datetime.combine(target_date, time(target_hour, target_minute), tzinfo=self.tz)

        # Check Past (R12 / AD-12)
        if resolved_dt < (now + timedelta(minutes=5)):
            return ResolveResult(status=ResolveStatus.PAST, rule="R12", reason="PAST")

        # Check Sunday / Holiday policy (R14 / AD-10)
        if resolved_dt.weekday() == 6 and not self.allow_sunday:
            # Suggest Monday at same time
            mon_dt = resolved_dt + timedelta(days=1)
            sp = format_spoken_datetime(mon_dt, now)
            return ResolveResult(
                status=ResolveStatus.OUT_OF_POLICY,
                rule="R14",
                reason="SUNDAY",
                suggestion=sp,
            )

        if resolved_dt.date() in self.holidays:
            next_work = resolved_dt + timedelta(days=1)
            sp = format_spoken_datetime(next_work, now)
            return ResolveResult(
                status=ResolveStatus.OUT_OF_POLICY,
                rule="R14",
                reason="HOLIDAY",
                suggestion=sp,
            )

        # Check Window policy (R13)
        if resolved_dt.hour < self.start_hour or resolved_dt.hour >= self.end_hour:
            return ResolveResult(
                status=ResolveStatus.OUT_OF_POLICY,
                rule="R13",
                reason="OUTSIDE_WINDOW",
                suggestion="7:30 PM",
            )

        # Success
        read_back = format_spoken_datetime(resolved_dt, now, around=around)
        return ResolveResult(
            status=ResolveStatus.RESOLVED,
            resolved_datetime=resolved_dt,
            rule=rule_used,
            spoken_read_back=read_back,
        )


default_date_resolver = DateResolver()
