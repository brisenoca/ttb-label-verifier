"""Deterministic field matchers.

Every verdict in this module is produced by a rule that can be read, tested and
explained to an applicant whose label was rejected. No model judgment is used at
the comparison stage. That is a deliberate trade-off, discussed in ASSUMPTIONS.md.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.schemas import BeverageType, FieldCheck, Verdict

from .normalize import differs_only_cosmetically, normalize

# --- Fuzzy text thresholds -------------------------------------------------
# Tuned by hand against the sample set. These are the single most important
# numbers in the application and they are surfaced here rather than buried
# inline so a compliance lead can adjust them without reading the code.
MATCH_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.75


# A token counts as present in the other string if some token there is at least
# this similar to it. Set to absorb transcription typos ("DISTILLERV") without
# absorbing different words ("DISTILLING").
TOKEN_MATCH_THRESHOLD = 0.85


def char_similarity(a: str, b: str) -> float:
    """Normalized edit-distance ratio in [0, 1]."""
    return SequenceMatcher(None, a, b).ratio()


def token_similarity(a: str, b: str) -> float:
    """Symmetric ratio of tokens in each string that appear in the other.

    Character similarity alone is not sufficient for brand names. "OLD TOM
    DISTILLERY" and "NEW TOM DISTILLERY" are 89% similar character by character
    because the two long shared words swamp the one that changed, but they are
    different products. Comparing at the token level surfaces the substitution.
    """
    tokens_a, tokens_b = a.split(), b.split()
    if not tokens_a or not tokens_b:
        return 0.0

    def covered(source: list[str], target: list[str]) -> int:
        return sum(
            1 for token in source
            if any(char_similarity(token, other) >= TOKEN_MATCH_THRESHOLD for other in target)
        )

    matched = covered(tokens_a, tokens_b) + covered(tokens_b, tokens_a)
    return matched / (len(tokens_a) + len(tokens_b))


def similarity(a: str, b: str) -> float:
    """Combined score, taking the more pessimistic of the two views.

    A pair must look alike both as a sequence of characters and as a set of
    words before it is treated as a match. Either signal alone produces false
    positives on real label text.
    """
    return min(char_similarity(a, b), token_similarity(a, b))


def check_text_field(
    field: str,
    label: str,
    expected: str | None,
    found: str | None,
) -> FieldCheck:
    """Compare a free-text field using a normalize-then-fuzzy ladder.

    The ladder runs from strictest to loosest and stops at the first rung that
    matches, so the reported rule always names the strongest evidence available.
    """
    if not expected:
        return FieldCheck(
            field=field, label=label, expected=expected, found=found,
            verdict=Verdict.REVIEW, confidence=0.0,
            explanation="No value was declared on the application, so there is nothing to compare against.",
            rule="missing_application_value",
        )

    if not found:
        return FieldCheck(
            field=field, label=label, expected=expected, found=found,
            verdict=Verdict.MISMATCH, confidence=1.0,
            explanation=f"'{expected}' was declared on the application but no matching text was found on the label.",
            rule="absent_from_label",
        )

    if expected == found:
        return FieldCheck(
            field=field, label=label, expected=expected, found=found,
            verdict=Verdict.MATCH, confidence=1.0,
            explanation="The label matches the application exactly.",
            rule="exact",
        )

    if differs_only_cosmetically(expected, found):
        return FieldCheck(
            field=field, label=label, expected=expected, found=found,
            verdict=Verdict.MATCH, confidence=1.0,
            explanation="The wording matches. Only capitalization, punctuation or spacing differ.",
            rule="normalized_exact",
        )

    score = similarity(normalize(expected), normalize(found))

    if score >= MATCH_THRESHOLD:
        return FieldCheck(
            field=field, label=label, expected=expected, found=found,
            verdict=Verdict.MATCH, confidence=score,
            explanation=f"Close match ({score:.0%} similar). Minor spelling or spacing variation.",
            rule="fuzzy_match",
        )

    if score >= REVIEW_THRESHOLD:
        return FieldCheck(
            field=field, label=label, expected=expected, found=found,
            verdict=Verdict.REVIEW, confidence=score,
            explanation=f"Partial match ({score:.0%} similar). An agent should confirm whether this is the same value.",
            rule="fuzzy_review",
        )

    return FieldCheck(
        field=field, label=label, expected=expected, found=found,
        verdict=Verdict.MISMATCH, confidence=1.0 - score,
        explanation=f"The label and application do not agree ({score:.0%} similar).",
        rule="fuzzy_mismatch",
    )


# --- Alcohol content -------------------------------------------------------
# TTB permits a labeling tolerance rather than requiring an exact figure. The
# values below reflect the commonly cited tolerances in 27 CFR Parts 4, 5 and 7.
# They are configuration, not law: verify against the current CFR before any
# production use. See ASSUMPTIONS.md.
ABV_TOLERANCE = {
    BeverageType.DISTILLED_SPIRITS: 0.15,
    BeverageType.WINE: 1.0,
    BeverageType.MALT_BEVERAGE: 0.3,
}

_ABV_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_PROOF_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:proof)", re.IGNORECASE)


def parse_abv(text: str | None) -> float | None:
    """Pull an alcohol-by-volume percentage out of free text.

    Handles '45% Alc./Vol.', 'ALC 45% BY VOL', and falls back to proof
    (90 Proof -> 45.0) when no percentage is printed.
    """
    if not text:
        return None
    if m := _ABV_PATTERN.search(text):
        return float(m.group(1))
    if m := _PROOF_PATTERN.search(text):
        return float(m.group(1)) / 2.0
    return None


def check_alcohol_content(
    expected: str | None, found: str | None, beverage_type: BeverageType
) -> FieldCheck:
    tolerance = ABV_TOLERANCE[beverage_type]
    base = dict(field="alcohol_content", label="Alcohol content",
                expected=expected, found=found)

    expected_abv = parse_abv(expected)
    found_abv = parse_abv(found)

    if expected_abv is None:
        return FieldCheck(**base, verdict=Verdict.REVIEW, confidence=0.0,
                          explanation="No alcohol content could be read from the application.",
                          rule="unparseable_application_value")

    if found_abv is None:
        return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                          explanation="No alcohol content statement was found on the label.",
                          rule="absent_from_label")

    delta = abs(expected_abv - found_abv)

    if delta == 0:
        return FieldCheck(**base, verdict=Verdict.MATCH, confidence=1.0,
                          explanation=f"Both state {found_abv:g}% alcohol by volume.",
                          rule="abv_exact")

    if delta <= tolerance:
        return FieldCheck(**base, verdict=Verdict.MATCH, confidence=1.0,
                          explanation=(f"Label states {found_abv:g}% against {expected_abv:g}% declared. "
                                       f"The {delta:.2f} point difference is within the {tolerance:g} point "
                                       f"tolerance for this beverage type."),
                          rule="abv_within_tolerance")

    return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                      explanation=(f"Label states {found_abv:g}% against {expected_abv:g}% declared, "
                                   f"a difference of {delta:.2f} points. Tolerance is {tolerance:g}."),
                      rule="abv_outside_tolerance")


# --- Net contents ----------------------------------------------------------
_VOLUME_UNITS_ML = {
    "ml": 1.0, "milliliter": 1.0, "milliliters": 1.0, "millilitre": 1.0,
    "cl": 10.0, "centiliter": 10.0,
    "l": 1000.0, "liter": 1000.0, "liters": 1000.0, "litre": 1000.0,
    "floz": 29.5735, "flozs": 29.5735, "ozfl": 29.5735,
}
_VOLUME_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(fl\.?\s*oz|ml|cl|l|liters?|litres?|milliliters?|millilitres?)\b",
    re.IGNORECASE,
)


def parse_volume_ml(text: str | None) -> float | None:
    """Convert a net contents statement to millilitres for comparison."""
    if not text:
        return None
    m = _VOLUME_PATTERN.search(text)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = re.sub(r"[^a-z]", "", m.group(2).lower())
    factor = _VOLUME_UNITS_ML.get(unit)
    return value * factor if factor else None


def check_net_contents(expected: str | None, found: str | None) -> FieldCheck:
    base = dict(field="net_contents", label="Net contents",
                expected=expected, found=found)

    expected_ml = parse_volume_ml(expected)
    found_ml = parse_volume_ml(found)

    if expected_ml is None or found_ml is None:
        # Fall back to text comparison rather than failing outright.
        return check_text_field("net_contents", "Net contents", expected, found)

    # 0.5 mL absorbs float conversion noise from fl oz without masking a real
    # difference; the smallest standard of fill increment is far larger.
    if abs(expected_ml - found_ml) <= 0.5:
        return FieldCheck(**base, verdict=Verdict.MATCH, confidence=1.0,
                          explanation=f"Both state the same volume ({found_ml:g} mL).",
                          rule="volume_equivalent")

    return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                      explanation=(f"Label states {found_ml:g} mL against {expected_ml:g} mL declared."),
                      rule="volume_mismatch")
