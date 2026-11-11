"""Brand tokens (brand/style.json), font files and text measurement."""
import json
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parent.parent
BRAND_DIR = REPO / "brand"
FONTS_DIR = BRAND_DIR / "fonts"

# family names baked into the static font instances in brand/fonts
F_BLACK, F_HEAVY, F_FILLER = "TM Archivo Black", "TM Archivo Heavy", "TM Archivo Filler"
F_MONO_BOLD, F_MONO = "TM Mono Bold", "TM Mono Medium"


def load_style(path=None) -> dict:
    return json.loads(Path(path or BRAND_DIR / "style.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _metrics(family: str):
    font = TTFont(FONTS_DIR / (family.replace(" ", "") + "-Regular.ttf"))
    return font.getBestCmap(), font["hmtx"].metrics, font["head"].unitsPerEm


def text_width(text: str, family: str, size: float, spacing: float = 0) -> float:
    """Advance width in px (no kerning) of text set in a brand font."""
    cmap, hmtx, upem = _metrics(family)
    fallback = cmap[ord("?")]
    return sum(hmtx[cmap.get(ord(c), fallback)][0] for c in text) / upem * size + spacing * len(text)


def ass_color(hex_rgb: str) -> str:
    """#RRGGBB -> ASS &HBBGGRR&"""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"
