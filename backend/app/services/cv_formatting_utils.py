import logging
import re
from pathlib import Path
from typing import Any, List, Optional
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from ..config import FONTS_DIR

logger = logging.getLogger(__name__)


def normalize_contact_href(raw: str, is_email: bool = False) -> str:
    """Normalizes LinkedIn, GitHub, Portfolio, or Email into an actionable href/mailto URL."""
    val = (raw or "").strip()
    if not val:
        return ""
    if is_email or ("@" in val and not val.startswith("http")):
        return val if val.startswith("mailto:") else f"mailto:{val}"
    if val.startswith(("http://", "https://")):
        return val
    return f"https://{val.lstrip('/')}"


def clean_foreign_script_text(raw: Any, cv_language: str = "en") -> str:
    """Prevents foreign script contamination (e.g. Cyrillic) inside EN/KA CVs while preserving paragraph breaks."""
    s = str(raw or "")
    if not s:
        return ""
    s = re.sub(r"[\u0400-\u04FF]+", "", s)
    if cv_language == "en":
        s = re.sub(r"[\u10A0-\u10FF]+", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"[ \t]+([,.;:!?])", r"\1", s)
    return s.strip(" -–—•|")


def clean_bullets(highlights: Optional[List[Any]]) -> List[str]:
    """Filters out blank bullets and Markdown divider artifacts such as '--' or '---'."""
    if not highlights:
        return []
    result = []
    for h in highlights:
        s = str(h or "").strip()
        if s and not re.fullmatch(r"[-*_•–—.\s]+", s):
            result.append(s)
    return result


def format_pdf_mixed_script(text: str, base_font: str, georgian_font: str) -> str:
    """
    XML-escapes text and switches font runs inline so Georgian glyphs (Mkhedruli) always
    render in georgian_font even inside English CVs (and Latin spans keep base_font).
    """
    raw = str(text or "")
    if not raw or base_font == georgian_font or georgian_font == "Helvetica":
        return escape(raw)
    parts: List[str] = []
    for chunk in re.split(r"([\u10A0-\u10FF]+)", raw):
        if not chunk:
            continue
        esc_chunk = escape(chunk)
        if re.search(r"[\u10A0-\u10FF]", chunk):
            parts.append(f'<font name="{georgian_font}">{esc_chunk}</font>')
        else:
            parts.append(esc_chunk)
    return "".join(parts)


def register_unicode_font(prefer_georgian: bool = False) -> str:
    """
    Registers a Unicode TrueType font family (Normal, Bold, Italic, BoldItalic) in ReportLab
    with cross-platform support. Prioritizes Sylfaen when prefer_georgian=True for crisp Georgian rendering.
    """
    family_candidates: List[tuple[str, str, Optional[str], Optional[str], Optional[str]]] = []

    if FONTS_DIR.exists():
        for f in sorted(FONTS_DIR.glob("*.ttf")):
            if any(tag in f.stem.lower() for tag in ("-bold", "-italic", "-oblique", "bold", "italic")):
                continue
            stem_base = f.stem.replace("-Regular", "")
            bold_c = next(
                (p for p in [f.with_name(f"{stem_base}-Bold.ttf"), f.with_name(f"{stem_base}Bold.ttf")] if p.exists()),
                None,
            )
            italic_c = next(
                (p for p in [f.with_name(f"{stem_base}-Italic.ttf"), f.with_name(f"{stem_base}-Oblique.ttf")] if p.exists()),
                None,
            )
            bi_c = next(
                (p for p in [f.with_name(f"{stem_base}-BoldItalic.ttf"), f.with_name(f"{stem_base}-BoldOblique.ttf")] if p.exists()),
                None,
            )
            family_candidates.append(
                (f.stem, str(f), str(bold_c) if bold_c else None, str(italic_c) if italic_c else None, str(bi_c) if bi_c else None)
            )

    sylfaen_tuple = ("Sylfaen", "C:/Windows/Fonts/sylfaen.ttf", None, None, None)
    segoe_tuple = (
        "SegoeUI",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
        "C:/Windows/Fonts/segoeuiz.ttf",
    )
    if prefer_georgian:
        family_candidates.extend([sylfaen_tuple, segoe_tuple])
    else:
        family_candidates.extend([segoe_tuple, sylfaen_tuple])

    family_candidates.extend([
        (
            "ArialUnicode",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/ariali.ttf",
            "C:/Windows/Fonts/arialbi.ttf",
        ),
        (
            "FreeSans",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf",
        ),
        (
            "DejaVuSans",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        ),
        (
            "NotoSansGeorgian",
            "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansGeorgian-Bold.ttf",
            None,
            None,
        ),
        (
            "LiberationSans",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        ),
        ("ArialUnicodeMac", "/Library/Fonts/Arial Unicode.ttf", None, None, None),
        (
            "ArialMac",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
        ),
    ])

    for font_name, normal_path, bold_path, italic_path, bi_path in family_candidates:
        if not Path(normal_path).exists():
            continue
        try:
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, normal_path))
            bold_name = f"{font_name}-Bold"
            italic_name = f"{font_name}-Italic"
            bi_name = f"{font_name}-BoldItalic"
            b_file = bold_path if (bold_path and Path(bold_path).exists()) else normal_path
            i_file = italic_path if (italic_path and Path(italic_path).exists()) else normal_path
            bi_file = bi_path if (bi_path and Path(bi_path).exists()) else b_file
            for sub_name, sub_path in [(bold_name, b_file), (italic_name, i_file), (bi_name, bi_file)]:
                if sub_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(sub_name, sub_path))
            pdfmetrics.registerFontFamily(
                font_name,
                normal=font_name,
                bold=bold_name,
                italic=italic_name,
                boldItalic=bi_name,
            )
            return font_name
        except Exception as e:
            logger.debug(f"Could not register TTF family {font_name} ({normal_path}): {e}")
    return "Helvetica"


UNICODE_FONT_NAME = register_unicode_font(prefer_georgian=False)
GEORGIAN_PDF_FONT_NAME = register_unicode_font(prefer_georgian=True)
