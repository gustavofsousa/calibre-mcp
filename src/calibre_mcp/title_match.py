"""Pure title/author matching for search-based enrichment (ENRICH-04, TSEARCH-02).

Scores Open Library search candidates against a book and picks the best one. No
I/O — the facade fetches candidates, this module only judges them. The rule is
deliberately deterministic string similarity, not an LLM (AD-006): the same
book and candidates always yield the same confidence, so a reviewer can
reproduce why a match was (or wasn't) proposed.

Only a ``high`` match may become a proposal (the facade enforces it). ``high``
needs BOTH the title and the author to agree: title-only agreement is exactly
how a different author's book with a similar title slips through.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .openlibrary_client import SearchCandidate

Confidence = Literal["high", "medium", "low"]

HIGH_TITLE_MIN = 0.90
HIGH_AUTHOR_MIN = 0.85
MEDIUM_TITLE_MIN = 0.60

_RANK: dict[Confidence, int] = {"high": 2, "medium": 1, "low": 0}
_SUBTITLE_START = re.compile(r"[:(]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class MatchScore:
    """How well one search candidate matches a book."""

    candidate: SearchCandidate
    title_similarity: float
    author_similarity: float | None
    confidence: Confidence


def normalize_title(text: str) -> str:
    """Accent-free, case-folded, subtitle-less, punctuation-free form of ``text``."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii").casefold()
    main_title = _SUBTITLE_START.split(ascii_only, maxsplit=1)[0]
    return " ".join(_NON_ALNUM.sub(" ", main_title).split())


def _normalize_name(name: str) -> str:
    # Token-sorted so "Bach, James" and "James Bach" compare equal.
    return " ".join(sorted(normalize_title(name).split()))


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _usable_author(author: str | None) -> str | None:
    if author is None or not author.strip() or author.strip() == "Unknown":
        return None
    return author


def classify(title_similarity: float, author_similarity: float | None) -> Confidence:
    """Map similarities to a confidence (thresholds per TSEARCH-02)."""
    if (
        author_similarity is not None
        and title_similarity >= HIGH_TITLE_MIN
        and author_similarity >= HIGH_AUTHOR_MIN
    ):
        return "high"
    if title_similarity >= MEDIUM_TITLE_MIN:
        return "medium"
    return "low"


def score(
    book_title: str, book_author: str | None, candidate: SearchCandidate
) -> MatchScore:
    """Score one candidate against the book's title and primary author."""
    title_similarity = _ratio(
        normalize_title(book_title), normalize_title(candidate.title)
    )
    author = _usable_author(book_author)
    author_similarity: float | None = None
    if author is not None:
        book_name = _normalize_name(author)
        author_similarity = max(
            (_ratio(book_name, _normalize_name(name)) for name in candidate.authors),
            default=0.0,
        )
    return MatchScore(
        candidate=candidate,
        title_similarity=title_similarity,
        author_similarity=author_similarity,
        confidence=classify(title_similarity, author_similarity),
    )


def pick_best(
    book_title: str, book_author: str | None, candidates: Sequence[SearchCandidate]
) -> MatchScore | None:
    """Best candidate: confidence first, then summed similarity, then source order."""
    best: MatchScore | None = None
    for candidate in candidates:
        current = score(book_title, book_author, candidate)
        if best is None or _sort_key(current) > _sort_key(best):
            best = current  # strict ">" keeps the earlier one on an exact tie
    return best


def _sort_key(match: MatchScore) -> tuple[int, float]:
    return (
        _RANK[match.confidence],
        match.title_similarity + (match.author_similarity or 0.0),
    )
