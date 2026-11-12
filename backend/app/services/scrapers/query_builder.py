import json
import logging
from typing import Dict, Any, List, Optional
from urllib.parse import quote_plus
from pydantic import BaseModel, Field
from ...config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


class SearchQueryPackage(BaseModel):
    target_role: str = "Specialist"
    detected_industry: str = "General Professional"
    primary_queries_ge: List[str] = Field(default_factory=list)
    adjacent_queries_ge: List[str] = Field(default_factory=list)
    internship_queries: List[str] = Field(default_factory=lambda: ["სტაჟიორი", "დამწყები", "Junior", "Trainee"])
    remote_keywords_int: List[str] = Field(default_factory=list)
    jobs_ge_urls: List[str] = Field(default_factory=list)
    hr_ge_urls: List[str] = Field(default_factory=list)
    headhunter_urls: List[str] = Field(default_factory=list)
    hr_gov_queries: List[str] = Field(default_factory=list)
    djinni_url: Optional[str] = None
    dou_url: Optional[str] = None
    justjoin_url: Optional[str] = None
    domain_keywords: List[str] = Field(default_factory=list)
    adjacent_keywords: List[str] = Field(default_factory=list)


_DOMAIN_QUERY_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "qa_tech": {
        "primary_ge": ["QA", "Tester"],
        "adjacent_ge": ["Support", "SQL"],
        "remote_int": ["QA", "Tester", "Automation"],
        "is_it_category": True,
        "djinni_kw": "QA",
        "dou_cat": "QA",
        "justjoin_cat": "testing",
        "domain_kw": ["qa", "quality assurance", "tester", "test engineer", "sdet", "automation", "playwright", "cypress", "selenium", "ტესტ"],
        "adjacent_kw": ["technical support", "application support", "data quality", "sql", "python", "integration engineer", "it operations", "helpdesk", "მხარდაჭერ", "ანალიტიკ"],
    },
    "software_engineering": {
        "primary_ge": ["Developer", "პროგრამისტი"],
        "adjacent_ge": ["QA", "Support"],
        "remote_int": ["Python", "Developer", "JavaScript"],
        "is_it_category": True,
        "djinni_kw": "Python",
        "dou_cat": "Python",
        "justjoin_cat": "python",
        "domain_kw": ["developer", "engineer", "programmer", "backend", "frontend", "full stack", "python", "typescript", "დეველოპერ", "პროგრამისტ"],
        "adjacent_kw": ["qa", "automation", "devops", "technical support", "sql", "data", "ტესტ", "მხარდაჭერ"],
    },
    "data_analytics": {
        "primary_ge": ["Analyst", "SQL"],
        "adjacent_ge": ["QA", "Operations"],
        "remote_int": ["Data Analyst", "BI"],
        "is_it_category": True,
        "djinni_kw": "Data+Analyst",
        "dou_cat": "Analyst",
        "justjoin_cat": "data",
        "domain_kw": ["analyst", "data", "power bi", "tableau", "sql", "reporting", "ანალიტიკოს"],
        "adjacent_kw": ["qa", "finance", "operations", "excel", "python", "ფინანს"],
    },
    "logistics_supply_chain": {
        "primary_ge": ["ლოჯისტიკა", "Logistics"],
        "adjacent_ge": ["შესყიდვები", "Operations"],
        "remote_int": ["Logistics", "Supply Chain"],
        "is_it_category": False,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["logistics", "supply chain", "procurement", "warehouse", "dispatch", "freight", "customs", "ლოჯისტიკ", "შესყიდვ", "საწყობ", "მომარაგებ"],
        "adjacent_kw": ["operations", "import", "export", "inventory", "coordinator", "ოპერაციებ", "კოორდინატორ", "ადმინისტრატორ"],
    },
    "finance_accounting": {
        "primary_ge": ["ბუღალტერი", "Finance"],
        "adjacent_ge": ["Audit", "Operations"],
        "remote_int": ["Finance", "Analyst"],
        "is_it_category": False,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["finance", "accountant", "accounting", "audit", "bookkeeper", "ifrs", "1c", "oris", "ბუღალტ", "ფინანს", "აუდიტ"],
        "adjacent_kw": ["analyst", "billing", "treasury", "operations", "excel", "ოპერაციებ", "ანალიტიკ"],
    },
    "marketing_growth": {
        "primary_ge": ["მარკეტინგი", "Marketing"],
        "adjacent_ge": ["Content", "Sales"],
        "remote_int": ["Marketing", "SEO"],
        "is_it_category": False,
        "djinni_kw": "Marketing",
        "dou_cat": "Marketing",
        "justjoin_cat": None,
        "domain_kw": ["marketing", "seo", "smm", "social media", "copywriter", "ads", "brand", "მარკეტინგ", "კონტენტ"],
        "adjacent_kw": ["sales", "pr", "communications", "e-commerce", "გაყიდვ", "კომუნიკაცი"],
    },
    "sales_bd": {
        "primary_ge": ["გაყიდვები", "Sales"],
        "adjacent_ge": ["Support", "Account"],
        "remote_int": ["Sales", "Business Development"],
        "is_it_category": False,
        "djinni_kw": "Sales",
        "dou_cat": "Sales",
        "justjoin_cat": None,
        "domain_kw": ["sales", "business development", "account manager", "b2b", "გაყიდვ", "კონსულტანტ"],
        "adjacent_kw": ["customer", "support", "crm", "onboarding", "marketing", "მომხმარებელ"],
    },
    "hr_recruiting": {
        "primary_ge": ["HR", "ადამიანური რესურსები"],
        "adjacent_ge": ["Admin", "Coordinator"],
        "remote_int": ["HR", "Recruiter"],
        "is_it_category": False,
        "djinni_kw": "HR",
        "dou_cat": "HR",
        "justjoin_cat": None,
        "domain_kw": ["hr", "recruiter", "talent acquisition", "human resources", "onboarding", "ადამიანური რესურს", "რეკრუტ"],
        "adjacent_kw": ["office manager", "coordinator", "administrative", "operations", "ადმინისტრ"],
    },
    "public_admin_legal": {
        "primary_ge": ["იურისტი", "Legal"],
        "adjacent_ge": ["ადმინისტრაციული", "Coordinator"],
        "remote_int": ["Legal", "Compliance"],
        "is_it_category": False,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["legal", "lawyer", "compliance", "policy", "public administration", "იურისტ", "სამართლ", "შესყიდვ", "ადმინისტრაცი"],
        "adjacent_kw": ["coordinator", "specialist", "clerk", "analyst", "სტაჟიორი", "სპეციალისტ"],
    },
    "receptionist_hospitality": {
        "primary_ge": ["Receptionist", "მიმღები"],
        "adjacent_ge": ["ადმინისტრატორი", "Hospitality"],
        "remote_int": [],
        "is_it_category": False,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["receptionist", "front desk", "hospitality", "concierge", "hotel", "guest", "მიმღები", "რეცეფციონისტი", "სასტუმრო", "ადმინისტრატორი"],
        "adjacent_kw": ["customer service", "office manager", "coordinator", "მომხმარებელ", "მენეჯერი"],
    },
    "healthcare_hospital": {
        "primary_ge": ["სამედიცინო", "Medical"],
        "adjacent_ge": ["კლინიკა", "Coordinator"],
        "remote_int": [],
        "is_it_category": False,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["medical", "hospital", "clinic", "patient", "coordinator", "სამედიცინო", "კლინიკა", "პაციენტ", "რეგისტრატორი"],
        "adjacent_kw": ["reception", "support", "administrator", "ადმინისტრატორი", "ოპერატორი"],
    },
    "customer_service": {
        "primary_ge": ["Support", "მხარდაჭერა"],
        "adjacent_ge": ["Customer", "QA"],
        "remote_int": ["Support"],
        "is_it_category": False,
        "djinni_kw": "Support",
        "dou_cat": "Support",
        "justjoin_cat": "support",
        "domain_kw": ["support", "customer service", "client care", "call center", "helpdesk", "მხარდაჭერა", "ოპერატორი", "ქოლ"],
        "adjacent_kw": ["qa", "manual testing", "onboarding", "sales", "coordinator", "ადმინისტრატორი"],
    },
}


def build_search_queries(
    parsed_skills: Optional[Dict[str, Any]] = None,
    headline: str = "",
) -> Dict[str, Any]:
    """
    Universal Dynamic Real-Time Search Query Generator (query_builder.py).
    Builds primary, adjacent, public-sector internship, and international remote search queries
    dynamically for ANY uploaded candidate profile (Tech, Logistics, Finance, Marketing, Public, etc.).
    """
    skills = parsed_skills or {}
    target_industry = str(skills.get("target_industry") or "qa_tech").lower()
    detected_ind = str(skills.get("detected_industry") or target_industry)
    primary_role = str(skills.get("primary_role") or headline or skills.get("headline") or "Specialist").strip()
    adj_roles = [str(r) for r in (skills.get("adjacent_roles") or []) if r]
    verified = [str(s) for s in (skills.get("verified_skills") or skills.get("all_skills") or []) if s]
    exp_years = float(skills.get("years_of_experience") or 1.5)
    cap_exp = min(exp_years + 0.5, 2.0)

    tmpl = _DOMAIN_QUERY_TEMPLATES.get(target_industry)
    if tmpl:
        primary_ge = list(tmpl["primary_ge"])
        adjacent_ge = list(tmpl["adjacent_ge"])
        remote_int = list(tmpl["remote_int"])
        is_it = bool(tmpl["is_it_category"])
        djinni_kw = tmpl["djinni_kw"]
        dou_cat = tmpl["dou_cat"]
        justjoin_cat = tmpl["justjoin_cat"]
        domain_kw = list(tmpl["domain_kw"])
        adjacent_kw = list(tmpl["adjacent_kw"])
    else:
        # Completely dynamic construction for any arbitrary/custom industry!
        role_tokens = [w for w in primary_role.replace("/", " ").split() if len(w) >= 3][:2]
        primary_ge = role_tokens or [primary_role]
        adjacent_ge = [r.split()[0] for r in adj_roles[:2] if len(r.split()[0]) >= 3] or (verified[:2] if verified else ["Coordinator"])
        remote_int = role_tokens[:2]
        is_it = any(s.lower() in ("python", "sql", "javascript", "typescript", "docker", "aws", "qa") for s in verified)
        djinni_kw = role_tokens[0] if (is_it and role_tokens) else None
        dou_cat = None
        justjoin_cat = None
        domain_kw = [t.lower() for t in role_tokens] + [s.lower() for s in verified[:6]]
        adjacent_kw = [r.lower() for r in adj_roles] + [s.lower() for s in verified[:8]]

    # Enrich adjacent keywords cleanly with candidate's actual adjacent roles + verified transferable tools
    for ar in adj_roles:
        for tok in ar.lower().split():
            if len(tok) >= 4 and tok not in adjacent_kw and tok not in ("junior", "associate", "specialist"):
                adjacent_kw.append(tok)

    internship_queries = ["სტაჟიორი", "დამწყები"]
    if primary_ge:
        internship_queries.append(primary_ge[0])

    # Jobs.ge: loop through primary_queries_ge + adjacent_queries_ge (only add cid=6 for IT/Software roles)
    cid_suffix = "&cid=6" if is_it else ""
    jobs_ge_urls: List[str] = []
    for idx, q in enumerate((primary_ge[:2] + adjacent_ge[:1])):
        enc = quote_plus(q)
        cat_part = cid_suffix if idx < len(primary_ge[:2]) else ""
        u = f"https://jobs.ge/ge/?page=1&q={enc}{cat_part}"
        if u not in jobs_ge_urls:
            jobs_ge_urls.append(u)

    hr_ge_urls = [
        f"https://www.hr.ge/search-posting?q={quote_plus(q)}"
        for q in dict.fromkeys(primary_ge[:2] + adjacent_ge[:1])
    ]
    headhunter_urls = [
        f"https://tbilisi.headhunter.ge/search/vacancy?text={quote_plus(q)}&area=28"
        for q in dict.fromkeys(primary_ge[:2] + adjacent_ge[:1])
    ]

    # Enforce strict exp_years filter on Djinni via djinni_exp_url while keeping clean base djinni_url
    djinni_url = None
    djinni_exp_url = None
    if djinni_kw:
        djinni_url = f"https://djinni.co/jobs/?primary_keyword={quote_plus(djinni_kw)}&employment=remote"
        exp_param = "&exp_years=0-1" if cap_exp <= 1.5 else "&exp_years=1"
        djinni_exp_url = f"{djinni_url}{exp_param}"

    dou_url = f"https://jobs.dou.ua/vacancies/?category={quote_plus(dou_cat)}&remote" if dou_cat else None
    justjoin_url = f"https://justjoin.it/job-offers/all-locations/{justjoin_cat}?workplace=remote" if justjoin_cat else None

    hr_gov_queries = list(dict.fromkeys(
        ["IT", "ანალიტიკ", "სისტემ"] if is_it else (primary_ge[:2] + adjacent_ge[:1])
    ))

    pkg = SearchQueryPackage(
        target_role=primary_role,
        detected_industry=detected_ind,
        primary_queries_ge=primary_ge,
        adjacent_queries_ge=adjacent_ge,
        internship_queries=internship_queries,
        remote_keywords_int=remote_int,
        jobs_ge_urls=jobs_ge_urls,
        hr_ge_urls=hr_ge_urls,
        headhunter_urls=headhunter_urls,
        hr_gov_queries=hr_gov_queries,
        djinni_url=djinni_url,
        dou_url=dou_url,
        justjoin_url=justjoin_url,
        domain_keywords=domain_kw,
        adjacent_keywords=adjacent_kw,
    )
    res = pkg.model_dump()
    res["djinni_exp_url"] = djinni_exp_url
    res["search_terms"] = list(dict.fromkeys(primary_ge + adjacent_ge))
    res["hr_ge_url"] = hr_ge_urls[0] if hr_ge_urls else "https://www.hr.ge/search-posting?q="
    res["headhunter_url"] = headhunter_urls[0] if headhunter_urls else None
    return res
