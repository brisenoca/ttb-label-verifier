"""Vision extraction interface.

The application depends on this abstraction rather than on any vendor SDK.
Marcus Williams flagged that TTB's network blocks outbound traffic to many
domains and that the previous vendor pilot broke when the firewall blocked their
ML endpoints. Keeping extraction behind a one-method interface means swapping to
a different provider, an Azure-hosted model inside the FedRAMP boundary, or a
local model is a new file rather than a rewrite.
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod

from PIL import Image, ImageOps

from app.schemas import ExtractedLabel

# Label artwork is routinely submitted at print resolution. Downscaling before
# upload is the single largest latency win available: it cuts both the upload
# time and the number of image tokens the model has to process, with no
# measurable accuracy cost at this size.
MAX_EDGE_PX = 1400
JPEG_QUALITY = 85

SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_EXIF_ORIENTATION = 0x0112


def _encode_jpeg(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def preprocess_image(raw: bytes, media_type: str = "image/jpeg") -> tuple[bytes, str]:
    """Prepare an image for upload. Returns the bytes and their media type.

    Downscaling is the largest latency win available for photographed labels,
    which arrive at print or phone-camera resolution. But it is not a win for
    every input: flat vector-style artwork stored as PNG compresses far better
    as PNG than as JPEG, and blindly re-encoding it *inflates* the payload.
    Measured on the sample set, a 56 KB PNG became an 82 KB JPEG.

    So the rule is: rotate and downscale when those are needed, and otherwise
    only re-encode when re-encoding actually produces a smaller file.
    """
    with Image.open(io.BytesIO(raw)) as img:
        oversized = max(img.size) > MAX_EDGE_PX
        misoriented = img.getexif().get(_EXIF_ORIENTATION, 1) not in (1, None)

        if oversized or misoriented:
            # EXIF transposition matters more than it looks: phone photos of
            # bottles are frequently stored rotated, and an upside-down label
            # reads as an unreadable one.
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
            return _encode_jpeg(img), "image/jpeg"

        if media_type not in SUPPORTED_MEDIA_TYPES:
            return _encode_jpeg(img), "image/jpeg"

        candidate = _encode_jpeg(img)
        if len(candidate) < len(raw):
            return candidate, "image/jpeg"
        return raw, media_type


class ExtractionError(RuntimeError):
    """Raised when the label could not be read at all."""


class VisionExtractor(ABC):
    """Reads structured fields off a label image."""

    name: str = "unknown"

    @abstractmethod
    async def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        """Return the fields visible on the label.

        Implementations must not guess. A field that is not legible on the
        artwork should come back as None so the comparison stage can report it as
        absent rather than silently inventing a match.
        """
        raise NotImplementedError
