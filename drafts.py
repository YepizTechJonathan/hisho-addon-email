"""Drafts, for the Email add-on: the ONLY file that puts a message in a mailbox's Drafts folder. It runs when the owner
asks Ask Hisho (or Hisho's MCP) for a draft: the draft lands in their mail provider's own Drafts folder (Zoho, Gmail...),
where they open it, change it and press Send themselves. Hisho never sends it.

What it can do: log in, LIST the folders (to find Drafts by its special-use flag or usual name), APPEND one message
there with the \\Draft flag, and open Drafts read only to check it arrived (SEARCH by Message-ID). ``DraftsIMAP``
refuses every other IMAP command, and APPEND to any folder but that Drafts folder. No SMTP lives here.
"""
from __future__ import annotations

import imaplib
import re
import ssl
import time
from typing import Any, Callable

DRAFT_NAMES = ("drafts", "draft", "[gmail]/drafts", "inbox.drafts", "inbox/drafts")


class DraftViolation(RuntimeError):
    pass


def mailbox(name: str) -> str:
    """A folder name as IMAP wants it on the wire (quoted when it has a space or other special characters)."""
    name = str(name)
    if re.fullmatch(r"[A-Za-z0-9_.\-/\[\]&+:]+", name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def check_draft_command(name: str, args: tuple[Any, ...], drafts_folder: str | None) -> None:
    """The IMAP saving a draft may use: log in, list folders, open Drafts read only, search it, append to it."""
    name = str(name).upper()
    if name in ("LOGIN", "CAPABILITY", "LIST", "EXAMINE", "NOOP", "LOGOUT"):
        return
    if name == "UID" and args and str(args[0]).upper() == "SEARCH":
        return
    if name == "APPEND" and drafts_folder and args and _unquote(args[0]) == drafts_folder:
        return
    raise DraftViolation(f"refused IMAP {name} {str(args[:1])[:60]}: saving a draft may only add it to Drafts")


def _unquote(v: Any) -> str:
    s = v.decode() if isinstance(v, bytes) else str(v)
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


class DraftsIMAP(imaplib.IMAP4_SSL):
    drafts_folder: str | None = None

    def _command(self, name: str, *args: Any) -> Any:
        check_draft_command(name, args, self.drafts_folder)
        return super()._command(name, *args)


def find_drafts(conn: Any, entry: dict[str, Any]) -> str:
    """The Drafts folder's real name: the entry's ``drafts_folder``, else LIST's \\Drafts flag, else the usual names."""
    if entry.get("drafts_folder"):
        return str(entry["drafts_folder"])
    typ, data = conn.list()
    named = []
    for line in (data or []) if typ == "OK" else []:
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line or "")
        m = re.search(r'"((?:[^"\\]|\\.)*)"\s*$', text) or re.search(r"(\S+)\s*$", text)
        if not m:
            continue
        name = m.group(1).replace('\\"', '"')
        flags = (re.match(r"\s*\(([^)]*)\)", text) or [None, ""])[1].lower()
        if "\\drafts" in flags:
            return name
        named.append(name)
    for name in named:
        if name.lower() in DRAFT_NAMES:
            return name
    raise RuntimeError("this mailbox has no Drafts folder Hisho can find (set drafts_folder on the mailbox)")


def tls_context(host: str) -> ssl.SSLContext:
    return ssl.create_default_context()


def save(entry: dict[str, Any], password: str, raw: bytes, message_id: str, *,
         imap_factory: Callable[..., Any] = DraftsIMAP) -> dict[str, Any]:
    """Put ``raw`` (one built message) in the mailbox's Drafts folder and check it is there. {ok, folder} or {ok, error}."""
    host, port = str(entry.get("imap_host") or "imap.zoho.com"), int(entry.get("imap_port") or 993)
    conn = imap_factory(host, port, ssl_context=tls_context(host), timeout=30)
    try:
        conn.login(str(entry["address"]), password)
        folder = find_drafts(conn, entry)
        conn.drafts_folder = folder
        typ, data = conn.append(mailbox(folder), "(\\Draft \\Seen)", imaplib.Time2Internaldate(time.time()), raw)
        if typ != "OK":
            return {"ok": False, "error": f"{entry.get('address')} refused the draft: {data!r}"[:240]}
        there = False
        if conn.select(mailbox(folder), readonly=True)[0] == "OK":
            typ, data = conn.uid("SEARCH", None, "HEADER", "Message-ID", message_id)
            there = typ == "OK" and bool((data[0] or b"").split())
        return {"ok": True, "folder": folder, "checked": there}
    except (imaplib.IMAP4.error, OSError, ssl.SSLError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc).replace(password, "***")[:240]}
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
