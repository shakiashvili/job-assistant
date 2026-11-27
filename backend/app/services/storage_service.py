import base64
import hashlib
import hmac
import logging
import os
import tempfile
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

import httpx

from .crypto_service import decrypt_str, encrypt_str
import contextlib

logger = logging.getLogger(__name__)

MAX_DB_BLOB_BYTES = int(os.getenv("MAX_DB_BLOB_BYTES", str(10 * 1024 * 1024)))  # 10 MB


def _s3_config() -> Dict[str, str]:
    bucket = os.getenv("S3_BUCKET", "").strip()
    access_key = os.getenv("S3_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
    endpoint = os.getenv("S3_ENDPOINT_URL", "").strip().rstrip("/")
    region = os.getenv("S3_REGION", "").strip() or ("auto" if "r2.cloudflarestorage.com" in endpoint else "us-east-1")
    prefix = os.getenv("S3_PREFIX", "talentflow").strip().strip("/")
    return {
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint": endpoint,
        "region": region,
        "prefix": prefix,
    }


def is_s3_configured() -> bool:
    cfg = _s3_config()
    return bool(cfg["bucket"] and cfg["access_key"] and cfg["secret_key"])


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sigv4_headers(
    method: str,
    url: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    payload: bytes = b"",
    content_type: Optional[str] = None,
) -> Dict[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = quote(parsed.path or "/", safe="/~-._")
    canonical_querystring = parsed.query or ""

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    headers_map: Dict[str, str] = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if content_type:
        headers_map["content-type"] = content_type

    sorted_keys = sorted(headers_map.keys())
    canonical_headers = "".join(f"{k}:{headers_map[k].strip()}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)

    canonical_request = "\n".join(
        [method.upper(), canonical_uri, canonical_querystring, canonical_headers, signed_headers, payload_hash]
    )
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, "s3")
    k_signing = _hmac_sha256(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    auth_header = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    out_headers = {
        "Authorization": auth_header,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }
    if content_type:
        out_headers["Content-Type"] = content_type
    return out_headers


def _object_url(cfg: Dict[str, str], object_key: str) -> str:
    clean_key = object_key.lstrip("/")
    if cfg["endpoint"]:
        return f"{cfg['endpoint']}/{cfg['bucket']}/{clean_key}"
    return f"https://{cfg['bucket']}.s3.{cfg['region']}.amazonaws.com/{clean_key}"


def build_object_key(user_id: Optional[int], category: str, filename: str) -> str:
    cfg = _s3_config()
    safe_cat = "uploads" if category == "uploaded_cv" else "generated"
    folder = f"user_{int(user_id)}" if user_id is not None else "guest"
    clean_name = Path(filename).name
    parts = [p for p in (cfg["prefix"], "users", folder, safe_cat, clean_name) if p]
    return "/".join(parts)


def encode_encrypted_blob(raw_bytes: bytes) -> str:
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    enc = encrypt_str(b64)
    if not enc:
        raise ValueError("Failed encrypting document payload.")
    return enc


def decode_encrypted_blob(encrypted_content: str) -> bytes:
    b64 = decrypt_str(encrypted_content, raise_on_error=True)
    if not b64:
        raise ValueError("Failed decrypting document payload.")
    return base64.b64decode(b64.encode("ascii"))


def _atomic_write_bytes(target_path: Path, data: bytes) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".hydrate_", dir=str(target_path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, target_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return target_path


class DocumentStorageService:
    """
    Durable document storage abstraction for uploaded and generated CVs:
    - Primary recommended production backend: S3-compatible object storage (Cloudflare R2, AWS S3, MinIO)
      configured via S3_BUCKET + S3_ACCESS_KEY_ID + S3_SECRET_ACCESS_KEY (+ optional S3_ENDPOINT_URL).
    - Zero-config stateless durability fallback: Fernet-encrypted document blobs stored in PostgreSQL/SQLite
      (`CandidateDocument.encrypted_content`) so files survive ephemeral container restarts/redeploys
      and are captured automatically by database backups.
    """

    def get_storage_status(self) -> Dict[str, Any]:
        s3_on = is_s3_configured()
        cfg = _s3_config()
        return {
            "backend": "s3" if s3_on else "db_blob",
            "s3_configured": s3_on,
            "s3_bucket": cfg["bucket"] if s3_on else None,
            "durable": True,
        }

    def put_s3_object(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        cfg = _s3_config()
        url = _object_url(cfg, object_key)
        headers = _sigv4_headers(
            "PUT",
            url,
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
            region=cfg["region"],
            payload=data,
            content_type=content_type,
        )
        with httpx.Client(timeout=20.0) as client:
            resp = client.put(url, content=data, headers=headers)
            resp.raise_for_status()

    def get_s3_object(self, object_key: str) -> Optional[bytes]:
        cfg = _s3_config()
        url = _object_url(cfg, object_key)
        headers = _sigv4_headers(
            "GET",
            url,
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
            region=cfg["region"],
        )
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.content

    def delete_s3_object(self, object_key: str) -> bool:
        cfg = _s3_config()
        url = _object_url(cfg, object_key)
        headers = _sigv4_headers(
            "DELETE",
            url,
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
            region=cfg["region"],
        )
        with httpx.Client(timeout=15.0) as client:
            resp = client.delete(url, headers=headers)
            return resp.status_code in (200, 202, 204, 404)

    def persist_document(
        self,
        *,
        user_id: Optional[int],
        doc_type: str,
        filename: str,
        raw_bytes: bytes,
    ) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Persists document bytes durably to S3/R2 (when configured) or encrypted DB blob fallback.
        Returns `(storage_backend, object_key, encrypted_content)`.
        """
        ext = Path(filename).suffix.lower()
        content_type = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".html": "text/html; charset=utf-8",
            ".eml": "message/rfc822",
            ".md": "text/markdown; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }.get(ext, "application/octet-stream")

        if is_s3_configured():
            obj_key = build_object_key(user_id, doc_type, filename)
            try:
                self.put_s3_object(obj_key, raw_bytes, content_type=content_type)
                return "s3", obj_key, None
            except Exception as exc:
                logger.error("S3 upload failed for %s (%s); falling back to encrypted DB blob.", obj_key, exc)

        if len(raw_bytes) <= MAX_DB_BLOB_BYTES:
            try:
                return "db_blob", None, encode_encrypted_blob(raw_bytes)
            except Exception as exc:
                logger.warning("Encrypted DB blob encoding failed for %s: %s", filename, exc)

        return "local", None, None

    def hydrate_local_file(
        self,
        target_path: Path,
        *,
        storage_backend: Optional[str],
        object_key: Optional[str],
        encrypted_content: Optional[str],
        expected_sha256: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Ensures `target_path` exists on local disk by restoring bytes from S3/R2 or encrypted DB blob
        after container restarts, ephemeral disk wipes, or horizontal scaling.
        """
        if target_path.is_file():
            return target_path

        restored: Optional[bytes] = None
        if storage_backend == "s3" and object_key and is_s3_configured():
            try:
                restored = self.get_s3_object(object_key)
            except Exception as exc:
                logger.error("Failed hydrating S3 object %s: %s", object_key, exc)

        if restored is None and encrypted_content:
            try:
                restored = decode_encrypted_blob(encrypted_content)
            except Exception as exc:
                logger.error("Failed decrypting DB document blob for %s: %s", target_path.name, exc)
                return None

        if restored is None:
            return None

        if expected_sha256:
            actual_sha = hashlib.sha256(restored).hexdigest()
            if actual_sha != expected_sha256:
                logger.error(
                    "SHA-256 mismatch while hydrating %s (expected %s, got %s).",
                    target_path.name,
                    expected_sha256,
                    actual_sha,
                )
                return None

        return _atomic_write_bytes(target_path, restored)

    def delete_remote_document(self, storage_backend: Optional[str], object_key: Optional[str]) -> bool:
        if storage_backend == "s3" and object_key and is_s3_configured():
            try:
                return self.delete_s3_object(object_key)
            except Exception as exc:
                logger.warning("Failed deleting S3 object %s: %s", object_key, exc)
                return False
        return True


storage_service = DocumentStorageService()
