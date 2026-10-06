"""Human-approved demo knowledge set for Subbu and Town Bank."""

from kural.knowledge.script_store import default_script_store

APP_VERSION = "5.0.0 (demo)"
BANK_NAME = "Town Bank"
ASSISTANT_NAME = "Subbu"

DISCLOSURE = default_script_store.get_line("S-OPEN-01n")
UPDATE_INSTRUCTIONS = default_script_store.get_line("S-UPD-01")
SUPPORT_WORDING = default_script_store.get_line("S-HUMAN-01")
CALLBACK_ACKNOWLEDGEMENT = "Done — we'll arrange a callback and call you tomorrow at your preferred time."
OPT_OUT_ACKNOWLEDGEMENT = default_script_store.get_line("S-OPTOUT-01") + " " + default_script_store.get_line("S-OPTOUT-END")

