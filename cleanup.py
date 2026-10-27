"""Inbox clean-up, for the Email add-on: the ONLY code that changes a mailbox. It runs only from Hisho's Approvals
list, when the owner pressed Approve on a "Clean up" card that listed these exact messages (Core checks the
payload's hash first, and the provider drops anything that may never be cleaned before calling ``trash``).

What it can do: move the listed messages from the inbox to the Trash folder (where Zoho keeps them about 30 days),
nothing else. Before moving, each one is checked: same UIDVALIDITY, and the UID still carries the Message-ID the
card showed; a message that doesn't match is left alone. It uses UID MOVE, or where the server lacks MOVE, UID COPY
to Trash + UID STORE \\Deleted + UID EXPUNGE of only those UIDs. ``TrashIMAP`` refuses everything else, before it is
sent: any other folder, any UID not on the card, a plain EXPUNGE or CLOSE (they would remove other deleted mail too),
APPEND, and permanent deletion of any kind.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import re
import ssl
from typing import Any, Callable

MAX_ITEMS = 500
_UIDSET = re.compile(r"^\d+(,\d+)*$")
_FETCH_HEAD = re.compile(rb"UID (\d+)")


class CleanupError(RuntimeError):
    pass


class CleanupViolation(RuntimeError):
    pass


def check_cleanup_command(name: str, args: tuple[Any, ...], *, inbox: str, trash: str, uids: set[int]) -> None:
    """The IMAP clean-up may use, and only on the approved UIDs."""
    name = str(name).upper()
    if name in ("LOGIN", "CAPABILITY", "NOOP", "LOGOUT"):
        return
    if name in ("SELECT", "EXAMINE"):
        if args and str(args[0]).strip('"') == inbox:
            return
        raise CleanupViolation(f"refused {name} {args[:1]}: clean-up only opens {inbox}")
    if name == "UID" and args:
        sub, rest = str(args[0]).upper(), args[1:]
        if sub == "SEARCH":
            return
        uidset = str(rest[0]) if rest else ""
        if not _UIDSET.match(uidset) or not {int(u) for u in uidset.split(",")} <= uids:
            raise CleanupViolation(f"refused UID {sub} {uidset[:40]}: only the approved messages")
        items = " ".join(str(a) for a in rest[1:])
        if sub == "FETCH" and "PEEK" in items.upper() and "BODY[" not in items.upper().replace("BODY.PEEK[", ""):
            return
        if sub in ("MOVE", "COPY") and items.strip('"') == trash:
            return
        if sub == "STORE" and items.replace(" ", "").upper() == "+FLAGS(\\DELETED)":
            return
        if sub == "EXPUNGE" and not items:
            return
        raise CleanupViolation(f"refused UID {sub} {items[:40]}: clean-up only moves to {trash}")
    raise CleanupViolation(f"refused IMAP {name}: clean-up only moves the approved messages to Trash")


class TrashIMAP(imaplib.IMAP4_SSL):
    inbox, trash, uids = "INBOX", "Trash", frozenset()

    def _command(self, name: str, *args: Any) -> Any:
        check_cleanup_command(name, args, inbox=self.inbox, trash=self.trash, uids=set(self.uids))
        return super()._command(name, *args)


def validate(payload: Any) -> dict[str, Any]:
    """Only these keys survive; each item needs a UID and the Message-ID it had when the card was made."""
    if not isinstance(payload, dict):
        raise CleanupError("clean-up needs a mailbox and its messages")
    mailbox = str(payload.get("mailbox") or "")
    if not re.match(r"^[a-z0-9-]{1,40}$", mailbox):
        raise CleanupError("which mailbox")
    items, seen = [], set()
    for it in payload.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            uid = int(it.get("uid"))
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        items.append({"uid": uid, "message_id": str(it.get("message_id") or "")[:300],
                      "from": str(it.get("from") or "")[:120], "from_addr": str(it.get("from_addr") or "").lower()[:120],
                      "subject": str(it.get("subject") or "")[:200], "about": str(it.get("about") or "")[:120],
                      "date": str(it.get("date") or "")[:40], "group": str(it.get("group") or "")[:30]})
    keep = sorted({str(a).strip().lower()[:120] for a in payload.get("keep_senders") or [] if "@" in str(a)})[:200]
    items = [it for it in items if it["from_addr"] not in keep]    # "always keep this sender": never on the card
    if not items and not keep:
        raise CleanupError("nothing left to clean up (every message was unticked)")
    if len(items) > MAX_ITEMS:
        raise CleanupError(f"at most {MAX_ITEMS} messages per card")
    folder = str(payload.get("folder") or "INBOX")
    if not re.match(r"^[^\x00-\x1f\"*%]{1,100}$", folder) or folder.lower() in ("trash", "sent", "drafts"):
        raise CleanupError("which folder the messages are in")
    return {"mailbox": mailbox, "folder": folder, "uidvalidity": str(payload.get("uidvalidity") or ""), "items": items,
            "keep_senders": keep}


def trash(entry: dict[str, Any], password: str, p: dict[str, Any], *,
          imap_factory: Callable[..., Any] = TrashIMAP) -> dict[str, Any]:
    """Move exactly ``p['items']`` (still matching their Message-IDs) from the inbox to Trash."""
    inbox, folder = str(entry.get("folder") or "INBOX"), str(entry.get("trash_folder") or "Trash")
    want = {it["uid"]: it for it in p["items"]}
    conn = imap_factory(str(entry.get("imap_host") or "imap.zoho.com"), int(entry.get("imap_port") or 993),
                        ssl_context=ssl.create_default_context(), timeout=60)
    conn.inbox, conn.trash, conn.uids = inbox, folder, frozenset(want)
    try:
        conn.login(str(entry["address"]), password)
        typ, _ = conn.select(inbox)                   # read-write: a move needs it (nothing is marked read)
        if typ != "OK":
            return {"ok": False, "error": f"can't open {inbox}"}
        validity = str((conn.response("UIDVALIDITY")[1] or [b""])[0] or b"", "ascii", "replace")
        if p.get("uidvalidity") and validity != p["uidvalidity"]:
            return {"ok": False, "error": "the inbox was renumbered since the card was made; nothing was moved"}
        # verify: the UID must still be the message the card showed
        typ, data = conn.uid("FETCH", ",".join(str(u) for u in sorted(want)), "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        found: dict[int, str] = {}
        for part in (data or []) if typ == "OK" else []:
            if isinstance(part, tuple) and len(part) >= 2:
                m = _FETCH_HEAD.search(part[0])
                if m:
                    h = email.message_from_bytes(part[1], policy=email.policy.default)
                    found[int(m.group(1))] = (re.findall(r"<[^<>\s]+>", str(h.get("Message-ID") or "")) or [""])[0]
        ok = sorted(u for u, it in want.items() if u in found and (not it["message_id"] or found[u] == it["message_id"]))
        skipped = len(want) - len(ok)
        if not ok:
            return {"ok": False, "error": "none of them are in the inbox any more (moved or deleted already); nothing done"}
        uidset = ",".join(str(u) for u in ok)
        caps = {c.upper() for c in (getattr(conn, "capabilities", ()) or ())}
        if "MOVE" in caps:
            typ, data = conn.uid("MOVE", uidset, folder)
            how = "MOVE"
        else:
            typ, data = conn.uid("COPY", uidset, folder)
            if typ == "OK":
                typ, data = conn.uid("STORE", uidset, "+FLAGS (\\Deleted)")
            if typ == "OK":
                typ, data = conn.uid("EXPUNGE", uidset)
            how = "COPY+EXPUNGE"
        if typ != "OK":
            return {"ok": False, "error": f"Zoho refused the move: {data!r}"[:240]}
        return {"ok": True, "moved": ok, "skipped": skipped, "how": how,
                "message": f"Moved {len(ok)} email{'s' * (len(ok) != 1)} to {folder} (Zoho keeps them about 30 days)"
                           + (f"; {skipped} had already gone or changed and were left alone" if skipped else "") + "."}
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as exc:
        return {"ok": False, "error": f"clean-up stopped: {str(exc).replace(password, '***')[:200]}"}
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
