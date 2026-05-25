"""
Javris Email Skill — Gmail IMAP + SMTP
────────────────────────────────────────
Reads Gmail credentials from GMAIL_ADDRESS and GMAIL_APP_PASSWORD.

Actions:
  send     — compose & send email (SMTP SSL :465)
  read     — fetch recent inbox/folder messages (IMAP SSL :993)
  search   — search inbox by keyword/sender/subject
  unread   — count + list unread messages
  reply    — reply to a specific email (by UID)
  delete   — move email to Trash (by UID)
  validate — Disify API: check email deliverability

Features:
  • Persistent IMAP connection pool (one connection reused per session)
  • HTML + plain-text multipart send
  • Full header decode (RFC2047 encoded subjects / senders)
  • Body preview with smart truncation
  • Unread count for morning digest integration
  • Thread-safe: IMAP calls run in executor so asyncio is never blocked
"""

from __future__ import annotations

import asyncio
import email as _email_lib
import email.header as _email_header
import imaplib
import os
import smtplib
import textwrap
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.skill.email")
cfg = get_config()

# ── Credentials ───────────────────────────────────────────────────
# pydantic-settings populates its model but does NOT modify os.environ.
# Load .env explicitly so that direct os.environ reads work too.
try:
    from dotenv import load_dotenv as _load_dotenv
    from pathlib import Path as _Path
    _load_dotenv(_Path(__file__).resolve().parent.parent / ".env", override=False)
except Exception:
    pass

_GMAIL_ADDRESS  = os.environ.get("GMAIL_ADDRESS", "")
_GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
_IMAP_HOST      = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
_IMAP_PORT      = int(os.environ.get("GMAIL_IMAP_PORT", "993"))
_SMTP_HOST      = os.environ.get("GMAIL_SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT      = int(os.environ.get("GMAIL_SMTP_PORT", "465"))


# ── RFC2047 header decoder ────────────────────────────────────────

def _decode_header(raw: str) -> str:
    """Decode RFC2047-encoded email header (e.g. =?utf-8?b?...?=)."""
    if not raw:
        return ""
    parts = _email_header.decode_header(raw)
    decoded = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
            except Exception:
                decoded.append(chunk.decode("utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return " ".join(decoded).strip()


def _extract_body(msg) -> str:
    """Extract plain-text body from a parsed email.Message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                charset  = part.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace") if payload else ""
                break
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        body = payload.decode(charset, errors="replace") if payload else ""
    return body.strip()


def _parse_message(uid: bytes, raw_bytes: bytes) -> dict:
    """Turn raw RFC822 bytes into a clean dict."""
    msg = _email_lib.message_from_bytes(raw_bytes)
    body = _extract_body(msg)
    return {
        "uid":     uid.decode() if isinstance(uid, bytes) else str(uid),
        "from":    _decode_header(msg.get("From", "")),
        "to":      _decode_header(msg.get("To", "")),
        "subject": _decode_header(msg.get("Subject", "(no subject)")),
        "date":    msg.get("Date", ""),
        "body":    textwrap.shorten(body, width=400, placeholder="…"),
        "snippet": textwrap.shorten(body, width=100, placeholder="…"),
    }


# ── IMAP connection pool (one persistent connection per thread) ───

_imap_lock = threading.Lock()
_imap_conn: Optional[imaplib.IMAP4_SSL] = None
_imap_folder: str = ""


def _get_imap(folder: str = "INBOX") -> imaplib.IMAP4_SSL:
    """Return a live IMAP connection, reconnecting if needed."""
    global _imap_conn, _imap_folder
    if not _GMAIL_ADDRESS or not _GMAIL_PASSWORD:
        raise RuntimeError("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD before using email")
    with _imap_lock:
        try:
            if _imap_conn:
                _imap_conn.noop()   # check if alive
                if _imap_folder != folder:
                    _imap_conn.select(folder)
                    _imap_folder = folder
                return _imap_conn
        except Exception:
            _imap_conn = None

        conn = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        conn.login(_GMAIL_ADDRESS, _GMAIL_PASSWORD)
        conn.select(folder)
        _imap_conn = conn
        _imap_folder = folder
        logger.info(f"IMAP connected to {_IMAP_HOST} as {_GMAIL_ADDRESS}")
        return conn


def _close_imap() -> None:
    global _imap_conn
    with _imap_lock:
        if _imap_conn:
            try:
                _imap_conn.logout()
            except Exception:
                pass
            _imap_conn = None


# ── EmailSkill ────────────────────────────────────────────────────

class EmailSkill(BaseSkill):
    name        = "email"
    aliases     = ["send_email", "read_emails", "check_email", "search_email",
                   "unread_email", "reply_email", "delete_email", "validate_email"]
    description = "Read, send, search, and manage Gmail via IMAP + SMTP"

    tool_definition = {
        "name": "email",
        "description": (
            "Full Gmail integration: read inbox, send emails, search, check unread, "
            "reply to a thread, delete, or validate an address. "
            "Actions: read | send | search | unread | reply | delete | validate"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "send", "search", "unread", "reply", "delete", "validate"],
                    "description": (
                        "read=list recent emails | send=compose+send | search=find by keyword | "
                        "unread=count+list unread | reply=reply to UID | delete=trash email | "
                        "validate=check deliverability"
                    ),
                },
                "to": {
                    "type": "string",
                    "description": "Recipient address (send / validate)",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject (send / reply)",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (send / reply)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query — supports Gmail-style: 'from:name', 'subject:hello', 'keyword' (search action)",
                },
                "uid": {
                    "type": "string",
                    "description": "Email UID for reply / delete actions",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of emails to return (read / search / unread). Default 5.",
                    "default": 5,
                },
                "folder": {
                    "type": "string",
                    "description": "IMAP folder name. Default INBOX. Others: [Gmail]/Sent Mail, [Gmail]/Drafts, [Gmail]/Spam",
                    "default": "INBOX",
                },
            },
            "required": ["action"],
        },
    }

    async def run(
        self,
        action: str = "read",
        to: str = "",
        subject: str = "",
        body: str = "",
        query: str = "",
        uid: str = "",
        count: int = 5,
        folder: str = "INBOX",
        **_,
    ) -> dict | list | str:
        a = action.lower().strip()
        loop = asyncio.get_event_loop()

        if a == "send":
            return await loop.run_in_executor(None, self._smtp_send, to, subject, body)
        elif a == "read":
            return await loop.run_in_executor(None, self._imap_read, count, folder)
        elif a == "search":
            return await loop.run_in_executor(None, self._imap_search, query, count, folder)
        elif a == "unread":
            return await loop.run_in_executor(None, self._imap_unread, count, folder)
        elif a == "reply":
            return await loop.run_in_executor(None, self._imap_reply, uid, body)
        elif a == "delete":
            return await loop.run_in_executor(None, self._imap_delete, uid, folder)
        elif a == "validate":
            return await self._validate(to or query)
        else:
            return {"error": f"Unknown action '{action}'. Use: read|send|search|unread|reply|delete|validate"}

    # ── SMTP SEND ─────────────────────────────────────────────

    def _smtp_send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_uid: str = "",
        in_reply_to: str = "",
    ) -> dict:
        if not to:
            return {"error": "Recipient (to) is required"}
        if not _GMAIL_ADDRESS or not _GMAIL_PASSWORD:
            return {"error": "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD before sending email"}

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject or "(no subject)"
        msg["From"]    = f"Javris <{_GMAIL_ADDRESS}>"
        msg["To"]      = to
        msg["Date"]    = _email_lib.utils.formatdate(localtime=True)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"]  = in_reply_to

        msg.attach(MIMEText(body, "plain", "utf-8"))
        # HTML version with simple styling
        html = f"""<div style="font-family:sans-serif;font-size:14px;color:#1a1a1a">
{body.replace(chr(10), "<br>")}
<br><br><span style="color:#888;font-size:12px">Sent via Javris AI Assistant</span>
</div>"""
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
                server.login(_GMAIL_ADDRESS, _GMAIL_PASSWORD)
                server.sendmail(_GMAIL_ADDRESS, to, msg.as_string())
            logger.info(f"Email sent → {to} | {subject}")
            return {"status": "sent", "to": to, "subject": subject or "(no subject)"}
        except smtplib.SMTPAuthenticationError:
            return {"error": "Gmail authentication failed — check App Password in .env"}
        except smtplib.SMTPRecipientsRefused:
            return {"error": f"Recipient refused: {to}"}
        except Exception as e:
            return {"error": f"SMTP error: {e}"}

    # ── IMAP READ ─────────────────────────────────────────────

    def _imap_read(self, count: int, folder: str) -> list[dict]:
        try:
            conn = _get_imap(folder)
            _, data = conn.search(None, "ALL")
            ids = data[0].split()
            if not ids:
                return [{"info": f"No messages in {folder}"}]
            latest = list(reversed(ids[-count:])) if len(ids) >= count else list(reversed(ids))
            return self._fetch_messages(conn, latest)
        except Exception as e:
            _close_imap()
            return [{"error": f"IMAP read failed: {e}"}]

    # ── IMAP SEARCH ──────────────────────────────────────────

    def _imap_search(self, query: str, count: int, folder: str) -> list[dict]:
        """
        Supports Gmail-style query fragments:
          'from:someone'    → FROM "someone"
          'subject:hello'   → SUBJECT "hello"
          'has:attachment'  → ignored (not standard IMAP)
          plain keyword     → TEXT "keyword"
        """
        if not query:
            return [{"error": "query is required for search"}]

        # Build IMAP search criteria
        criteria = []
        parts = query.strip().split()
        fallback_terms = []
        for p in parts:
            lp = p.lower()
            if lp.startswith("from:"):
                criteria.append(f'FROM "{p[5:]}"')
            elif lp.startswith("subject:"):
                criteria.append(f'SUBJECT "{p[8:]}"')
            elif lp.startswith("to:"):
                criteria.append(f'TO "{p[3:]}"')
            elif lp.startswith("is:unread"):
                criteria.append("UNSEEN")
            else:
                fallback_terms.append(p)

        if fallback_terms:
            criteria.append(f'TEXT "{" ".join(fallback_terms)}"')

        search_str = " ".join(criteria) if criteria else f'TEXT "{query}"'

        try:
            conn = _get_imap(folder)
            _, data = conn.search(None, search_str)
            ids = data[0].split()
            if not ids:
                return [{"info": f"No emails matching '{query}'"}]
            latest = list(reversed(ids[-count:])) if len(ids) >= count else list(reversed(ids))
            return self._fetch_messages(conn, latest)
        except Exception as e:
            _close_imap()
            return [{"error": f"Search failed: {e}"}]

    # ── IMAP UNREAD ──────────────────────────────────────────

    def _imap_unread(self, count: int, folder: str) -> dict:
        try:
            conn = _get_imap(folder)
            _, data = conn.search(None, "UNSEEN")
            ids = data[0].split()
            total_unread = len(ids)
            if not ids:
                return {"unread_count": 0, "messages": [], "info": "No unread emails"}
            latest = list(reversed(ids[-count:])) if len(ids) >= count else list(reversed(ids))
            msgs = self._fetch_messages(conn, latest)
            return {
                "unread_count": total_unread,
                "showing": len(msgs),
                "messages": msgs,
            }
        except Exception as e:
            _close_imap()
            return {"error": f"Unread check failed: {e}"}

    # ── IMAP REPLY ───────────────────────────────────────────

    def _imap_reply(self, uid: str, body: str) -> dict:
        if not uid:
            return {"error": "UID required for reply"}
        if not body:
            return {"error": "Reply body cannot be empty"}
        try:
            conn = _get_imap("INBOX")
            _, raw = conn.fetch(uid.encode(), "(RFC822)")
            if not raw or not raw[0]:
                return {"error": f"Message UID {uid} not found"}
            original = _email_lib.message_from_bytes(raw[0][1])
            to        = _decode_header(original.get("Reply-To") or original.get("From", ""))
            orig_subj = _decode_header(original.get("Subject", ""))
            reply_subj = orig_subj if orig_subj.lower().startswith("re:") else f"Re: {orig_subj}"
            message_id = original.get("Message-ID", "")
            return self._smtp_send(to, reply_subj, body, uid, message_id)
        except Exception as e:
            _close_imap()
            return {"error": f"Reply failed: {e}"}

    # ── IMAP DELETE (move to Trash) ──────────────────────────

    def _imap_delete(self, uid: str, folder: str) -> dict:
        if not uid:
            return {"error": "UID required for delete"}
        try:
            conn = _get_imap(folder)
            # Move to Gmail Trash
            conn.copy(uid.encode(), "[Gmail]/Trash")
            conn.store(uid.encode(), "+FLAGS", "\\Deleted")
            conn.expunge()
            logger.info(f"Email UID {uid} moved to Trash")
            return {"status": "deleted", "uid": uid}
        except Exception as e:
            _close_imap()
            return {"error": f"Delete failed: {e}"}

    # ── Shared fetch helper ──────────────────────────────────

    def _fetch_messages(self, conn: imaplib.IMAP4_SSL, uids: list) -> list[dict]:
        results = []
        for uid in uids:
            try:
                _, raw = conn.fetch(uid, "(RFC822)")
                if raw and raw[0] and isinstance(raw[0], tuple):
                    results.append(_parse_message(uid, raw[0][1]))
            except Exception as e:
                results.append({"uid": uid, "error": str(e)})
        return results

    # ── Email validation (Disify) ────────────────────────────

    async def _validate(self, address: str) -> dict:
        if not address:
            return {"error": "Email address required"}
        try:
            url = f"https://www.disify.com/api/email/{address}"
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {cfg.disify_api_key}"})
            if r.status_code == 200:
                d = r.json()
                return {
                    "email":       address,
                    "format_valid": d.get("format", False),
                    "disposable":  d.get("disposable", False),
                    "dns_valid":   d.get("dns", False),
                    "deliverable": d.get("format", False) and d.get("dns", False) and not d.get("disposable", False),
                }
            return {"error": f"Disify HTTP {r.status_code}"}
        except Exception as e:
            return {"error": f"Validation error: {e}"}
