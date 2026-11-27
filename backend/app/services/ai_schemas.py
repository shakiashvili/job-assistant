"""Strict Pydantic output schemas for every LLM task in TalentFlow AI."""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ExtractedJobDetailsSchema(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    company: str = Field(..., min_length=1, max_length=200)
    portal: str = Field(default="generic", max_length=80)
    industry: str = Field(default="general_professional", max_length=80)
    experience_years_required: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    required_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    visa_requirements: str = Field(default="", max_length=400)
    language_requirements: List[str] = Field(default_factory=list)
    location: str = Field(default="Remote", max_length=200)
    remote_policy: str = Field(default="Remote", max_length=80)
    salary_range: Optional[str] = Field(default=None, max_length=160)
    summary: str = Field(default="", max_length=1200)

    @field_validator("required_skills", "nice_to_have_skills", "language_requirements", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:40]


class NarrativePackageSchema(BaseModel):
    human_tone_summary: str = Field(..., min_length=20, max_length=1600)
    motivation_statement: str = Field(default="", max_length=1200)
    cover_letter: str = Field(..., min_length=40, max_length=4000)
    dou_motivational_letter: str = Field(..., min_length=40, max_length=4500)


class ScreeningAnswerItemSchema(BaseModel):
    index: int = Field(..., ge=0)
    answer: str = Field(default="", max_length=2000)


class ScreeningAnswerListSchema(BaseModel):
    answers: List[ScreeningAnswerItemSchema] = Field(default_factory=list)


class CompanyResearchSchema(BaseModel):
    summary: str = Field(..., min_length=15, max_length=1500)
    talking_points: List[str] = Field(default_factory=list)

    @field_validator("talking_points", mode="before")
    @classmethod
    def _coerce_points(cls, value: object) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:6]


class TranslationListSchema(BaseModel):
    translated: List[str] = Field(default_factory=list)
