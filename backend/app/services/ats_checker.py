import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pypdf import PdfReader

logger = logging.getLogger(__name__)


def check_pdf_ats_parseability(
    pdf_path: Path,
    candidate_name: str = "",
    expected_email: str = "",
    expected_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Deterministic ATS PDF parseability audit via pypdf text extraction.
    Checks selectable text extraction, single/two-page ergonomics, mojibake/null bytes,
    candidate name & contact extractability, core section headings (EN/KA), and keyword survival.
    """
    path = Path(pdf_path)
    if not path.exists() or not path.is_file():
        return {
            "status": "FAIL",
            "score": 0,
            "page_count": 0,
            "selectable_text_ok": False,
            "extracted_char_count": 0,
            "candidate_name_present": False,
            "contact_present": False,
            "mojibake_free": False,
            "single_column_layout_ok": True,
            "sections_detected": [],
            "keywords_extracted": [],
            "warnings": ["Generated PDF file not found on disk."],
        }

    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        page_texts = [p.extract_text() or "" for p in reader.pages]
        full_text = "\n".join(page_texts)
    except Exception as exc:
        logger.warning("ATS PDF reader failed on %s: %s", path.name, exc)
        return {
            "status": "FAIL",
            "score": 0,
            "page_count": 0,
            "selectable_text_ok": False,
            "extracted_char_count": 0,
            "candidate_name_present": False,
            "contact_present": False,
            "mojibake_free": False,
            "single_column_layout_ok": True,
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
    name_ok = any(tok in lower_text for tok in name_tokens) if name_tokens else bool(char_count >= 80)

    clean_email = (expected_email or "").strip().lower()
    contact_ok = bool(
        (clean_email and clean_email != "candidate@example.com" and clean_email in lower_text)
        or re.search(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", lower_text)
        or re.search(r"(?:linkedin|github)\.com|https?://|\+\d{6,}", lower_text)
    )

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
    if not name_ok:
        warnings.append("Candidate name was not cleanly detected in extracted PDF text.")
    if not contact_ok:
        warnings.append("No email, phone, or link extracted from PDF text.")
    if len(sections_detected) < 2:
        warnings.append("Fewer than 2 standard CV section headings detected by ATS parser.")

    score = 0
    if selectable_ok:
        score += 35
    if mojibake_free:
        score += 20
    if name_ok:
        score += 15
    if contact_ok:
        score += 15
    score += min(15, len(sections_detected) * 5)
    if page_count > 2:
        score = max(0, score - 10)

    status = "PASS" if (score >= 75 and selectable_ok and mojibake_free) else "WARN"
    return {
        "status": status,
        "score": min(100, score),
        "page_count": page_count,
        "selectable_text_ok": selectable_ok,
        "extracted_char_count": char_count,
        "candidate_name_present": name_ok,
        "contact_present": contact_ok,
        "mojibake_free": mojibake_free,
        "single_column_layout_ok": True,
        "sections_detected": sections_detected,
        "keywords_extracted": kw_found,
        "warnings": warnings,
    }
