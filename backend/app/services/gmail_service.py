import base64
import email.mime.application
import email.mime.multipart
import email.mime.text
import imaplib
import logging
import re
import smtplib
import ssl
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from urllib.parse import urlencode

from ..config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GENERATED_RESUMES_DIR,
    get_email_delivery_config,
    get_smtp_config,
)
from ..db.document_repository import resolve_owned_generated_document, user_generated_resumes_dir
from ..db.models import User
from .crypto_service import mask_email
from datetime import UTC

logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/userinfo.email",
]
GOOGLE_WORKSPACE_SCOPES = GMAIL_SCOPES


class GmailService:
    """
    Manages Google OAuth2 flow, RFC 2822 MIME email preparation, and Gmail API draft/send dispatch.
    """

    @staticmethod
    def _resolve_safe_attachment_path(fpath: Optional[str], user_id: Optional[int] = None) -> Optional[Path]:
        """Restricts outbound email/draft attachments strictly to files owned by user_id (or root dir when unauthenticated)."""
        if not fpath or "\x00" in str(fpath):
            return None
        raw = Path(str(fpath).strip())
        if user_id is not None:
            user_dir = user_generated_resumes_dir(user_id)
            candidate = raw.resolve() if raw.is_absolute() else (user_dir / raw.name).resolve()
            if candidate.is_relative_to(user_dir) and candidate.is_file():
                owned, _ = resolve_owned_generated_document(candidate.name, user_id=user_id, is_guest=False)
                if owned is not None or candidate.parent == user_dir:
                    return candidate
            logger.warning("Blocked or missing user-scoped email attachment %s for user_id=%s", fpath, user_id)
            return None

        gen_root = GENERATED_RESUMES_DIR.resolve()
        candidate = raw.resolve() if raw.is_absolute() else (gen_root / raw.name).resolve()
        if candidate.parent != gen_root or not candidate.is_relative_to(gen_root) or not candidate.is_file():
            logger.warning("Blocked or missing email attachment path outside generated resumes dir: %s", fpath)
            return None
        return candidate

    def is_configured(self) -> bool:
        return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

    def get_authorization_url(self, state: str) -> str:
        """Returns the real Google OAuth 2.0 consent URL using configured GCP credentials."""
        if not self.is_configured():
            raise ValueError(
                "Google OAuth credentials (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) are not configured."
            )

        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchanges an authorization code for real Google OAuth tokens."""
        if not self.is_configured():
            return {"error": "Google OAuth credentials are not configured on the server."}

        try:
            import httpx

            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
            res = httpx.post(token_url, data=data, timeout=10.0)
            if res.is_success:
                return res.json()
            logger.error("Google token exchange failed (HTTP %s): %s", res.status_code, res.text[:300])
            return {"error": res.text}
        except Exception as e:
            logger.error("Exception during Google token exchange: %s", e)
            return {"error": str(e)}

    def build_mime_message(
        self,
        sender_email: str,
        to_email: str,
        subject: str,
        body_text: str,
        pdf_path: Optional[str] = None,
        attachment_paths: Optional[List[str]] = None,
        user_id: Optional[int] = None,
    ) -> email.mime.multipart.MIMEMultipart:
        """Constructs an RFC 2822 compliant MIME message with Word (.docx) / PDF resume attachments."""
        msg = email.mime.multipart.MIMEMultipart()
        if sender_email:
            msg["From"] = sender_email
        if to_email:
            msg["To"] = to_email
        msg["Subject"] = subject

        # Attach text body
        msg.attach(email.mime.text.MIMEText(body_text, "plain", "utf-8"))

        all_files: List[str] = []
        if pdf_path:
            all_files.append(pdf_path)
        if attachment_paths:
            for ap in attachment_paths:
                if ap and ap not in all_files:
                    all_files.append(ap)

        for fpath in all_files:
            p = self._resolve_safe_attachment_path(fpath, user_id=user_id)
            if p is not None:
                with open(p, "rb") as f:
                    ext = p.suffix.lower()
                    subtype = "pdf" if ext == ".pdf" else (
                        "vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == ".docx" else "octet-stream"
                    )
                    part = email.mime.application.MIMEApplication(f.read(), _subtype=subtype)
                    part.add_header("Content-Disposition", "attachment", filename=p.name)
                    msg.attach(part)
                logger.info(f"Attached resume '{p.name}' to outgoing MIME email.")
            else:
                logger.warning(f"Resume attachment '{fpath}' rejected or not found inside generated resumes directory; skipping.")

        return msg

    def _find_gmail_drafts_mailbox(self, imap_conn: imaplib.IMAP4_SSL) -> str:
        """Detects the localized Gmail Drafts IMAP mailbox (handles [Gmail]/Drafts, [Google Mail]/Drafts, etc.)."""
        try:
            status, boxes = imap_conn.list()
            if status == "OK" and boxes:
                for raw in boxes:
                    line = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
                    if "\\Drafts" in line:
                        m = re.search(r'"([^"]+)"\s*$', line)
                        if m:
                            return f'"{m.group(1)}"' if " " in m.group(1) else m.group(1)
                        last_tok = line.strip().split()[-1]
                        if last_tok:
                            return last_tok
        except Exception as e:
            logger.debug(f"IMAP LIST fallback: {e}")
        return '"[Gmail]/Drafts"'

    def create_gmail_draft(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        attachment_paths: Optional[List[str]] = None,
        user: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Creates a real Gmail Draft WITH the tailored .docx/.pdf resume already attached inside Gmail Drafts!
        1. Uses Gmail API drafts().create if Google OAuth token is connected.
        2. Uses Gmail IMAP (imap.gmail.com:993) with GMAIL_USER + GMAIL_APP_PASSWORD from backend/.env.
        Returns {draft_created, attached_files, drafts_url, mode_used, error}.
        """
        resolved_files: List[str] = []
        uid = user.id if user else None
        for fpath in (attachment_paths or []):
            p = self._resolve_safe_attachment_path(fpath, user_id=uid)
            if p is not None:
                resolved_files.append(str(p))

        # Path 1: Connected Google OAuth API
        if user and user.gmail_oauth_token and not user.gmail_oauth_token.get("simulated") and self.is_configured():
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build

                td = user.gmail_oauth_token
                creds = Credentials(
                    token=td.get("access_token"),
                    refresh_token=td.get("refresh_token"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=GOOGLE_CLIENT_SECRET,
                    scopes=GMAIL_SCOPES,
                )
                service = build("gmail", "v1", credentials=creds)
                mime_msg = self.build_mime_message(
                    sender_email=user.email,
                    to_email=recipient_email,
                    subject=subject,
                    body_text=body_text,
                    attachment_paths=resolved_files,
                    user_id=uid,
                )
                raw_b64 = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")
                draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw_b64}}).execute()
                return {
                    "draft_created": True,
                    "draft_id": draft.get("id"),
                    "attached_files": [Path(x).name for x in resolved_files],
                    "drafts_url": "https://mail.google.com/mail/u/0/#drafts",
                    "mode_used": "gmail_oauth_api",
                    "error": None,
                }
            except Exception as oe:
                logger.warning(f"OAuth draft creation fell back to IMAP: {oe}")

        # Path 2: Gmail IMAP (uses the same GMAIL_USER + GMAIL_APP_PASSWORD as SMTP)
        cfg = get_smtp_config()
        if not cfg.get("configured"):
            return {
                "draft_created": False,
                "draft_id": None,
                "attached_files": [Path(x).name for x in resolved_files],
                "drafts_url": None,
                "mode_used": "browser_compose_fallback",
                "error": "GMAIL_USER / GMAIL_APP_PASSWORD not configured in backend/.env; opened compose window with CV downloaded.",
            }

        sender_addr = cfg["user"]
        mime_msg = self.build_mime_message(
            sender_email=sender_addr,
            to_email=recipient_email,
            subject=subject,
            body_text=body_text,
            attachment_paths=resolved_files,
        )
        try:
            ctx = ssl.create_default_context()
            with imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ctx, timeout=14) as imap_conn:
                imap_conn.login(cfg["user"], cfg["password"])
                drafts_box = self._find_gmail_drafts_mailbox(imap_conn)
                res_status, res_data = imap_conn.append(
                    drafts_box,
                    "\\Draft",
                    imaplib.Time2Internaldate(time.time()),
                    mime_msg.as_bytes(),
                )
                if res_status != "OK":
                    raise RuntimeError(f"IMAP APPEND returned {res_status}: {res_data}")
            logger.info(f"Created real Gmail Draft via IMAP with attachments {[Path(x).name for x in resolved_files]} for {mask_email(sender_addr)}.")
            return {
                "draft_created": True,
                "draft_id": "imap-draft",
                "attached_files": [Path(x).name for x in resolved_files],
                "drafts_url": "https://mail.google.com/mail/u/0/#drafts",
                "mode_used": "gmail_imap_drafts",
                "error": None,
            }
        except imaplib.IMAP4.error as ie:
            err = f"Gmail IMAP rejected credentials or IMAP is disabled in Gmail settings: {ie}"
            logger.warning(err)
            return {
                "draft_created": False,
                "draft_id": None,
                "attached_files": [Path(x).name for x in resolved_files],
                "drafts_url": None,
                "mode_used": "browser_compose_fallback",
                "error": err,
            }
        except Exception as e:
            err = f"Gmail IMAP draft creation error: {e}"
            logger.warning(err)
            return {
                "draft_created": False,
                "draft_id": None,
                "attached_files": [Path(x).name for x in resolved_files],
                "drafts_url": None,
                "mode_used": "browser_compose_fallback",
                "error": err,
            }

    def dispatch_email(
        self,
        user: User,
        recipient_email: str,
        subject: str,
        body_text: str,
        pdf_path: Optional[str] = None,
        mode: str = "draft",  # "draft" or "send"
    ) -> Dict[str, Any]:
        """
        Creates a draft or sends an email via Gmail API or simulation.
        """
        mime_msg = self.build_mime_message(
            sender_email=user.email,
            to_email=recipient_email,
            subject=subject,
            body_text=body_text,
            pdf_path=pdf_path,
            user_id=user.id,
        )
        raw_base64 = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        token_data = user.gmail_oauth_token
        # If user has a live Google access token and credentials are valid, invoke Google API
        if token_data and not token_data.get("simulated") and self.is_configured():
            try:
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build

                creds = Credentials(
                    token=token_data.get("access_token"),
                    refresh_token=token_data.get("refresh_token"),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=GOOGLE_CLIENT_SECRET,
                    scopes=GMAIL_SCOPES,
                )
                service = build("gmail", "v1", credentials=creds)

                if mode == "send":
                    sent = service.users().messages().send(userId="me", body={"raw": raw_base64}).execute()
                    return {
                        "status": "success",
                        "mode": "send",
                        "channel": "gmail_oauth",
                        "message_id": sent.get("id"),
                        "thread_id": sent.get("threadId"),
                        "recipient": recipient_email,
                        "subject": subject,
                        "pdf_attached": bool(pdf_path),
                    }
                else:
                    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw_base64}}).execute()
                    return {
                        "status": "success",
                        "mode": "draft",
                        "draft_id": draft.get("id"),
                        "recipient": recipient_email,
                        "subject": subject,
                        "pdf_attached": bool(pdf_path),
                    }
            except Exception as e:
                logger.error(f"Live Gmail API dispatch failed, falling back to verified MIME receipt: {e}")

        # Try live SMTP fallback when mode == "send" and SMTP credentials are configured
        smtp_cfg = get_smtp_config()
        if mode == "send" and smtp_cfg["configured"]:
            ok, detail = self.send_email_smtp(
                to_email=recipient_email,
                subject=subject,
                body_text=body_text,
                pdf_path=pdf_path,
                user_id=user.id,
            )
            if ok:
                return {
                    "status": "success",
                    "mode": "send",
                    "action": "Dispatched via Gmail SMTP",
                    "recipient": recipient_email,
                    "subject": subject,
                    "pdf_attached": bool(pdf_path and Path(pdf_path).exists()),
                    "attached_filename": Path(pdf_path).name if pdf_path else None,
                    "gmail_account": smtp_cfg["from_email"],
                    "simulated": False,
                    "note": detail,
                }

        # Build downloadable RFC 2822 .eml draft file so user can open directly in any mail client with CV attached
        import uuid
        eml_filename = f"application_{uuid.uuid4().hex[:8]}.eml"
        user_dir = user_generated_resumes_dir(user.id)
        eml_path = user_dir / eml_filename
        eml_path.write_bytes(mime_msg.as_bytes())
        return {
            "status": "needs_transport",
            "mode": mode,
            "action": "Prepared Downloadable .eml Draft (Configure Gmail OAuth or SMTP App Password for 1-Click Send)",
            "recipient": recipient_email,
            "subject": subject,
            "pdf_attached": bool(pdf_path and Path(pdf_path).exists()),
            "attached_filename": Path(pdf_path).name if pdf_path else None,
            "eml_filename": eml_filename,
            "eml_url": f"/api/resumes/generated/{eml_filename}",
            "gmail_account": user.email,
            "message_size_bytes": len(raw_base64),
            "simulated": False,
            "note": (
                "No simulated transmission: download the pre-assembled .eml file (with CV attached) "
                "or connect Gmail OAuth / SMTP App Password to send directly."
            ),
        }

    @staticmethod
    def _smtp_execute(host: str, port: int, user: str, password: str, msg=None) -> None:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=12) as server:
                server.login(user, password)
                if msg is not None:
                    server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=12) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                server.login(user, password)
                if msg is not None:
                    server.send_message(msg)

    def verify_smtp_credentials(
        self,
        user: str,
        password: str,
        host: str = "smtp.gmail.com",
        port: int = 465,
    ) -> Tuple[bool, str]:
        """Tests live SMTP authentication against Gmail without persisting anything if rejected."""
        clean_user = (user or "").strip()
        clean_pass = (password or "").replace(" ", "").strip()
        if not clean_user or "@" not in clean_user or len(clean_pass) < 8:
            return False, "Provide a valid Gmail address and 16-character Google App Password."
        try:
            self._smtp_execute(host, port, clean_user, clean_pass)
            return True, f"Authenticated SMTP sender {mask_email(clean_user)}."
        except smtplib.SMTPAuthenticationError:
            return False, "Gmail rejected the email or App Password. Make sure 2FA is enabled and use a 16-character Google App Password."
        except Exception as e:
            return False, f"Could not connect to {host}:{port}: {e}"

    def send_email_smtp(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        html_body: Optional[str] = None,
        pdf_path: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> tuple[bool, str]:
        """Sends a real email via Gmail / SMTP (SSL on 465 or STARTTLS on 587)."""
        cfg = get_smtp_config()
        if not cfg["configured"]:
            return False, "SMTP not configured (missing GMAIL_USER / GMAIL_APP_PASSWORD in backend/.env)"

        msg = email.mime.multipart.MIMEMultipart("alternative" if html_body and not pdf_path else "mixed")
        msg["From"] = f"TalentFlow AI <{cfg['from_email']}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        if html_body and not pdf_path:
            msg.attach(email.mime.text.MIMEText(body_text, "plain", "utf-8"))
            msg.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))
        elif html_body and pdf_path:
            alt = email.mime.multipart.MIMEMultipart("alternative")
            alt.attach(email.mime.text.MIMEText(body_text, "plain", "utf-8"))
            alt.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))
            msg.attach(alt)
        else:
            msg.attach(email.mime.text.MIMEText(body_text, "plain", "utf-8"))

        if pdf_path and (p := self._resolve_safe_attachment_path(pdf_path, user_id=user_id)):
            with open(p, "rb") as f:
                part = email.mime.application.MIMEApplication(f.read(), _subtype="pdf")
                part.add_header("Content-Disposition", "attachment", filename=p.name)
                msg.attach(part)

        try:
            self._smtp_execute(cfg["host"], cfg["port"], cfg["user"], cfg["password"], msg=msg)
            logger.info(f"SMTP email successfully sent to {mask_email(to_email)} via {cfg['host']}:{cfg['port']}")
            return True, f"Sent to {mask_email(to_email)} via {cfg['host']}"
        except smtplib.SMTPAuthenticationError as e:
            err = f"Gmail SMTP authentication rejected (check GMAIL_USER & 16-char App Password): {e}"
            logger.error(err)
            return False, err
        except Exception as e:
            err = f"SMTP delivery error: {e}"
            logger.error(err)
            return False, err

    def _send_https_email(self, provider: str, url: str, api_key: str, payload: Dict[str, Any], to_email: str) -> Tuple[bool, str]:
        try:
            import httpx

            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=12.0,
            )
            if 200 <= resp.status_code < 300:
                logger.info("HTTPS %s OTP email delivered to %s", provider, mask_email(to_email))
                return True, f"Sent via {provider} HTTPS API to {mask_email(to_email)}"
            err = f"{provider} API returned HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            err = f"{provider} HTTPS delivery error: {exc}"
        logger.error(err)
        return False, err

    def _send_email_resend(self, *, api_key: str, from_email: str, to_email: str, subject: str, body_text: str, html_body: str) -> Tuple[bool, str]:
        return self._send_https_email(
            "Resend",
            "https://api.resend.com/emails",
            api_key,
            {"from": from_email, "to": [to_email], "subject": subject, "text": body_text, "html": html_body},
            to_email,
        )

    def _send_email_sendgrid(self, *, api_key: str, from_email: str, to_email: str, subject: str, body_text: str, html_body: str) -> Tuple[bool, str]:
        return self._send_https_email(
            "SendGrid",
            "https://api.sendgrid.com/v3/mail/send",
            api_key,
            {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": from_email},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body_text}, {"type": "text/html", "value": html_body}],
            },
            to_email,
        )

    def send_otp_email(self, to_email: str, code: str) -> Dict[str, Any]:
        """
        Dispatches a 6-digit passwordless OTP verification email.
        Supports HTTPS API providers (Resend, SendGrid over port 443) for cloud hosting compatibility,
        with fallback to Gmail/SMTP where outbound SMTP ports are permitted.
        """
        delivery_cfg = get_email_delivery_config()
        if not delivery_cfg["otp_enabled"]:
            return {
                "delivered": False,
                "smtp_configured": False,
                "provider": "disabled",
                "otp_available": False,
                "error": "Passwordless Email OTP sign-in is disabled on this server. Please use email and password sign-in.",
            }
        if not delivery_cfg["configured"] and get_smtp_config().get("configured"):
            delivery_cfg = {**delivery_cfg, "configured": True, "provider": "smtp"}
        if not delivery_cfg["configured"]:
            return {
                "delivered": False,
                "smtp_configured": False,
                "provider": "none",
                "otp_available": False,
                "error": (
                    "No OTP email provider is configured (set RESEND_API_KEY or SENDGRID_API_KEY + EMAIL_FROM "
                    "for HTTPS delivery, or local GMAIL_USER & GMAIL_APP_PASSWORD)."
                ),
            }

        subject = "Your TalentFlow AI Sign-In Verification Code"
        body_text = (
            f"Hello,\n\n"
            f"Your 6-digit verification code for TalentFlow AI is:\n\n"
            f"    {code}\n\n"
            f"This code expires in 10 minutes.\n\n"
            f"If you did not request this code, you can safely ignore this message."
        )
        html_body = (
            f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:20px auto;padding:24px;"
            f"background:#0f172a;color:#f8fafc;border-radius:12px;border:1px solid #1e293b;'>"
            f"<h2 style='margin:0 0 8px;color:#38bdf8;'>TalentFlow AI Verification</h2>"
            f"<p style='font-size:14px;color:#cbd5e1;'>Use this 6-digit one-time code to sign in:</p>"
            f"<div style='font-size:32px;font-weight:700;letter-spacing:8px;text-align:center;padding:16px;"
            f"margin:16px 0;background:#020617;border:1px solid #38bdf8;border-radius:10px;color:#ffffff;'>{code}</div>"
            f"<p style='font-size:12px;color:#94a3b8;'>Valid for 10 minutes. Do not share this code with anyone.</p>"
            f"</div>"
        )
        provider = delivery_cfg["provider"]
        if provider == "resend":
            ok, detail = self._send_email_resend(
                api_key=delivery_cfg["resend_api_key"],
                from_email=delivery_cfg["from_email"],
                to_email=to_email,
                subject=subject,
                body_text=body_text,
                html_body=html_body,
            )
        elif provider == "sendgrid":
            ok, detail = self._send_email_sendgrid(
                api_key=delivery_cfg["sendgrid_api_key"],
                from_email=delivery_cfg["from_email"],
                to_email=to_email,
                subject=subject,
                body_text=body_text,
                html_body=html_body,
            )
        else:
            ok, detail = self.send_email_smtp(to_email=to_email, subject=subject, body_text=body_text, html_body=html_body)
        return {
            "delivered": ok,
            "smtp_configured": True,
            "provider": provider,
            "otp_available": True,
            "error": None if ok else detail,
        }

    def send_application_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        pdf_path: Optional[str] = None,
        user: Optional[User] = None,
    ) -> Dict[str, Any]:
        """Direct email dispatch helper: prefers the user's connected Google OAuth token, falling back to SMTP."""
        if user and user.gmail_oauth_token and not user.gmail_oauth_token.get("simulated") and self.is_configured():
            dispatched = self.dispatch_email(
                user=user,
                recipient_email=to_email,
                subject=subject,
                body_text=body_text,
                pdf_path=pdf_path,
                mode="send",
            )
            if dispatched.get("channel") == "gmail_oauth":
                return {
                    "delivered": True,
                    "channel": "gmail_oauth",
                    "smtp_configured": get_smtp_config()["configured"],
                    "message_id": dispatched.get("message_id"),
                    "thread_id": dispatched.get("thread_id"),
                    "error": None,
                }

        cfg = get_smtp_config()
        if not cfg["configured"]:
            return {"delivered": False, "smtp_configured": False, "error": "Neither Google OAuth nor SMTP is configured"}
        ok, detail = self.send_email_smtp(to_email=to_email, subject=subject, body_text=body_text, pdf_path=pdf_path)
        return {"delivered": ok, "channel": "smtp", "smtp_configured": True, "error": None if ok else detail}

    @staticmethod
    def _parse_interview_window(start_iso: Optional[str], duration_minutes: int = 45):
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        start_dt = None
        if start_iso:
            raw = str(start_iso).strip()
            for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
                try:
                    start_dt = datetime.strptime(raw[:19], fmt)
                    break
                except ValueError:
                    continue
            if start_dt is None:
                try:
                    start_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    start_dt = None
        if start_dt is None:
            start_dt = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(minutes=max(15, int(duration_minutes or 45)))
        return start_dt, end_dt

    def build_google_calendar_template_url(
        self,
        *,
        summary: str,
        description: str = "",
        location: str = "",
        start_iso: Optional[str] = None,
        duration_minutes: int = 45,
    ) -> str:
        """Builds an instant one-click pre-filled Google Calendar event creation URL."""
        start_dt, end_dt = self._parse_interview_window(start_iso, duration_minutes)
        fmt = "%Y%m%dT%H%M%S"
        start_str = start_dt.strftime(fmt)
        end_str = end_dt.strftime(fmt)
        params = {
            "action": "TEMPLATE",
            "text": summary,
            "dates": f"{start_str}/{end_str}",
            "details": description or "Scheduled via TalentFlow AI",
        }
        if location:
            params["location"] = location
        return f"https://calendar.google.com/calendar/render?{urlencode(params)}"

    def build_ics_calendar_file(
        self,
        *,
        summary: str,
        description: str = "",
        location: str = "",
        start_iso: Optional[str] = None,
        duration_minutes: int = 45,
        uid_seed: str = "talentflow",
    ) -> str:
        """Generates a standards-compliant RFC 5545 .ics calendar invite with 60m and 15m reminders."""
        from datetime import datetime

        def _ics_escape(val: str) -> str:
            return (
                str(val or "")
                .replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\r\n", "\\n")
                .replace("\n", "\\n")
            )

        start_dt, end_dt = self._parse_interview_window(start_iso, duration_minutes)
        dtstamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
        dtend = end_dt.strftime("%Y%m%dT%H%M%S")
        event_uid = f"{re.sub(r'[^A-Za-z0-9_-]+', '-', uid_seed)}-{dtstart}@talentflow.local"
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//TalentFlow AI//Career Pipeline//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{event_uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description or 'Scheduled via TalentFlow AI')}",
        ]
        if location:
            lines.append(f"LOCATION:{_ics_escape(location)}")
        lines.extend([
            "BEGIN:VALARM",
            "TRIGGER:-PT60M",
            "ACTION:DISPLAY",
            "DESCRIPTION:Reminder: 1 hour until interview/follow-up",
            "END:VALARM",
            "BEGIN:VALARM",
            "TRIGGER:-PT15M",
            "ACTION:DISPLAY",
            "DESCRIPTION:Reminder: 15 minutes until interview/follow-up",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ])
        return "\r\n".join(lines)

    def create_calendar_event(
        self,
        *,
        user: Optional[User],
        summary: str,
        description: str = "",
        location: str = "",
        start_iso: Optional[str] = None,
        duration_minutes: int = 45,
        attendee_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a Google Calendar event using connected Google OAuth tokens (when calendar.events scope is authorized)
        and always returns a pre-filled Google Calendar popup link as an instant universal fallback.
        """
        start_dt, end_dt = self._parse_interview_window(start_iso, duration_minutes)
        template_url = self.build_google_calendar_template_url(
            summary=summary,
            description=description,
            location=location,
            start_iso=start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            duration_minutes=duration_minutes,
        )

        token_dict = (user.gmail_oauth_token if user else None) or {}
        has_live_oauth = bool(
            token_dict
            and not token_dict.get("simulated")
            and token_dict.get("access_token")
            and self.is_configured()
        )
        if not has_live_oauth:
            return {
                "created_in_google_calendar": False,
                "oauth_connected": False,
                "needs_oauth": True,
                "event_id": None,
                "html_link": template_url,
                "google_calendar_template_url": template_url,
                "start_iso": start_dt.isoformat(),
                "end_iso": end_dt.isoformat(),
                "message": "Google OAuth is not connected yet — open the pre-filled Google Calendar link or connect your Google account in Settings.",
            }

        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = Credentials(
                token=token_dict.get("access_token"),
                refresh_token=token_dict.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                scopes=GMAIL_SCOPES,
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())

            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            start_rfc = start_dt.isoformat() + ("Z" if start_dt.tzinfo is None else "")
            end_rfc = end_dt.isoformat() + ("Z" if end_dt.tzinfo is None else "")
            event_body: Dict[str, Any] = {
                "summary": summary,
                "description": description or "Scheduled via TalentFlow AI",
                "start": {"dateTime": start_rfc},
                "end": {"dateTime": end_rfc},
            }
            if location:
                event_body["location"] = location
            if attendee_email and "@" in attendee_email:
                event_body["attendees"] = [{"email": attendee_email}]

            created = service.events().insert(calendarId="primary", body=event_body).execute()
            return {
                "created_in_google_calendar": True,
                "oauth_connected": True,
                "needs_oauth": False,
                "event_id": created.get("id"),
                "html_link": created.get("htmlLink") or template_url,
                "google_calendar_template_url": template_url,
                "start_iso": start_dt.isoformat(),
                "end_iso": end_dt.isoformat(),
                "message": "Interview added directly to your Google Calendar.",
            }
        except Exception as exc:
            logger.warning("Google Calendar API insert fallback to template link: %s", exc)
            return {
                "created_in_google_calendar": False,
                "oauth_connected": True,
                "needs_oauth": "insufficient" in str(exc).lower() or "scope" in str(exc).lower(),
                "event_id": None,
                "html_link": template_url,
                "google_calendar_template_url": template_url,
                "start_iso": start_dt.isoformat(),
                "end_iso": end_dt.isoformat(),
                "error": str(exc),
                "message": "Could not write via Calendar API automatically (re-authorize Google Calendar scope or use the quick Google Calendar link).",
            }


gmail_service = GmailService()
