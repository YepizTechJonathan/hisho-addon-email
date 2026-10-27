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
    monkeypatch.setattr(mod, "connect", lambda e, p: pytest.fail("a test tried to reach a real mail server"))
    monkeypatch.setattr(mod, "_kick", lambda *a: None)
    monkeypatch.setattr(mod, "_now", lambda: NOW)
    monkeypatch.setattr(mod, "_tz", lambda: dt.timezone(dt.timedelta(hours=-7), "PDT"))


def poll(box):
    def connect(e, p):
        box.login(e["address"], p)
        return box
    return mod.poll("yt", YT, Ctx(), now=NOW, ask=claude, connect_fn=connect)


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
    assert "Folders read: INBOX, Newsletter, Notification" in sec["facts"]
    assert any(i["id"] == "newsletter-4" and "in Newsletter" in i["facts"][0] for i in sec["items"])


def test_inbox_card_keys_are_unchanged():
    assert mod.stream_name("yt", "INBOX") == "yt" and mod.stream_name("yt", "Newsletter") == "yt--newsletter"


def test_a_missing_folder_is_named_on_the_page():
    box = Box()
    box.list = lambda: (box._cmd("LIST"), ("OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Newsletter"']))[1]
    poll(box)
    assert "Folders read: INBOX, Newsletter (not found: Notification)" in mod.details({"yt": YT}, Ctx())[0]["facts"]


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
    assert "isn't one of the folders" in mod.run_trash({"yt": YT}, Ctx(), bad)["error"]
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
    assert "never cleans it up" in mod.run_trash({"yt": yt}, Ctx(), mod.cleaner.validate(forged))["error"]
