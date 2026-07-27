"""Data contracts for the label verification pipeline.

Three shapes move through the system:
  ApplicationData  -> what the applicant typed into the COLA form
  ExtractedLabel   -> what the vision model actually read off the label artwork
  VerificationResult -> the agent-facing verdict produced by comparing the two
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BeverageType(str, Enum):
    """Drives which ABV tolerance rule applies. See comparison/matchers.py."""

    DISTILLED_SPIRITS = "distilled_spirits"
    WINE = "wine"
    MALT_BEVERAGE = "malt_beverage"


class Verdict(str, Enum):
    """Three states, not two.

    REVIEW exists because Dave Morrison is right: a rigid pass/fail forces the
    system to make judgment calls it is not qualified to make. When the evidence
    is ambiguous we escalate to a human instead of guessing.
    """

    MATCH = "match"
    REVIEW = "review"
    MISMATCH = "mismatch"


class ApplicationData(BaseModel):
    """The values the applicant declared on their COLA application."""

    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    beverage_type: BeverageType = BeverageType.DISTILLED_SPIRITS
    bottler_name: Optional[str] = None
    country_of_origin: Optional[str] = None


class ExtractedLabel(BaseModel):
    """What the vision model read off the artwork.

    Every field is optional: a field being absent from the label is itself a
    finding, and is reported differently from a field that is present but wrong.
    """

    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    alcohol_content: Optional[str] = None
    net_contents: Optional[str] = None
    bottler_name: Optional[str] = None
    country_of_origin: Optional[str] = None
    government_warning: Optional[str] = None
    government_warning_is_all_caps: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the literal prefix 'GOVERNMENT WARNING:' appears in full "
            "capitals on the artwork. Tracked separately because casing is a "
            "rendering property the model must judge visually, and 27 CFR 16.21 "
            "requires it."
        ),
    )
    legibility_notes: Optional[str] = None


class FieldCheck(BaseModel):
    """One row of the agent's checklist."""

    field: str
    label: str
    expected: Optional[str]
    found: Optional[str]
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    rule: str = Field(description="Which comparison rule produced this verdict.")


class VerificationResult(BaseModel):
    filename: str
    overall: Verdict
    checks: list[FieldCheck]
    extraction_ms: int
    comparison_ms: int
    total_ms: int
    model: str
    legibility_notes: Optional[str] = None
    error: Optional[str] = None


class BatchResult(BaseModel):
    results: list[VerificationResult]
    total_ms: int
    counts: dict[str, int]
