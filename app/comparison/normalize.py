"""Text normalization.

Normalization is deliberately separated from matching so that a verdict can
report *why* two strings differed: a difference that survives normalization is a
substantive mismatch, while one that disappears under normalization is a
cosmetic formatting difference. Dave Morrison's "STONE'S THROW" vs
"Stone's Throw" case is the second kind, and the interface should say so rather
than flagging it as an error.
"""

from __future__ import annotations

import re
import unicodedata

# Curly quotes, en/em dashes and non-breaking spaces are extremely common in
# label artwork set in design software. They are cosmetic, never substantive.
_PUNCT_FOLD = {
    "\u2018": "'", "\u2019": "'", "\u201b": "'", "\u02bc": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ",
}

_STRIP_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def fold_typography(text: str) -> str:
    """Replace typographic variants with their ASCII equivalents."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(_PUNCT_FOLD.get(ch, ch) for ch in text)


def collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space and trim.

    Applied even to the government warning check: line breaks in the artwork are
    a typesetting decision, not a wording change.
    """
    return _WHITESPACE.sub(" ", text).strip()


def normalize(text: str | None) -> str:
    """Aggressive normalization for fuzzy field comparison.

    Case-insensitive, punctuation-insensitive, whitespace-insensitive.
    Never use this for the government warning statement.
    """
    if not text:
        return ""
    text = fold_typography(text)
    text = _STRIP_PUNCT.sub(" ", text)
    text = collapse_whitespace(text)
    return text.upper()


def differs_only_cosmetically(expected: str, found: str) -> bool:
    """True when the two strings are identical once formatting is set aside."""
    return expected != found and normalize(expected) == normalize(found)
