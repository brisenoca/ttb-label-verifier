"""Assembles individual field checks into one verification result."""

from __future__ import annotations

from app.schemas import ApplicationData, ExtractedLabel, FieldCheck, Verdict

from .matchers import check_alcohol_content, check_net_contents, check_text_field
from .warning import check_government_warning


def compare(application: ApplicationData, extracted: ExtractedLabel) -> list[FieldCheck]:
    """Run every applicable rule. Order matches the agents' paper checklist."""
    checks = [
        check_text_field("brand_name", "Brand name",
                         application.brand_name, extracted.brand_name),
        check_text_field("class_type", "Class / type",
                         application.class_type, extracted.class_type),
        check_alcohol_content(application.alcohol_content,
                              extracted.alcohol_content,
                              application.beverage_type),
        check_net_contents(application.net_contents, extracted.net_contents),
        check_government_warning(extracted.government_warning,
                                 extracted.government_warning_is_all_caps),
    ]

    # Optional fields are only checked when the application declares them.
    if application.bottler_name:
        checks.append(check_text_field("bottler_name", "Bottler / producer",
                                       application.bottler_name, extracted.bottler_name))
    if application.country_of_origin:
        checks.append(check_text_field("country_of_origin", "Country of origin",
                                       application.country_of_origin, extracted.country_of_origin))

    return checks


def overall_verdict(checks: list[FieldCheck]) -> Verdict:
    """The worst individual verdict wins.

    A label is not approvable because most of it is correct, so this does not
    average or score. One mismatch fails the label; one ambiguity sends the whole
    label to a human.
    """
    verdicts = {c.verdict for c in checks}
    if Verdict.MISMATCH in verdicts:
        return Verdict.MISMATCH
    if Verdict.REVIEW in verdicts:
        return Verdict.REVIEW
    return Verdict.MATCH
