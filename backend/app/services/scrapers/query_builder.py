import logging
from typing import Dict, Any, List, Optional
from urllib.parse import quote_plus
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


from .linkedin_scraper import build_linkedin_search_urls


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
    linkedin_urls: List[str] = Field(default_factory=list)
    hr_gov_queries: List[str] = Field(default_factory=list)
    djinni_url: Optional[str] = None
    dou_url: Optional[str] = None
    justjoin_url: Optional[str] = None
    domain_keywords: List[str] = Field(default_factory=list)
    adjacent_keywords: List[str] = Field(default_factory=list)


_DOMAIN_QUERY_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "qa_tech": {
        "primary_ge": ["QA", "Tester", "ხარისხის უზრუნველყოფა"],
        "adjacent_ge": ["SQL", "Python"],
        "remote_int": ["QA", "Tester", "Automation"],
        "is_it_category": True,
        "jobs_ge_cid": 6,
        "djinni_kw": "QA",
        "dou_cat": "QA",
        "justjoin_cat": "testing",
        "domain_kw": ["qa", "quality assurance", "tester", "test engineer", "sdet", "automation", "playwright", "cypress", "selenium", "ტესტ", "ხარისხის უზრუნველყოფ"],
        "adjacent_kw": ["data quality", "sql", "python", "integration engineer", "application support", "automation developer", "devops", "ანალიტიკ"],
    },
    "software_engineering": {
        "primary_ge": ["Developer", "პროგრამისტი"],
        "adjacent_ge": ["Backend", "Support"],
        "remote_int": ["Python", "Developer", "JavaScript"],
        "is_it_category": True,
        "jobs_ge_cid": 6,
        "djinni_kw": "Python",
        "dou_cat": "Python",
        "justjoin_cat": "python",
        "domain_kw": ["developer", "engineer", "programmer", "backend", "frontend", "full stack", "python", "typescript", "დეველოპერ", "პროგრამისტ"],
        "adjacent_kw": ["devops", "technical support", "sql", "data", "automation", "მხარდაჭერ"],
    },
    "data_analytics": {
        "primary_ge": ["Analyst", "SQL"],
        "adjacent_ge": ["BI", "Operations"],
        "remote_int": ["Data Analyst", "BI"],
        "is_it_category": True,
        "jobs_ge_cid": 6,
        "djinni_kw": "Data Analyst",
        "dou_cat": "Analyst",
        "justjoin_cat": "data",
        "domain_kw": ["analyst", "data", "power bi", "tableau", "sql", "reporting", "ანალიტიკოს"],
        "adjacent_kw": ["finance", "operations", "excel", "python", "reporting", "ფინანს"],
    },
    "logistics_supply_chain": {
        "primary_ge": ["ლოჯისტიკა", "Logistics"],
        "adjacent_ge": ["შესყიდვები", "Operations"],
        "remote_int": ["Logistics", "Supply Chain"],
        "is_it_category": False,
        "jobs_ge_cid": 5,
        "djinni_kw": "kw:Logistics",
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["logistics", "supply chain", "procurement", "warehouse", "dispatch", "freight", "customs", "ლოჯისტიკ", "შესყიდვ", "საწყობ", "მომარაგებ"],
        "adjacent_kw": ["operations", "import", "export", "inventory", "coordinator", "ოპერაციებ", "კოორდინატორ", "ადმინისტრატორ"],
    },
    "finance_accounting": {
        "primary_ge": ["ბუღალტერი", "Finance"],
        "adjacent_ge": ["Audit", "Financial Analyst"],
        "remote_int": ["Finance", "Accounting", "Financial Analyst"],
        "is_it_category": False,
        "jobs_ge_cid": 3,
        "djinni_kw": "kw:Finance",
        "dou_cat": "Finance",
        "justjoin_cat": "analytics",
        "domain_kw": ["finance", "accountant", "accounting", "audit", "bookkeeper", "ifrs", "1c", "oris", "financial analyst", "ბუღალტ", "ფინანს", "აუდიტ"],
        "adjacent_kw": ["analyst", "billing", "treasury", "controller", "excel", "fp&a", "ანალიტიკ"],
    },
    "marketing_growth": {
        "primary_ge": ["მარკეტინგი", "Marketing"],
        "adjacent_ge": ["Content", "SMM"],
        "remote_int": ["Marketing", "SEO", "Growth"],
        "is_it_category": False,
        "jobs_ge_cid": 4,
        "djinni_kw": "Marketing",
        "dou_cat": "Marketing",
        "justjoin_cat": None,
        "domain_kw": ["marketing", "seo", "smm", "social media", "copywriter", "ads", "brand", "growth", "მარკეტინგ", "კონტენტ"],
        "adjacent_kw": ["pr", "communications", "e-commerce", "digital", "კომუნიკაცი"],
    },
    "sales_bd": {
        "primary_ge": ["გაყიდვები", "Sales"],
        "adjacent_ge": ["Account Manager", "Business Development"],
        "remote_int": ["Sales", "Business Development"],
        "is_it_category": False,
        "jobs_ge_cid": 2,
        "djinni_kw": "Sales",
        "dou_cat": "Sales",
        "justjoin_cat": None,
        "domain_kw": ["sales", "business development", "account manager", "account executive", "b2b", "გაყიდვ", "კონსულტანტ"],
        "adjacent_kw": ["customer", "crm", "onboarding", "partnerships", "მომხმარებელ"],
    },
    "hr_recruiting": {
        "primary_ge": ["HR", "ადამიანური რესურსები"],
        "adjacent_ge": ["Recruiter", "People Operations"],
        "remote_int": ["HR", "Recruiter", "Talent Acquisition"],
        "is_it_category": False,
        "jobs_ge_cid": 1,
        "djinni_kw": "HR",
        "dou_cat": "HR",
        "justjoin_cat": None,
        "domain_kw": ["hr", "recruiter", "talent acquisition", "human resources", "people operations", "onboarding", "ადამიანური რესურს", "რეკრუტ"],
        "adjacent_kw": ["office manager", "coordinator", "administrative", "ადმინისტრ"],
    },
    "public_admin_legal": {
        "primary_ge": ["იურისტი", "Legal"],
        "adjacent_ge": ["Compliance", "ადმინისტრაციული"],
        "remote_int": ["Legal", "Compliance"],
        "is_it_category": False,
        "jobs_ge_cid": 7,
        "djinni_kw": "kw:Legal",
        "dou_cat": "Legal",
        "justjoin_cat": None,
        "domain_kw": ["legal", "lawyer", "counsel", "compliance", "policy", "public administration", "იურისტ", "სამართლ", "შესყიდვ", "ადმინისტრაცი"],
        "adjacent_kw": ["coordinator", "specialist", "clerk", "analyst", "სტაჟიორი", "სპეციალისტ"],
    },
    "receptionist_hospitality": {
        "primary_ge": ["Receptionist", "მიმღები"],
        "adjacent_ge": ["ადმინისტრატორი", "Hospitality"],
        "remote_int": ["Hospitality", "Guest"],
        "is_it_category": False,
        "jobs_ge_cid": 10,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["receptionist", "front desk", "hospitality", "concierge", "hotel", "guest", "მიმღები", "რეცეფციონისტი", "სასტუმრო", "ადმინისტრატორი"],
        "adjacent_kw": ["customer service", "office manager", "coordinator", "მომხმარებელ"],
    },
    "healthcare_hospital": {
        "primary_ge": ["სამედიცინო", "Medical"],
        "adjacent_ge": ["კლინიკა", "Nurse"],
        "remote_int": ["Healthcare", "Clinical", "Medical"],
        "is_it_category": False,
        "jobs_ge_cid": 8,
        "djinni_kw": None,
        "dou_cat": None,
        "justjoin_cat": None,
        "domain_kw": ["medical", "hospital", "clinic", "patient", "clinical", "nurse", "pharmacy", "სამედიცინო", "კლინიკა", "პაციენტ", "ექთანი", "რეგისტრატორი"],
        "adjacent_kw": ["reception", "coordinator", "administrator", "ადმინისტრატორი"],
    },
    "customer_service": {
        "primary_ge": ["Support", "მხარდაჭერა"],
        "adjacent_ge": ["Customer", "Operator"],
        "remote_int": ["Customer Support", "Support"],
        "is_it_category": False,
        "jobs_ge_cid": 1,
        "djinni_kw": "Support",
        "dou_cat": "Support",
        "justjoin_cat": "support",
        "domain_kw": ["support", "customer service", "client care", "call center", "helpdesk", "მხარდაჭერა", "ოპერატორი", "ქოლ"],
        "adjacent_kw": ["onboarding", "coordinator", "client success", "ადმინისტრატორი"],
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
    target_industry = str(skills.get("target_industry") or "general_professional").lower()
    detected_ind = str(skills.get("detected_industry") or target_industry)
    primary_role = str(skills.get("primary_role") or headline or skills.get("headline") or "Specialist").strip()
    adj_roles = [str(r) for r in (skills.get("adjacent_roles") or []) if r]
    verified = [str(s) for s in (skills.get("verified_skills") or skills.get("all_skills") or []) if s]
    raw_exp = skills.get("years_of_experience")
    exp_years = float(raw_exp) if raw_exp is not None else 0.0
    cap_exp = min(exp_years + 0.5, 2.0) if exp_years <= 2.0 else round(exp_years + 0.5, 1)

    tmpl = _DOMAIN_QUERY_TEMPLATES.get(target_industry)
    if tmpl:
        primary_ge = list(tmpl["primary_ge"])
        adjacent_ge = list(tmpl["adjacent_ge"])
        remote_int = list(tmpl["remote_int"])
        is_it = bool(tmpl["is_it_category"])
        jobs_ge_cid = tmpl.get("jobs_ge_cid")
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
        jobs_ge_cid = 6 if is_it else None
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

    edu_entries = skills.get("education") or []
    courses_certs = skills.get("courses_and_certifications") or []
    eligible_internships = bool(skills.get("eligible_internships") or edu_entries or courses_certs or exp_years <= 2.5)
    for e in edu_entries:
        if isinstance(e, dict):
            fos = str(e.get("field_of_study") or "").strip()
            for tok in fos.lower().split():
                if len(tok) >= 4 and tok not in ("bachelor", "master", "degree", "university"):
                    if tok not in domain_kw:
                        domain_kw.append(tok)

    internship_queries = ["სტაჟიორი", "დამწყები", "Junior", "Trainee"]
    if primary_ge:
        internship_queries.append(primary_ge[0])
    if eligible_internships and primary_ge:
        internship_queries.append(f"{primary_ge[0]} სტაჟიორი")

    # Jobs.ge: always include the newest industry category feed (cid=...) + localized queries + internship feed
    cid_suffix = f"&cid={jobs_ge_cid}" if jobs_ge_cid else ""
    jobs_ge_urls: List[str] = []
    if jobs_ge_cid:
        jobs_ge_urls.append(f"https://jobs.ge/ge/?page=1&cid={jobs_ge_cid}")
    for idx, q in enumerate((primary_ge[:2] + adjacent_ge[:1])):
        enc = quote_plus(q)
        cat_part = cid_suffix if idx < len(primary_ge[:2]) else ""
        u = f"https://jobs.ge/ge/?page=1&q={enc}{cat_part}"
        if u not in jobs_ge_urls:
            jobs_ge_urls.append(u)
    if eligible_internships:
        intern_url = f"https://jobs.ge/ge/?page=1&q={quote_plus('სტაჟირება')}{cid_suffix}"
        if intern_url not in jobs_ge_urls:
            jobs_ge_urls.append(intern_url)

    hr_ge_urls = [
        f"https://www.hr.ge/search-posting?q={quote_plus(q)}"
        for q in dict.fromkeys(primary_ge[:2] + adjacent_ge[:1])
    ]
    headhunter_urls = [
        f"https://headhunter.ge/search/vacancy?text={quote_plus(q)}&area=28&order_by=publication_time"
        for q in dict.fromkeys(primary_ge[:2] + adjacent_ge[:1])
    ]

    # Adapt exp_years filter on Djinni to candidate's actual experience band
    djinni_url = None
    djinni_exp_url = None
    if djinni_kw:
        if djinni_kw.startswith("kw:"):
            djinni_url = f"https://djinni.co/jobs/?keywords={quote_plus(djinni_kw[3:])}&employment=remote"
        else:
            djinni_url = f"https://djinni.co/jobs/?primary_keyword={quote_plus(djinni_kw)}&employment=remote"
        if cap_exp <= 1.5:
            exp_param = "&exp_years=0-1"
        elif cap_exp <= 2.5:
            exp_param = "&exp_years=1"
        elif cap_exp <= 5.5:
            exp_param = "&exp_years=3"
        else:
            exp_param = ""
        djinni_exp_url = f"{djinni_url}{exp_param}"

    dou_url = f"https://jobs.dou.ua/vacancies/?category={quote_plus(dou_cat)}&remote" if dou_cat else None
    justjoin_url = f"https://justjoin.it/job-offers/all-locations/{justjoin_cat}?workplace=remote" if justjoin_cat else None

    hr_gov_queries = list(dict.fromkeys(
        (primary_ge[:2] + ["IT", "ანალიტიკ"]) if is_it else (primary_ge[:2] + adjacent_ge[:1])
    ))
    linkedin_urls = build_linkedin_search_urls(
        primary_role=primary_role,
        verified_skills=verified,
        cap_exp=cap_exp,
    )

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
        linkedin_urls=linkedin_urls,
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
