"""Render synthetic test labels.

Real COLA artwork is not public, so the test set is generated. Each label is
built to exercise one specific comparison path, and the filenames say which:
a reviewer can look at `titlecase.png` and know before running anything what the
application is supposed to catch.

    python samples/generate_labels.py

Writes PNGs to samples/labels/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.comparison.warning import REQUIRED_WARNING  # noqa: E402

OUT = Path(__file__).parent / "labels"
W, H = 900, 1250
CREAM, INK, GOLD = (243, 238, 226), (26, 24, 20), (150, 116, 44)

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FALLBACKS = [FONT_DIR, Path("/usr/share/fonts/truetype/liberation"),
             Path("/Library/Fonts"), Path("C:/Windows/Fonts")]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for directory in FALLBACKS:
        candidate = directory / name
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


SERIF_BOLD = "DejaVuSerif-Bold.ttf"
SERIF = "DejaVuSerif.ttf"
SANS = "DejaVuSans.ttf"
SANS_BOLD = "DejaVuSans-Bold.ttf"


def centered(draw, y, text, fnt, fill=INK, spacing=0):
    if spacing:
        widths = [draw.textlength(ch, font=fnt) + spacing for ch in text]
        x = (W - (sum(widths) - spacing)) / 2
        for ch, width in zip(text, widths):
            draw.text((x, y), ch, font=fnt, fill=fill)
            x += width
    else:
        draw.text(((W - draw.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=fill)


def wrap(draw, text, fnt, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render(filename: str, *, brand="OLD TOM DISTILLERY",
           class_type="Kentucky Straight Bourbon Whiskey",
           abv="45% Alc./Vol. (90 Proof)", net="750 mL",
           bottler="Old Tom Distillery, Bardstown, KY",
           warning: str | None = REQUIRED_WARNING):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    d.rectangle([28, 28, W - 28, H - 28], outline=GOLD, width=4)
    d.rectangle([44, 44, W - 44, H - 44], outline=GOLD, width=1)

    centered(d, 130, "ESTABLISHED 1868", font(SANS, 20), GOLD, spacing=5)
    d.line([(W / 2 - 90, 172), (W / 2 + 90, 172)], fill=GOLD, width=2)

    y = 230
    for line in wrap(d, brand, font(SERIF_BOLD, 62), W - 200):
        centered(d, y, line, font(SERIF_BOLD, 62))
        y += 76

    y += 30
    for line in wrap(d, class_type, font(SERIF, 30), W - 220):
        centered(d, y, line, font(SERIF, 30))
        y += 42

    d.line([(160, y + 40), (W - 160, y + 40)], fill=GOLD, width=2)

    centered(d, y + 90, abv, font(SANS_BOLD, 30))
    centered(d, y + 140, net, font(SANS, 28))
    centered(d, y + 200, bottler, font(SANS, 20), (90, 84, 74))

    if warning:
        warn_font = font(SANS_BOLD, 17)
        lines = wrap(d, warning, warn_font, W - 180)
        wy = H - 90 - len(lines) * 24
        for line in lines:
            d.text((90, wy), line, font=warn_font, fill=INK)
            wy += 24

    OUT.mkdir(exist_ok=True)
    img.save(OUT / filename, optimize=True)
    print(f"  {filename}")


def main() -> None:
    print("Writing test labels:")
    render("clean.png")
    render("casing.png", brand="Old Tom Distillery")
    render("titlecase.png",
           warning=REQUIRED_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"))
    render("reworded.png",
           warning=REQUIRED_WARNING.replace(
               "should not drink alcoholic beverages during pregnancy",
               "may wish to avoid alcoholic beverages during pregnancy"))
    render("nowarning.png", warning=None)
    render("tolerance.png", abv="45.1% Alc./Vol.")
    render("abv.png", abv="40% Alc./Vol. (80 Proof)")
    render("volume.png", net="700 mL")
    render("units.png", net="0.75 L")
    render("wrongbrand.png", brand="NEW TOM DISTILLERY")
    print(f"\nDone. {len(list(OUT.glob('*.png')))} labels in {OUT}")


if __name__ == "__main__":
    main()
