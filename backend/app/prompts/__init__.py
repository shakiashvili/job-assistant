"""Versioned prompt template loader for TalentFlow AI."""

import hashlib
from pathlib import Path
from typing import Any, Tuple

PROMPTS_DIR = Path(__file__).resolve().parent
PROMPT_VERSION = "2026-11-v1"


def render_prompt_template(template_name: str, **variables: Any) -> Tuple[str, str]:
    """
    Loads a versioned prompt template from backend/app/prompts/<template_name>.txt
    and renders it with str.format(**variables).
    Returns (rendered_prompt, versioned_prompt_id).
    """
    tpl_path = PROMPTS_DIR / f"{template_name}.txt"
    if not tpl_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {tpl_path.name}")
    raw_template = tpl_path.read_text(encoding="utf-8")
    tpl_digest = hashlib.sha256(raw_template.encode("utf-8")).hexdigest()[:8]
    rendered = raw_template.format(**variables)
    version_id = f"{PROMPT_VERSION}:{template_name}:{tpl_digest}"
    return rendered, version_id
