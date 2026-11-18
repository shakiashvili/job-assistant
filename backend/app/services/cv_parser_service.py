import io
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

SUPPORTED_CV_EXTENSIONS = (".pdf", ".docx", ".doc", ".md", ".txt")


class CVParserService:
    """
    Universal Multi-Format CV & Skills Parser (.pdf, .docx, .md, .txt).
    Extracts plain UTF-8 text cleanly without third-party external binaries,
    rejects unreadable/corrupted/image-only files explicitly, and enriches parsed text
    into normalized candidate sections + explicit missing-field checks.
    """

    def extract_text_from_bytes(self, content: bytes, filename: str = "cv.md") -> str:
        ext = Path(filename or "cv.md").suffix.lower()
        if not content:
            raise ValueError("Uploaded file is empty.")

        if ext in (".md", ".txt", ""):
            text = content.decode("utf-8", errors="replace").strip()
            if not text:
                raise ValueError("Uploaded text/markdown file contains no readable text.")
            return text

        if ext == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Invalid PDF header: file does not start with %PDF-.")
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                if getattr(reader, "is_encrypted", False):
                    try:
                        reader.decrypt("")
                    except Exception as dec_err:
                        raise ValueError(f"Encrypted PDF cannot be read without password: {dec_err}")
                pages_text: List[str] = []
                for page in reader.pages:
                    extracted = (page.extract_text() or "").strip()
                    if extracted:
                        pages_text.append(extracted)
                full_text = "\n\n".join(pages_text).strip()
                if not full_text or len(full_text) < 15:
                    raise ValueError(
                        "PDF contains no selectable text (likely an image-only scan). "
                        "Export a text-based PDF, DOCX, or Markdown file."
                    )
                return self._normalize_extracted_plain_text(full_text)
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"Failed to parse PDF file: {e}")

        if ext in (".docx", ".doc"):
            if ext == ".docx" and not content.startswith(b"PK"):
                raise ValueError("Invalid DOCX header: file is not a valid Word .docx archive.")
            try:
                from docx import Document

                doc = Document(io.BytesIO(content))
                lines: List[str] = []
                for para in doc.paragraphs:
                    txt = (para.text or "").strip()
                    if txt:
                        lines.append(txt)
                for table in doc.tables:
                    for row in table.rows:
                        row_cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
                        if row_cells:
                            lines.append(" | ".join(dict.fromkeys(row_cells)))
                full_text = "\n".join(lines).strip()
                if not full_text or len(full_text) < 15:
                    raise ValueError("Word document contains no readable text.")
                return self._normalize_extracted_plain_text(full_text)
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"Failed to parse Word document: {e}")

        raise ValueError(
            f"Unsupported CV format '{ext}'. Supported formats: .pdf, .docx, .md, .txt."
        )

    def _normalize_extracted_plain_text(self, raw_text: str) -> str:
        """
        Adds clean markdown section headings around standard PDF/DOCX CV headers when missing,
        preserving all original lines truthfully so downstream parser extracts skills/experience cleanly.
        """
        lines = [ln.rstrip() for ln in raw_text.splitlines()]
        section_aliases = {
            "skills": "## Core Skills",
            "technical skills": "## Core Skills",
            "core competencies": "## Core Skills",
            "competencies": "## Core Skills",
            "technologies": "## Core Skills",
            "experience": "## Work Experience",
            "work experience": "## Work Experience",
            "professional experience": "## Work Experience",
            "employment history": "## Work Experience",
            "projects": "## Technical Projects",
            "technical projects": "## Technical Projects",
            "relevant projects": "## Technical Projects",
            "relevant qa & automation project": "## Technical Projects",
            "education": "## Education",
            "education & certifications": "## Education",
            "education & specialized training": "## Education",
            "certifications": "## Courses & Certifications",
            "courses & certifications": "## Courses & Certifications",
            "professional training & certifications": "## Courses & Certifications",
            "languages": "## Languages",
            "spoken languages": "## Languages",
            "summary": "## Summary",
            "professional summary": "## Summary",
            "profile": "## Summary",
        }
        out: List[str] = []
        for idx, ln in enumerate(lines):
            stripped = ln.strip()
            low = stripped.lower().rstrip(":")
            if idx == 0 and stripped and not stripped.startswith("#") and len(stripped.split()) <= 8:
                out.append(f"# {stripped}")
                continue
            if low in section_aliases and not stripped.startswith("#"):
                out.append(section_aliases[low])
                continue
            out.append(ln)
        return "\n".join(out).strip()

    @staticmethod
    def compute_missing_fields(profile_dict: Dict[str, Any]) -> Tuple[int, List[str]]:
        cand = profile_dict.get("candidate") if "candidate" in profile_dict else profile_dict
        if not isinstance(cand, dict):
            cand = {}
        skills_core = (
            (profile_dict.get("skills") or {}).get("core")
            if "skills" in profile_dict
            else profile_dict.get("all_skills")
        ) or []
        wh = profile_dict.get("work_history") or []
        edu = profile_dict.get("education") or []
        loc = cand.get("location")
        has_loc = bool(
            (isinstance(loc, dict) and (loc.get("city") or loc.get("country")))
            or (isinstance(loc, str) and loc.strip())
        )
        links = cand.get("links") if isinstance(cand.get("links"), dict) else {}
        has_links = bool(
            links.get("linkedin")
            or links.get("github")
            or links.get("portfolio")
            or profile_dict.get("linkedin_url")
            or profile_dict.get("github_url")
        )
        checks = {
            "full_name": bool(str(cand.get("full_name") or "").strip() and cand.get("full_name") != "Candidate"),
            "email": bool(str(cand.get("email") or "").strip() and "example.com" not in str(cand.get("email") or "")),
            "phone": bool(str(cand.get("phone") or "").strip()),
            "location": has_loc,
            "skills": bool(skills_core),
            "work_history": bool(wh),
            "education": bool(edu),
            "links": has_links,
        }
        missing = [k for k, ok in checks.items() if not ok]
        pct = int(round((sum(1 for ok in checks.values() if ok) / len(checks)) * 100))
        return pct, missing


cv_parser_service = CVParserService()
