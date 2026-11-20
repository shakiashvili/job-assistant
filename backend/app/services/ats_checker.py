import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def _inspect_single_column_layout(reader: PdfReader) -> tuple[bool, bool]:
    """
    Inspects text matrix + CTM coordinates across PDF pages using pypdf visitor callbacks.
    Returns `(layout_check_performed, single_column_layout_ok)`.
    """
    total_fragments = 0
    total_lines = 0
    dual_column_lines = 0

    for page in reader.pages:
        try:
            page_width = float(page.mediabox.width or 595.0)
        except Exception:
            page_width = 595.0
        rows: Dict[float, List[tuple[float, str]]] = {}

        def _visitor(text: str, cm: Any, tm: Any, _font_dict: Any, _font_size: Any) -> None:
            nonlocal total_fragments
            clean = (text or "").strip()
            if len(clean) < 2:
                return
            try:
                tx = float(tm[4]) if tm and len(tm) >= 6 else 0.0
                ty = float(tm[5]) if tm and len(tm) >= 6 else 0.0
                if cm and len(cm) >= 6:
                    x = float(cm[0]) * tx + float(cm[2]) * ty + float(cm[4])
                    y = float(cm[1]) * tx + float(cm[3]) * ty + float(cm[5])
                else:
                    x, y = tx, ty
            except Exception:
                return
            total_fragments += 1
            y_bin = round(y / 4.0) * 4.0
            rows.setdefault(y_bin, []).append((x, clean))

        try:
            page.extract_text(visitor_text=_visitor)
        except Exception:
            continue

        for spans in rows.values():
            total_lines += 1
            left_spans = [s for s in spans if s[0] < page_width * 0.42]
            right_spans = [s for s in spans if s[0] >= page_width * 0.48]
            if left_spans and right_spans:
                right_text = " ".join(s[1] for s in right_spans).strip()
                min_left = min(s[0] for s in left_spans)
                max_right = max(s[0] for s in right_spans)
                if (max_right - min_left) >= (page_width * 0.25) and len(right_text) >= 8:
                    dual_column_lines += 1

    if total_fragments == 0 or total_lines == 0:
        return False, False
    is_single_col = not (dual_column_lines >= 4 and (dual_column_lines / total_lines) >= 0.20)
    return True, is_single_col


def check_pdf_ats_parseability(
    pdf_path: Path,
    candidate_name: str = "",
    expected_email: str = "",
    expected_phone: str = "",
    expected_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Deterministic PDF text extraction and geometry check via pypdf.
    Verifies selectable text extraction, single/two-page length, mojibake/null-byte cleanliness,
    full candidate name tokens, expected candidate contact details, coordinate-based
    single-column text flow, core section headings (EN/KA), and keyword survival.
    """
    path = Path(pdf_path)
    if not path.exists() or not path.is_file():
        return {
            "audit_label": "PDF Text Extraction & Layout Check",
            "status": "FAIL",
            "score": 0,
            "page_count": 0,
            "selectable_text_ok": False,
            "extracted_char_count": 0,
            "candidate_name_present": False,
            "contact_present": False,
            "mojibake_free": False,
            "layout_check_performed": False,
            "single_column_layout_ok": False,
            "sections_detected": [],
            "keywords_extracted": [],
            "warnings": ["Generated PDF file not found on disk."],
        }

    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        page_texts = [p.extract_text() or "" for p in reader.pages]
        full_text = "\n".join(page_texts)
        layout_checked, single_col_ok = _inspect_single_column_layout(reader)
    except Exception as exc:
        logger.warning("ATS PDF reader failed on %s: %s", path.name, exc)
        return {
            "audit_label": "PDF Text Extraction & Layout Check",
            "status": "FAIL",
            "score": 0,
            "page_count": 0,
            "selectable_text_ok": False,
            "extracted_char_count": 0,
            "candidate_name_present": False,
            "contact_present": False,
            "mojibake_free": False,
            "layout_check_performed": False,
            "single_column_layout_ok": False,
            "sections_detected": [],
            "keywords_extracted": [],
            "warnings": [f"PDF stream failed to parse cleanly: {exc}"],
        }

    stripped = full_text.strip()
    char_count = len(stripped)
    lower_text = stripped.lower()
    selectable_ok = char_count >= 80
    mojibake_free = ("\ufffd" not in full_text) and ("\x00" not in full_text)

    name_tokens = [tok.lower() for tok in re.split(r"\s+", (candidate_name or "").strip()) if len(tok) >= 2]
    name_ok = bool(name_tokens) and all(tok in lower_text for tok in name_tokens)

    clean_email = (expected_email or "").strip().lower()
    if clean_email == "candidate@example.com":
        clean_email = ""
    raw_phone_digits = re.sub(r"\D+", "", (expected_phone or "").strip())
    clean_phone_digits = raw_phone_digits if len(raw_phone_digits) >= 6 else ""

    if clean_email or clean_phone_digits:
        email_ok = (clean_email in lower_text) if clean_email else True
        extracted_digits = re.sub(r"\D+", "", full_text)
        phone_ok = (clean_phone_digits in extracted_digits) if clean_phone_digits else True
        contact_ok = email_ok and phone_ok
    else:
        contact_ok = False

    section_patterns = {
        "Summary": r"(?:professional\s+summary|executive\s+profile|პროფესიული\s+მიმოხილვა)",
        "Skills": r"(?:technical\s+skills|ტექნიკური\s+კომპეტენციები)",
        "Experience": r"(?:professional\s+experience|work\s+experience|სამუშაო\s+გამოცდილება)",
        "Education": r"(?:education|განათლება)",
    }
    sections_detected = [
        label for label, pat in section_patterns.items()
        if re.search(pat, lower_text, re.IGNORECASE)
    ]

    kw_found: List[str] = []
    for kw in (expected_keywords or [])[:15]:
        k_clean = str(kw or "").strip()
        if k_clean and k_clean.lower() in lower_text and k_clean not in kw_found:
            kw_found.append(k_clean)

    warnings: List[str] = []
    if not selectable_ok:
        warnings.append("Selectable PDF text is sparse or missing (<80 extracted chars).")
    if page_count > 2:
        warnings.append(f"Resume spans {page_count} pages; 1-2 pages recommended for ATS.")
    if not mojibake_free:
        warnings.append("Detected replacement/unmapped glyph characters in extracted PDF stream.")
    if not layout_checked:
        warnings.append("Coordinate-based layout inspection could not inspect text geometry.")
    elif not single_col_ok:
        warnings.append("Detected multi-column text placement; single-column flow is safer for ATS parsers.")
    if not name_tokens:
        warnings.append("Expected candidate full name was not supplied for identity verification.")
    elif not name_ok:
        warnings.append("Full candidate name tokens were not all found in extracted PDF text.")
    if not (clean_email or clean_phone_digits):
        warnings.append("Expected candidate email/phone was not supplied for contact verification.")
    elif not contact_ok:
        warnings.append("Expected candidate email or phone number is missing from extracted PDF text.")
    if len(sections_detected) < 2:
        warnings.append("Fewer than 2 standard CV section headings detected by text extractor.")

    score = 0
    if selectable_ok:
        score += 30
    if mojibake_free:
        score += 15
    if single_col_ok:
        score += 15
    if name_ok:
        score += 15
    if contact_ok:
        score += 15
    score += min(10, len(sections_detected) * 5)
    if page_count > 2:
        score = max(0, score - 10)

    status = (
        "PASS"
        if (score >= 75 and selectable_ok and mojibake_free and single_col_ok and name_ok and contact_ok)
        else "WARN"
    )
    return {
        "audit_label": "PDF Text Extraction & Layout Check",
        "status": status,
        "score": min(100, score),
        "page_count": page_count,
        "selectable_text_ok": selectable_ok,
        "extracted_char_count": char_count,
        "candidate_name_present": name_ok,
        "contact_present": contact_ok,
        "mojibake_free": mojibake_free,
        "layout_check_performed": layout_checked,
        "single_column_layout_ok": single_col_ok,
        "sections_detected": sections_detected,
        "keywords_extracted": kw_found,
        "warnings": warnings,
    }
