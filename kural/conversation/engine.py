"""Deterministic KURAL FSM backed by domain-level repository transactions."""

from datetime import datetime
import logging
from collections.abc import Callable
from uuid import uuid4

from kural.conversation.intents import MIN_INTENT_CONFIDENCE, detect_identity_interruption, detect_intent
from kural.conversation.session import Conversation
from kural.gateway.mock_bank import MockBankGateway
from kural.knowledge import approved
from kural.models import Action, Intent, State, TurnResponse
from kural.policy.safety import authorize, inspect_input
from kural.privacy.transcript import safe_transcript
from kural.repositories import KuralRepository, RepositoryTransaction
from kural.providers.config import create_llm_provider
from kural.providers.contracts import LLMProvider
from kural.providers.schemas import IntentProposal


TERMINAL_STATES = {State.OPT_OUT, State.FRAUD_ESCALATION, State.HUMAN_ESCALATION, State.ENDED}
logger = logging.getLogger(__name__)
ALLOWED_TRANSITIONS: dict[State, set[State]] = {
    State.DISCLOSURE: {State.IDENTITY_CHECK, State.CLOSING, State.ENDED},
    State.IDENTITY_CHECK: {State.PERMISSION, State.CALLBACK_BOOKING, State.CLOSING, State.ENDED},
    State.PERMISSION: {State.APP_STATUS, State.CALLBACK_BOOKING, State.CLOSING, State.ENDED},
    State.APP_STATUS: {State.UPDATE_HELP, State.CLOSING, State.ENDED},
    State.UPDATE_HELP: {State.ISSUE_CAPTURE, State.CLOSING, State.ENDED},
    State.ISSUE_CAPTURE: {State.CASE_CREATION, State.CLOSING, State.ENDED},
    State.CASE_CREATION: {State.ENDED},
    State.CALLBACK_BOOKING: {State.ENDED},
    State.HUMAN_ESCALATION: set(),
    State.OPT_OUT: set(),
    State.FRAUD_ESCALATION: set(),
    State.CLOSING: {State.ENDED},
    State.ENDED: set(),
}


class InvalidTransitionError(RuntimeError):
    """Raised when a decision attempts a transition outside the FSM."""


class KuralEngine:
    def __init__(self, repository: KuralRepository, gateway: MockBankGateway | None = None,
                 *, llm_provider: LLMProvider | None = None) -> None:
        self.repository = repository
        self.gateway = gateway or MockBankGateway()
        self.llm_provider = llm_provider or create_llm_provider()
        self._session_sensitive_counts: dict[str, int] = {}

    def create_session(self, customer_ref: str = "demo-001") -> tuple[Conversation, str]:
        # Reject non-fixture customer references before a session can be persisted.
        self.gateway.get_customer(customer_ref, {"customer_ref"})
        session_id = str(uuid4())
        with self.repository.transaction() as tx:
            conversation = tx.create_session(session_id, customer_ref, State.DISCLOSURE)
            tx.add_audit_event(session_id, "session_start", State.DISCLOSURE, {})
        return conversation, approved.DISCLOSURE

    @staticmethod
    def opening_message(name: str = "Rahul") -> str:
        """Return the approved live-call disclosure and identity question."""
        return f"Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with {name}?"

    def begin_live_call(self, session_id: str) -> None:
        """Record the live call's spoken identity prompt as the IDENTITY_CHECK state."""
        with self.repository.transaction() as tx:
            conversation = tx.get_session(session_id)
            if conversation is None:
                raise KeyError("Session not found")
            if conversation.state == State.DISCLOSURE:
                self._transition(tx, conversation, State.IDENTITY_CHECK)

    def turn(self, session_id: str, text: str, confidence: float = 1.0,
             requested_at: datetime | None = None,
             on_timing: Callable[[str], None] | None = None) -> TurnResponse:
        with self.repository.transaction() as tx:
            conversation = tx.get_session(session_id)
            if conversation is None:
                raise KeyError("Session not found")
            if conversation.state in TERMINAL_STATES:
                return self._response(conversation, Intent.OTHER, "This session has ended. Goodbye.")

            import re
            safety = inspect_input(text)
            sanitized_text = safe_transcript(text)
            warning_prefix = ""

            if safety.blocked:
                # Sensitive authentication pattern detected: warn and continue (Spec §8.1)
                count = self._session_sensitive_counts.get(session_id, 0) + 1
                self._session_sensitive_counts[session_id] = count
                self._record_event(
                    tx, conversation, "security_event",
                    {"type": "SENSITIVE_DATA", "subtype": safety.sensitive_types, "state": conversation.state.value}
                )
                if count == 1:
                    warning_prefix = "Please don't share your OTP, PIN, password or CVV with me — Town Bank will never ask for those on a call."
                elif count == 2:
                    warning_prefix = "Just a reminder — no codes or passwords needed for this."
                else:
                    warning_prefix = (
                        "Just a reminder — no codes or passwords needed for this. "
                        "If you've shared a code or PIN with anyone, it's a good idea to change it through the official app or by calling the number on your card."
                    )

                # Check if customer utterance was ONLY the sensitive credentials
                clean_remainder = re.sub(
                    r"\[REDACTED_[A-Z]+\]|\[BLOCKED SENSITIVE AUTHENTICATION DATA\]", "", sanitized_text, flags=re.I
                )
                clean_remainder = re.sub(
                    r"\b(?:my|the|is|was|it'?s|otp|pin|password|cvv|code|number|here|got|an|and)\b",
                    "", clean_remainder, flags=re.I
                ).strip(" ,.-;:!?")

                if not clean_remainder:
                    # Pure sensitive data: warn + continue + re-ask current state's question
                    intent = Intent.SENSITIVE_DATA
                    response = f"{warning_prefix} That's okay, we can carry on. {self._state_prompt(conversation.state)}"
                    self._record_event(tx, conversation, "customer_turn", {"text": sanitized_text})
                    self._record_event(tx, conversation, "intent_detected", {"intent": intent.value})
                    self._record_event(tx, conversation, "policy_decision", {"decision": "blocked", "reason": safety.reason})
                    outcome = "IN_PROGRESS"
                    self._record_turn(tx, conversation, sanitized_text, intent, response, outcome)
                    return self._response(conversation, intent, response, "BLOCKED", sanitized_text)

            identity_interruption = (
                detect_identity_interruption(sanitized_text, confidence)
                if conversation.state == State.IDENTITY_CHECK else None
            )
            intent = identity_interruption or self._understand_intent(
                sanitized_text, text, confidence, on_timing,
            )
            self._record_event(tx, conversation, "customer_turn", {"text": sanitized_text})
            self._record_event(tx, conversation, "intent_detected", {"intent": intent.value})
            response, target_state, actions = self._decide(conversation, intent)
            if warning_prefix:
                response = f"{warning_prefix} {response}"

            if not all(authorize(action, conversation.state, target_state) for action in actions):
                self._record_event(tx, conversation, "policy_decision", {"decision": "denied", "actions": [a.value for a in actions]})
                response, target_state, actions = (
                    "I’m unable to safely continue this request. Please contact the bank through its official support channel.",
                    State.ENDED,
                    (Action.END_SESSION,),
                )
            else:
                for action in actions:
                    self._record_event(tx, conversation, "policy_decision", {"decision": "allowed", "action": action.value})

            self._transition(tx, conversation, target_state)
            for action in actions:
                self._execute_action(tx, conversation, action, requested_at)
            if target_state in {State.CLOSING, State.CASE_CREATION} or (
                target_state == State.CALLBACK_BOOKING and Action.REQUEST_CALLBACK in actions
            ):
                self._transition(tx, conversation, State.ENDED)

            outcome = "ENDED" if conversation.state in TERMINAL_STATES else "IN_PROGRESS"
            self._record_turn(tx, conversation, sanitized_text, intent, response, outcome)
            if conversation.state in TERMINAL_STATES:
                self._record_event(tx, conversation, "call_ending", {"reason": intent.value})
            policy_dec = "BLOCKED" if safety.blocked else "ALLOWED"
            return self._response(conversation, intent, response, policy_dec, sanitized_text)

    def _understand_intent(self, sanitized_text: str, original_text: str,
                           input_confidence: float,
                           on_timing: Callable[[str], None] | None = None) -> Intent:
        provider_name = self.llm_provider.provider_name
        model_name = self.llm_provider.model_name
        try:
            if on_timing:
                on_timing("gemini_request_start")
            raw_proposal = self.llm_provider.classify(sanitized_text)
            if on_timing:
                on_timing("gemini_response_start")
            proposal = IntentProposal.model_validate(raw_proposal)
            if input_confidence < MIN_INTENT_CONFIDENCE or proposal.confidence < MIN_INTENT_CONFIDENCE:
                intent = Intent.LOW_CONFIDENCE
            else:
                intent = proposal.intent
            logger.info(
                "Intent proposal provider=%s model=%s intent=%s confidence=%.3f fallback=false",
                provider_name, model_name, intent.value, proposal.confidence,
            )
            return intent
        except Exception as error:
            # Do not log exception text or user content: SDK errors may include request data.
            intent = detect_intent(original_text, input_confidence)
            logger.warning(
                "Intent fallback provider=%s model=%s intent=%s confidence=%.3f fallback=true error_type=%s",
                provider_name, model_name, intent.value, input_confidence, type(error).__name__,
            )
            return intent

    @staticmethod
    def _response(conversation: Conversation, intent: Intent, response: str,
                  policy_decision: str = "ALLOWED", sanitized_user_text: str = "") -> TurnResponse:
        return TurnResponse(
            session_id=conversation.session_id, state=conversation.state, intent=intent,
            response=response, ended=conversation.state in TERMINAL_STATES,
            case_id=conversation.case_id, callback_id=conversation.callback_id,
            policy_decision=policy_decision,
            sanitized_user_text=sanitized_user_text,
        )

    @staticmethod
    def _record_turn(tx: RepositoryTransaction, conversation: Conversation, text: str,
                     intent: Intent, response: str, outcome: str) -> None:
        conversation.turn_order += 1
        tx.add_turn(conversation.session_id, conversation.turn_order, text, intent.value,
                    conversation.state, response, outcome)

    @staticmethod
    def _record_event(tx: RepositoryTransaction, conversation: Conversation, event_type: str,
                      metadata: dict[str, object]) -> None:
        tx.add_audit_event(conversation.session_id, event_type, conversation.state, metadata)

    @staticmethod
    def _transition(tx: RepositoryTransaction, conversation: Conversation, target: State) -> None:
        current = conversation.state
        if target == current:
            return
        allowed = ALLOWED_TRANSITIONS[current]
        is_global_escalation = target in {State.OPT_OUT, State.FRAUD_ESCALATION, State.HUMAN_ESCALATION}
        if target not in allowed and not is_global_escalation:
            raise InvalidTransitionError(f"Transition {current.value} -> {target.value} is not allowed")
        conversation.state = target
        tx.update_state(conversation.session_id, target)
        tx.add_audit_event(conversation.session_id, "state_transition", target,
                           {"old": current.value, "new": target.value})

    @staticmethod
    def _execute_action(tx: RepositoryTransaction, conversation: Conversation,
                        action: Action, requested_at: datetime | None) -> None:
        if action == Action.CREATE_APP_UPDATE_CASE:
            case = tx.create_case(conversation.session_id, conversation.customer_ref,
                                  "APP_UPDATE_FAILURE", "Customer reported an app update failure.", "OPEN")
            conversation.case_id = case.case_id
            tx.add_audit_event(conversation.session_id, "case_creation", conversation.state,
                               {"case_id": case.case_id, "category": case.category})
        elif action == Action.REQUEST_CALLBACK:
            callback = tx.request_callback(conversation.session_id, conversation.case_id, requested_at)
            conversation.callback_id = callback.callback_id
            tx.add_audit_event(conversation.session_id, "callback_request", conversation.state,
                               {"callback_id": callback.callback_id, "case_id": callback.case_id})

    def _decide(self, c: Conversation, intent: Intent) -> tuple[str, State, tuple[Action, ...]]:
        global_responses = {
            Intent.FRAUD_REPORT: ("I’m treating this as a potential fraud concern. I cannot make a fraud determination. Please end this call and contact the bank through its official app or the number on your card.", State.FRAUD_ESCALATION),
            Intent.OPT_OUT: (approved.OPT_OUT_ACKNOWLEDGEMENT, State.OPT_OUT),
            Intent.WANTS_HUMAN: (approved.SUPPORT_WORDING + " Goodbye.", State.HUMAN_ESCALATION),
            Intent.ASKS_IF_AI: ("Yes, I’m Subbu, an automated assistant from Town Bank. " + self._state_prompt(c.state), c.state),
            Intent.ASKS_IDENTITY: ("I'm Subbu, Town Bank's automated assistant. Am I speaking with Rahul?", c.state),
            Intent.TRUST_CONCERN: ("It's a genuine Town Bank service call, and I'll never ask for your PIN, OTP or password. If you'd prefer, you can hang up and call the number on the back of your card.", c.state),
            Intent.OUT_OF_SCOPE: ("I can only help with the demo mobile-app update call. I cannot access balances, statements, or transactions. Goodbye.", State.CLOSING),
            Intent.LANGUAGE_SWITCH: ("This prototype currently supports English only. I can arrange human support. Goodbye.", State.HUMAN_ESCALATION),
            Intent.ABUSE: ("I’ll end this call now. Goodbye.", State.CLOSING),
            Intent.LOW_CONFIDENCE: ("I didn’t catch that clearly. Could you repeat your answer?", c.state),
            Intent.SILENCE: ("I didn’t hear a response. Please say a short reply, or ask for human support.", c.state),
        }
        if intent in global_responses:
            response, target = global_responses[intent]
            action = Action.NO_OP if target == c.state else Action.END_SESSION
            return response, target, (action,)

        if c.state == State.DISCLOSURE:
            return "Am I speaking with the intended customer? Please answer yes or no. I won’t ask for an OTP or password.", State.IDENTITY_CHECK, (Action.NO_OP,)
        if c.state == State.IDENTITY_CHECK:
            if intent == Intent.AFFIRM:
                return "Thank you. Is now a convenient time to discuss the mobile app update?", State.PERMISSION, (Action.NO_OP,)
            if intent in (Intent.BUSY, Intent.CALLBACK):
                return approved.CALLBACK_ACKNOWLEDGEMENT, State.CALLBACK_BOOKING, (Action.REQUEST_CALLBACK,)
            return "I can’t confirm the intended person, so I’ll end the call. Goodbye.", State.ENDED, (Action.END_SESSION,)
        if c.state == State.PERMISSION:
            if intent == Intent.BUSY:
                return "No problem. Would you like a callback?", State.CALLBACK_BOOKING, (Action.NO_OP,)
            if intent == Intent.CALLBACK:
                return approved.CALLBACK_ACKNOWLEDGEMENT, State.CALLBACK_BOOKING, (Action.REQUEST_CALLBACK,)
            if intent == Intent.AFFIRM:
                return "Is the demo bank app installed on your device?", State.APP_STATUS, (Action.NO_OP,)
            return "Understood. I’ll end the call. Goodbye.", State.CLOSING, (Action.END_SESSION,)
        if c.state == State.CALLBACK_BOOKING:
            if intent in (Intent.AFFIRM, Intent.CALLBACK, Intent.BUSY):
                return approved.CALLBACK_ACKNOWLEDGEMENT, State.ENDED, (Action.REQUEST_CALLBACK,)
            return "Understood. You can contact the bank through its official support channel. Goodbye.", State.ENDED, (Action.END_SESSION,)
        if c.state == State.APP_STATUS:
            if intent in (Intent.APP_INSTALLED, Intent.AFFIRM):
                return f"The demo app’s current version is {approved.APP_VERSION}. {approved.UPDATE_INSTRUCTIONS}", State.UPDATE_HELP, (Action.NO_OP,)
            if intent in (Intent.APP_NOT_INSTALLED, Intent.NEGATE):
                return "Thank you. You can install the app from your device’s official app store. I’ll end the call. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            return "Please tell me whether the app is installed, or ask for human support.", c.state, (Action.NO_OP,)
        if c.state == State.UPDATE_HELP:
            if intent in (Intent.UPDATE_SUCCESS, Intent.AFFIRM):
                return "Great. Thank you for updating the demo app. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            if intent in (Intent.UPDATE_FAILURE, Intent.APP_UPDATE_ISSUE):
                return "I’m sorry the update did not work. Would you like human app support to follow up?", State.ISSUE_CAPTURE, (Action.NO_OP,)
            return "Please let me know if the update worked or if you had a problem.", c.state, (Action.NO_OP,)
        if c.state == State.ISSUE_CAPTURE:
            if intent in (Intent.AFFIRM, Intent.CALLBACK, Intent.UPDATE_FAILURE, Intent.APP_UPDATE_ISSUE, Intent.WANTS_HUMAN):
                return "The prototype created an app-update support case and recorded a callback request. It does not place a real call. Goodbye.", State.CASE_CREATION, (Action.CREATE_APP_UPDATE_CASE, Action.REQUEST_CALLBACK)
            return "Would you like me to request human follow-up for the update problem?", c.state, (Action.NO_OP,)
        return "This session has ended. Goodbye.", State.ENDED, (Action.END_SESSION,)

    @staticmethod
    def _state_prompt(state: State) -> str:
        return {
            State.DISCLOSURE: "Hi, this is Subbu, Town Bank's automated assistant. Am I speaking with Rahul?",
            State.IDENTITY_CHECK: "Am I speaking with Rahul?",
            State.PERMISSION: "Is now a convenient time to talk?",
            State.APP_STATUS: "Is the Town Bank app installed on your phone?",
            State.UPDATE_HELP: approved.UPDATE_INSTRUCTIONS,
            State.CALLBACK_BOOKING: "When would be a good time to call you back?",
        }.get(state, "How can I help with the Town Bank app update?")
