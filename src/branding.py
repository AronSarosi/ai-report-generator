"""Extract a brand palette + fonts from an uploaded PowerPoint template.

We read the template's theme (ppt/theme/theme1.xml) straight from the .pptx/.potx zip: the
accent color, the dark/text color, and the major/minor fonts. The renderer applies these to its
own clean layout, so an uploaded corporate template makes the deck come out on-brand.

We deliberately do NOT copy the template's master slides or logos — placement is too
template-specific to reproduce reliably — colors + fonts are what make a deck read as "ours".
"""

from __future__ import annotations

import re
import zipfile
from typing import Optional
from xml.etree import ElementTree as ET

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _hex_from(el) -> Optional[str]:
    """A theme color element wraps either an <a:srgbClr val> or an <a:sysClr lastClr>."""
    if el is None:
        return None
    srgb = el.find(f"{_A}srgbClr")
    if srgb is not None and srgb.get("val"):
        return "#" + srgb.get("val").upper()
    sysc = el.find(f"{_A}sysClr")
    if sysc is not None and sysc.get("lastClr"):
        return "#" + sysc.get("lastClr").upper()
    return None


def extract_brand(template_path) -> dict:
    """Return {'accent','ink','font_head','font_body'} — any key may be missing on failure."""
    out: dict = {}
    try:
        with zipfile.ZipFile(template_path) as z:
            name = next((n for n in z.namelist()
                         if re.fullmatch(r"ppt/theme/theme\d+\.xml", n)), None)
            if not name:
                return {}
            root = ET.fromstring(z.read(name))
        clr = root.find(f".//{_A}clrScheme")
        if clr is not None:
            out["accent"] = _hex_from(clr.find(f"{_A}accent1"))
            out["ink"] = _hex_from(clr.find(f"{_A}dk2")) or _hex_from(clr.find(f"{_A}dk1"))
        fonts = root.find(f".//{_A}fontScheme")
        if fonts is not None:
            major = fonts.find(f"{_A}majorFont/{_A}latin")
            minor = fonts.find(f"{_A}minorFont/{_A}latin")
            if major is not None and major.get("typeface"):
                out["font_head"] = major.get("typeface")
            if minor is not None and minor.get("typeface"):
                out["font_body"] = minor.get("typeface")
    except Exception:  # noqa: BLE001 — a malformed template just yields no branding
        return {}
    # Drop empty values so callers can use dict.get() with their own defaults.
    return {k: v for k, v in out.items() if v}
