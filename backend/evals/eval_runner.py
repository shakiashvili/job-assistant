"""
Offline golden-set evaluation and zero-fabrication groundedness runner.

Run via:
    python -m evals.eval_runner
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

from app.services.gemini_service import GeminiService
from app.services.matching.gates import DisciplineGate, SeniorityGate

GOLDEN_DATASET_PATH = Path(__file__).resolve().parent / "golden_dataset.json"

_KNOWN_FABRICATED_EMPLOYERS = (
    "google", "meta", "amazon", "microsoft", "apple", "netflix", "stripe", "goldman sachs",
)
_KNOWN_FABRICATED_HONORS = (
    "graduated with honors", "summa cum laude", "magna cum laude", "erasmus+",
)
_PERCENT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")


@dataclass
class EvalMetrics:
    total_cases: int
    seniority_tp: int
    seniority_fp: int
    seniority_fn: int
    seniority_precision: float
    seniority_recall: float
    domain_accuracy: float
    groundedness_checked: int
    groundedness_violations: List[str]


def check_groundedness(generated_text: str, profile: Dict[str, Any], company: str = "") -> List[str]:
    """
    Verifies a generated CV summary or cover letter contains zero fabricated claims:
    - No unverified famous employers absent from profile['employers'] or target company
    - No unverified numeric percentages absent from profile text/bullets
    - No unverified honors/Erasmus awards absent from profile['education']
    """
    violations: List[str] = []
    text_low = (generated_text or "").lower()
    allowed_blob = json.dumps(profile, ensure_ascii=False).lower() + " " + (company or "").lower()

    for employer in _KNOWN_FABRICATED_EMPLOYERS:
        if re.search(rf"\b{re.escape(employer)}\b", text_low) and employer not in allowed_blob:
            violations.append(f"Unverified employer mentioned: '{employer}'")

    for honor in _KNOWN_FABRICATED_HONORS:
        if honor in text_low and honor not in allowed_blob:
            violations.append(f"Unverified academic honor/award mentioned: '{honor}'")

    allowed_percents: Set[str] = set(_PERCENT_RE.findall(allowed_blob))
    for pct in _PERCENT_RE.findall(text_low):
        if pct not in allowed_percents:
            violations.append(f"Unverified percentage metric: '{pct}%'")

    return violations


def run_golden_eval(dataset_path: Path = GOLDEN_DATASET_PATH) -> EvalMetrics:
    """Runs all golden dataset cases offline and computes precision, recall, accuracy, and groundedness."""
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    profiles: Dict[str, Dict[str, Any]] = data["profiles"]
    cases: List[Dict[str, Any]] = data["cases"]

    seniority_gate = SeniorityGate()
    discipline_gate = DisciplineGate()
    offline_ai = GeminiService(api_key="", openrouter_api_key="")

    sen_tp = sen_fp = sen_fn = 0
    domain_correct = 0
    grounded_checked = 0
    violations: List[str] = []

    for case in cases:
        prof = profiles[case["profile"]]
        sen_res = seniority_gate.evaluate(
            title=case["title"],
            description=case["description"],
            parsed_skills=prof,
            portal=case["portal"],
            company=case["company"],
        )
        # Positive class = "rejected by seniority gate" (caught over-senior vacancy)
        predicted_reject = not sen_res.passed
        actual_reject = not bool(case["expected_seniority_pass"])
        if predicted_reject and actual_reject:
            sen_tp += 1
        elif predicted_reject and not actual_reject:
            sen_fp += 1
        elif not predicted_reject and actual_reject:
            sen_fn += 1

        dom_res = discipline_gate.evaluate(
            title=case["title"],
            description=case["description"],
            parsed_skills=prof,
            portal=case["portal"],
            company=case["company"],
        )
        if dom_res.passed == bool(case["expected_domain_pass"]):
            domain_correct += 1

        if case["expected_seniority_pass"] and case["expected_domain_pass"]:
            job_details = {
                "title": case["title"],
                "company": case["company"],
                "industry": prof["target_industry"],
                "description": case["description"],
                "work_history": [{"company": emp, "role": prof["primary_role"]} for emp in prof.get("employers", [])],
                "education": [{"degree": ed, "institution": ""} for ed in prof.get("education", [])],
            }
            narratives = offline_ai.craft_human_tone_narratives(
                job_details=job_details,
                skills_md="\n".join(prof.get("all_skills", [])),
                matched_skills=prof.get("all_skills", [])[:5],
                missing_skills=[],
                cv_language="en",
                candidate_name=prof.get("full_name", "Candidate"),
            )
            grounded_checked += 1
            for field_name in ("human_tone_summary", "cover_letter", "dou_motivational_letter"):
                found = check_groundedness(narratives.get(field_name, ""), prof, company=case["company"])
                for item in found:
                    violations.append(f"{case['id']}.{field_name}: {item}")

    precision = sen_tp / (sen_tp + sen_fp) if (sen_tp + sen_fp) else 1.0
    recall = sen_tp / (sen_tp + sen_fn) if (sen_tp + sen_fn) else 1.0
    domain_acc = domain_correct / len(cases) if cases else 1.0

    return EvalMetrics(
        total_cases=len(cases),
        seniority_tp=sen_tp,
        seniority_fp=sen_fp,
        seniority_fn=sen_fn,
        seniority_precision=round(precision, 4),
        seniority_recall=round(recall, 4),
        domain_accuracy=round(domain_acc, 4),
        groundedness_checked=grounded_checked,
        groundedness_violations=violations,
    )


if __name__ == "__main__":
    metrics = run_golden_eval()
    print(json.dumps(metrics.__dict__, indent=2))
