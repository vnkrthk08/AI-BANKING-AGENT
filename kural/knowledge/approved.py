"""Human-approved demo knowledge set for Subbu and Town Bank."""

from kural.knowledge.script_store import default_script_store

APP_VERSION = "5.0.0 (demo)"
BANK_NAME = "Town Bank"
ASSISTANT_NAME = "Subbu"

DISCLOSURE = default_script_store.get_line("S-OPEN-01n")
UPDATE_INSTRUCTIONS = default_script_store.get_line("S-UPD-01")
SUPPORT_WORDING = default_script_store.get_line("S-HUMAN-01")
CALLBACK_ACKNOWLEDGEMENT = (
    "I've recorded your callback request. A Town Bank colleague will contact you during working hours "
    "to agree a convenient time. Goodbye."
)
CALLBACK_SCHEDULED_TEMPLATE = "I've scheduled your callback for {when}. You'll see it confirmed by the bank. Goodbye."
HUMAN_HANDOFF = (
    "I can't connect you to a colleague on this call, so I've raised a support request for you. "
    "Someone from our support team will call you back during working hours. Goodbye."
)
ISSUE_CASE_CREATED = (
    "I'm sorry about the trouble. I've raised a support case for the update problem, and our app support "
    "team will call you back during working hours. Goodbye."
)
OPT_OUT_ACKNOWLEDGEMENT = default_script_store.get_line("S-OPTOUT-01") + " " + default_script_store.get_line("S-OPTOUT-END")

from kural.knowledge.kb import DEMO_KNOWLEDGE_BASE, PRODUCTION_KNOWLEDGE_BASE, KnowledgeArticle, KnowledgeSource
from kural.knowledge.retriever import DeterministicLexicalRetriever, KnowledgeResult, default_retriever

