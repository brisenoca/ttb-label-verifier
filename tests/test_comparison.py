"""Tests for the comparison rules.

These target the part of the system that decides whether a label passes. They
run offline and deterministically: the vision model is a dependency, not the
subject. Several tests are named for the stakeholder who described the case.
"""

import os

import pytest

from app.comparison.engine import compare, overall_verdict
from app.comparison.matchers import parse_abv, parse_volume_ml
from app.comparison.warning import REQUIRED_WARNING, check_government_warning
from app.schemas import ApplicationData, BeverageType, ExtractedLabel, Verdict


def application(**overrides) -> ApplicationData:
    base = dict(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        beverage_type=BeverageType.DISTILLED_SPIRITS,
    )
    return ApplicationData(**{**base, **overrides})


def label(**overrides) -> ExtractedLabel:
    base = dict(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        government_warning=REQUIRED_WARNING,
        government_warning_is_all_caps=True,
    )
    return ExtractedLabel(**{**base, **overrides})


def check_for(field, checks):
    return next(c for c in checks if c.field == field)


# --- Brand name -----------------------------------------------------------

def test_clean_label_passes():
    assert overall_verdict(compare(application(), label())) is Verdict.MATCH


def test_dave_morrisons_casing_case_is_a_match_not_a_mismatch():
    """'STONE'S THROW' on the label vs 'Stone's Throw' on the form."""
    checks = compare(
        application(brand_name="Stone's Throw"),
        label(brand_name="STONE\u2019S THROW"),
    )
    brand = check_for("brand_name", checks)
    assert brand.verdict is Verdict.MATCH
    assert brand.rule == "normalized_exact"
    # The agent still gets told the formatting differed.
    assert "capitalization" in brand.explanation.lower()


def test_a_genuinely_different_brand_is_a_mismatch():
    checks = compare(application(), label(brand_name="NEW TOM DISTILLERY"))
    assert check_for("brand_name", checks).verdict is Verdict.MISMATCH


def test_a_transcription_typo_is_still_a_match():
    """One wrong character inside a word is an extraction artefact, not a finding."""
    checks = compare(application(), label(brand_name="OLD TOM DISTILLERV"))
    assert check_for("brand_name", checks).verdict is Verdict.MATCH


def test_an_extra_word_on_the_label_goes_to_review():
    checks = compare(application(), label(brand_name="OLD TOM DISTILLERY COMPANY"))
    assert check_for("brand_name", checks).verdict in {Verdict.REVIEW, Verdict.MISMATCH}


def test_a_near_miss_brand_goes_to_review_not_to_a_verdict():
    checks = compare(
        application(brand_name="Old Tom Distillery Company"),
        label(brand_name="Old Tom Distilling Co"),
    )
    assert check_for("brand_name", checks).verdict in {Verdict.REVIEW, Verdict.MISMATCH}


def test_missing_brand_on_label_is_reported_as_absent():
    checks = compare(application(), label(brand_name=None))
    brand = check_for("brand_name", checks)
    assert brand.verdict is Verdict.MISMATCH
    assert brand.rule == "absent_from_label"


# --- Government warning ---------------------------------------------------

def test_exact_warning_passes():
    assert check_government_warning(REQUIRED_WARNING, True).verdict is Verdict.MATCH


def test_line_breaks_in_the_warning_are_not_a_finding():
    wrapped = REQUIRED_WARNING.replace(". (2)", ".\n\n   (2)")
    assert check_government_warning(wrapped, True).verdict is Verdict.MATCH


def test_jenny_parks_title_case_warning_is_rejected():
    """Correct wording, but 'Government Warning:' instead of all caps."""
    titled = REQUIRED_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    result = check_government_warning(titled, False)
    assert result.verdict is Verdict.MISMATCH
    assert "capital" in result.explanation.lower()


def test_all_caps_flag_alone_can_fail_an_otherwise_perfect_warning():
    result = check_government_warning(REQUIRED_WARNING, is_all_caps=False)
    assert result.verdict is Verdict.MISMATCH
    assert result.rule == "warning_prefix_not_capitalized"


def test_reworded_warning_is_rejected_and_the_difference_is_located():
    reworded = REQUIRED_WARNING.replace("should not drink", "may prefer not to drink")
    result = check_government_warning(reworded, True)
    assert result.verdict is Verdict.MISMATCH
    # The explanation must point the agent at the specific altered wording.
    assert "prefer" in result.explanation


def test_truncated_warning_is_rejected():
    result = check_government_warning(REQUIRED_WARNING.split(". (2)")[0], True)
    assert result.verdict is Verdict.MISMATCH


def test_absent_warning_is_rejected():
    for value in (None, "", "   "):
        assert check_government_warning(value, None).verdict is Verdict.MISMATCH


def test_warning_gets_no_fuzzy_tolerance():
    """A single missing word must fail even though similarity is above 99%."""
    almost = REQUIRED_WARNING.replace("birth defects", "defects")
    assert check_government_warning(almost, True).verdict is Verdict.MISMATCH


# --- Alcohol content ------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("45% Alc./Vol. (90 Proof)", 45.0),
    ("ALC. 12.5% BY VOL", 12.5),
    ("40 % alc/vol", 40.0),
    ("90 Proof", 45.0),
    ("no alcohol statement", None),
])
def test_abv_parsing(text, expected):
    assert parse_abv(text) == expected


def test_abv_within_spirits_tolerance_passes():
    checks = compare(application(), label(alcohol_content="45.1% Alc./Vol."))
    check = check_for("alcohol_content", checks)
    assert check.verdict is Verdict.MATCH
    assert check.rule == "abv_within_tolerance"


def test_abv_outside_spirits_tolerance_fails():
    checks = compare(application(), label(alcohol_content="45.5% Alc./Vol."))
    assert check_for("alcohol_content", checks).verdict is Verdict.MISMATCH


def test_wine_tolerance_is_wider_than_spirits():
    checks = compare(
        application(alcohol_content="13.0% Alc./Vol.", beverage_type=BeverageType.WINE),
        label(alcohol_content="13.8% Alc./Vol."),
    )
    assert check_for("alcohol_content", checks).verdict is Verdict.MATCH


def test_proof_only_label_matches_percentage_application():
    checks = compare(application(), label(alcohol_content="90 PROOF"))
    assert check_for("alcohol_content", checks).verdict is Verdict.MATCH


# --- Net contents ---------------------------------------------------------

@pytest.mark.parametrize("text,expected_ml", [
    ("750 mL", 750.0),
    ("750ML", 750.0),
    ("0.75 L", 750.0),
    ("1 Liter", 1000.0),
    ("75 cl", 750.0),
])
def test_volume_parsing(text, expected_ml):
    assert parse_volume_ml(text) == pytest.approx(expected_ml)


def test_equivalent_volumes_in_different_units_match():
    checks = compare(application(), label(net_contents="0.75 L"))
    check = check_for("net_contents", checks)
    assert check.verdict is Verdict.MATCH
    assert check.rule == "volume_equivalent"


def test_different_volumes_mismatch():
    checks = compare(application(), label(net_contents="700 mL"))
    assert check_for("net_contents", checks).verdict is Verdict.MISMATCH


# --- Overall verdict ------------------------------------------------------

def test_one_mismatch_fails_the_whole_label():
    checks = compare(application(), label(net_contents="700 mL"))
    assert overall_verdict(checks) is Verdict.MISMATCH


def test_mismatch_outranks_review():
    checks = compare(
        application(brand_name="Old Tom Distillery Company"),
        label(brand_name="Old Tom Distilling Co", net_contents="700 mL"),
    )
    assert overall_verdict(checks) is Verdict.MISMATCH


def test_optional_fields_are_only_checked_when_declared():
    without = compare(application(), label())
    with_bottler = compare(application(bottler_name="Old Tom Distillery"), label(bottler_name="Old Tom Distillery"))
    assert len(with_bottler) == len(without) + 1


def test_every_check_carries_an_explanation_and_a_rule():
    for check in compare(application(), label(net_contents="700 mL")):
        assert check.explanation.strip()
        assert check.rule.strip()


# --- Image preprocessing --------------------------------------------------

def test_preprocessing_never_enlarges_a_suitable_image():
    """Re-encoding flat artwork to JPEG can inflate it. Don't."""
    from app.extraction.base import preprocess_image
    raw = open("samples/labels/clean.png", "rb").read()
    out, media_type = preprocess_image(raw, "image/png")
    assert len(out) <= len(raw)
    assert media_type in {"image/png", "image/jpeg"}


def test_preprocessing_downscales_an_oversized_image():
    import io
    from PIL import Image
    from app.extraction.base import MAX_EDGE_PX, preprocess_image

    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (200, 180, 140)).save(buf, format="PNG")
    out, media_type = preprocess_image(buf.getvalue(), "image/png")

    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= MAX_EDGE_PX


# --- Configuration loading ------------------------------------------------

def test_env_file_survives_windows_notepad_quirks(tmp_path, monkeypatch):
    """BOM, CRLF line endings, quotes and trailing spaces must all be tolerated.

    Every one of these came up in real use. A config loader that only handles
    clean input is a config loader that fails silently on Windows.
    """
    from app.config import _load_env_file

    env = tmp_path / ".env"
    env.write_bytes(
        b'\xef\xbb\xbf# a comment\r\n'
        b'ANTHROPIC_API_KEY="sk-ant-quoted"  \r\n'
        b'\r\n'
        b"MAX_CONCURRENCY='4'\r\n"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MAX_CONCURRENCY", raising=False)

    _load_env_file(env)

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-quoted"
    assert os.environ["MAX_CONCURRENCY"] == "4"


def test_real_environment_variables_win_over_the_env_file(tmp_path, monkeypatch):
    """Deployment platforms set real variables; they must not be overridden."""
    from app.config import _load_env_file

    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-platform")

    _load_env_file(env)

    assert os.environ["ANTHROPIC_API_KEY"] == "from-platform"


def test_missing_env_file_is_not_an_error(tmp_path):
    from app.config import _load_env_file
    _load_env_file(tmp_path / "nope.env")
