"""Field extraction via the Claude API.

Structure is enforced with a tool definition rather than by asking for JSON in
prose and parsing the reply. The model is required to call the tool, so the
response arrives already conforming to the schema and there is no brace-matching
or markdown-fence stripping anywhere in the codebase.
"""

from __future__ import annotations

import anthropic

from app.schemas import ExtractedLabel

from .base import ExtractionError, VisionExtractor, preprocess_image
import base64

EXTRACTION_TOOL = {
    "name": "record_label_fields",
    "description": "Record the fields visible on an alcohol beverage label.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand_name": {"type": ["string", "null"], "description": "The brand name exactly as printed, preserving capitalization and punctuation."},
            "class_type": {"type": ["string", "null"], "description": "The class or type designation, for example 'Kentucky Straight Bourbon Whiskey'."},
            "alcohol_content": {"type": ["string", "null"], "description": "The alcohol content statement exactly as printed, for example '45% Alc./Vol. (90 Proof)'."},
            "net_contents": {"type": ["string", "null"], "description": "The net contents statement exactly as printed, for example '750 mL'."},
            "bottler_name": {"type": ["string", "null"], "description": "The name of the bottler, producer or importer."},
            "country_of_origin": {"type": ["string", "null"], "description": "The country of origin, if stated."},
            "government_warning": {"type": ["string", "null"], "description": "The complete government health warning statement, transcribed word for word with original capitalization. Do not correct, complete or paraphrase it."},
            "government_warning_is_all_caps": {"type": ["boolean", "null"], "description": "True only if the words GOVERNMENT WARNING appear in full capital letters on the artwork."},
            "legibility_notes": {"type": ["string", "null"], "description": "Note any glare, blur, angle or cropping that prevented a field from being read. Null if the image was clear."},
        },
        "required": ["brand_name", "class_type", "alcohol_content", "net_contents", "government_warning"],
    },
}

SYSTEM_PROMPT = """You transcribe alcohol beverage label artwork for TTB compliance review.

Transcribe only what is actually printed on the label. Follow these rules strictly:

- Reproduce text exactly, preserving capitalization, punctuation and spacing. Capitalization is legally significant on these labels.
- If a field is not present or not legible, return null for it. Never infer a value from context, never complete a partially visible phrase, and never correct an apparent typo on the label.
- Transcribe the government warning word for word even if it is misspelled, abbreviated, reworded or truncated. Its deviations are the finding.
- If glare, blur, angle or cropping prevented you from reading something, say so in legibility_notes.

You are a transcriber, not a reviewer. Do not judge compliance."""


class AnthropicExtractor(VisionExtractor):
    def __init__(self, api_key: str, model: str, timeout: float = 20.0):
        self.name = model
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)

    async def extract(self, image_bytes: bytes, media_type: str) -> ExtractedLabel:
        processed, processed_type = preprocess_image(image_bytes, media_type)
        encoded = base64.standard_b64encode(processed).decode("ascii")

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=0,
                system=SYSTEM_PROMPT,
                tools=[EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "record_label_fields"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": processed_type,
                            "data": encoded,
                        }},
                        {"type": "text", "text": "Transcribe the fields on this label."},
                    ],
                }],
            )
        except anthropic.APIStatusError as exc:
            raise ExtractionError(f"The extraction service returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError("Could not reach the extraction service. Check network access and try again.") from exc

        for block in response.content:
            if block.type == "tool_use":
                return ExtractedLabel(**block.input)

        raise ExtractionError("The extraction service did not return label fields.")
