"""
Generates deterministic TypeScript schema declarations from FastAPI's live OpenAPI spec.

Run from backend/:
    python scripts/generate_openapi_types.py
"""

import sys
from pathlib import Path
from typing import Any, Dict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
OUT_FILE = PROJECT_ROOT / "frontend" / "src" / "types" / "openapi.generated.d.ts"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402


def _schema_to_ts(schema: Dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "anyOf" in schema:
        return " | ".join(_schema_to_ts(opt) for opt in schema["anyOf"])
    t = schema.get("type")
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return f"Array<{_schema_to_ts(schema.get('items', {}))}>"
    if t == "object":
        return "Record<string, unknown>"
    return "unknown"


def generate() -> str:
    spec = app.openapi()
    schemas: Dict[str, Any] = (spec.get("components") or {}).get("schemas") or {}
    paths: Dict[str, Any] = spec.get("paths") or {}

    lines = [
        "/* eslint-disable */",
        "// AUTO-GENERATED from FastAPI OpenAPI schema by backend/scripts/generate_openapi_types.py",
        "// Do not hand-edit; re-run the generator after backend Pydantic contract changes.",
        "",
        "export type ApiEndpointPath =",
    ]
    for path in sorted(paths.keys()):
        lines.append(f"  | '{path}'")
    lines.append(";")
    lines.append("")

    for name in sorted(schemas.keys()):
        defn = schemas[name]
        props: Dict[str, Any] = defn.get("properties") or {}
        required = set(defn.get("required") or [])
        lines.append(f"export interface {name} {{")
        for prop_name, prop_schema in props.items():
            opt = "" if prop_name in required else "?"
            lines.append(f"  {prop_name}{opt}: {_schema_to_ts(prop_schema)};")
        lines.append("}")
        lines.append("")

    output = "\n".join(lines)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(output, encoding="utf-8")
    return f"Generated {len(schemas)} schemas and {len(paths)} paths -> {OUT_FILE}"


if __name__ == "__main__":
    print(generate())
