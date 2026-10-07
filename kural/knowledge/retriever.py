"""Deterministic lexical retrieval for approved Town Bank knowledge.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. Retrieval is strictly lexical/token-based (Deterministic Lexical Retrieval).
2. Closed-world knowledge grounding: Answers are retrieved only from approved
   corpus articles. If sufficient evidence is unavailable, it returns None.
3. Sub-millisecond execution overhead (< 1 ms) to preserve real-time voice latency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from kural.knowledge.kb import (
    KnowledgeArticle,
    KnowledgeSource,
    get_active_knowledge_base,
)


@dataclass(frozen=True)
class KnowledgeResult:
    article_id: str
    topic: str
    title: str
    content: str
    confidence: float
    is_demo: bool
    source: KnowledgeSource


MIN_RETRIEVAL_CONFIDENCE = 0.40


STOP_WORDS = {
    "what", "whats", "what's", "is", "the", "of", "your", "to", "a", "an", "in", "on",
    "for", "are", "am", "do", "does", "did", "can", "could", "would", "should", "it",
    "this", "that", "you", "me", "my", "i", "we", "our", "app", "allow", "or", "and", "there",
    "tell", "about", "give", "please", "with", "any"
}


def _tokenize(text: str) -> set[str]:
    """Tokenize and normalize text into alphanumeric words."""
    cleaned = re.sub(r"[^\w\s]", " ", text.casefold())
    return {w for w in cleaned.split() if len(w) > 1}


def _salient_tokens(text: str) -> set[str]:
    return _tokenize(text) - STOP_WORDS


class DeterministicLexicalRetriever:
    """Fast in-memory deterministic lexical retriever with exact and salient keyword scoring."""

    def __init__(self, corpus: Sequence[KnowledgeArticle] | None = None) -> None:
        self._corpus = list(corpus) if corpus is not None else get_active_knowledge_base()

    def retrieve(self, query: str) -> KnowledgeResult | None:
        """Find the highest scoring approved knowledge article or return None if ungrounded."""
        q_norm = query.casefold().strip()
        if not q_norm:
            return None

        q_tokens = _tokenize(q_norm)
        q_salient = _salient_tokens(q_norm)
        if not q_tokens:
            return None

        best_article: KnowledgeArticle | None = None
        best_score = 0.0

        for article in self._corpus:
            score = 0.0

            # 1. Exact phrase match in keywords with word boundaries
            for kw in article.keywords:
                kw_norm = kw.casefold().strip()
                if kw_norm == q_norm or (
                    len(kw_norm) >= 4 and re.search(rf"(?<!\w){re.escape(kw_norm)}(?!\w)", q_norm)
                ):
                    score = max(score, 1.0)
                else:
                    kw_salient = _salient_tokens(kw_norm)
                    if kw_salient and q_salient:
                        inter = q_salient & kw_salient
                        if inter:
                            union = q_salient | kw_salient
                            jaccard = len(inter) / len(union)
                            score = max(score, jaccard * 0.70)

            # 2. Check title overlap with salient tokens
            title_salient = _salient_tokens(article.title)
            if title_salient and q_salient:
                inter = q_salient & title_salient
                if inter:
                    union = q_salient | title_salient
                    title_jaccard = len(inter) / len(union)
                    score = max(score, title_jaccard * 0.60)

            if score > best_score:
                best_score = score
                best_article = article

        if best_article and best_score >= MIN_RETRIEVAL_CONFIDENCE:
            return KnowledgeResult(
                article_id=best_article.id,
                topic=best_article.topic,
                title=best_article.title,
                content=best_article.content,
                confidence=round(best_score, 3),
                is_demo=best_article.is_demo,
                source=best_article.source,
            )

        return None


# Global singleton instance for high-speed local usage
default_retriever = DeterministicLexicalRetriever()
