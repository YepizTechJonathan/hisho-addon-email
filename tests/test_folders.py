"""0.4.0: Zoho's smart filters file mail into Newsletter and Notification; Hisho reads those folders too (read only,
one login), so misfiled real mail still gets its label, draft and line in Today.md, and clean-up works per folder.
Run with Hisho's venv at the repository's top: ~/code/hisho/.venv/bin/python -m pytest -q"""
import datetime as dt
import json
from email.message import EmailMessage

import pytest

from hisho import addons

NOW = dt.datetime(2026, 10, 26, 13, 0, tzinfo=dt.timezone.utc)
YT = {"company": "Acme", "address": "alex@example.com", "password": "ZOHO_ACME_APP_PASSWORD",
      "imap_host": "imappro.zoho.com", "signature": "Alex Rivera\nAcme"}
mod = None


def mail(subject, sender, date, mid):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"], m["Message-ID"] = sender, "alex@example.com", subject, date, mid
    m.set_content("We'd like the Tripleseat lead form on our site, codes below.")
    return m.as_bytes()


JESUS = mail("Fwd: Tripleseat Dynamic Lead Form Integration", "Jesus Juarez <jesus@goldencoast.com>",
             "Fri, 23 Oct 2026 11:25:00 -0700", "<tripleseat@gc.com>")
NEWS = mail("Zoho's October update", "Zoho Team <news@zoho.com>", "Thu, 22 Oct 2026 08:00:00 -0700", "<news1@zoho.com>")


class Box:
    """INBOX, Newsletter, Notification and Sent; LIST answers like Zoho; every command is read-only-checked."""

    def __init__(self):
        self.folders = {"INBOX": {}, "Newsletter": {4: JESUS, 5: NEWS}, "Notification": {}, "Sent": {}}
        self.cur, self.cmds = "INBOX", []

    def _cmd(self, name, *args):
        self.cmds.append((name, *args))
        mod.check_command(name, args)

    def login(self, u, p):
        self._cmd("LOGIN", u, p)

    def list(self):
        self._cmd("LIST")
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Newsletter"',
                      b'(\\HasNoChildren) "/" "Notification"', b'(\\HasNoChildren) "/" "Sent"', b'(\\HasNoChildren) "/" "Trash"']

    def select(self, folder="INBOX", readonly=False):
        self._cmd("EXAMINE" if readonly else "SELECT", folder)
        folder = folder[1:-1] if folder.startswith('"') else folder   # a quoted name, as a server reads it
        self.cur = folder
        return "OK", [str(len(self.folders[folder])).encode()]

    def response(self, code):
        f = self.folders[self.cur]
        return code, [b"3" if code == "UIDVALIDITY" else str(max(f, default=0) + 1).encode()]

    def uid(self, command, *args):
        self._cmd("UID", command, *args)
        f = self.folders[self.cur]
        if command == "SEARCH":
            lo = int(args[2].split(":")[0]) if args[1] == "UID" else 0
            return "OK", [" ".join(str(u) for u in sorted(f) if u >= lo).encode()]
        out = []
        for u in [int(x) for x in args[0].split(",")]:
            raw = f[u]
            out += [(f'{u} (UID {u} INTERNALDATE "23-Oct-2026 11:25:00 -0700" BODY[] {{{len(raw)}}}'.encode(), raw), b")"]
        return "OK", out

    def logout(self):
        self._cmd("LOGOUT")


class Ctx:
    input = ""

    def secret(self, name):
        return "app-pw"


def claude(prompt):
    if prompt.startswith("You sort the owner's business email"):
        out = []
        for n, subj in enumerate([l for l in prompt.splitlines() if l.startswith("Subject: ")], 1):
            label = "Customer request" if "Tripleseat" in subj else "Newsletter"
            out.append(json.dumps({"id": n, "label": label, "summary": "Wants the Tripleseat form on the site"
                                   if label == "Customer request" else "Zoho update"}))
        return "\n".join(out)
    if prompt.startswith("You draft a reply"):
        return json.dumps({"subject": "x", "body": "Hi Jesús,\nYes, I'll add it this week.\n\nAlex Rivera\nAcme"})
    if prompt.startswith("You sort email the owner doesn't need"):
        return "\n".join(json.dumps({"id": n, "group": "Newsletters", "about": "update"}) for n in range(1, 10))
    return ""


@pytest.fixture(autouse=True)
def _mod(addon, monkeypatch, tmp_path):
    global mod
    mod = addons.provider(addon)
    monkeypatch.setenv("HISHO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(mod, "imap_connect", lambda e, p: pytest.fail("a test tried to reach a real mail server"))
    monkeypatch.setattr(mod, "_kick", lambda *a: None)
    monkeypatch.setattr(mod, "_now", lambda: NOW)
    monkeypatch.setattr(mod, "_tz", lambda: dt.timezone(dt.timedelta(hours=-7), "PDT"))


def poll(box, entry=None, now=NOW, ask=None):
    def connect(e, p):
        box.login(e["address"], p)
        return box
    return mod.poll("yt", entry or YT, Ctx(), now=now, ask=ask or claude, connect_fn=connect)


def test_all_folders_are_read_read_only_with_one_login():
    box = Box()
    st = poll(box)
    names = [c[0] for c in box.cmds]
    assert names.count("LOGIN") == 1 and names.count("LOGOUT") == 1 and "LIST" in names
    assert {c[1] for c in box.cmds if c[0] == "EXAMINE"} == {"INBOX", "Newsletter", "Notification", "Sent"}
    assert "SELECT" not in names and st["folders_found"] == ["Newsletter", "Notification"]


def test_misfiled_real_mail_still_gets_its_label_draft_card_and_today_line():
    poll(Box())
    sub = mod.load_state("yt--newsletter")
    jesus = next(m for m in sub["messages"] if "Tripleseat" in m["subject"])
    assert jesus["label"] == "Customer request" and jesus["draft"]["subject"].startswith("Re: Fwd: Tripleseat")
    cards = mod.proposals({"yt": YT}, Ctx())
    reply = next(c for c in cards if c["action"]["type"] == "email.send")
    assert reply["key"] == "reply:yt--newsletter:3:4" and reply["action"]["payload"]["mailbox"] == "yt"
    assert reply["action"]["payload"]["in_reply_to"] == "<tripleseat@gc.com>"
    lines = mod.morning({"yt": YT}, Ctx())["lines"]
    assert any("Tripleseat" in l and "in Newsletter" in l for l in lines)
    sec = mod.details({"yt": YT}, Ctx())[0]
    fact = next(f for f in sec["facts"] if f.startswith("Folders read:"))
    assert fact.startswith("Folders read: INBOX, Newsletter, Notification; every folder but Trash, Drafts and Sent")
    assert fact.endswith("Clean-up only in INBOX, Newsletter, Notification")
    assert any(i["id"] == "newsletter-4" and "in Newsletter" in i["facts"][0] for i in sec["items"])


def test_inbox_card_keys_are_unchanged():
    assert mod.stream_name("yt", "INBOX") == "yt" and mod.stream_name("yt", "Newsletter") == "yt--newsletter"


def test_a_missing_folder_is_named_on_the_page():
    box = Box()
    box.list = lambda: (box._cmd("LIST"), ("OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Newsletter"']))[1]
    named = {**YT, "folders": "Newsletter, Notification"}   # named folders (not the default, all)
    poll(box, named)
    fact = next(f for f in mod.details({"yt": named}, Ctx())[0]["facts"] if f.startswith("Folders read:"))
    assert fact.startswith("Folders read: INBOX, Newsletter (not found: Notification). Clean-up only in")


def test_cleanup_cards_are_per_folder_and_run_in_that_folder(monkeypatch):
    poll(Box())
    card = next(c for c in mod.proposals({"yt": YT}, Ctx()) if c["action"]["type"] == "email.trash")
    pay = card["action"]["payload"]
    assert pay["folder"] == "Newsletter" and [it["uid"] for it in pay["items"]] == [5]      # Jesús: never (customer)
    assert card["title"].startswith("Clean up Acme Newsletter folder")
    seen = {}

    def fake_trash(entry, pw, p, **kw):
        seen.update(folder=entry["folder"], uids=[it["uid"] for it in p["items"]])
        return {"ok": True, "moved": [5], "message": "Moved 1 email to Trash."}
    monkeypatch.setattr(mod.cleaner, "trash", fake_trash)
    r = mod.run_trash({"yt": YT}, Ctx(), mod.cleaner.validate(pay))
    assert r["ok"] and seen == {"folder": "Newsletter", "uids": [5]}
    bad = mod.cleaner.validate({**pay, "folder": "Archive"})
    assert "never cleans up Archive" in mod.run_trash({"yt": YT}, Ctx(), bad)["error"]
    with pytest.raises(mod.cleaner.CleanupError):
        mod.cleaner.validate({**pay, "folder": "Sent"})


def test_payments_is_read_but_never_cleaned_up(monkeypatch):
    box = Box()
    box.folders["Payments"] = {7: mail("Your Zoho receipt", "Zoho Store <store@zoho.com>", "Thu, 22 Oct 2026 08:00:00 -0700", "<r1@zoho.com>")}
    real_list = box.list
    box.list = lambda: (real_list()[0], real_list()[1] + [b'(\\HasNoChildren) "/" "Payments"'])
    yt = {**YT, "folders": "Newsletter, Notification, Payments"}

    def connect(e, p):
        box.login(e["address"], p)
        return box
    mod.poll("yt", yt, Ctx(), now=NOW, ask=claude, connect_fn=connect)
    assert "Payments" in mod.load_state("yt")["folders_found"] and mod.load_state("yt--payments")["status"] == "ok"
    assert not [c for c in mod.proposals({"yt": yt}, Ctx()) if c["action"]["type"] == "email.trash"
                and c["action"]["payload"]["folder"] == "Payments"]
    forged = {"mailbox": "yt", "folder": "Payments", "uidvalidity": "3",
              "items": [{"uid": 7, "message_id": "<r1@zoho.com>", "from_addr": "store@zoho.com", "group": "Promotions"}]}
    monkeypatch.setattr(mod.cleaner, "trash", lambda *a, **k: pytest.fail("Payments must never be moved"))
    assert "never cleans up Payments" in mod.run_trash({"yt": yt}, Ctx(), mod.cleaner.validate(forged))["error"]


# ── 0.11.0: every folder (LIST), Spam shown but never acted on, moved mail recognised, clean-up scope unchanged ──

ZOHO_LIST = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Noinferiors \\Drafts) "/" "Drafts"', b'(\\Noinferiors) "/" "Templates"',
             b'(\\HasNoChildren) "/" "Snoozed"', b'(\\Noinferiors \\Sent) "/" "Sent"', b'(\\Noinferiors \\Junk) "/" "Spam"',
             b'(\\HasNoChildren \\Trash) "/" "Trash"', b'(\\HasNoChildren) "/" "Notification"',
             b'(\\HasNoChildren) "/" "Newsletter"', b'(\\HasNoChildren) "/" "Archive"', b'(\\HasNoChildren) "/" "Payments"',
             b'(\\HasNoChildren) "/" "Clients/Golden Coast"']
REAL = mail("Can you fix the contact form?", "Maria Lopez <maria@goldencoast.com>", "Thu, 22 Oct 2026 09:00:00 -0700",
            "<maria1@gc.com>")


def zoho_box():
    box = Box()
    box.folders.update({name: {} for name in ("Drafts", "Templates", "Snoozed", "Spam", "Trash", "Archive", "Payments",
                                              "Clients/Golden Coast")})
    box.list = lambda: (box._cmd("LIST"), ("OK", list(ZOHO_LIST)))[1]
    return box


def labeller(calls):
    def ask(prompt):
        if prompt.startswith("You sort the owner's business email"):
            calls.append(prompt)
            out = []
            for n, subj in enumerate([l for l in prompt.splitlines() if l.startswith("Subject: ")], 1):
                real = "contact form" in subj or "Tripleseat" in subj
                out.append(json.dumps({"id": n, "label": "Customer request" if real else "Newsletter",
                                       "summary": "Wants the contact form fixed" if real else "update",
                                       **({"pressing": "client problem"} if "contact form" in subj else {})}))
            return "\n".join(out)
        return claude(prompt)
    return ask


def test_all_folders_by_default_but_trash_drafts_templates_and_sent():
    box = zoho_box()
    st = poll(box)
    assert st["folders_found"] == ["Snoozed", "Spam", "Notification", "Newsletter", "Archive", "Payments",
                                   "Clients/Golden Coast"]
    assert st["folders_junk"] == ["Spam"]
    examined = [c[1] for c in box.cmds if c[0] == "EXAMINE"]
    assert not {"Drafts", "Templates", "Trash"} & set(examined)
    assert examined.count("Sent") == 5   # answered mail once; the day's clean-up scan reads contacts per cleanable folder
    box.cmds.clear()
    poll(box, now=NOW + dt.timedelta(minutes=5))
    assert [c[1] for c in box.cmds if c[0] == "EXAMINE"].count("Sent") == 1   # an ordinary poll: once, for every folder
    assert "SELECT" not in [c[0] for c in box.cmds]
    assert mod.wanted_folders({}) == ["all"] and mod.wanted_folders({"folders": "All"}) == ["all"]


def test_a_new_folder_is_picked_up_at_the_next_poll():
    box = zoho_box()
    poll(box)
    ZOHO = box.list
    box.folders["Vendors"] = {}
    box.list = lambda: (ZOHO()[0], ZOHO()[1] + [b'(\\HasNoChildren) "/" "Vendors"'])
    assert "Vendors" in poll(box, now=NOW + dt.timedelta(minutes=5))["folders_found"]


def test_real_mail_in_spam_shows_but_is_never_drafted_carded_or_pushed():
    box = zoho_box()
    box.folders["Spam"] = {9: REAL}
    poll(box, ask=labeller([]))
    m = mod.load_state("yt--spam")["messages"][0]
    assert m["junk"] and m["label"] == "Customer request" and m["pressing"] == "client problem" and "draft" not in m
    assert not [c for c in mod.proposals({"yt": YT}, Ctx()) if "Maria" in c["title"] or "contact form" in c["title"]]
    assert not [p for p in mod.summary({"yt": YT}, Ctx())["problems"] if "Maria" in p["title"]]
    assert any("contact form" in l and "in Spam" in l for l in mod.morning({"yt": YT}, Ctx())["lines"])


def test_mail_moved_to_archive_is_recognised_not_labelled_drafted_carded_or_pushed_again():
    box, calls = zoho_box(), []
    box.folders["INBOX"] = {11: REAL}
    later = NOW + dt.timedelta(minutes=5)
    poll(box, ask=labeller(calls))
    first = mod.load_state("yt")["messages"][0]
    assert first["label"] == "Customer request" and first["draft"]
    cards = [c for c in mod.proposals({"yt": YT}, Ctx()) if c["action"]["type"] == "email.send"]
    # he files it in Archive: a new UID there, gone from the inbox
    box.folders["INBOX"], box.folders["Archive"] = {}, {3: REAL}
    calls.clear()
    poll(box, now=later, ask=labeller(calls))
    copy = mod.load_state("yt--archive")["messages"][0]
    assert copy["moved_from"] == "INBOX" and copy["label"] == "Customer request" and "draft" not in copy
    assert not any("contact form" in c for c in calls)   # not labelled again
    again = [c for c in mod.proposals({"yt": YT}, Ctx()) if c["action"]["type"] == "email.send"]
    assert [c["key"] for c in again] == [c["key"] for c in cards]   # one card, the original one
    pushes = [p for p in mod.summary({"yt": YT}, Ctx())["problems"] if "client problem" in p["title"]]
    assert len(pushes) <= 1 and all("archive" not in p["key"] for p in pushes)
    lines = [l for l in mod.morning({"yt": YT}, Ctx())["lines"] if "contact form" in l]
    assert len(lines) == 1 and "in Archive" in lines[0]   # once, where it is now


def test_clean_up_scope_is_the_inbox_the_filters_and_spam(monkeypatch):
    box = zoho_box()
    for f in ("Archive", "Spam", "Clients/Golden Coast", "Snoozed"):
        box.folders[f] = {21: NEWS}
    poll(box)
    searched = {c[1] for c in box.cmds if c[0] == "UID" and c[1] == "SEARCH" and c[2:4] == (None, "ALL")}
    folders = [c[1] for c in box.cmds if c[0] == "EXAMINE"]
    assert searched   # the scan ran (inbox, Newsletter, Notification)...
    for f in ("Archive", "Clients/Golden Coast", "Snoozed", "Payments"):
        assert not (mod.load_state(mod.stream_name("yt", f)).get("cleanup") or {}).get("cats"), f   # ...but not here
    assert (mod.load_state("yt--spam").get("cleanup") or {}).get("cats")   # Spam is scanned (0.12.2)
    trash = {c["action"]["payload"]["folder"] for c in mod.proposals({"yt": YT}, Ctx())
             if c["action"]["type"] == "email.trash"}
    assert trash <= {"INBOX", "Newsletter", "Notification", "Spam"} and "Spam" in trash
    monkeypatch.setattr(mod.cleaner, "trash", lambda *a, **k: pytest.fail("never moved"))
    for f in ("Archive", "Clients/Golden Coast", "Payments"):
        forged = {"mailbox": "yt", "folder": f, "uidvalidity": "3",
                  "items": [{"uid": 21, "message_id": "<news1@zoho.com>", "from_addr": "news@zoho.com",
                             "group": "Newsletters"}]}
        assert "never cleans up" in mod.run_trash({"yt": YT}, Ctx(), mod.cleaner.validate(forged))["error"]
    assert "Archive" in folders


def test_spam_junk_is_counted_not_listed_and_real_looking_spam_is_flagged():
    box = zoho_box()
    junk = mail("You won a cruise", "Prize <win@scam.example>", "Thu, 22 Oct 2026 09:00:00 -0700", "<scam1@x>")
    box.folders["Spam"] = {9: REAL, 10: junk}   # REAL: a customer asking to fix the contact form

    def ask(prompt):
        if prompt.startswith("You sort the owner's business email"):
            out = []
            for n, subj in enumerate([l for l in prompt.splitlines() if l.startswith("Subject: ")], 1):
                real = "contact form" in subj
                out.append(json.dumps({"id": n, "label": "Customer request" if real else "Junk",
                                       "summary": "Wants the contact form fixed" if real else "prize scam"}))
            return "\n".join(out)
        return claude(prompt)
    poll(box, ask=ask)
    lines = mod.morning({"yt": YT}, Ctx())["lines"]
    assert any("contact form" in l and "possibly misfiled in Spam: check it" in l for l in lines)
    assert not any("cruise" in l for l in lines) and any("1 junk in Spam: offered on the clean-up card" in l for l in lines)
    items = mod.details({"yt": YT}, Ctx())[0]["items"]
    assert not any("cruise" in i["name"] for i in items)
    assert any("contact form" in i["name"] and "possibly misfiled" in i["facts"][0] for i in items)


def test_an_approved_spam_card_moves_to_trash(monkeypatch):
    box = zoho_box()
    box.folders["Spam"] = {21: NEWS}
    poll(box)
    card = next(c for c in mod.proposals({"yt": YT}, Ctx())
                if c["action"]["type"] == "email.trash" and c["action"]["payload"]["folder"] == "Spam")
    seen = {}
    monkeypatch.setattr(mod.cleaner, "trash", lambda entry, pw, p, **kw: seen.update(folder=entry["folder"]) or
                        {"ok": True, "moved": [21], "message": "Moved 1 email to Trash."})
    assert mod.run_trash({"yt": YT}, Ctx(), mod.cleaner.validate(card["action"]["payload"]))["ok"]
    assert seen == {"folder": "Spam"}
