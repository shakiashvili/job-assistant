import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional
from sqlalchemy import Date, DateTime
from sqlmodel import SQLModel

from ..config import DATA_DIR
from ..db.database import engine, init_db

logger = logging.getLogger(__name__)

BACKUPS_DIR: Path = DATA_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialize_cell(val: Any) -> Any:
    if isinstance(val, datetime | date):
        return val.isoformat()
    return val


def _deserialize_cell(val: Any, col_type: Any) -> Any:
    if val is None or not isinstance(val, str):
        return val
    if isinstance(col_type, DateTime):
        return datetime.fromisoformat(val)
    if isinstance(col_type, Date):
        return date.fromisoformat(val[:10])
    return val


def _resolve_safe_backup_path(backup_path: Path, allowed_dir: Optional[Path] = None) -> Path:
    """Strictly resolves backup_path inside BACKUPS_DIR (or allowed_dir) and rejects symlinks/traversal."""
    root = (allowed_dir or BACKUPS_DIR).resolve()
    raw = Path(backup_path)
    if raw.is_symlink():
        raise ValueError("Refusing symlink backup path.")
    candidate = raw if raw.is_absolute() else (root / raw)
    # Check symlink components along relative path if present before full resolve
    if candidate.is_symlink():
        raise ValueError("Refusing symlink backup target.")
    resolved = candidate.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f"Backup path '{backup_path}' escapes authorized backups directory.")
    return resolved


class DatabaseBackupService:
    """
    Provides hot atomic SQLite database backups and portable JSON full-table snapshots
    (supporting both SQLite and PostgreSQL), with mandatory SHA-256 verification and
    pre-restore safety snapshots.
    """

    _BACKUP_COUNT_TABLES = (
        "users",
        "candidate_profiles",
        "candidate_documents",
        "cv_versions",
        "job_postings",
        "application_tracker",
        "application_records",
    )

    @classmethod
    def _collect_table_counts(cls) -> Dict[str, int]:
        from sqlalchemy import func, select as sa_select

        counts: Dict[str, int] = {}
        with engine.connect() as conn:
            for tbl_name in cls._BACKUP_COUNT_TABLES:
                tbl_obj = SQLModel.metadata.tables.get(tbl_name)
                if tbl_obj is None:
                    counts[tbl_name] = 0
                    continue
                try:
                    cnt = conn.execute(sa_select(func.count()).select_from(tbl_obj)).scalar_one()
                    counts[tbl_name] = int(cnt or 0)
                except Exception as cnt_err:
                    logger.warning("Could not count rows in table '%s': %s", tbl_name, cnt_err)
                    counts[tbl_name] = 0
        return counts

    def create_backup(
        self,
        target_dir: Optional[Path] = None,
        reason: Optional[str] = None,
        tag: Optional[str] = None,
        portable_json: bool = False,
    ) -> Dict[str, Any]:
        init_db()
        out_dir = (target_dir or BACKUPS_DIR).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        url_str = engine.url.render_as_string(hide_password=False)

        table_counts = self._collect_table_counts()

        if url_str.startswith("sqlite") and not portable_json:
            backup_file = out_dir / f"talentflow_backup_{ts}.sqlite3"
            raw_conn = engine.raw_connection()
            dst_conn = sqlite3.connect(str(backup_file))
            try:
                src_sqlite = getattr(raw_conn, "driver_connection", None) or getattr(raw_conn, "connection", raw_conn)
                with dst_conn:
                    src_sqlite.backup(dst_conn)
                chk = dst_conn.execute("PRAGMA integrity_check;").fetchone()
                integrity = str(chk[0]).lower() if chk else "unknown"
            finally:
                dst_conn.close()
                raw_conn.close()

            checksum = _sha256_file(backup_file)
            meta_file = backup_file.with_suffix(".meta.json")
            meta = {
                "filename": backup_file.name,
                "backup_path": str(backup_file),
                "created_at": datetime.now(UTC).isoformat(),
                "sha256": checksum,
                "size_bytes": backup_file.stat().st_size,
                "integrity_check": integrity,
                "reason": reason or tag or "manual",
                "table_counts": table_counts,
                "format": "sqlite3_hot_backup",
            }
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta

        # Portable full-row JSON snapshot for PostgreSQL or cross-engine backup/restore
        snapshot_file = out_dir / f"talentflow_backup_{ts}.json"
        tables_dump: Dict[str, list[Dict[str, Any]]] = {}
        with engine.connect() as conn:
            for table in SQLModel.metadata.sorted_tables:
                try:
                    rows = conn.execute(table.select()).mappings().all()
                    tables_dump[table.name] = [
                        {col: _serialize_cell(val) for col, val in dict(r).items()}
                        for r in rows
                    ]
                    table_counts[table.name] = len(tables_dump[table.name])
                except Exception as dump_err:
                    logger.debug(f"Skipping table '{table.name}' during portable JSON backup: {dump_err}")

        payload = {
            "created_at": datetime.now(UTC).isoformat(),
            "format": "portable_json_backup",
            "table_counts": table_counts,
            "tables": tables_dump,
        }
        snapshot_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        checksum = _sha256_file(snapshot_file)
        meta_file = snapshot_file.with_suffix(".meta.json")
        meta = {
            "filename": snapshot_file.name,
            "backup_path": str(snapshot_file),
            "created_at": payload["created_at"],
            "sha256": checksum,
            "size_bytes": snapshot_file.stat().st_size,
            "integrity_check": "ok",
            "reason": reason or tag or "manual",
            "table_counts": table_counts,
            "format": "portable_json_backup",
        }
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    def list_backups(self, target_dir: Optional[Path] = None) -> list[Dict[str, Any]]:
        out_dir = (target_dir or BACKUPS_DIR).resolve()
        if not out_dir.exists():
            return []
        items: list[Dict[str, Any]] = []
        for meta_file in sorted(out_dir.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                items.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as meta_err:
                logger.warning("Skipping unreadable backup metadata file %s: %s", meta_file.name, meta_err)
                continue
        return items

    def _restore_portable_json(self, json_path: Path) -> None:
        raw_payload = json.loads(json_path.read_text(encoding="utf-8"))
        tables_data = raw_payload.get("tables")
        if not isinstance(tables_data, dict):
            raise ValueError("Invalid portable JSON backup: missing 'tables' payload.")

        sorted_tables = SQLModel.metadata.sorted_tables
        with engine.begin() as conn:
            for tbl in reversed(sorted_tables):
                if tbl.name in tables_data:
                    conn.execute(tbl.delete())
            for tbl in sorted_tables:
                rows = tables_data.get(tbl.name)
                if not rows:
                    continue
                col_map = {c.name: c.type for c in tbl.columns}
                parsed_rows = [
                    {
                        k: _deserialize_cell(v, col_map[k])
                        for k, v in row.items()
                        if k in col_map
                    }
                    for row in rows
                ]
                if parsed_rows:
                    conn.execute(tbl.insert(), parsed_rows)

    def restore_backup(self, backup_path: Path, allowed_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Restores a SQLite or portable JSON backup after enforcing containment, .meta.json SHA-256 verification, and a pre-restore safety snapshot."""
        b_path = _resolve_safe_backup_path(backup_path, allowed_dir=allowed_dir)
        if not b_path.exists() or not b_path.is_file():
            raise FileNotFoundError(f"Backup file not found: {b_path}")

        meta_file = b_path.with_suffix(".meta.json")
        if meta_file.is_symlink() or not meta_file.exists():
            raise ValueError("Missing backup metadata sidecar (.meta.json) — refusing unverified restore.")

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        expected_hash = str(meta.get("sha256") or "").strip()
        if not expected_hash:
            raise ValueError("Missing SHA-256 digest in backup metadata sidecar.")
        actual_hash = _sha256_file(b_path)
        if expected_hash != actual_hash:
            raise ValueError("Backup SHA-256 checksum mismatch — refusing to restore corrupted backup.")

        is_json_backup = b_path.suffix.lower() == ".json" or meta.get("format") == "portable_json_backup"
        if is_json_backup:
            probe = json.loads(b_path.read_text(encoding="utf-8"))
            if not isinstance(probe, dict) or not isinstance(probe.get("tables"), dict):
                raise ValueError("Portable JSON backup is corrupted or missing table rows.")
        else:
            check_conn = sqlite3.connect(str(b_path))
            try:
                res = check_conn.execute("PRAGMA integrity_check;").fetchone()
                if not res or str(res[0]).lower() != "ok":
                    raise ValueError(f"Backup failed SQLite integrity_check: {res}")
            finally:
                check_conn.close()

        url_str = engine.url.render_as_string(hide_password=False)
        if not is_json_backup and not url_str.startswith("sqlite:///"):
            raise RuntimeError("Direct SQLite file restore is only supported for SQLite databases; use portable JSON backup.")

        # Always capture a pre-restore safety backup before overwriting live data
        safety_meta = self.create_backup(
            target_dir=b_path.parent,
            reason="pre_restore_safety",
            portable_json=is_json_backup and not url_str.startswith("sqlite:///"),
        )

        if is_json_backup:
            self._restore_portable_json(b_path)
        else:
            engine.dispose()
            live_path = Path(url_str.replace("sqlite:///", "", 1))
            src_conn = sqlite3.connect(str(b_path))
            dst_conn = sqlite3.connect(str(live_path))
            try:
                with dst_conn:
                    src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

        init_db(force=True)
        restored_counts = self._collect_table_counts()

        return {
            "status": "restored",
            "restored_from": str(b_path),
            "safety_backup": safety_meta.get("filename"),
            "table_counts": restored_counts,
        }


backup_service = DatabaseBackupService()
