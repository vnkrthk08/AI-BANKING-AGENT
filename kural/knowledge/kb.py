"""Approved Knowledge Base for Town Bank Voice Assistant.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. DEMO_KNOWLEDGE_BASE is strictly isolated from PRODUCTION_KNOWLEDGE_BASE.
2. Demo articles are explicitly tagged `is_demo=True` and `source=KnowledgeSource.DEMO`.
3. Fictional demo data must NEVER present fictional claims (such as RBI compliance,
   encryption certifications, cashback, or promotional banking offers) as real-world
   regulatory facts.
4. Installation links policy: AVA may send only bank-approved official Google Play Store
   or Apple App Store links. AVA must NEVER send APK files or unofficial download links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os


class KnowledgeSource(StrEnum):
    DEMO = "DEMO"
    PRODUCTION = "PRODUCTION"


@dataclass(frozen=True)
class KnowledgeArticle:
    id: str
    topic: str
    title: str
    keywords: list[str]
    content: str
    is_demo: bool = True
    source: KnowledgeSource = KnowledgeSource.DEMO
    requires_human_escalation: bool = False


# ==============================================================================
# DEMO KNOWLEDGE BASE (Clearly isolated and labeled DEMO DATA)
# ==============================================================================

DEMO_KNOWLEDGE_BASE: list[KnowledgeArticle] = [
    KnowledgeArticle(
        id="KB-DEMO-01",
        topic="APP_PURPOSE",
        title="Application Purpose",
        keywords=["purpose", "what is this app", "why use it", "what is the app", "what is town bank app", "what can i use it for"],
        content=(
            "The Town Bank demo mobile app provides everyday digital banking, allowing you "
            "to check account balances, send instant UPI payments, and manage your debit card safely."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-02",
        topic="APP_FEATURES",
        title="Application Features",
        keywords=["features", "what does the app do", "what can it do", "app features", "capabilities", "functionality", "what does it do"],
        content=(
            "The demo app supports instant 24/7 UPI transfers, one-tap debit card lock and unlock, "
            "biometric login, fixed deposit creation, and digital account statement downloads."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-03",
        topic="LATEST_VERSION",
        title="Latest Version Information",
        keywords=["latest version", "current version", "version number", "app version", "which version", "what version"],
        content=(
            "The current release of the Town Bank demo app is version 5.0.0. "
            "It brings updated biometric security protections, UPI Lite for small instant transfers, and bug fixes."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-04",
        topic="WHATS_NEW",
        title="What's New in Version 5.0.0",
        keywords=["what's new", "whats new", "new features", "changes", "latest update", "new in this version", "new in latest"],
        content=(
            "Version 5.0.0 introduces improved biometric authentication stability, "
            "UPI Lite for payments without entering an MPIN each time, and an optional dark mode interface."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-05",
        topic="UPDATE_PROCESS",
        title="Update and Installation Guidelines",
        keywords=["how to update", "update process", "where to update", "download update", "install update", "how to install"],
        content=(
            "You can update the app directly through your device's official store — Google Play Store on Android "
            "or Apple App Store on iOS. Town Bank only provides official store links and never distributes APK files."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-06",
        topic="SECURITY_POLICY",
        title="Security & Confidentiality Standards",
        keywords=["is it safe", "is it secure", "security", "safe to use", "privacy", "safety", "trust"],
        content=(
            "The Town Bank demo app follows bank-grade security protocols. "
            "Subbu and Town Bank will never ask you for your PIN, MPIN, OTP, CVV, or passwords over any call."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-07",
        topic="UPDATE_COST",
        title="Cost and Charges",
        keywords=["is it free", "is this free", "any charge", "cost", "charges", "fees", "fee", "free of charge", "does it cost"],
        content=(
            "Yes, the Town Bank mobile app and all version updates are completely free of charge. "
            "There are no fees to install or update the app."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-08",
        topic="IDENTITY_ASSISTANT",
        title="Assistant Identity",
        keywords=["who are you", "who is this", "what is your name", "who am i speaking with", "who is speaking"],
        content=(
            "I'm Subbu, Town Bank's automated customer service assistant calling regarding your mobile app update."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-09",
        topic="AI_DISCLOSURE",
        title="AI Persona Disclosure",
        keywords=["are you ai", "are you an ai", "is this an ai", "are you a bot", "are you a robot", "automated assistant", "are you human"],
        content=(
            "Yes, I am Subbu, an automated AI assistant calling from Town Bank to guide you with the mobile app update."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-10",
        topic="TROUBLESHOOTING_GENERAL",
        title="General Troubleshooting",
        keywords=["troubleshoot", "app not opening", "keeps crashing", "white screen", "loading problem"],
        content=(
            "If the app does not open or keeps loading, try clearing the app cache in device settings or "
            "restarting your phone. If the problem persists, our human support team will gladly assist you."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
    KnowledgeArticle(
        id="KB-DEMO-11",
        topic="OFFICIAL_LINKS",
        title="Official Installation Links Policy",
        keywords=["send link", "installation link", "download link", "sms link", "app link", "official link"],
        content=(
            "AVA may send only bank-approved official Google Play Store or Apple App Store links. "
            "AVA will never send APK files or unofficial download links."
        ),
        is_demo=True,
        source=KnowledgeSource.DEMO,
    ),
]


# ==============================================================================
# PRODUCTION KNOWLEDGE BASE (Isolated placeholder for real banking integration)
# ==============================================================================

PRODUCTION_KNOWLEDGE_BASE: list[KnowledgeArticle] = [
    # Production articles will be provisioned by the verified bank CMS
]


def get_active_knowledge_base() -> list[KnowledgeArticle]:
    """Retrieve the active knowledge corpus based on environment configuration."""
    kb_mode = os.getenv("KNOWLEDGE_BASE_MODE", "DEMO").strip().upper()
    if kb_mode == "PRODUCTION":
        return PRODUCTION_KNOWLEDGE_BASE
    return DEMO_KNOWLEDGE_BASE
