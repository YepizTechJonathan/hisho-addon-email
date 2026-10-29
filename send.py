"""Sending, for the Email add-on: the ONLY file with SMTP in it. It runs only from Hisho's Approvals list, when the
owner pressed Approve on a card that showed this exact message (Core checks the payload's hash first).

What it can do: send ONE plain-text message from the mailbox the card names, to the recipients the card listed
(To and Cc; never a Bcc, never an attachment), threaded with In-Reply-To / References, and make sure exactly one copy
is in that mailbox's Sent folder: Zoho usually files SMTP mail there itself, so it looks first (EXAMINE, SEARCH) and
APPENDs only if no copy shows up. ``SentIMAP`` refuses every IMAP command except those, and APPEND to any folder but
Sent. It never moves, flags, deletes or marks anything. A rate guard caps sends per mailbox per hour.
"""
from __future__ import annotations

import datetime as dt
import email.message
import html as html_mod
import email.policy
import email.utils
import imaplib
import json
import os
import re
import smtplib
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable

ADDR_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
MAX_RECIPIENTS = 10
MAX_BODY = 20_000
DEFAULT_PER_HOUR = 10
SENT_LOOKS = 4            # look for Zoho's own copy 4 times, 3 s apart, before appending one
_lock = threading.Lock()


class SendError(RuntimeError):
    pass


class SendViolation(RuntimeError):
    pass


def check_send_command(name: str, args: tuple[Any, ...], sent_folder: str) -> None:
    """The IMAP the send path may use: log in, open Sent read only, search it, append to it; nothing else."""
    name = str(name).upper()
    if name in ("LOGIN", "CAPABILITY", "EXAMINE", "NOOP", "LOGOUT"):
        return
    if name == "UID" and args and str(args[0]).upper() == "SEARCH":
        return
    if name == "APPEND" and args and str(args[0]).strip('"') == sent_folder:
        return
    raise SendViolation(f"refused IMAP {name} {str(args[:1])[:60]}: sending may only file a copy in {sent_folder}")


class SentIMAP(imaplib.IMAP4_SSL):
    sent_folder = "Sent"

    def _command(self, name: str, *args: Any) -> Any:
        check_send_command(name, args, self.sent_folder)
        return super()._command(name, *args)


# ── checking what the card asks for ───────────────────────────────────────

def _addrs(value: Any) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    out = []
    for a in items:
        a = email.utils.parseaddr(str(a).strip())[1]
        if a:
            if not ADDR_RE.match(a):
                raise SendError(f"{a!r} is not an email address")
            if a.lower() not in [x.lower() for x in out]:
                out.append(a)
    return out


def validate(payload: Any) -> dict[str, Any]:
    """The card's payload, checked and normalised: only these keys survive (so no Bcc, no attachments)."""
    if not isinstance(payload, dict):
        raise SendError("send needs mailbox, to, subject and body")
    to, cc = _addrs(payload.get("to")), _addrs(payload.get("cc"))
    if not to:
        raise SendError("say who it goes to")
    if len(to) + len(cc) > MAX_RECIPIENTS:
        raise SendError(f"at most {MAX_RECIPIENTS} recipients")
    subject = " ".join(str(payload.get("subject") or "").split())
    body = str(payload.get("body") or "").replace("\r\n", "\n").strip()
    if not subject or len(subject) > 250:
        raise SendError("a subject of 1 to 250 characters")
    if not body or len(body) > MAX_BODY:
        raise SendError(f"a body of 1 to {MAX_BODY} characters")
    mailbox = str(payload.get("mailbox") or "")
    if not re.match(r"^[a-z0-9-]{1,40}$", mailbox):
        raise SendError("which mailbox it's sent from")
    refs = [r for r in str(" ".join(payload.get("references") or []) if isinstance(payload.get("references"), list)
                           else payload.get("references") or "").split() if re.match(r"^<[^<>\s]{3,250}>$", r)][-20:]
    irt = str(payload.get("in_reply_to") or "").strip()
    irt = irt if re.match(r"^<[^<>\s]{3,250}>$", irt) else ""
    return {"mailbox": mailbox, "to": to, "cc": cc, "subject": subject, "body": body,
            "in_reply_to": irt, "references": refs}


def tls_context(host: str) -> ssl.SSLContext:
    """Checked TLS, except on this machine itself (Proton Mail Bridge on 127.0.0.1 has a certificate of its own;
    that traffic never leaves the machine)."""
    ctx = ssl.create_default_context()
    if str(host).strip().lower() in ("127.0.0.1", "localhost", "::1"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def open_smtp(host: str, port: int, smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL) -> Any:
    """An SMTP connection that is encrypted before the login: TLS from the start (465), or STARTTLS on 587
    (Microsoft and iCloud offer only that). A server that won't start TLS on 587 is refused, never used in plain."""
    context = tls_context(host)
    if port == 587 and smtp_factory is smtplib.SMTP_SSL:
        s = smtplib.SMTP(host, port, timeout=30)
        try:
            s.starttls(context=context)
        except Exception:
            s.close()
            raise
        return s
    return smtp_factory(host, port, context=context, timeout=30)


def smtp_server(entry: dict[str, Any]) -> tuple[str, int]:
    """Zoho's SMTP host for this mailbox: the paid plan's smtppro with an imappro mailbox, else smtp."""
    host = entry.get("smtp_host") or ("smtppro.zoho.com" if str(entry.get("imap_host") or "").startswith("imappro")
                                      else "smtp.zoho.com")
    return str(host), int(entry.get("smtp_port") or 465)


# ── the sign-off: plain text always, an HTML version when the mailbox has one ──

def plain_signature(entry: dict[str, Any]) -> str:
    """The sign-off drafts end with (``signature``), with a Phone line added once ``phone`` is set."""
    sig = str(entry.get("signature") or f"{entry.get('from_name') or ''}\n{entry.get('company') or ''}").strip()
    phone = str(entry.get("phone") or "").strip()
    if phone:
        lines = sig.split("\n")
        at = next((i for i, line in enumerate(lines) if line.lower().startswith("email:")), len(lines))
        lines.insert(at, f"Phone: {phone}")
        sig = "\n".join(lines)
    return sig


_DROP_TAGS = re.compile(r"(?is)<(script|style|iframe|object|embed|form|svg|math|template)\b.*?</\1\s*>")
_DROP_SINGLE = re.compile(r"(?is)<(img|link|meta|base|input|button|textarea|select|frame|frameset|source|video|audio)\b[^>]*>")
_ON_ATTR = re.compile(r"""(?is)\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")
_BAD_URL = re.compile(r"""(?is)\s+(href|src|action|formaction|background)\s*=\s*(["']?)\s*(javascript|data|vbscript):[^"'>]*\2""")
_CSS_URL = re.compile(r"(?is)url\s*\([^)]*\)|expression\s*\(")


def sanitize(markup: str) -> str:
    """The signature HTML minus anything that runs or loads: scripts, styles blocks, frames, forms, images,
    event handlers, javascript:/data: links and CSS url()/expression()."""
    out = re.sub(r"(?s)<!--.*?-->", "", markup)
    for _ in range(3):
        out = _DROP_TAGS.sub("", out)
    out = _DROP_SINGLE.sub("", out)
    out = _ON_ATTR.sub("", out)
    out = _BAD_URL.sub("", out)
    return _CSS_URL.sub("", out).strip()


def signature_html(entry: dict[str, Any], base: Path | None = None) -> str:
    """The mailbox's HTML sign-off (``signature_html``: a file under the Addons settings folder), sanitized,
    with its phone block kept only when ``phone`` is set. '' when there is none."""
    name = str(entry.get("signature_html") or "").strip()
    if not name:
        return ""
    if base is None:
        from hisho import addons
        base = addons.config_path("email").parent
    path = (base / name).resolve()
    if base.resolve() not in path.parents or path.suffix.lower() not in (".html", ".htm"):
        return ""                                    # only a .html file inside the settings folder
    try:
        raw = path.read_text(encoding="utf-8")[:50_000]
    except OSError:
        return ""
    phone = str(entry.get("phone") or "").strip()
    block = re.compile(r"(?s)<!--\s*phone\s*-->(.*?)<!--\s*/phone\s*-->")
    if phone:
        safe = html_mod.escape(phone, quote=True)
        raw = block.sub(lambda m: m.group(1).replace("{phone_tel}", tel_link(phone)).replace("{phone}", safe), raw)
    else:
        raw = block.sub("", raw)
    return sanitize(raw)


def tel_link(phone: str) -> str:
    """A tap-to-call target in international form: (951) 499-5616 -> +19514995616 (US 10 digits get +1)."""
    digits = re.sub(r"\D", "", phone)
    return f"+1{digits}" if len(digits) == 10 else f"+{digits}"


def _ends_with(body: str, sig: str) -> int:
    """Where the plain sign-off starts at the end of ``body`` (whitespace-insensitive per line), else -1."""
    norm = lambda t: [" ".join(x.split()) for x in t.strip().split("\n") if x.strip()]  # noqa: E731
    want, lines = norm(sig), body.rstrip().split("\n")
    if not want:
        return -1
    kept = [i for i, x in enumerate(lines) if x.strip()]
    if len(kept) < len(want) or [" ".join(lines[i].split()) for i in kept[-len(want):]] != want:
        return -1
    return sum(len(x) + 1 for x in lines[:kept[-len(want)]])


def html_version(entry: dict[str, Any], body: str, base: Path | None = None) -> str:
    """The HTML part: the body as paragraphs, then the HTML sign-off in place of the plain one. '' when the
    mailbox has no HTML sign-off or the body doesn't end with the plain one (then plain text goes alone)."""
    sig_html = signature_html(entry, base)
    at = _ends_with(body, plain_signature(entry)) if sig_html else -1
    if at < 0:
        return ""
    main = body[:at].rstrip()
    paras = "".join(f"<p style=\"margin: 0 0 12px 0;\">{html_mod.escape(par).replace(chr(10), '<br>')}</p>"
                    for par in re.split(r"\n\s*\n", main) if par.strip())
    return (f'<div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: rgb(31, 41, 55);">{paras}</div>'
            f"<br>{sig_html}")


def build(entry: dict[str, Any], p: dict[str, Any]) -> email.message.EmailMessage:
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    address = str(entry["address"])
    msg["From"] = email.utils.formataddr((str(entry.get("from_name") or ""), address))
    msg["To"] = ", ".join(p["to"])
    if p["cc"]:
        msg["Cc"] = ", ".join(p["cc"])
    msg["Subject"] = p["subject"]
    msg["Date"] = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
    msg["Message-ID"] = email.utils.make_msgid(domain=address.rsplit("@", 1)[-1])
    if p["in_reply_to"]:
        msg["In-Reply-To"] = p["in_reply_to"]
        refs = [r for r in p["references"] if r != p["in_reply_to"]] + [p["in_reply_to"]]
        msg["References"] = " ".join(refs)
    msg.set_content(p["body"])
    as_html = html_version(entry, p["body"])
    if as_html:
        msg.add_alternative(as_html, subtype="html")   # the same text, with his HTML sign-off
    return msg


# ── rate guard ────────────────────────────────────────────────────────────

def _sends_file(mailbox: str) -> Path:
    base = Path(os.environ.get("HISHO_STATE_DIR") or "~/.local/state/hisho").expanduser()
    return base / "addons" / "email" / f"{mailbox}.sends.json"


def _recent_sends(mailbox: str, now: float) -> list[float]:
    try:
        return [t for t in json.loads(_sends_file(mailbox).read_text()) if now - t < 3600]
    except (OSError, ValueError):
        return []


def _record_send(mailbox: str, now: float) -> None:
    path = _sends_file(mailbox)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_recent_sends(mailbox, now) + [now]))
    os.chmod(path, 0o600)


# ── sending ───────────────────────────────────────────────────────────────

def _copy_in_sent(entry: dict[str, Any], password: str, msg: email.message.EmailMessage,
                  imap_factory: Callable[..., Any], sleep: Callable[[float], None]) -> str:
    """'zoho' when Zoho filed its own copy, 'appended' when we put one there, '' when neither worked."""
    folder = str(entry.get("sent_folder") or "Sent")
    host, port = str(entry.get("imap_host") or "imap.zoho.com"), int(entry.get("imap_port") or 993)
    conn = imap_factory(host, port, ssl_context=tls_context(host), timeout=30)
    conn.sent_folder = folder
    try:
        conn.login(str(entry["address"]), password)
        mid = str(msg["Message-ID"])
        for i in range(SENT_LOOKS):
            if conn.select(folder, readonly=True)[0] == "OK":
                typ, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", mid)
                if typ == "OK" and (data[0] or b"").split():
                    return "zoho"
            if i < SENT_LOOKS - 1:
                sleep(3)
        typ, _ = conn.append(folder, "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        return "appended" if typ == "OK" else ""
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def send(entries: dict[str, dict[str, Any]], ctx: Any, payload: dict[str, Any], *,
         smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL, imap_factory: Callable[..., Any] = SentIMAP,
         sleep: Callable[[float], None] = time.sleep, journal: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Send exactly ``payload`` (already checked by ``validate`` and approved by the owner)."""
    p = validate(payload)
    entry = entries.get(p["mailbox"])
    if not entry:
        return {"ok": False, "error": f"no mailbox {p['mailbox']} in email.yaml"}
    per_hour = int(entry.get("max_sends_per_hour") or DEFAULT_PER_HOUR)
    with _lock:
        now = time.time()
        if len(_recent_sends(p["mailbox"], now)) >= per_hour:
            return {"ok": False, "error": f"{per_hour} emails already went out from {entry['address']} in the last "
                                          "hour (max_sends_per_hour); approve it again later"}
        password = ctx.secret(str(entry.get("password") or ""))
        msg = build(entry, p)
        host, port = smtp_server(entry)
        try:
            with open_smtp(host, port, smtp_factory) as s:
                s.login(str(entry["address"]), password)
                refused = s.send_message(msg, from_addr=str(entry["address"]), to_addrs=p["to"] + p["cc"])
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            return {"ok": False, "error": f"not sent: {str(exc).replace(password, '***')[:240]}"}
        _record_send(p["mailbox"], now)
    try:
        filed = _copy_in_sent(entry, password, msg, imap_factory, sleep)
    except Exception as exc:  # noqa: BLE001 -- it went out; only the Sent copy is in doubt
        filed = f"failed ({type(exc).__name__})"
    took = [a for a in p["to"] + p["cc"] if a not in (refused or {})]
    record = {"addon": "email", "mailbox": p["mailbox"], "from": entry["address"], "to": p["to"], "cc": p["cc"],
              "subject": p["subject"], "message_id": str(msg["Message-ID"]), "in_reply_to": p["in_reply_to"],
              "refused": sorted(refused or {}), "sent_copy": filed}
    try:
        (journal or _journal)(record)
    except Exception:  # noqa: BLE001
        pass
    note = {"zoho": "Zoho filed it in Sent", "appended": "a copy was put in Sent"}.get(filed, f"Sent copy: {filed or 'not found'}")
    if refused:
        return {"ok": bool(took), "message": f"Sent to {', '.join(took)}; refused: {', '.join(refused)}. {note}.",
                "message_id": str(msg["Message-ID"])}
    return {"ok": True, "message": f"Sent from {entry['address']} to {', '.join(took)}. {note}.",
            "message_id": str(msg["Message-ID"])}


def _journal(record: dict[str, Any]) -> None:
    from hisho.jobs import append_event
    append_event(Path(os.environ.get("HISHO_ROOT") or "~/Hisho").expanduser(), "email-sent", record)


def smtp_login_test(entry: dict[str, Any], password: str, smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL) -> dict[str, Any]:
    """Log in to SMTP and quit, sending nothing (the page's Test)."""
    host, port = smtp_server(entry)
    try:
        with open_smtp(host, port, smtp_factory) as s:
            s.login(str(entry["address"]), password)
        return {"ok": True, "message": f"SMTP {host}:{port} accepts the login (nothing sent)"}
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        return {"ok": False, "error": f"SMTP {host}:{port}: {str(exc).replace(password, '***')[:200]}"}
