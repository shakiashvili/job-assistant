import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..db.models import User
from ..db.profile_repository import ground_truth_store
from ..services.auth_service import get_current_user
from ..services.gemini_service import gemini_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/b2b", tags=["Georgia & Global Remote B2B Toolkit"])

DEFAULT_FX_TO_GEL = {
    "GEL": 1.0,
    "USD": 2.72,
    "EUR": 2.95,
    "GBP": 3.45,
}


class TaxCalculatorRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Monthly or hourly compensation amount")
    currency: str = Field("USD", pattern="^(USD|EUR|GBP|GEL)$")
    billing_period: str = Field("monthly", pattern="^(monthly|hourly|annual)$")
    hours_per_month: int = Field(160, ge=20, le=260)
    custom_fx_to_gel: Optional[float] = Field(None, gt=0)
    include_pension_for_labor: bool = True
    transfer_fee_pct: float = Field(0.5, ge=0.0, le=5.0)


class B2BProposalRequest(BaseModel):
    target_role: str = Field(..., min_length=2)
    target_company: str = Field(..., min_length=1)
    client_region: str = Field("EU / Worldwide", description="e.g., EU (CET), UK, US East, Worldwide")
    contract_rate: Optional[str] = None
    requirements_snippet: Optional[str] = None
    language: str = Field("en", pattern="^(en|ka)$")


@router.post("/tax-calculator")
def calculate_georgia_b2b_net(req: TaxCalculatorRequest) -> Dict[str, Any]:
    """
    Compares Georgian Individual Entrepreneur 1% Small Business B2B taxation (up to 500,000 GEL/year)
    against a standard Georgian labor contract (20% Personal Income Tax + 2% employee pension).
    """
    cur = req.currency.upper()
    fx = float(req.custom_fx_to_gel or DEFAULT_FX_TO_GEL.get(cur, 1.0))

    if req.billing_period == "hourly":
        monthly_orig = req.amount * req.hours_per_month
    elif req.billing_period == "annual":
        monthly_orig = req.amount / 12.0
    else:
        monthly_orig = req.amount

    monthly_gross_gel = monthly_orig * fx
    annual_gross_gel = monthly_gross_gel * 12.0

    # 1. Georgia IE Small Business Status (1% under 500,000 GEL/yr, 3% excess)
    under_500k_cap = annual_gross_gel <= 500_000.0
    b2b_tax_rate = 0.01 if under_500k_cap else 0.03
    b2b_tax_gel = monthly_gross_gel * b2b_tax_rate
    transfer_fee_gel = monthly_gross_gel * (req.transfer_fee_pct / 100.0) if cur != "GEL" else 0.0
    b2b_net_gel = monthly_gross_gel - b2b_tax_gel - transfer_fee_gel
    b2b_net_orig = b2b_net_gel / fx

    # 2. Standard Georgian Labor Contract (2% employee pension + 20% income tax on remaining 98% = 21.6% total)
    pension_rate = 0.02 if req.include_pension_for_labor else 0.0
    pension_gel = monthly_gross_gel * pension_rate
    taxable_labor_gel = monthly_gross_gel - pension_gel
    pit_gel = taxable_labor_gel * 0.20
    labor_net_gel = monthly_gross_gel - pension_gel - pit_gel
    labor_net_orig = labor_net_gel / fx

    monthly_savings_gel = max(0.0, b2b_net_gel - labor_net_gel)
    effective_hourly_net_orig = b2b_net_orig / max(req.hours_per_month, 1)

    return {
        "currency": cur,
        "fx_to_gel": round(fx, 4),
        "monthly_gross_orig": round(monthly_orig, 2),
        "monthly_gross_gel": round(monthly_gross_gel, 2),
        "annual_gross_gel": round(annual_gross_gel, 2),
        "under_500k_cap": under_500k_cap,
        "b2b_small_business": {
            "tax_rate_pct": round(b2b_tax_rate * 100, 1),
            "tax_gel": round(b2b_tax_gel, 2),
            "transfer_fee_gel": round(transfer_fee_gel, 2),
            "net_gel": round(b2b_net_gel, 2),
            "net_orig": round(b2b_net_orig, 2),
            "hourly_net_orig": round(effective_hourly_net_orig, 2),
        },
        "standard_labor_contract": {
            "pension_gel": round(pension_gel, 2),
            "income_tax_gel": round(pit_gel, 2),
            "net_gel": round(labor_net_gel, 2),
            "net_orig": round(labor_net_orig, 2),
        },
        "monthly_b2b_advantage_gel": round(monthly_savings_gel, 2),
        "cap_usage_pct": round(min(999.0, (annual_gross_gel / 500_000.0) * 100.0), 1),
        "notes": [
            "Georgian Small Business status applies 1% tax on revenue up to 500,000 GEL per calendar year (3% if exceeded).",
            "Foreign B2B digital service exports are outside Georgian VAT territorial scope (consult a Georgian CPA for exact classification).",
        ],
    }


@router.get("/timezone-matrix")
def get_tbilisi_timezone_matrix(work_start_get: int = 11, work_end_get: int = 19) -> Dict[str, Any]:
    """
    Computes exact working-hour overlap between Georgia Time (GET, UTC+4 fixed year-round)
    and key remote hiring hubs across Europe, UK, Middle East, and North America.
    """
    start_get = max(0, min(23, int(work_start_get)))
    end_get = max(1, min(24, int(work_end_get)))
    if end_get <= start_get:
        end_get = min(24, start_get + 8)

    ge_hours = set(range(start_get, end_get))

    regions = [
        {"region": "UAE / Gulf (Dubai GST)", "utc_offset": 4, "typical_window": "09:00–17:00"},
        {"region": "Central Europe Standard (Berlin / Warsaw CET)", "utc_offset": 1, "typical_window": "09:00–17:00"},
        {"region": "Central Europe Summer (CEST)", "utc_offset": 2, "typical_window": "09:00–17:00"},
        {"region": "United Kingdom (London GMT)", "utc_offset": 0, "typical_window": "09:00–17:00"},
        {"region": "US East Coast (New York EST)", "utc_offset": -5, "typical_window": "09:00–17:00"},
        {"region": "US West Coast (San Francisco PST)", "utc_offset": -8, "typical_window": "09:00–17:00"},
    ]

    matrix: List[Dict[str, Any]] = []
    for reg in regions:
        diff = 4 - reg["utc_offset"]  # How many hours Georgia is ahead
        client_start_in_get = 9 + diff
        client_end_in_get = 17 + diff
        client_hours_in_get = {h % 24 for h in range(client_start_in_get, client_end_in_get)}
        overlap = sorted(ge_hours & client_hours_in_get)
        recommended_get_start = max(8, min(16, client_start_in_get))
        matrix.append({
            "region": reg["region"],
            "hours_behind_tbilisi": diff,
            "client_hours_tbilisi_time": f"{client_start_in_get % 24:02d}:00–{client_end_in_get % 24:02d}:00 GET",
            "overlap_hours_count": len(overlap),
            "overlap_window_get": (
                f"{min(overlap):02d}:00–{max(overlap) + 1:02d}:00 GET" if overlap else "Async handoff only"
            ),
            "recommended_shift_get": f"{recommended_get_start:02d}:00–{(recommended_get_start + 8) % 24:02d}:00 GET",
        })

    return {
        "base_timezone": "Asia/Tbilisi (GET, UTC+4, No DST)",
        "selected_shift_get": f"{start_get:02d}:00–{end_get:02d}:00 GET",
        "regions": matrix,
    }


@router.post("/proposal")
def generate_b2b_contractor_proposal(
    req: B2BProposalRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Generates a practical, concise B2B remote contractor pitch & invoicing readiness snippet
    strictly grounded in the candidate's saved Profile Vault skills and experience.
    """
    owner = current_user.email if current_user.email != "guest@talentflow.local" else None
    uid = current_user.id if owner else None
    gt = ground_truth_store.get_data(owner_email=owner, user_id=uid)
    cand = gt.get("candidate") or {}
    full_name = str(cand.get("full_name") or current_user.full_name or "Candidate").strip()
    core_skills = [str(s) for s in ((gt.get("skills") or {}).get("core") or [])][:6]
    skills_str = ", ".join(core_skills) if core_skills else req.target_role

    if req.language == "ka":
        subject = f"B2B კონტრაქტორი: {req.target_role} — {full_name} (UTC+4 თბილისი)"
        proposal = (
            f"გამარჯობა {req.target_company}-ს გუნდს,\n\n"
            f"გწერთ {req.target_role}-ის დისტანციურ (Remote B2B) პოზიციასთან დაკავშირებით. "
            f"ვმუშაობ თბილისიდან (UTC+4 — სრული სინქრონიზაცია {req.client_region}-ის სამუშაო საათებთან) "
            f"და მაქვს პრაქტიკული გამოცდილება შემდეგ მიმართულებებში: {skills_str}.\n\n"
            f"B2B თანამშრომლობის დეტალები:\n"
            f"• კონტრაქტი: დამოუკიდებელი B2B კონტრაქტორი (ინდ. მეწარმე საქართველოში, ვიზის/სპონსორობის საჭიროების გარეშე)\n"
            f"• ანგარიშსწორება: ყოველთვიური ინვოისი USD/EUR-ში (SWIFT / Wise / Payoneer)\n"
            + (f"• შემოთავაზებული განაკვეთი: {req.contract_rate}\n" if req.contract_rate else "")
            + f"\nსიამოვნებით განვიხილავ მოკლე გაცნობით ზარს.\n\nპატივისცემით,\n{full_name}"
        )
        return {"subject": subject, "proposal_text": proposal, "language": "ka"}

    # Try concise Gemini refinement when live key is present, keeping strict factual grounding
    if gemini_service.is_available and req.requirements_snippet:
        prompt = (
            f"Write a concise, natural 130-word B2B remote contractor outreach proposal for {full_name} "
            f"applying for '{req.target_role}' at '{req.target_company}' ({req.client_region}). "
            f"Verified skills ONLY: {skills_str}. Key requirements: {req.requirements_snippet[:800]}. "
            f"Explicitly highlight: based in Tbilisi (UTC+4 with seamless overlap for {req.client_region}), "
            f"ready for direct B2B invoicing (USD/EUR via SWIFT/Wise/Deel) with zero visa sponsorship needed. "
            f"Do not fabricate metrics or unverified companies."
        )
        try:
            ai_txt = gemini_service.generate_text(
                prompt,
                task_type="b2b_proposal",
                model_tier="fast",
                user_id=uid,
            )
            if ai_txt and len(ai_txt.strip()) >= 80:
                return {
                    "subject": f"Remote B2B Contractor — {req.target_role} ({full_name})",
                    "proposal_text": ai_txt.strip(),
                    "language": "en",
                }
        except Exception:
            pass

    subject = f"Remote B2B Contractor — {req.target_role} | {full_name} (UTC+4)"
    rate_line = f"- Proposed Rate: {req.contract_rate}\n" if req.contract_rate else ""
    proposal = (
        f"Hi {req.target_company} Team,\n\n"
        f"I am reaching out regarding your {req.target_role} opening as a remote B2B specialist with hands-on experience in {skills_str}.\n\n"
        f"Why B2B engagement is frictionless with me:\n"
        f"- Timezone Overlap: Based in Tbilisi (UTC+4, DST-free), providing full daily overlap with {req.client_region} standups and code/QA reviews.\n"
        f"- Zero Sponsorship Overhead: Registered independent B2B contractor in Georgia billing cleanly via monthly invoice (USD/EUR SWIFT, Wise, Payoneer, or Deel/Remote).\n"
        f"{rate_line}\n"
        f"Happy to share work samples or jump on a brief intro call this week.\n\n"
        f"Best regards,\n{full_name}"
    )
    return {"subject": subject, "proposal_text": proposal, "language": "en"}
