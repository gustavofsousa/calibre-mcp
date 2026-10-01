"""Unit tests for the title/author matcher (ENRICH-04, TSEARCH-02).

Pure module, no I/O. Derived from the spec's confidence rule:
- titles are compared after normalization (accents dropped, case-folded, cut at
  the first ``:`` or ``(``, non-alphanumerics -> spaces, whitespace collapsed);
- authors are compared with their name tokens sorted ("Bach, James" == "James
  Bach"), best ratio across the candidate's authors, ``None`` when the book's
  author is blank/"Unknown";
- high iff title >= 0.90 and author >= 0.85; else medium iff title >= 0.60;
  else low. A ``None`` author similarity can never be high.
- best = highest confidence, then highest title+author similarity, then the
  source's own order.
"""

from __future__ import annotations

import pytest

from calibre_mcp.openlibrary_client import SearchCandidate
from calibre_mcp.title_match import classify, normalize_title, pick_best, score


def _candidate(title: str, *authors: str, key: str = "/works/OL1W") -> SearchCandidate:
    return SearchCandidate(
        work_key=key, title=title, authors=list(authors), cover_url=None
    )


# ------------------------------------------------------------- normalization


@pytest.mark.unit
def test_normalize_drops_accents_case_and_punctuation():
    assert normalize_title("Histórias da Meia-Noite") == "historias da meia noite"


@pytest.mark.unit
def test_normalize_cuts_subtitle_at_colon_or_parenthesis():
    assert normalize_title("O Almada (Ilustrado)") == "o almada"
    assert normalize_title("Crucial Conversations: Tools for Talking") == (
        "crucial conversations"
    )


# ------------------------------------------------------------------ scoring


@pytest.mark.unit
def test_score_equal_after_normalization_is_full_similarity_and_high():
    # Edge case: accents/case/subtitle differences still reach high.
    result = score(
        "Historias da Meia-Noite",
        "Machado de Assis",
        _candidate("Histórias da meia noite (Contos)", "Machado de Assis"),
    )

    assert result.title_similarity == 1.0
    assert result.author_similarity == 1.0
    assert result.confidence == "high"


@pytest.mark.unit
def test_score_author_token_order_does_not_matter():
    result = score("Secrets", "Bach, James", _candidate("Secrets", "James Bach"))

    assert result.author_similarity == 1.0


@pytest.mark.unit
def test_score_uses_best_ratio_across_candidate_authors():
    # Edge case: several catalog authors -> the best one counts.
    result = score(
        "Vidas Paralelas",
        "Plutarco",
        _candidate("Vidas Paralelas", "Someone Else", "Plutarco"),
    )

    assert result.author_similarity == 1.0


@pytest.mark.unit
def test_score_candidate_without_authors_has_zero_author_similarity():
    # Edge case: a candidate with no author at all -> 0.0, never high.
    result = score("Programa de Latim", "Some Author", _candidate("Programa de latim"))

    assert result.author_similarity == 0.0
    assert result.confidence == "medium"


@pytest.mark.unit
@pytest.mark.parametrize("book_author", [None, "", "  ", "Unknown"])
def test_score_unknown_or_blank_book_author_is_never_high(book_author):
    # A5: title-only agreement is the wrong-book risk -> capped at medium.
    result = score("Same Title", book_author, _candidate("Same Title", "Anyone"))

    assert result.author_similarity is None
    assert result.title_similarity == 1.0
    assert result.confidence == "medium"


@pytest.mark.unit
def test_score_different_author_same_title_is_not_high():
    # The real false friend from the probe: same-ish title, another author.
    result = score(
        "Biografia papa Francisco",
        "Vaticano",
        _candidate("Biografia Del Papa Francisco - No Oficial", "Antonio Romero"),
    )

    assert result.confidence != "high"


# ---------------------------------------------------------- classification


@pytest.mark.unit
@pytest.mark.parametrize(
    ("title_sim", "author_sim", "expected"),
    [
        (0.90, 0.85, "high"),
        (0.8999, 1.0, "medium"),
        (1.0, 0.8499, "medium"),
        (1.0, None, "medium"),
        (0.60, None, "medium"),
        (0.5999, 1.0, "low"),
        (0.0, 0.0, "low"),
    ],
)
def test_classify_thresholds_at_the_boundaries(title_sim, author_sim, expected):
    assert classify(title_sim, author_sim) == expected


# -------------------------------------------------------------- pick_best


@pytest.mark.unit
def test_pick_best_prefers_higher_confidence_over_source_order():
    low_first = _candidate("Unrelated Book", "Nobody", key="/works/OL1W")
    exact = _candidate("The Hobbit", "J. R. R. Tolkien", key="/works/OL2W")

    best = pick_best("The Hobbit", "J. R. R. Tolkien", [low_first, exact])

    assert best is not None
    assert best.candidate.work_key == "/works/OL2W"
    assert best.confidence == "high"


@pytest.mark.unit
def test_pick_best_breaks_ties_by_similarity_then_source_order():
    # Same confidence (medium): the higher summed similarity wins; an exact
    # tie keeps the source's own order (first wins).
    weaker = _candidate("The Hobbits", "X", key="/works/OL1W")
    stronger = _candidate("The Hobbit", "X", key="/works/OL2W")
    twin = _candidate("The Hobbit", "X", key="/works/OL3W")

    best = pick_best("The Hobbit", "Unknown", [weaker, stronger, twin])

    assert best is not None
    assert best.confidence == "medium"
    assert best.candidate.work_key == "/works/OL2W"


@pytest.mark.unit
def test_pick_best_of_no_candidates_is_none():
    assert pick_best("The Hobbit", "Tolkien", []) is None
