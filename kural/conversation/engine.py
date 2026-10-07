"""Deterministic KURAL FSM backed by domain-level repository transactions."""

from datetime import datetime
import logging
from collections.abc import Callable
from uuid import uuid4

from kural.conversation.intents import (
    MIN_INTENT_CONFIDENCE,
    detect_identity_interruption,
    detect_intent,
    detect_issue_details,
    detect_side_question,
)
from kural.conversation.session import Conversation
from kural.gateway.mock_bank import MockBankGateway
from kural.knowledge import approved
from kural.knowledge.retriever import default_retriever
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
    State.PERMISSION: {State.APP_STATUS, State.UPDATE_HELP, State.CALLBACK_BOOKING, State.CLOSING, State.ENDED},
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
        self._session_repetition_counts: dict[str, int] = {}

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

            conversation.repetition_count = self._session_repetition_counts.get(session_id, 0)

            import re
            safety = inspect_input(text)
            sanitized_text = safe_transcript(text)
            warning_prefix = ""

            if safety.blocked:
                if safety.reason == "prompt_injection_attempt":
                    self._record_event(
                        tx, conversation, "security_event",
                        {"type": "PROMPT_INJECTION", "state": conversation.state.value}
                    )
                    intent = Intent.OTHER
                    response = f"I am Subbu, Town Bank's automated assistant. I can only assist you with our official mobile app update. Let's return to the update. {self._state_prompt(conversation.state)}"
                    self._record_event(tx, conversation, "customer_turn", {"text": sanitized_text})
                    self._record_event(tx, conversation, "intent_detected", {"intent": intent.value})
                    self._record_event(tx, conversation, "policy_decision", {"decision": "blocked", "reason": safety.reason})
                    outcome = "IN_PROGRESS"
                    self._record_turn(tx, conversation, sanitized_text, intent, response, outcome)
                    tx.update_session(conversation)
                    return self._response(conversation, intent, response, "BLOCKED", sanitized_text)

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
                    tx.update_session(conversation)
                    return self._response(conversation, intent, response, "BLOCKED", sanitized_text)

            identity_interruption = (
                detect_identity_interruption(sanitized_text, confidence)
                if conversation.state == State.IDENTITY_CHECK else None
            )
            if identity_interruption is not None:
                intent = identity_interruption
                proposal = None
                fallback_used = False
            else:
                intent, proposal, fallback_used = self._understand_intent(
                    sanitized_text, text, confidence, on_timing,
                )

            # Update known facts from extracted proposal entities and customer facts
            if proposal and proposal.entities:
                conversation.known_customer_facts.update(proposal.entities)
            if proposal and proposal.customer_facts:
                conversation.known_customer_facts.update(proposal.customer_facts)

            if conversation.state not in {State.DISCLOSURE, State.IDENTITY_CHECK}:
                if intent == Intent.APP_INSTALLED:
                    conversation.known_customer_facts["app_installed"] = True
                elif intent == Intent.APP_NOT_INSTALLED:
                    conversation.known_customer_facts["app_installed"] = False

            if intent in (Intent.UPDATE_FAILURE, Intent.APP_UPDATE_ISSUE) or (proposal and proposal.issue_present):
                has_issue, cat, desc = detect_issue_details(sanitized_text)
                final_cat = (proposal.issue_category if proposal and proposal.issue_category else cat) or "GENERAL"
                final_desc = (proposal.issue_description if proposal and proposal.issue_description else desc) or "app update issue"
                conversation.active_issue = {
                    "category": final_cat,
                    "description": final_desc,
                    "raw_quote": sanitized_text,
                    "human_assistance_required": proposal.human_assistance_required if proposal else True,
                }

            self._record_event(tx, conversation, "customer_turn", {"text": sanitized_text})
            self._record_event(tx, conversation, "intent_detected", {
                "intent": intent.value,
                "secondary_question": proposal.secondary_question if proposal else None,
                "fallback_used": fallback_used,
            })
            if conversation.known_customer_facts:
                self._record_event(tx, conversation, "customer_fact_captured", {"facts": dict(conversation.known_customer_facts)})
            if intent == Intent.OUT_OF_SCOPE:
                self._record_event(tx, conversation, "unsupported_intent_detected", {"intent": intent.value})

            prev_detour_depth = conversation.detour_depth
            response, target_state, actions = self._decide(conversation, intent, proposal, sanitized_text, tx=tx)
            if conversation.detour_depth > prev_detour_depth:
                self._record_event(tx, conversation, "detour_taken", {"topic": conversation.active_question, "depth": conversation.detour_depth})
            elif prev_detour_depth > 0 and conversation.detour_depth == 0:
                self._record_event(tx, conversation, "detour_returned", {"return_state": conversation.state.value})

            self._session_repetition_counts[session_id] = conversation.repetition_count
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
            tx.update_session(conversation)
            policy_dec = "BLOCKED" if safety.blocked else "ALLOWED"
            return self._response(
                conversation, intent, response, policy_dec, sanitized_text,
                secondary_question=proposal.secondary_question if proposal else None,
                entities=proposal.entities if proposal else {},
                fallback_used=fallback_used,
            )

    def _understand_intent(self, sanitized_text: str, original_text: str,
                           input_confidence: float,
                           on_timing: Callable[[str], None] | None = None) -> tuple[Intent, IntentProposal | None, bool]:
        provider_name = self.llm_provider.provider_name
        model_name = self.llm_provider.model_name
        try:
            if on_timing:
                on_timing("llm_request_start")
            raw_proposal = self.llm_provider.classify(sanitized_text)
            if on_timing:
                on_timing("llm_response_start")
            proposal = IntentProposal.model_validate(raw_proposal)
            if input_confidence < MIN_INTENT_CONFIDENCE or proposal.confidence < MIN_INTENT_CONFIDENCE:
                intent = Intent.LOW_CONFIDENCE
            else:
                intent = proposal.primary_intent
            logger.info(
                "Intent proposal provider=%s model=%s intent=%s confidence=%.3f secondary_q=%s fallback=false",
                provider_name, model_name, intent.value, proposal.confidence, proposal.secondary_question,
            )
            return intent, proposal, False
        except Exception as error:
            # Fallback must execute locally without blocking turn (Task 2 & User Correction 4)
            intent = detect_intent(original_text, input_confidence)
            side_q = detect_side_question(original_text)
            has_issue, cat, desc = detect_issue_details(original_text)
            if has_issue and intent in (Intent.OTHER, Intent.LOW_CONFIDENCE):
                intent = Intent.UPDATE_FAILURE
            customer_facts = {}
            if intent == Intent.APP_INSTALLED:
                customer_facts["app_installed"] = True
            elif intent == Intent.APP_NOT_INSTALLED:
                customer_facts["app_installed"] = False

            proposal = IntentProposal(
                primary_intent=intent,
                confidence=input_confidence,
                secondary_question=side_q,
                issue_present=has_issue,
                issue_category=cat,
                issue_description=desc,
                customer_facts=customer_facts,
            )
            logger.warning(
                "Intent fallback provider=%s model=%s intent=%s confidence=%.3f fallback=true error_type=%s",
                provider_name, model_name, intent.value, input_confidence, type(error).__name__,
            )
            return intent, proposal, True

    @staticmethod
    def _response(conversation: Conversation, intent: Intent, response: str,
                  policy_decision: str = "ALLOWED", sanitized_user_text: str = "",
                  secondary_question: str | None = None, entities: dict[str, object] | None = None,
                  fallback_used: bool = False) -> TurnResponse:
        return TurnResponse(
            session_id=conversation.session_id, state=conversation.state, intent=intent,
            response=response, ended=conversation.state in TERMINAL_STATES,
            case_id=conversation.case_id, callback_id=conversation.callback_id,
            policy_decision=policy_decision,
            sanitized_user_text=sanitized_user_text,
            secondary_question=secondary_question,
            entities=entities or {},
            fallback_used=fallback_used,
            detour_depth=conversation.detour_depth,
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
            category = "APP_UPDATE_FAILURE"
            description = "Customer reported an app update failure."
            if conversation.active_issue:
                cat = conversation.active_issue.get("category", category)
                category = "APP_UPDATE_FAILURE" if cat == "GENERAL" else cat
                raw_quote = conversation.active_issue.get("raw_quote", "")
                issue_desc = conversation.active_issue.get("description", description)
                description = f"{issue_desc} | Quote: '{raw_quote}'" if raw_quote else issue_desc
            case = tx.create_case(conversation.session_id, conversation.customer_ref,
                                  category, description, "OPEN")
            conversation.case_id = case.case_id
            tx.add_audit_event(conversation.session_id, "case_creation", conversation.state,
                               {"case_id": case.case_id, "category": case.category})
            tx.add_audit_event(conversation.session_id, "support_case_created", conversation.state,
                               {"case_id": case.case_id, "category": case.category})
        elif action == Action.REQUEST_CALLBACK:
            callback = tx.request_callback(conversation.session_id, conversation.case_id, requested_at)
            conversation.callback_id = callback.callback_id
            tx.add_audit_event(conversation.session_id, "callback_request", conversation.state,
                               {"callback_id": callback.callback_id, "case_id": callback.case_id})

    SIDE_QUESTION_ANSWERS: dict[str, str] = {
        "APP_FEATURES": "The Town Bank demo app lets you manage accounts, send instant UPI payments, and lock your debit card with one tap.",
        "IS_IT_SAFE": "The Town Bank demo app follows bank-grade security protocols, and we will never ask for your PIN, OTP or password.",
        "IS_IT_FREE": "Yes, the Town Bank mobile app and all version updates are completely free of charge.",
        "WHO_ARE_YOU": "I'm Subbu, Town Bank's automated assistant calling about our app update.",
        "WHY_CALLING": "I'm calling to make sure you have the latest and most secure version of the Town Bank app.",
        "WHAT_IS_NEW": "Version 5.0.0 brings updated biometric security protections, UPI Lite for small instant transfers, and bug fixes.",
    }

    def _decide(self, c: Conversation, intent: Intent, proposal: IntentProposal | None = None,
                user_text: str = "", tx: RepositoryTransaction | None = None) -> tuple[str, State, tuple[Action, ...]]:
        secondary_q = proposal.secondary_question if proposal else None
        if not secondary_q and user_text:
            secondary_q = detect_side_question(user_text)

        global_responses = {
            Intent.FRAUD_REPORT: ("I’m treating this as a potential fraud concern. I cannot make a fraud determination. Please end this call and contact the bank through its official app or the number on your card.", State.FRAUD_ESCALATION),
            Intent.OPT_OUT: (approved.OPT_OUT_ACKNOWLEDGEMENT, State.OPT_OUT),
            Intent.WANTS_HUMAN: (approved.SUPPORT_WORDING + " Goodbye.", State.HUMAN_ESCALATION),
            Intent.ASKS_IF_AI: ("Yes, I’m Subbu, an automated assistant from Town Bank. " + self._state_prompt(c.state), c.state),
            Intent.ASKS_IDENTITY: (
                ("I'm Subbu, Town Bank's automated assistant. Am I speaking with Rahul?"
                 if c.state in {State.DISCLOSURE, State.IDENTITY_CHECK}
                 else f"I'm Subbu, Town Bank's automated assistant calling about our app update. {self._state_prompt(c.state)}"),
                c.state,
            ),
            Intent.TRUST_CONCERN: ("It's a genuine Town Bank service call, and I'll never ask for your PIN, OTP or password. If you'd prefer, you can hang up and call the number on the back of your card.", c.state),
            Intent.OUT_OF_SCOPE: ("I can only assist you with our official mobile app update. For your security, account balances and financial transactions cannot be handled on this automated call. You can safely check your balance in the official Town Bank app or at your nearest branch. Goodbye.", State.CLOSING),
            Intent.LANGUAGE_SWITCH: ("This prototype currently supports English only. I can arrange human support. Goodbye.", State.HUMAN_ESCALATION),
            Intent.ABUSE: ("I’ll end this call now. Goodbye.", State.CLOSING),
            Intent.LOW_CONFIDENCE: ("I didn’t catch that clearly. Could you repeat your answer?", c.state),
            Intent.SILENCE: ("I didn’t hear a response. Please say a short reply, or ask for human support.", c.state),
        }
        if intent in global_responses:
            if intent in (Intent.LOW_CONFIDENCE, Intent.SILENCE):
                c.repetition_count += 1
                if c.repetition_count == 2:
                    return "I'm still having a little trouble hearing you. Would you like us to arrange a callback, or speak with human support?", State.CALLBACK_BOOKING, (Action.NO_OP,)
                elif c.repetition_count >= 3:
                    exit_state = State.ENDED if c.state == State.CALLBACK_BOOKING else State.CLOSING
                    return "I'm having trouble hearing you clearly today. I'll end the call for now so you're not inconvenienced. You can reach Town Bank anytime through the official app. Goodbye.", exit_state, (Action.END_SESSION,)
            else:
                c.repetition_count = 0
            response, target = global_responses[intent]
            action = Action.NO_OP if target == c.state else Action.END_SESSION
            return response, target, (action,)

        # Knowledge Grounding & Side-Question Detour Evaluation
        kb_result = None
        if user_text:
            kb_result = default_retriever.retrieve(user_text)
        if not kb_result and secondary_q:
            kb_result = default_retriever.retrieve(secondary_q)

        side_text = ""
        if kb_result:
            side_text = kb_result.content
            c.active_question = kb_result.topic
            if tx:
                self._record_event(tx, c, "knowledge_retrieval", {
                    "article_id": kb_result.article_id,
                    "topic": kb_result.topic,
                    "confidence": kb_result.confidence,
                })
            c.active_question = kb_result.topic
        elif secondary_q and secondary_q in self.SIDE_QUESTION_ANSWERS:
            side_text = self.SIDE_QUESTION_ANSWERS[secondary_q]
            c.active_question = secondary_q
        elif user_text and any(q in user_text.casefold() for q in ("?", "what", "how", "can i", "does it", "is there", "why", "crypto", "stocks", "loan")):
            # Closed-world knowledge grounding: If sufficient evidence is unavailable, do NOT invent an answer!
            side_text = "I don't have that specific information in my approved demo knowledge. The Town Bank app focuses on secure everyday banking and UPI payments."
            c.active_question = "UNKNOWN_QUESTION"

        # Check pure side-question detour turn
        if side_text and intent in (Intent.LOW_CONFIDENCE, Intent.OTHER, Intent.SILENCE):
            c.repetition_count = 0
            c.detour_depth += 1
            if not c.return_state:
                c.return_state = c.state

            return_target = c.return_state
            if c.known_customer_facts.get("app_installed") is True and return_target == State.APP_STATUS:
                return_target = State.UPDATE_HELP
                c.return_state = State.UPDATE_HELP

            if c.state == State.DISCLOSURE:
                return f"{side_text} Am I speaking with the intended customer? Please answer yes or no. I won’t ask for an OTP or password.", State.IDENTITY_CHECK, (Action.NO_OP,)

            if c.detour_depth >= 3:
                # Max detour depth limit: answer 3rd question and guide back to workflow!
                return (
                    f"{side_text} I'm happy to answer more questions, but first, to make sure your app is working properly, {self._state_prompt(return_target)}",
                    return_target,
                    (Action.NO_OP,)
                )

            return f"{side_text} {self._state_prompt(return_target)}", return_target, (Action.NO_OP,)

        side_prefix = f"{side_text} " if side_text else ""

        if c.state == State.DISCLOSURE:
            c.repetition_count = 0
            c.detour_depth = 0
            c.return_state = None
            return "Am I speaking with the intended customer? Please answer yes or no. I won’t ask for an OTP or password.", State.IDENTITY_CHECK, (Action.NO_OP,)

        if c.state == State.IDENTITY_CHECK:
            if intent == Intent.AFFIRM:
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return f"{side_prefix}Thank you. Is now a convenient time to discuss the mobile app update?", State.PERMISSION, (Action.NO_OP,)
            if intent in (Intent.BUSY, Intent.CALLBACK):
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return approved.CALLBACK_ACKNOWLEDGEMENT, State.CALLBACK_BOOKING, (Action.REQUEST_CALLBACK,)
            if intent == Intent.NEGATE:
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return "I can’t confirm the intended person, so I’ll end the call. Goodbye.", State.ENDED, (Action.END_SESSION,)
            c.repetition_count += 1
            if c.repetition_count == 2:
                return "I'm having trouble understanding. Would you like us to arrange a callback, or speak with human support?", State.CALLBACK_BOOKING, (Action.NO_OP,)
            elif c.repetition_count >= 3:
                return "I'm having trouble understanding. I'll end the call for now so you're not inconvenienced. You can reach Town Bank anytime through the official app. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            return "Could you please confirm if I am speaking with Rahul?", c.state, (Action.NO_OP,)

        if c.state == State.PERMISSION:
            if intent == Intent.BUSY:
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return "No problem. Would you like a callback?", State.CALLBACK_BOOKING, (Action.NO_OP,)
            if intent == Intent.CALLBACK:
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return approved.CALLBACK_ACKNOWLEDGEMENT, State.CALLBACK_BOOKING, (Action.REQUEST_CALLBACK,)
            if intent in (Intent.AFFIRM, Intent.APP_INSTALLED) or c.known_customer_facts.get("app_installed") is True:
                c.repetition_count = 0
                c.detour_depth = 0
                if c.known_customer_facts.get("app_installed") is True and (
                    intent == Intent.APP_INSTALLED or "installed" in user_text.lower() or "have" in user_text.lower()
                ):
                    c.return_state = State.UPDATE_HELP
                    return f"{side_prefix}The demo app’s current version is {approved.APP_VERSION}. {approved.UPDATE_INSTRUCTIONS}", State.UPDATE_HELP, (Action.NO_OP,)
                c.return_state = None
                return f"{side_prefix}Is the demo bank app installed on your device?", State.APP_STATUS, (Action.NO_OP,)
            if intent == Intent.NEGATE:
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return "Understood. I’ll end the call. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            c.repetition_count += 1
            if c.repetition_count == 2:
                return "I'm having trouble understanding. Would you like us to arrange a callback, or speak with human support?", State.CALLBACK_BOOKING, (Action.NO_OP,)
            elif c.repetition_count >= 3:
                return "I'm having trouble understanding. I'll end the call for now so you're not inconvenienced. You can reach Town Bank anytime through the official app. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            return "This call is regarding Town Bank's mobile app update. Is now a convenient time to speak, or would you prefer a callback?", c.state, (Action.NO_OP,)

        if c.state == State.CALLBACK_BOOKING:
            c.repetition_count = 0
            c.detour_depth = 0
            c.return_state = None
            if intent in (Intent.AFFIRM, Intent.CALLBACK, Intent.BUSY):
                return approved.CALLBACK_ACKNOWLEDGEMENT, State.ENDED, (Action.REQUEST_CALLBACK,)
            return "Understood. You can contact the bank through its official support channel. Goodbye.", State.ENDED, (Action.END_SESSION,)

        if c.state == State.APP_STATUS:
            if intent in (Intent.APP_INSTALLED, Intent.AFFIRM) or c.known_customer_facts.get("app_installed") is True:
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return f"{side_prefix}The demo app’s current version is {approved.APP_VERSION}. {approved.UPDATE_INSTRUCTIONS}", State.UPDATE_HELP, (Action.NO_OP,)
            if intent in (Intent.APP_NOT_INSTALLED, Intent.NEGATE):
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return "Thank you. You can install the app from your device’s official app store. I’ll end the call. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            c.repetition_count += 1
            if c.repetition_count == 2:
                return "I'm having trouble understanding. Would you like us to arrange a callback, or speak with human support?", State.CALLBACK_BOOKING, (Action.NO_OP,)
            elif c.repetition_count >= 3:
                return "I'm having trouble understanding. I'll end the call for now so you're not inconvenienced. You can reach Town Bank anytime through the official app. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            return "Please tell me whether the app is installed, or ask for human support.", c.state, (Action.NO_OP,)

        if c.state == State.UPDATE_HELP:
            if intent in (Intent.UPDATE_SUCCESS, Intent.AFFIRM):
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return f"{side_prefix}Great. Thank you for updating the demo app. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            if (
                intent in (Intent.UPDATE_FAILURE, Intent.APP_UPDATE_ISSUE)
                or (proposal and proposal.issue_present)
                or (c.active_issue is not None)
            ):
                c.repetition_count = 0
                c.detour_depth = 0
                c.return_state = None
                return "I’m sorry the update did not work. Would you like human app support to follow up?", State.ISSUE_CAPTURE, (Action.NO_OP,)
            c.repetition_count += 1
            if c.repetition_count == 2:
                return "I'm having trouble understanding. Would you like us to arrange a callback, or speak with human support?", State.CALLBACK_BOOKING, (Action.NO_OP,)
            elif c.repetition_count >= 3:
                return "I'm having trouble understanding. I'll end the call for now so you're not inconvenienced. You can reach Town Bank anytime through the official app. Goodbye.", State.CLOSING, (Action.END_SESSION,)
            return "Please let me know if the update worked or if you had a problem.", c.state, (Action.NO_OP,)

        if c.state == State.ISSUE_CAPTURE:
            c.repetition_count = 0
            c.detour_depth = 0
            c.return_state = None
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
