"""Offline extractor used for tests and for demoing without network access.

Two reasons this exists rather than being a testing afterthought:

1. The comparison rules are the part of the system that decides whether a label
   passes. Testing them against a live model would make the test suite slow,
   costly and non-deterministic, and would test the model rather than the rules.
2. Marcus Williams described a vendor pilot where half the features died behind
   the firewall. An application that cannot demonstrate anything without an
   outbound connection is hard to evaluate in that environment.

Selection is by filename keyword so the sample set exercises each interesting
comparison path.
"""

from __future__ import annotations

import asyncio

from app.comparison.warning import REQUIRED_WARNING
from app.schemas import ExtractedLabel

from .base import VisionExtractor

_CLEAN = ExtractedLabel(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
    bottler_name="Old Tom Distillery, Bardstown, KY",
    government_warning=REQUIRED_WARNING,
    government_warning_is_all_caps=True,
)

_FIXTURES: dict[str, ExtractedLabel] = {
    # Dave Morrison's case: cosmetically different, substantively identical.
    "casing": _CLEAN.model_copy(update={"brand_name": "Old Tom Distillery"}),
    # Jenny Park's case: correct wording, wrong capitalization on the prefix.
    "titlecase": _CLEAN.model_copy(update={
        "government_warning": REQUIRED_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"),
        "government_warning_is_all_caps": False,
    }),
    # A creatively reworded warning.
    "reworded": _CLEAN.model_copy(update={
        "government_warning": REQUIRED_WARNING.replace(
            "should not drink alcoholic beverages during pregnancy",
            "may wish to avoid alcoholic beverages during pregnancy"),
    }),
    "nowarning": _CLEAN.model_copy(update={
        "government_warning": None, "government_warning_is_all_caps": None}),
    # Within the 0.15 point distilled spirits tolerance.
    "tolerance": _CLEAN.model_copy(update={"alcohol_content": "45.1% Alc./Vol."}),
    # Well outside it.
    "abv": _CLEAN.model_copy(update={"alcohol_content": "40% Alc./Vol. (80 Proof)"}),
    "volume": _CLEAN.model_copy(update={"net_contents": "700 mL"}),
    # Same volume, different unit.
    "units": _CLEAN.model_copy(update={"net_contents": "0.75 L"}),
    "blurry": _CLEAN.model_copy(update={
        "class_type": None,
        "legibility_notes": "Glare across the lower third of the label obscured the class designation.",
    }),
    "wrongbrand": _CLEAN.model_copy(update={"brand_name": "NEW TOM DISTILLERY"}),
}


class MockExtractor(VisionExtractor):
    name = "mock-extractor"

    def __init__(self, latency_s: float = 0.15):
        self._latency = latency_s

    async def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        await asyncio.sleep(self._latency)
        return _CLEAN

    async def extract_named(self, filename: str) -> ExtractedLabel:
        await asyncio.sleep(self._latency)
        stem = filename.lower()
        for keyword, fixture in _FIXTURES.items():
            if keyword in stem:
                return fixture
        return _CLEAN
