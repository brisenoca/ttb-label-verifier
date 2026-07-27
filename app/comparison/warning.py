"""Government health warning statement check.

This is the one field that gets no fuzzy tolerance at all. 27 CFR 16.21
prescribes the exact wording, and 27 CFR 16.22 requires the words
"GOVERNMENT WARNING" to appear in capital letters and bold type. Jenny Park
rejected a label last month for title-casing that prefix, so the rule the
software applies has to be the same rule the agents apply.

The only normalization permitted here is whitespace collapsing, because where a
line breaks on the artwork is a typesetting decision and does not change the
wording.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from app.schemas import FieldCheck, Verdict

from .normalize import collapse_whitespace, fold_typography

# 27 CFR 16.21. Held here as configuration rather than inline so that a
# regulatory amendment is a one-line change with a matching test.
REQUIRED_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

REQUIRED_PREFIX = "GOVERNMENT WARNING:"


def _canonical(text: str) -> str:
    """Whitespace and typography folding only. Case is preserved on purpose."""
    return collapse_whitespace(fold_typography(text))


def first_difference(expected: str, found: str) -> str:
    """Describe where the two statements diverge, for the agent's benefit."""
    matcher = SequenceMatcher(None, expected, found)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        expected_frag = expected[i1:i2].strip() or "(nothing)"
        found_frag = found[j1:j2].strip() or "(nothing)"
        context = expected[max(0, i1 - 30):i1].strip()
        lead = f"after '...{context}'" if context else "at the start of the statement"
        return f"{lead} the statement should read '{expected_frag}' but the label reads '{found_frag}'"
    return "the statements differ in length"


def check_government_warning(
    found: str | None, is_all_caps: bool | None = None
) -> FieldCheck:
    base = dict(field="government_warning", label="Government warning",
                expected=REQUIRED_WARNING, found=found)

    if not found or not found.strip():
        return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                          explanation="No government warning statement was found on the label. This statement is mandatory.",
                          rule="warning_absent")

    found_canonical = _canonical(found)

    if found_canonical == REQUIRED_WARNING:
        if is_all_caps is False:
            return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                              explanation=("The wording is correct, but 'GOVERNMENT WARNING:' is not in capital "
                                           "letters. Capitalization of this prefix is mandatory."),
                              rule="warning_prefix_not_capitalized")
        return FieldCheck(**base, verdict=Verdict.MATCH, confidence=1.0,
                          explanation="The statement matches the required wording exactly.",
                          rule="warning_exact")

    # Wording is correct but the prefix casing is wrong in the extracted text.
    if found_canonical.upper() == REQUIRED_WARNING.upper():
        return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                          explanation=("The wording is correct, but the capitalization does not match. "
                                       "'GOVERNMENT WARNING:' must appear in capital letters."),
                          rule="warning_case_mismatch")

    if not found_canonical.startswith(REQUIRED_PREFIX):
        opening = found_canonical[:40]
        return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                          explanation=(f"The statement must begin with 'GOVERNMENT WARNING:' in capital letters. "
                                       f"The label begins '{opening}...'."),
                          rule="warning_prefix_wrong")

    detail = first_difference(REQUIRED_WARNING, found_canonical)
    return FieldCheck(**base, verdict=Verdict.MISMATCH, confidence=1.0,
                      explanation=f"The wording does not match the required statement: {detail}.",
                      rule="warning_wording_altered")
