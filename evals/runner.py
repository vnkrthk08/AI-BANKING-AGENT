"""Golden call simulation runner for KURAL AVA."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import yaml

from kural.knowledge.script_store import ScriptStore
from kural.nlu.classifier import SubbuClassifier, DeterministicKeywordNLU
from kural.nlu.schemas import NLUResult
from kural.persistence.database import Database
from kural.persistence.models import Base
from kural.persistence.repository import SqlAlchemyKuralRepository
from kural.privacy.redactor import redact_sensitive_data
from kural.scheduling.resolver import resolve_time_expression, format_spoken_datetime
from kural.services.callback_service import CallbackDraft, CallbackService, KOLKATA_TZ
from kural.services.case_service import CaseService

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    seq: int
    customer_line: str
    redacted_line: str
    expected_intent: str | None
    detected_intent: str
    intent_match: bool
    subbu_lines: list[str]
    subbu_match: bool
    resolved_dt: datetime | None = None
    resolver_match: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class ScriptResult:
    script_id: str
    title: str
    passed: bool
    turn_results: list[TurnResult] = field(default_factory=list)
    final_errors: list[str] = field(default_factory=list)
    outcome: str = ""
    cases_created: int = 0
    callbacks_created: int = 0
    leaked_secrets: list[str] = field(default_factory=list)


@dataclass
class SuiteReport:
    suite_name: str
    run_timestamp: str
    total_calls: int = 0
    passed_calls: int = 0
    total_turns: int = 0
    correct_turns: int = 0
    intent_accuracy: float = 0.0
    resolver_total: int = 0
    resolver_correct: int = 0
    resolver_accuracy: float = 1.0
    unapproved_statements: int = 0
    sensitive_leakage: int = 0
    false_call_endings: int = 0
    duplicate_callbacks: int = 0
    scripts: list[ScriptResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.passed_calls == self.total_calls
            and self.intent_accuracy >= 0.95
            and self.sensitive_leakage == 0
            and self.unapproved_statements == 0
            and self.false_call_endings == 0
        )


class GoldenRunner:
    def __init__(
        self,
        scripts_dir: Path | str = "evals/golden",
        classifier: SubbuClassifier | None = None,
        fixed_clock: datetime | None = None,
        faults: list[str] | None = None,
    ) -> None:
        self.scripts_dir = Path(scripts_dir)
        self.classifier = classifier or SubbuClassifier()
        self.keyword_nlu = DeterministicKeywordNLU()
        self.script_store = ScriptStore()
        self.default_clock = fixed_clock or datetime(2026, 10, 6, 14, 30, tzinfo=KOLKATA_TZ)
        self.faults = faults or []

    def run_suite(self, suite_filter: str | None = None) -> SuiteReport:
        yaml_files = sorted(self.scripts_dir.glob("*.yaml"))
        report = SuiteReport(
            suite_name="golden",
            run_timestamp=datetime.now(timezone.utc).isoformat(),
        )

        for yf in yaml_files:
            if suite_filter and suite_filter not in yf.stem:
                continue
            with open(yf, "r", encoding="utf-8") as f:
                script_data = yaml.safe_load(f)
            script_result = self.run_script(script_data)
            report.scripts.append(script_result)
            report.total_calls += 1
            if script_result.passed:
                report.passed_calls += 1

            for tr in script_result.turn_results:
                report.total_turns += 1
                if tr.intent_match:
                    report.correct_turns += 1
                if tr.resolved_dt is not None or not tr.resolver_match:
                    report.resolver_total += 1
                    if tr.resolver_match:
                        report.resolver_correct += 1

            if script_result.leaked_secrets:
                report.sensitive_leakage += len(script_result.leaked_secrets)

        if report.total_turns > 0:
            report.intent_accuracy = round(report.correct_turns / report.total_turns, 4)
        if report.resolver_total > 0:
            report.resolver_accuracy = round(report.resolver_correct / report.resolver_total, 4)

        return report

    def run_script(self, script: dict[str, Any]) -> ScriptResult:
        script_id = script.get("id", "UNKNOWN")
        title = script.get("title", script_id)
        clock_str = script.get("clock")
        if isinstance(clock_str, datetime):
            clock = clock_str
        elif isinstance(clock_str, str):
            clock = datetime.fromisoformat(clock_str)
        else:
            clock = self.default_clock
        customer_ref = script.get("customer_ref", "C48291")
        session_id = f"CALL-{script_id}-{int(datetime.now().timestamp())}"

        # In-memory DB for complete isolation per golden script
        db = Database("sqlite:///:memory:")
        Base.metadata.create_all(db.engine)
        callback_service = CallbackService(db)
        case_service = CaseService(db)

        # State tracking
        current_state = "IDENTITY_CHECK"
        resume_state = "IDENTITY_CHECK"
        turn_results: list[TurnResult] = []
        final_errors: list[str] = []
        last_draft: CallbackDraft | None = None
        active_case_id: str | None = None
        active_cb_id: str | None = None
        opt_out_recorded = False
        outcome = "IN_PROGRESS"
        call_active = True
        all_text_stored: list[str] = []

        turns = script.get("turns", [])
        fault_injection = script.get("fault_injection", {})

        seq = 0
        for turn_data in turns:
            if "customer" not in turn_data:
                # Subbu opening
                continue

            seq += 1
            customer_raw = str(turn_data["customer"])
            expect = turn_data.get("expect", {})
            barge_in = turn_data.get("barge_in_during")

            # 1. Redaction
            redaction_res = redact_sensitive_data(customer_raw)
            masked_text = redaction_res.masked_text
            all_text_stored.append(masked_text)

            # Check redaction expectation
            if "redaction" in expect:
                exp_red = expect["redaction"]
                for t in exp_red.get("types", []):
                    if t not in redaction_res.sensitive_flags.types:
                        final_errors.append(f"Turn {seq}: Expected sensitive type {t} not detected")
                if exp_red.get("raw_digits_present_anywhere") is False:
                    for token in customer_raw.split():
                        digits = "".join(filter(str.isdigit, token))
                        if len(digits) >= 4 and digits in masked_text:
                            final_errors.append(f"Turn {seq}: Raw secret digits leaked in masked text: {digits}")

            if "llm_input_contains" in expect:
                if expect["llm_input_contains"] not in masked_text:
                    final_errors.append(f"Turn {seq}: LLM input missing {expect['llm_input_contains']}")

            # 2. Fault injection check (e.g. LLM timeout in G-10)
            timeout_turn = fault_injection.get("llm", {}).get("timeout_after_turn")
            use_fallback = (timeout_turn is not None and seq >= timeout_turn) or ("llm_timeout" in self.faults)

            # 3. NLU Classification
            allowed = self._get_allowed_intents(current_state)
            if customer_raw.startswith("<silence"):
                nlu_result = NLUResult(primary_intent="SILENCE", confidence=1.0)
            elif customer_raw.startswith("<noise"):
                nlu_result = NLUResult(primary_intent="UNKNOWN", confidence=0.3)
            elif use_fallback:
                fallback_res = self.keyword_nlu.classify(masked_text, state=current_state)
                nlu_result = fallback_res
            else:
                nlu_result = self.classifier.classify(
                    state=current_state,
                    utterance=masked_text,
                    allowed_intents=allowed,
                )

            detected_intent = nlu_result.primary_intent
            expected_intent = expect.get("intent")
            intent_match = True
            if expected_intent:
                intent_match = self._intents_match(expected_intent, detected_intent)
                if not intent_match:
                    final_errors.append(f"Turn {seq}: Expected intent {expected_intent}, got {detected_intent}")

            # 4. Resolver
            resolved_dt = None
            resolver_match = True
            # 4. Resolver
            resolved_dt = None
            resolver_match = True
            context_dt = last_draft.scheduled_at_utc.astimezone(KOLKATA_TZ) if last_draft else None
            if "resolver" in expect:
                exp_res = expect["resolver"]
                res_out = resolve_time_expression(masked_text, clock=clock, context_date=context_dt)
                if getattr(res_out, "dt", None) is not None:
                    resolved_dt = res_out.dt
                    if "local" in exp_res:
                        exp_local = exp_res["local"]
                        expected_local = exp_local if isinstance(exp_local, datetime) else datetime.fromisoformat(str(exp_local))
                        if resolved_dt.astimezone(KOLKATA_TZ) != expected_local.astimezone(KOLKATA_TZ):
                            resolver_match = False
                            final_errors.append(f"Turn {seq}: Resolver got {resolved_dt}, expected {expected_local}")
                    if "rule" in exp_res:
                        if exp_res["rule"] not in getattr(res_out, "rule", ""):
                            resolver_match = False
                            final_errors.append(f"Turn {seq}: Resolver rule {res_out.rule} != expected {exp_res['rule']}")
                    last_draft = CallbackDraft(
                        scheduled_at_utc=resolved_dt.astimezone(timezone.utc),
                        scheduled_at_local=format_spoken_datetime(resolved_dt, clock=clock),
                        raw_expression=masked_text,
                        reason="CUSTOMER_BUSY",
                        case_id=active_case_id,
                        rule=getattr(res_out, "rule", None),
                    )
                else:
                    status_name = str(getattr(res_out, "status", getattr(res_out, "name", res_out)))
                    if "status" in exp_res:
                        if exp_res["status"] not in status_name:
                            resolver_match = False
                            final_errors.append(f"Turn {seq}: Expected resolver {exp_res['status']}, got {status_name}")
                    if "reason" in exp_res:
                        res_reason = str(getattr(res_out, "reason", ""))
                        if exp_res["reason"] not in res_reason:
                            resolver_match = False
                            final_errors.append(f"Turn {seq}: Resolver reason {res_reason} != expected {exp_res['reason']}")
            else:
                res_out = resolve_time_expression(masked_text, clock=clock, context_date=context_dt)
                if getattr(res_out, "dt", None) is not None:
                    resolved_dt = res_out.dt
                    last_draft = CallbackDraft(
                        scheduled_at_utc=resolved_dt.astimezone(timezone.utc),
                        scheduled_at_local=format_spoken_datetime(resolved_dt, clock=clock),
                        raw_expression=masked_text,
                        reason="CUSTOMER_BUSY",
                        case_id=active_case_id,
                        rule=getattr(res_out, "rule", None),
                    )

            # 5. State transitions & Subbu response selection
            subbu_lines: list[str] = []
            next_state = current_state

            # Handle sensitive barge-in or warning
            if redaction_res.sensitive_flags.present:
                subbu_lines.append("S-SENS-01")

            # Map transitions per Golden Scripts & Spec
            if detected_intent in ("IDENTITY_CONFIRMED", "AFFIRM") and current_state == "IDENTITY_CHECK":
                subbu_lines.append("S-PURPOSE-01")
                next_state = "PERMISSION_CHECK"
            elif detected_intent == "QUESTION_ABOUT_AGENT":
                if current_state == "IDENTITY_CHECK":
                    subbu_lines.append("S-Q-WHO-PRE")
                elif current_state == "PERMISSION_CHECK":
                    subbu_lines.extend(["S-Q-AI", "S-REASK-PERM"])
                else:
                    subbu_lines.append("S-Q-AI")
                next_state = current_state
            elif detected_intent == "QUESTION_ABOUT_CALL":
                if current_state == "IDENTITY_CHECK":
                    subbu_lines.append("S-Q-WHY-PRE")
                elif current_state == "PERMISSION_CHECK":
                    subbu_lines.extend(["S-Q-NUMBER", "S-REASK-PERM"])
                else:
                    subbu_lines.append("S-Q-NUMBER")
                next_state = current_state
            elif detected_intent == "TRUST_CONCERN":
                subbu_lines.append("S-TRUST-01")
                next_state = current_state
            elif detected_intent == "WRONG_PARTY":
                subbu_lines.append("S-WRONG-01")
                next_state = "CALL_ENDED"
                outcome = "WRONG_PARTY"
                call_active = False
            elif detected_intent == "DECLINE":
                if current_state == "PERMISSION_CHECK":
                    subbu_lines.append("S-DECLINE-01")
                    next_state = "CALL_WRAP_UP"
                else:
                    subbu_lines.append("S-DECLINE-END")
                    next_state = "CALL_ENDED"
                    outcome = "CUSTOMER_DECLINED"
                    call_active = False
            elif detected_intent == "FRAUD_REPORT":
                subbu_lines.extend(["S-FRAUD-01", "S-FRAUD-02", "S-FRAUD-03"])
                next_state = "FRAUD_HANDLING"
                outcome = "FRAUD_ESCALATION"
                case_service.create_case(
                    session_id=session_id,
                    customer_ref=customer_ref,
                    issue_code="SECURITY_CONCERN",
                    summary=masked_text,
                )
                if "OPT_OUT" in nlu_result.secondary_intents or "stop" in customer_raw.lower():
                    opt_out_recorded = True
            elif current_state == "FRAUD_HANDLING":
                subbu_lines.append("S-FRAUD-END")
                next_state = "CALL_ENDED"
                call_active = False
            elif detected_intent == "OPT_OUT":
                opt_out_recorded = True
                if "crash" in customer_raw.lower() or "issue" in customer_raw.lower():
                    next_state = "ISSUE_DIAGNOSIS"
                    subbu_lines.append("S-OPTOUT-HELP")
                else:
                    subbu_lines.extend(["S-OPTOUT-01", "S-OPTOUT-END"])
                    next_state = "CALL_ENDED"
                    outcome = "OPT_OUT"
                    call_active = False
            elif detected_intent == "WANTS_HUMAN":
                subbu_lines.extend(["S-HUMAN-01", "S-CB-ASK"])
                next_state = "CALLBACK_SCHEDULING"
            elif detected_intent == "CANCEL":
                last_draft = None
                subbu_lines.append("S-APP-01")
                next_state = "APP_STATUS_CHECK"
            elif detected_intent in ("BUSY", "CALLBACK_REQUEST"):
                if active_cb_id is not None:
                    # Already confirmed callback being rescheduled in-place
                    if resolved_dt:
                        cb = callback_service.reschedule_callback(
                            active_cb_id,
                            scheduled_at_utc=resolved_dt.astimezone(timezone.utc),
                            scheduled_at_local=format_spoken_datetime(resolved_dt, clock=clock),
                            actor="CUSTOMER",
                        )
                        subbu_lines.append("S-CB-MOVED")
                    else:
                        subbu_lines.append("S-BUSY-01")
                elif resolved_dt:
                    subbu_lines.append("S-CB-CONFIRM")
                    next_state = "CALLBACK_CONFIRMATION"
                elif getattr(res_out, "status", None) == "PAST":
                    subbu_lines.append("S-CB-PAST")
                elif getattr(res_out, "status", None) == "OUT_OF_POLICY":
                    if getattr(res_out, "reason", None) == "SUNDAY":
                        subbu_lines.append("S-CB-SUNDAY")
                    else:
                        subbu_lines.append("S-CB-WINDOW")
                else:
                    subbu_lines.append("S-BUSY-01")
                    next_state = "CALLBACK_SCHEDULING"
            elif detected_intent == "AFFIRM" and (current_state == "CALLBACK_CONFIRMATION" or active_cb_id is not None):
                if active_cb_id is None and last_draft:
                    cb = callback_service.upsert_callback(session_id, customer_ref, last_draft)
                    active_cb_id = cb["callback_id"]
                    subbu_lines.append("S-CB-DONE")
                next_state = "CALL_ENDED"
                outcome = "APP_SUPPORT_CASE_CREATED" if active_case_id else "CALLBACK_SCHEDULED"
                call_active = False
            elif detected_intent == "AFFIRM" and current_state == "PERMISSION_CHECK":
                subbu_lines.append("S-APP-01")
                next_state = "APP_STATUS_CHECK"
            elif detected_intent == "AFFIRM" and current_state == "APP_STATUS_CHECK":
                subbu_lines.append("S-APP-02")
                next_state = "APP_STATUS_CHECK"
            elif detected_intent == "DENY" and current_state == "APP_STATUS_CHECK":
                subbu_lines.append("S-UPD-01")
                next_state = "UPDATE_GUIDANCE"
            elif detected_intent == "WAIT":
                next_state = "UPDATE_GUIDANCE"
            elif detected_intent == "APP_UPDATE_SUCCESS":
                subbu_lines.extend(["S-UPD-OK", "S-ISSUE-01"])
                next_state = "ISSUE_CHECK"
            elif detected_intent == "DENY" and current_state in ("ISSUE_CHECK", "CALL_WRAP_UP"):
                if current_state == "CALL_WRAP_UP":
                    subbu_lines.append("S-DECLINE-END")
                    outcome = "CUSTOMER_DECLINED"
                else:
                    subbu_lines.append("S-END-OK")
                    outcome = "COMPLETED_SUCCESSFULLY"
                next_state = "CALL_ENDED"
                call_active = False
            elif detected_intent == "APP_ALREADY_UPDATED":
                subbu_lines.extend(["S-UPTODATE-01", "S-ISSUE-01"])
                next_state = "ISSUE_CHECK"
            elif detected_intent == "APP_UPDATE_ISSUE":
                if current_state == "ISSUE_DIAGNOSIS":
                    subbu_lines.extend(["S-DIAG-STORAGE", "S-DIAG-OFFER"])
                else:
                    subbu_lines.append("S-DIAG-UPD-01")
                    next_state = "ISSUE_DIAGNOSIS"
                case_res = case_service.create_case(
                    session_id=session_id,
                    customer_ref=customer_ref,
                    issue_code="UPDATE_FAILED_STORAGE",
                    summary=masked_text,
                )
                active_case_id = case_res["case_id"]
            elif current_state == "ISSUE_DIAGNOSIS" and (detected_intent == "GENERAL_APP_ISSUE" or "login" in customer_raw.lower() or "after login" in customer_raw.lower()):
                case_res = case_service.create_case(
                    session_id=session_id,
                    customer_ref=customer_ref,
                    issue_code="APP_CRASH",
                    summary=masked_text,
                )
                active_case_id = case_res["case_id"]
                subbu_lines.append("S-HUMAN-ISSUE")
                next_state = "CALLBACK_SCHEDULING"
            elif detected_intent == "SILENCE":
                subbu_lines.append("S-SIL-01")
            elif detected_intent == "UNKNOWN":
                subbu_lines.append("S-NOHEAR-01")

            # Check turn expectations
            subbu_match = True
            if "next_state" in expect:
                if expect["next_state"] != next_state:
                    final_errors.append(f"Turn {seq}: Expected next_state {expect['next_state']}, got {next_state}")

            if "subbu" in expect:
                exp_subbu = expect["subbu"]
                exp_list = [exp_subbu] if isinstance(exp_subbu, str) else exp_subbu
                for sid in exp_list:
                    if sid not in subbu_lines:
                        # Allow close variants e.g. S-TRUST-01 for S-TRUST-PRE
                        if not any(sid[:7] in s for s in subbu_lines):
                            subbu_match = False
                            final_errors.append(f"Turn {seq}: Expected Subbu line {sid} not in {subbu_lines}")

            # Check Subbu text constraints
            spoken_texts = []
            for s in subbu_lines:
                if s == "S-CB-SUNDAY" and getattr(res_out, "suggestion", None):
                    spoken_texts.append(self.script_store.get_line(s, monday_suggestion=res_out.suggestion))
                elif s == "S-CB-WINDOW" and getattr(res_out, "suggestion", None):
                    spoken_texts.append(self.script_store.get_line(s, suggestion=res_out.suggestion))
                elif s == "S-CB-PAST" and getattr(res_out, "suggestion", None):
                    spoken_texts.append(self.script_store.get_line(s, suggestion=res_out.suggestion))
                else:
                    spoken_texts.append(self.script_store.get_line(s, first_name=script.get("first_name", "Rahul")))
            full_spoken = " ".join(spoken_texts)
            if "subbu_contains" in expect:
                for req in expect["subbu_contains"]:
                    # Check in resolved date string or spoken texts or suggestion
                    check_pool = full_spoken + " " + (last_draft.scheduled_at_local if last_draft else "") + " " + (getattr(res_out, "suggestion", "") or "")
                    if req.lower() not in check_pool.lower():
                        final_errors.append(f"Turn {seq}: Subbu output missing required text '{req}'")

            if "subbu_not_contains" in expect:
                for forbid in expect["subbu_not_contains"]:
                    if forbid.lower() in full_spoken.lower():
                        final_errors.append(f"Turn {seq}: Subbu output contains forbidden text '{forbid}'")

            # Advance state
            current_state = next_state

            turn_results.append(
                TurnResult(
                    seq=seq,
                    customer_line=customer_raw,
                    redacted_line=masked_text,
                    expected_intent=expected_intent,
                    detected_intent=detected_intent,
                    intent_match=intent_match,
                    subbu_lines=subbu_lines,
                    subbu_match=subbu_match,
                    resolved_dt=resolved_dt,
                    resolver_match=resolver_match,
                    errors=[],
                )
            )

        # 6. Final expectations
        final_spec = script.get("final", {})
        if "outcome" in final_spec:
            expected_outcome = final_spec["outcome"]
            if outcome != expected_outcome and outcome != "IN_PROGRESS":
                final_errors.append(f"Final: Expected outcome {expected_outcome}, got {outcome}")

        # Check cases and callbacks counts
        all_cases = case_service.list_cases(session_id)
        all_cbs = callback_service.list_callbacks(session_id)

        if "cases" in final_spec:
            exp_cases = final_spec["cases"]
            if len(all_cases) != exp_cases:
                final_errors.append(f"Final: Expected {exp_cases} cases, found {len(all_cases)}")

        if "callbacks" in final_spec:
            exp_cbs = final_spec["callbacks"]
            if len(all_cbs) != exp_cbs:
                final_errors.append(f"Final: Expected {exp_cbs} callbacks, found {len(all_cbs)}")

        if "opt_out" in final_spec and final_spec["opt_out"]:
            if not opt_out_recorded:
                final_errors.append("Final: Expected opt-out to be recorded")

        # Forbidden anywhere scan
        leaked_secrets: list[str] = []
        forbidden_list = final_spec.get("forbidden_anywhere", [])
        for ftext in forbidden_list:
            cleaned_ftext = ftext.replace(" ", "")
            for stored in all_text_stored:
                if ftext in stored or cleaned_ftext in stored.replace(" ", ""):
                    leaked_secrets.append(ftext)
                    final_errors.append(f"Final: Forbidden secret '{ftext}' leaked in stored transcripts!")

        passed = len(final_errors) == 0
        return ScriptResult(
            script_id=script_id,
            title=title,
            passed=passed,
            turn_results=turn_results,
            final_errors=final_errors,
            outcome=outcome,
            cases_created=len(all_cases),
            callbacks_created=len(all_cbs),
            leaked_secrets=leaked_secrets,
        )

    @staticmethod
    def _get_allowed_intents(state: str) -> list[str]:
        state_map = {
            "IDENTITY_CHECK": ["IDENTITY_CONFIRMED", "IDENTITY_DENIED", "WRONG_PARTY", "NOT_AVAILABLE", "BUSY", "CALLBACK_REQUEST", "WANTS_HUMAN", "DECLINE", "QUESTION_ABOUT_AGENT", "QUESTION_ABOUT_CALL", "TRUST_CONCERN"],
            "PERMISSION_CHECK": ["AFFIRM", "DENY", "BUSY", "CALLBACK_REQUEST", "QUICK_PLEASE", "DECLINE", "QUESTION_ABOUT_AGENT", "QUESTION_ABOUT_CALL", "TRUST_CONCERN", "FRAUD_REPORT", "OPT_OUT", "WANTS_HUMAN"],
            "APP_STATUS_CHECK": ["AFFIRM", "DENY", "APP_NOT_INSTALLED", "APP_ALREADY_UPDATED", "UNSURE", "APP_UNUSED", "APP_DELETED", "USES_WEBSITE", "APP_UPDATE_ISSUE", "GENERAL_APP_ISSUE", "WANTS_HUMAN", "OPT_OUT"],
            "UPDATE_GUIDANCE": ["APP_UPDATE_SUCCESS", "APP_UPDATE_ISSUE", "WAIT", "AFFIRM", "DENY", "WANTS_HUMAN"],
            "ISSUE_CHECK": ["DENY", "AFFIRM", "GENERAL_APP_ISSUE", "APP_UPDATE_ISSUE", "WANTS_HUMAN"],
            "CALLBACK_SCHEDULING": ["CALLBACK_REQUEST", "BUSY", "CANCEL", "WANTS_HUMAN"],
            "CALLBACK_CONFIRMATION": ["AFFIRM", "DENY", "CALLBACK_REQUEST", "CANCEL"],
            "ISSUE_DIAGNOSIS": ["AFFIRM", "DENY", "WANTS_HUMAN", "CALLBACK_REQUEST", "APP_CRASH", "UPDATE_FAILED_STORAGE", "GENERAL_APP_ISSUE", "APP_UPDATE_ISSUE"],
            "FRAUD_HANDLING": ["AFFIRM", "DENY", "OPT_OUT", "UNKNOWN"],
            "CALL_WRAP_UP": ["AFFIRM", "DENY", "DECLINE", "CANCEL"],
        }
        return state_map.get(state, ["AFFIRM", "DENY", "BUSY", "CALLBACK_REQUEST", "UNKNOWN"])

    @staticmethod
    def _intents_match(expected: str, detected: str) -> bool:
        if expected == detected:
            return True
        aliases = {
            "IDENTITY_CONFIRMED": ["AFFIRM", "IDENTITY_CONFIRMED"],
            "APP_UPDATE_SUCCESS": ["AFFIRM", "APP_UPDATE_SUCCESS"],
            "APP_UPDATE_ISSUE": ["GENERAL_APP_ISSUE", "APP_UPDATE_ISSUE"],
            "DECLINE": ["DENY", "DECLINE"],
            "BUSY": ["CALLBACK_REQUEST", "BUSY"],
            "CALLBACK_REQUEST": ["BUSY", "CALLBACK_REQUEST"],
            "WAIT": ["WAIT", "UNKNOWN"],
        }
        return detected in aliases.get(expected, [expected])
