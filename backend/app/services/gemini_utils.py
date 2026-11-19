import json
import re
import secrets
from typing import Any, Dict, Optional, Tuple


def sanitize_untrusted_input(text: str, max_chars: int = 10000) -> str:
    """Sanitizes untrusted text to prevent XML tag boundary escapes."""
    if not text:
        return ""
    cleaned = re.sub(
        r"</?\s*(?:job_posting|job_requirements|candidate_skills)[a-zA-Z0-9_-]*\s*>",
        "",
        str(text),
        flags=re.IGNORECASE,
    )
    return cleaned[:max_chars]


def wrap_untrusted_input(tag_prefix: str, text: str, max_chars: int = 10000) -> Tuple[str, str]:
    """Wraps untrusted input inside a per-call cryptographic nonce XML tag."""
    nonce = secrets.token_hex(6)
    tag = f"{tag_prefix}_{nonce}"
    safe_body = sanitize_untrusted_input(text, max_chars=max_chars).replace(f"</{tag}>", "")
    return tag, f"<{tag}>\n{safe_body}\n</{tag}>"


def safe_parse_json(text: str) -> Optional[Any]:
    """Safely extracts and parses JSON (object or array) even if wrapped in markdown fences."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
            match = re.search(pattern, cleaned)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
    return None


# Multi-industry skill dictionary (Domain-Agnostic: Tech, Logistics, Finance, Marketing, Sales, HR, Legal/Public, Support, Hospitality, Healthcare)
MULTI_INDUSTRY_SKILLS: Dict[str, list[str]] = {
    "qa_tech": [
        "playwright", "cypress", "selenium", "python", "typescript", "javascript",
        "pytest", "jest", "postman", "rest api", "graphql", "docker", "ci/cd",
        "github actions", "gitlab ci", "sql", "aws", "kubernetes", "k6", "jira", "xray", "bdd"
    ],
    "software_data": [
        "fastapi", "django", "flask", "react", "node.js", "postgresql", "mysql", "mongodb",
        "redis", "linux", "git", "power bi", "tableau", "looker", "pandas", "excel", "etl", "data quality"
    ],
    "logistics_supply_chain": [
        "logistics", "supply chain", "procurement", "warehouse", "wms", "erp", "sap",
        "incoterms", "customs", "freight", "dispatch", "inventory", "fleet", "1c", "import", "export", "forwarding"
    ],
    "finance_accounting": [
        "accounting", "financial analysis", "bookkeeping", "ifrs", "oris", "1c accounting", "excel",
        "financial modeling", "audit", "tax", "rs.ge", "budgeting", "accounts payable", "accounts receivable", "reconciliation"
    ],
    "marketing_sales": [
        "digital marketing", "seo", "sem", "google ads", "meta ads", "google analytics", "ga4",
        "smm", "copywriting", "content marketing", "hubspot", "crm", "b2b sales", "lead generation", "figma", "canva"
    ],
    "hr_legal_public": [
        "recruiting", "talent acquisition", "human resources", "hris", "onboarding", "public administration",
        "legal research", "compliance", "contract drafting", "procurement law", "project management", "agile", "scrum", "notion"
    ],
    "hospitality_reception": [
        "front desk", "receptionist", "opera pms", "fidelio", "guest relations",
        "check-in", "check-out", "booking.com", "expedia", "reservations", "concierge",
        "hospitality", "vip protocol", "pos", "phone etiquette", "night audit", "billing"
    ],
    "customer_service": [
        "customer service", "customer support", "client care", "zendesk", "intercom",
        "salesforce", "crm", "live chat", "inbound", "outbound", "conflict resolution",
        "de-escalation", "csat", "sla", "ticketing", "email support", "call center", "kyc", "technical support"
    ],
    "healthcare_hospital": [
        "patient coordinator", "medical receptionist", "hospital", "clinic", "emr", "ehr",
        "patient intake", "patient registration", "triage", "appointment scheduling",
        "health insurance", "medical billing", "icd-10", "patient care", "clinical"
    ]
}

GEORGIAN_SKILL_TRANSLATIONS: Dict[str, str] = {
    "Front Desk": "მიმღების (Front Desk) მართვა",
    "Receptionist": "ადმინისტრატორი / რეცეფციონისტი",
    "Opera PMS": "Opera PMS სისტემები",
    "Fidelio": "Fidelio სასტუმროს პროგრამა",
    "Guest Relations": "სტუმრებთან ურთიერთობა (Guest Relations)",
    "Check-In": "სტუმრების რეგისტრაცია (Check-in / Check-out)",
    "Reservations": "ჯავშნების მართვა (Booking / Expedia)",
    "Hospitality": "სტუმარმასპინძლობის სტანდარტები",
    "Customer Service": "მომხმარებელთა მომსახურება",
    "Customer Support": "მომხმარებელთა მხარდაჭერა",
    "Zendesk": "Zendesk / CRM სისტემები",
    "CRM": "CRM ბაზებთან მუშაობა",
    "Live Chat": "ონლაინ ჩატი და სატელეფონო კომუნიკაცია",
    "Conflict Resolution": "კონფლიქტური სიტუაციების მართვა",
    "Patient Coordinator": "პაციენტთა კოორდინაცია",
    "Medical Receptionist": "სამედიცინო რეგისტრატორი",
    "EMR": "ელექტრონული სამედიცინო ისტორიები (EMR/EHR)",
    "Health Insurance": "სამედიცინო დაზღვევასთან მუშაობა",
    "Appointment Scheduling": "ექიმთან ვიზიტების დაგეგმვა",
    "Playwright": "Playwright ტესტირების ავტომატიზაცია",
    "Python": "Python პროგრამირება",
    "TypeScript": "TypeScript / JavaScript",
    "REST API": "REST API ტესტირება",
    "Docker": "Docker & CI/CD ინფრასტრუქტურა",
}
