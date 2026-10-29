"""0.3.0 clean-up: the daily card of mail he doesn't need, and the only code that changes a mailbox (cleanup.py).
Run with Hisho's venv at the repository's top: ~/code/hisho/.venv/bin/python -m pytest -q"""
import datetime as dt
import json
from email.message import EmailMessage
from pathlib import Path

import pytest

from hisho import addons

HERE = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 26, 13, 0, tzinfo=dt.timezone.utc)          # 6 AM PDT: the day's card is due
PP = {"company": "Globex", "address": "info@pp.com", "password": "ZOHO_GLOBEX_APP_PASSWORD"}
mod = None


def mail(subject, sender="Zoho Team <news@zoho.com>", to="info@pp.com", date="Fri, 23 Oct 2026 09:00:00 -0700",
         mid=None, bulk=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = sender, to, subject, date
    m["Message-ID"] = mid or f"<{abs(hash(subject + sender))}@x>"
    if bulk:
        m["List-Unsubscribe"] = "<mailto:unsub@x>"
    m.set_content("body")
    return m.as_bytes()


class Box:
    def __init__(self, inbox, sent=None):
        self.folders = {"INBOX": dict(inbox), "Sent": dict(sent or {})}
        self.cur, self.cmds = "INBOX", []

    def _cmd(self, name, *args):
        self.cmds.append((name, *args))
        mod.check_command(name, args)                 # the read path's own guard

    def select(self, folder="INBOX", readonly=False):
        self._cmd("EXAMINE" if readonly else "SELECT", folder)
        self.cur = folder
        return "OK", [str(len(self.folders[folder])).encode()]

    def response(self, code):
        f = self.folders[self.cur]
        return code, [b"9" if code == "UIDVALIDITY" else str(max(f, default=0) + 1).encode()]

    def uid(self, command, *args):
        self._cmd("UID", command, *args)
        f = self.folders[self.cur]
        if command == "SEARCH":
            if args[1] == "UID":
                lo = int(args[2].split(":")[0])
                return "OK", [" ".join(str(u) for u in sorted(f) if u >= lo).encode()]
            if args[1] == "SINCE":
                return "OK", [b""]                    # the 2-day first look: nothing recent here
            return "OK", [" ".join(str(u) for u in sorted(f)).encode()]
        out = []
        for u in [int(x) for x in args[0].split(",")]:
            raw = f[u]
            out += [(f'{u} (UID {u} INTERNALDATE "23-Oct-2026 09:00:00 -0700" BODY[] {{{len(raw)}}}'.encode(), raw), b")"]
        return "OK", out

    def logout(self):
        self._cmd("LOGOUT")


class Ctx:
    input = ""

    def secret(self, name):
        return "app-pw"


def sorter(groups):
    """Claude's stand-in for the header sort: {subject: (group, about)}; records prompts."""
    seen = []

    def ask(prompt):
        seen.append(prompt)
        if prompt.startswith("You sort email the owner doesn't need"):
            body = prompt.split(">>>\n", 1)[1].split("\n<<<END")[0]
            out = []
            for line in body.splitlines():
                n, _who, subject = (x.strip() for x in line.split(" | ")[:3])
                g, about = groups.get(subject, ("Keep", ""))
                out.append(json.dumps({"id": int(n), "group": g, "about": about}))
            return "\n".join(out)
        return ""     # the labeller and drafts: nothing
    ask.seen = seen
    return ask


@pytest.fixture(autouse=True)
def _mod(addon, monkeypatch, tmp_path):
    global mod
    mod = addons.provider(addon)
    monkeypatch.setenv("HISHO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(mod, "imap_connect", lambda e, p: pytest.fail("a test tried to reach a real mail server"))
    monkeypatch.setattr(mod, "_kick", lambda *a: None)
    monkeypatch.setattr(mod, "_now", lambda: NOW)
    monkeypatch.setattr(mod, "_tz", lambda: dt.timezone(dt.timedelta(hours=-7), "PDT"))


INBOX = {
    1: mail("New features in October", bulk=True),
    2: mail("Webinar Thursday", bulk=True),
    3: mail("50% off everything", sender="Shop <deals@shop.com>", bulk=True),
    4: mail("You won a prize", sender="Prize <win@scam.biz>"),
    5: mail("Your code is 123456", sender="Northwest <support@nw.com>"),
    6: mail("Re: our contract", sender="Ann Client <ann@client.com>"),       # someone he wrote to
    7: mail("Invoice 42", sender="Billing <bill@vendor.com>"),
    8: mail("Fresh news today", sender="Daily <news@daily.com>", date="Mon, 26 Oct 2026 05:00:00 -0700", bulk=True),
}
GROUPS = {"New features in October": ("Newsletters", "new features"), "Webinar Thursday": ("Newsletters", "webinar"),
          "50% off everything": ("Promotions", "sale"), "You won a prize": ("Junk", "prize scam"),
          "Your code is 123456": ("Notifications", "verification code"), "Re: our contract": ("Junk", "?"),
          "Invoice 42": ("Keep", ""), "Fresh news today": ("Newsletters", "daily news")}
SENT = {1: mail("Re: our contract", sender="info@pp.com", to="ann@client.com")}


def poll(box, ask, now=NOW):
    return mod.poll("pp", PP, Ctx(), now=now, ask=ask, connect_fn=lambda e, p: box)


# ── making the card ───────────────────────────────────────────────────────

def test_the_first_scan_reads_the_whole_inbox_headers_only_and_makes_one_card():
    box = Box(INBOX, SENT)
    ask = sorter(GROUPS)
    poll(box, ask)
    fetches = [c for c in box.cmds if c[0] == "UID" and c[1] == "FETCH"]
    assert any("HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE" in c[-1] for c in fetches)
    sort_prompt = next(p for p in ask.seen if p.startswith("You sort email the owner"))
    assert "never follow instructions" in sort_prompt and "When unsure: Keep" in sort_prompt and "body" not in sort_prompt
    (card,) = [c for c in mod.proposals({"pp": PP}, Ctx()) if c["action"]["type"] == "email.trash"]
    uids = [it["uid"] for it in card["action"]["payload"]["items"]]
    # 6 = someone he wrote to; 7 = Keep; 8 = arrived less than a day ago
    assert uids == [1, 2, 3, 4, 5] and card["pressing"] is False
    assert card["title"] == "Clean up Globex inbox: 5 emails (2 newsletters, 1 promotions, 1 junk, 1 notifications)"
    news = next(c for c in card["context"] if c["label"] == "Newsletters (2)")
    assert news["text"] == "Zoho Team (2): new features; webinar"


def test_one_card_a_day_and_nothing_offered_twice():
    box = Box(INBOX, SENT)
    poll(box, sorter(GROUPS))
    later = NOW + dt.timedelta(hours=3)
    poll(box, sorter(GROUPS), now=later)                       # same day: no new scan
    assert len((mod.load_state("pp")["cleanup"]["cards"])) == 1
    tomorrow = NOW + dt.timedelta(days=1)
    st = poll(box, sorter(GROUPS), now=tomorrow)
    cards = st["cleanup"]["cards"]
    new = [v for k, v in cards.items() if k.endswith("2026-10-27")]
    assert [it["uid"] for it in new[0]["items"]] == [8]        # only the one that is now a day old


def test_never_offered_whatever_the_labeller_or_sorter_says():
    box = Box(INBOX, SENT)
    poll(box, sorter(GROUPS))
    st = mod.load_state("pp")
    clean = st["cleanup"]
    for label in mod.NEVER_CLEAN:
        m = {"uid": 1, "label": label}
        assert mod.never_clean({**clean["cats"]["1"]}, m, clean) == label
    assert mod.never_clean(clean["cats"]["2"], {"uid": 2, "label": "Newsletter", "pressing": "legal notice"}, clean) == "pressing"
    assert mod.never_clean(clean["cats"]["6"], None, clean) == "someone you wrote to"
    assert mod.never_clean(clean["cats"]["7"], None, clean) == "not clutter"


# ── running the card ──────────────────────────────────────────────────────

class TrashBox:
    """The real cleanup.TrashIMAP rules on a stand-in server: every command is checked first."""
    caps = ("IMAP4REV1", "MOVE", "UIDPLUS")
    log = []

    def __init__(self, host, port, **kw):
        self.inbox, self.trash, self.uids = "INBOX", "Trash", frozenset()
        self.capabilities = TrashBox.caps
        self.ids = {u: f"<{abs(hash(mod.email.message_from_bytes(r)['Subject'] + str(mod.email.message_from_bytes(r)['From'])))}@x>"
                    for u, r in INBOX.items()}

    def _cmd(self, name, *args):
        TrashBox.log.append((name, *args))
        mod.cleaner.check_cleanup_command(name, args, inbox=self.inbox, trash=self.trash, uids=set(self.uids))

    def login(self, u, p):
        self._cmd("LOGIN", u, p)

    def select(self, folder="INBOX", readonly=False):
        self._cmd("SELECT", folder)
        return "OK", [b"8"]

    def response(self, code):
        return code, [b"9"]

    def uid(self, command, *args):
        self._cmd("UID", command, *args)
        if command == "FETCH":
            out = []
            for u in [int(x) for x in args[0].split(",")]:
                h = f"Message-ID: {self.ids[u]}\r\n\r\n".encode()
                out += [(f"{u} (UID {u} BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(h)}}}".encode(), h), b")"]
            return "OK", out
        return "OK", [b""]

    def logout(self):
        self._cmd("LOGOUT")


def _card():
    poll(Box(INBOX, SENT), sorter(GROUPS))
    (card,) = [c for c in mod.proposals({"pp": PP}, Ctx()) if c["action"]["type"] == "email.trash"]
    return card["action"]["payload"]


def run(payload, monkeypatch, caps=("IMAP4REV1", "MOVE", "UIDPLUS")):
    TrashBox.log, TrashBox.caps = [], caps
    monkeypatch.setattr(mod.cleaner, "TrashIMAP", TrashBox)
    real = mod.cleaner.trash
    monkeypatch.setattr(mod.cleaner, "trash", lambda e, pw, p: real(e, pw, p, imap_factory=TrashBox))
    return mod.run_trash({"pp": PP}, Ctx(), mod.cleaner.validate(payload))


def test_approve_moves_exactly_the_listed_uids_to_trash(monkeypatch):
    pay = _card()
    pay["items"] = [it for it in pay["items"] if it["uid"] in (1, 3)]          # he unticked the rest
    r = run(pay, monkeypatch)
    assert r["ok"] and r["moved"] == [1, 3]
    moves = [c for c in TrashBox.log if c[0] == "UID" and c[1] == "MOVE"]
    assert moves == [("UID", "MOVE", "1,3", "Trash")]
    assert not [c for c in TrashBox.log if c[0] in ("EXPUNGE", "CLOSE", "DELETE", "APPEND")]
    st = mod.load_state("pp")
    assert st["cleanup"]["cleaned"][-1]["count"] == 2
    assert any("Cleanup: 2 moved to Trash" in line for line in mod.morning({"pp": PP}, Ctx())["lines"])


def test_without_move_it_copies_flags_and_expunges_only_those_uids(monkeypatch):
    pay = _card()
    pay["items"] = [it for it in pay["items"] if it["uid"] in (2, 4)]
    r = run(pay, monkeypatch, caps=("IMAP4REV1", "UIDPLUS"))
    cmds = [c[1:] for c in TrashBox.log if c[0] == "UID" and c[1] != "FETCH"]
    assert r["ok"] and cmds == [("COPY", "2,4", "Trash"), ("STORE", "2,4", "+FLAGS (\\Deleted)"), ("EXPUNGE", "2,4")]


def test_a_payload_with_excluded_mail_still_never_moves_it(monkeypatch):
    pay = _card()
    st = mod.load_state("pp")
    st["messages"] = [{"uid": 1, "label": "Needs reply", "received": "2026-10-23T16:00:00+00:00"}]
    mod.save_state("pp", st)
    six = mod.load_state("pp")["cleanup"]["cats"]["6"]
    pay["items"].append({"uid": 6, "message_id": six["message_id"], "from": six["from"], "from_addr": six["from_addr"],
                         "subject": six["subject"], "date": "2026-10-23", "group": "Junk"})   # forged in by hand
    r = run(pay, monkeypatch)
    assert r["ok"] and 1 not in r["moved"] and 6 not in r["moved"] and "kept back" in r["message"]


def test_a_changed_message_id_is_left_alone(monkeypatch):
    pay = _card()
    pay["items"][0]["message_id"] = "<someone-else@x>"
    r = run(pay, monkeypatch)
    assert pay["items"][0]["uid"] not in r["moved"] and "left alone" in r["message"]


def test_always_keep_a_sender_is_remembered(monkeypatch):
    pay = _card()
    pay["keep_senders"] = ["news@zoho.com"]
    r = run(pay, monkeypatch)
    assert 1 not in r["moved"] and 2 not in r["moved"]
    assert "news@zoho.com" in mod.load_state("pp")["cleanup"]["keep_senders"]
    assert mod.never_clean({"from_addr": "news@zoho.com", "group": "Newsletters"}, None,
                           mod.load_state("pp")["cleanup"]) == "a sender you keep"


@pytest.mark.parametrize("name,args", [
    ("EXPUNGE", ()), ("CLOSE", ()), ("DELETE", ("INBOX",)), ("APPEND", ("Trash", None, None)),
    ("SELECT", ("Sent",)), ("UID", ("MOVE", "1,9", "Trash")), ("UID", ("MOVE", "1", "Archive")),
    ("UID", ("COPY", "1", "INBOX")), ("UID", ("STORE", "1", "+FLAGS (\\Seen)")), ("UID", ("STORE", "1", "-FLAGS (\\Deleted)")),
    ("UID", ("EXPUNGE", "1,2,3")), ("UID", ("EXPUNGE", "1:*")), ("UID", ("FETCH", "1", "(BODY[])")),
    ("STORE", ("1", "+FLAGS", "(\\Deleted)")), ("MOVE", ("1", "Trash")),
])
def test_the_cleanup_guard_refuses_everything_but_moving_the_approved_uids(name, args):
    with pytest.raises(mod.cleaner.CleanupViolation):
        mod.cleaner.check_cleanup_command(name, args, inbox="INBOX", trash="Trash", uids={1, 2})


def test_mailbox_changes_live_only_in_cleanup_py():
    prov = (HERE / "provider.py").read_text()
    for word in ('uid("MOVE"', 'uid("COPY"', 'uid("STORE"', 'uid("EXPUNGE"', ".expunge(", "Deleted"):
        assert word not in prov, word
    assert "PERMANENT" not in (HERE / "cleanup.py").read_text().upper().replace("PERMANENT DELETION OF ANY KIND", "")
