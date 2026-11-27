from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from ..matcher_service import matcher_service


@dataclass(frozen=True)
class GateResult:
    """Typed outcome emitted by an individual matching gate."""

    gate_name: str
    passed: bool
    reason: str = ""
    penalty: float = 0.0
    metadata: Optional[Dict[str, Any]] = None


class MatchingGate(Protocol):
    name: str

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        portal: str,
        company: str,
    ) -> GateResult: ...


class SeniorityGate:
    """Rejects vacancies whose seniority ceiling exceeds the candidate's verified experience band."""

    name = "seniority_gate"

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        portal: str = "generic",
        company: str = "",
    ) -> GateResult:
        candidate_years = float(parsed_skills.get("years_experience", 0.0) or 0.0)
        candidate_seniority = str(parsed_skills.get("seniority_level", "Junior") or "Junior")
        max_allowed = parsed_skills.get("max_allowed_years")
        ok, reason = matcher_service.validate_seniority_gate(
            candidate_years=candidate_years,
            candidate_seniority=candidate_seniority,
            job_title=title,
            job_description=description,
            max_allowed_years=max_allowed,
        )
        return GateResult(gate_name=self.name, passed=ok, reason="" if ok else reason)


class ExperienceGate:
    """Evaluates whether explicit experience years in the JD exceed candidate max_allowed_years."""

    name = "experience_gate"

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        portal: str = "generic",
        company: str = "",
    ) -> GateResult:
        max_allowed = parsed_skills.get("max_allowed_years")
        if max_allowed is None:
            return GateResult(gate_name=self.name, passed=True, reason="Unknown candidate experience cap")
        candidate_years = float(parsed_skills.get("years_experience", 0.0) or 0.0)
        candidate_seniority = str(parsed_skills.get("seniority_level", "Junior") or "Junior")
        ok, reason = matcher_service.validate_seniority_gate(
            candidate_years=candidate_years,
            candidate_seniority=candidate_seniority,
            job_title=title,
            job_description=description,
            max_allowed_years=max_allowed,
        )
        if not ok and ("year" in reason.lower() or "experience" in reason.lower()):
            return GateResult(gate_name=self.name, passed=False, reason=reason)
        return GateResult(gate_name=self.name, passed=True)


class DisciplineGate:
    """Verifies candidate domain/role alignment (DIRECT, ADJACENT, PUBLIC_INTERNSHIP, or NONE)."""

    name = "discipline_gate"

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        portal: str = "generic",
        company: str = "",
    ) -> GateResult:
        cand_skills = list(parsed_skills.get("all_skills") or [])
        tier_hint, tier_label = matcher_service.classify_domain_alignment(
            parsed_skills,
            title,
            description,
            portal=portal,
            candidate_skills=cand_skills,
            company=company,
        )
        passed = tier_hint != "NONE"
        penalty = 0.0 if tier_hint == "DIRECT" else (10.0 if tier_hint in ("ADJACENT", "PUBLIC_INTERNSHIP") else 100.0)
        return GateResult(
            gate_name=self.name,
            passed=passed,
            reason="" if passed else tier_label,
            penalty=penalty,
            metadata={"tier": tier_hint, "label": tier_label},
        )


class LanguageGate:
    """Checks whether mandatory foreign-language requirements are compatible with candidate spoken languages."""

    name = "language_gate"

    def evaluate(
        self,
        *,
        title: str,
        description: str,
        parsed_skills: Dict[str, Any],
        portal: str = "generic",
        company: str = "",
    ) -> GateResult:
        from ..scrapers.base_scraper import evaluate_remote_and_language_gate

        spoken = list(parsed_skills.get("spoken_languages") or [])
        is_remote, status, filter_reason, langs_detected = evaluate_remote_and_language_gate(
            title=title,
            description=description,
            portal=portal,
            candidate_languages=spoken,
        )
        passed = status != "FILTERED_OUT"
        return GateResult(
            gate_name=self.name,
            passed=passed,
            reason="" if passed else filter_reason,
            metadata={"is_remote": is_remote, "status": status, "detected_languages": langs_detected},
        )


def run_gate_pipeline(
    *,
    title: str,
    description: str,
    parsed_skills: Dict[str, Any],
    portal: str = "generic",
    company: str = "",
    gates: Optional[List[MatchingGate]] = None,
) -> List[GateResult]:
    """Runs all matching gates sequentially and returns typed GateResult diagnostics for explainability."""
    active_gates: List[MatchingGate] = gates or [
        SeniorityGate(),
        DisciplineGate(),
        LanguageGate(),
    ]
    return [
        gate.evaluate(
            title=title,
            description=description,
            parsed_skills=parsed_skills,
            portal=portal,
            company=company,
        )
        for gate in active_gates
    ]
