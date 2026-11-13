"""0.12.0: a personal mailbox (company Personal, or personal: true) is sorted for a person, not a business, and gets no
reply drafts unless drafts: true. Folder names with spaces (Gmail's "[Gmail]/Sent Mail") go quoted on the wire.
Run with Hisho's venv at the repository's top: ~/code/hisho/.venv/bin/python -m pytest -q"""
import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from hisho import addons

NOW = dt.datetime(2026, 11, 6, 20, 0, tzinfo=dt.timezone.utc)
GMAIL = {"company": "Personal", "address": "a@gmail.com", "password": "GMAIL_APP_PASSWORD", "imap_host": "imap.gmail.com",
         "sent_folder": "[Gmail]/Sent Mail", "trash_folder": "[Gmail]/Trash"}


@pytest.fixture
def mod(addon, monkeypatch, tmp_path):
    m = addons.provider(addon)
    monkeypatch.setenv("HISHO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(m, "_now", lambda: NOW)
    return m


def test_personal_by_company_or_setting_and_drafts_follow(mod):
    assert mod.is_personal(GMAIL) and not mod.drafts_on(GMAIL)
    assert mod.drafts_on({**GMAIL, "drafts": True})
    assert not mod.is_personal({"company": "Acme Studio"}) and mod.drafts_on({"company": "Acme Studio"})
    assert mod.is_personal({"company": "Me", "personal": True})


def test_a_personal_mailbox_is_sorted_for_a_person(mod):
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return "\n".join([json.dumps({"id": 1, "label": "Customer request", "summary": "x"}),
                          json.dumps({"id": 2, "label": "Newsletter", "summary": "new sign-in", "pressing": "security notice"}),
                          json.dumps({"id": 3, "label": "Bill or invoice", "summary": "card payment failed",
                                      "pressing": "payment notice"}),
                          json.dumps({"id": 4, "label": "Deadline", "summary": "dentist tomorrow 9 AM",
                                      "pressing": "client problem"})])
    msgs = [{"uid": u, "from_addr": "x@y.com", "subject": "s", "body": "b", "received": "r"} for u in (11, 12, 13, 14)]
    got = mod.classify("Personal", msgs, NOW, ask, personal=True)
    assert "PERSONAL email" in seen[0] and "Customer request" not in seen[0].split("Labels:")[0]
    assert 11 not in got                                  # no customers in a personal mailbox: dropped
    assert got[12]["pressing"] == ""                      # a newsletter is never pressing
    assert got[13] == {"label": "Bill or invoice", "summary": "card payment failed", "pressing": "payment notice"}
    assert got[14]["pressing"] == ""                      # "client problem" isn't a personal kind
    biz = mod.parse_labels(json.dumps({"id": 1, "label": "Needs reply", "summary": "x", "pressing": "security notice"}), [1])
    assert biz[1]["pressing"] == ""                       # and a business mailbox keeps its own kinds


def test_personal_mail_gets_no_draft_unless_asked(mod):
    m = {"label": "Needs reply", "from_addr": "mom@example.com", "received": NOW.isoformat(), "uid": 1}
    assert not mod._wants_draft(m, NOW, GMAIL)
    assert mod._wants_draft(m, NOW, {**GMAIL, "drafts": True})


class GmailBox:
    """Answers like Gmail: a folder name with a space must come quoted, or it's a BAD command (seen 2026-11-06)."""

    def __init__(self):
        self.cmds = []

    def login(self, u, p):
        self.cmds.append(("LOGIN",))

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
                      b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"', b'(\\Drafts \\HasNoChildren) "/" "[Gmail]/Drafts"',
                      b'(\\HasNoChildren \\Important) "/" "[Gmail]/Important"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
                      b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"', b'(\\Flagged \\HasNoChildren) "/" "[Gmail]/Starred"',
                      b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"', b'(\\HasNoChildren) "/" "Family Stuff"']

    def select(self, folder="INBOX", readonly=False):
        self.cmds.append(("EXAMINE" if readonly else "SELECT", folder))
        if " " in folder and not folder.startswith('"'):
            raise __import__("imaplib").IMAP4.error("EXAMINE command error: BAD [b'Could not parse command']")
        return "OK", [b"0"]

    def response(self, code):
        return code, [b"1"]

    def uid(self, command, *args):
        return "OK", [b""]

    def logout(self):
        pass


def test_gmail_folders_with_spaces_are_quoted_and_every_label_is_read(mod):
    box = GmailBox()
    st = mod.poll("home", {**GMAIL, "folders": "all"}, type("C", (), {"secret": lambda s, n: "pw"})(), now=NOW,
                  ask=lambda p: "", connect_fn=lambda e, p: box)
    assert st["status"] == "ok", st.get("error")
    assert st["folders_found"] == ["[Gmail]/Spam", "Family Stuff"] and st["folders_junk"] == ["[Gmail]/Spam"]
    examined = [c[1] for c in box.cmds if c[0] == "EXAMINE"]
    assert '"[Gmail]/Sent Mail"' in examined and '"Family Stuff"' in examined and "INBOX" in examined
    assert mod.mailbox("INBOX") == "INBOX" and mod.mailbox('a"b') == '"a\\"b"'


def test_the_setup_test_opens_the_sent_folder_too(mod, monkeypatch):
    class NoSent(GmailBox):
        def select(self, folder="INBOX", readonly=False):
            if "Sent" in folder:
                return "NO", [b"no such folder"]
            return super().select(folder, readonly)
    monkeypatch.setattr(mod, "imap_connect", lambda e, p: NoSent())
    monkeypatch.setattr(mod.sender, "smtp_login_test", lambda e, p: pytest.fail("SMTP before the folders were fine"))
    out = mod.test({**GMAIL, "sent_folder": "Sent Stuff"}, type("C", (), {"secret": lambda s, n: "pw"})())
    assert not out["ok"] and "Sent folder 'Sent Stuff'" in out["error"] and "[Gmail]/Sent Mail" in out["explain"]


# ── 0.12.4: the job hunt (personal mailboxes): first everywhere, never cleaned up, a push only when someone waits ──

def jobs_state(mod, now=NOW):
    t = (now - dt.timedelta(hours=3)).isoformat()
    msgs = [
        {"uid": 1, "from_name": "Pat Recruiter", "from_addr": "pat@acme-staffing.example", "subject": "Interview Tuesday?",
         "label": "Job search", "summary": "Asks to confirm an interview time", "pressing": "job reply", "received": t},
        {"uid": 2, "from_name": "Hiring Desk", "from_addr": "hr@bigpay-jobs.example", "subject": "You're hired! Send your bank info",
         "label": "Job search", "summary": "Offer that asks for bank details", "pressing": "", "scam": True, "received": t},
        {"uid": 3, "from_name": "JobBoard Alerts", "from_addr": "alerts@jobboard.example", "subject": "5 new IT jobs",
         "label": "Job search", "summary": "Job alert", "pressing": "", "received": t},
        {"uid": 4, "from_name": "JobBoard Alerts", "from_addr": "alerts@jobboard.example", "subject": "3 new IT jobs",
         "label": "Job search", "summary": "Job alert", "pressing": "", "received": t},
        {"uid": 5, "from_name": "Shop", "from_addr": "deals@shop.example", "subject": "Sale", "label": "Newsletter",
         "summary": "sale", "pressing": "", "received": t},
        {"uid": 6, "from_name": "Sam Friend", "from_addr": "sam@example.com", "subject": "Dinner?", "label": "Needs reply",
         "summary": "Dinner plans", "pressing": "", "received": t}]
    mod.save_state("home", {"status": "ok", "checked": now.isoformat(), "uidvalidity": "1", "messages": msgs})


def test_job_mail_is_sorted_first_with_its_own_push_and_a_scam_flag(mod):
    def ask(prompt):
        assert "job" in prompt.lower() and "scam" in prompt and "job reply" in prompt
        return "\n".join([json.dumps({"id": 1, "label": "Job search", "summary": "interview", "pressing": "job reply"}),
                          json.dumps({"id": 2, "label": "Job search", "summary": "fee first", "pressing": "job reply",
                                      "scam": True}),
                          json.dumps({"id": 3, "label": "Newsletter", "summary": "x", "pressing": "job reply"})])
    msgs = [{"uid": u, "from_addr": "x@y.com", "subject": "s", "body": "b", "received": "r"} for u in (1, 2, 3)]
    got = mod.classify("Personal", msgs, NOW, ask, personal=True)
    assert got[1] == {"label": "Job search", "summary": "interview", "pressing": "job reply"}
    assert got[2]["scam"] is True and got[2]["pressing"] == ""   # a likely scam is never pushed
    assert got[3]["pressing"] == ""


def test_today_lists_the_job_hunt_first(mod):
    jobs_state(mod)
    lines = mod.morning({"home": {**GMAIL}}, None)["lines"]
    assert lines[0] == "- **Job search**"
    assert lines[1].startswith("    - **waiting on your reply**: Pat Recruiter, Interview Tuesday?")
    assert lines[2].startswith("    - ⚠ looks like a scam: don't send money or ID: Hiring Desk")
    assert lines[3] == "    - 2 job alerts: JobBoard Alerts 2 (Add-ons > Email)"
    assert lines[4].startswith("- **Personal**")
    assert not any("Interview Tuesday" in l for l in lines[4:])   # once, in the job block
    assert any("Reply: Sam Friend" in l for l in lines[4:])


def test_a_push_only_when_someone_waits_on_a_reply(mod):
    jobs_state(mod)
    probs = mod.summary({"home": {**GMAIL}}, type("C", (), {"secret": lambda s, n: "pw"})())["problems"]
    assert [p["title"] for p in probs if not p["key"].startswith("open-")] == ["Personal: job reply from Pat Recruiter"]


def test_job_mail_is_never_cleaned_and_comes_first_on_the_page(mod):
    jobs_state(mod)
    clean = {"cats": {"3": {"group": "Jobs", "from_addr": "alerts@jobboard.example"}}}
    assert mod.never_clean({"group": "Newsletters", "from_addr": "alerts@jobboard.example"},
                           {"label": "Job search"}, clean) == "Job search"
    assert mod.never_clean(clean["cats"]["3"], None, clean) == "not clutter"   # the header sort's Jobs group stays
    items = mod.details({"home": {**GMAIL}}, None)[0]["items"]
    names = [i["name"] for i in items if i["id"] not in ("new", "cleanup") and not i["id"].startswith("open-")]
    assert names[:2] == ["Interview Tuesday?", "You're hired! Send your bank info"] or \
        set(names[:2]) == {"Interview Tuesday?", "You're hired! Send your bank info"}
    scam = next(i for i in items if i["name"].startswith("You're hired"))
    assert "looks like a scam" in scam["facts"][0] and scam["facts"][0].startswith("💼 Job search")


def test_job_mail_sorted_before_this_version_is_sorted_again_once(mod):
    t = (NOW - dt.timedelta(hours=5)).isoformat()
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "last_uid": 10, "messages": [
        {"uid": 7, "from_name": "JobBoard", "from_addr": "alerts@linkedin.com", "subject": "New jobs for you",
         "label": "Newsletter", "summary": "x", "pressing": "", "received": t, "tries": 1},
        {"uid": 8, "from_name": "Shop", "from_addr": "deals@shop.example", "subject": "Sale", "label": "Newsletter",
         "summary": "x", "pressing": "", "received": t, "tries": 1}]})
    asked = []

    def ask(prompt):
        if prompt.startswith("You look through email still sitting"):
            return ""   # the inbox review (0.14.0): not what this test counts
        asked.append(prompt)
        return json.dumps({"id": 1, "label": "Job search", "summary": "job alert", "pressing": ""})
    box = GmailBox()
    mod.poll("home", {**GMAIL, "folders": ""}, type("C", (), {"secret": lambda s, n: "pw"})(), now=NOW, ask=ask,
             connect_fn=lambda e, p: box)
    msgs = {m["uid"]: m for m in mod.load_state("home")["messages"]}
    assert msgs[7]["label"] == "Job search" and msgs[8]["label"] == "Newsletter"
    assert len(asked) == 1 and "New jobs for you" in asked[0] and "Sale" not in asked[0]
    mod.poll("home", {**GMAIL, "folders": ""}, type("C", (), {"secret": lambda s, n: "pw"})(),
             now=NOW + dt.timedelta(minutes=5), ask=ask, connect_fn=lambda e, p: box)
    assert len(asked) == 1   # once


# ── 0.12.5: label tuning from two weeks of real sorting ─────────────────────────────────────────────────────────

def test_a_verification_code_never_needs_a_reply(mod):
    def ask(prompt):
        return "\n".join([json.dumps({"id": 1, "label": "Needs reply", "summary": "Verification code 123456, expires in 15 minutes"}),
                          json.dumps({"id": 2, "label": "Needs reply", "summary": "Support asks which motherboard you have"})])
    msgs = [{"uid": 1, "from_addr": "support@agent.example", "subject": "Your Verification Code - Expires in 15 Minutes",
             "body": "b", "received": "r"},
            {"uid": 2, "from_addr": "support@maker.example", "subject": "Pending request: the RAM stopped", "body": "b",
             "received": "r"}]
    got = mod.classify("Acme", msgs, NOW, ask)
    assert got[1]["label"] == "Newsletter" and got[2]["label"] == "Needs reply"   # a support ticket still needs you


def test_the_prompts_keep_marketing_reminders_out_of_deadlines(mod):
    seen = []
    mod.classify("Acme", [{"uid": 1, "from_addr": "a@b.c", "subject": "s", "body": "b", "received": "r"}], NOW,
                 lambda p: seen.append(p) or "")
    mod.classify("Personal", [{"uid": 1, "from_addr": "a@b.c", "subject": "s", "body": "b", "received": "r"}], NOW,
                 lambda p: seen.append(p) or "", personal=True)
    assert all("members' call" in p and "Newsletter" in p for p in seen)


def test_a_run_of_the_same_notice_pushes_once(mod):
    t = [(NOW - dt.timedelta(hours=h)).isoformat() for h in (30, 20, 2)]
    msgs = [{"uid": i, "from_name": "Host", "from_addr": "no-reply@host.example", "subject": "Your cloud will be deleted soon!",
             "label": "Deadline", "summary": "server deleted", "pressing": "deadline 48h", "received": t[i]} for i in range(3)]
    msgs.append({"uid": 9, "from_name": "Host", "from_addr": "no-reply@host.example", "subject": "Your product will expire soon!",
                 "label": "Deadline", "summary": "expires", "pressing": "deadline 48h", "received": t[2]})
    mod.save_state("biz", {"status": "ok", "checked": NOW.isoformat(), "uidvalidity": "1", "messages": msgs})
    biz = {"company": "Acme", "address": "a@acme.example", "password": "X"}
    probs = mod.summary({"biz": biz}, type("C", (), {"secret": lambda s, n: "pw"})())["problems"]
    assert len(probs) == 2 and probs[0]["key"].endswith("-2")   # the newest of the run, and the other notice


def test_a_cached_code_sorted_as_needing_a_reply_is_put_right_once(mod):
    t = (NOW - dt.timedelta(hours=5)).isoformat()
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "last_uid": 10, "jobs_resorted": True, "messages": [
        {"uid": 7, "from_addr": "support@agent.example", "subject": "Your Verification Code - Expires in 15 Minutes",
         "label": "Needs reply", "summary": "code", "pressing": "", "received": t, "tries": 1,
         "draft": {"subject": "Re: code", "body": "x"}}]})
    mod.poll("home", {**GMAIL, "folders": ""}, type("C", (), {"secret": lambda s, n: "pw"})(), now=NOW,
             ask=lambda p: "", connect_fn=lambda e, p: GmailBox())
    [m] = mod.load_state("home")["messages"]
    assert m["label"] == "Newsletter" and "draft" not in m


def test_job_boards_and_hidden_noreply_addresses_are_alerts_not_people(mod):
    for addr in ("jobalerts-noreply@linkedin.com", "messages-noreply@linkedin.com", "phil@ziprecruiter.com",
                 "donotreply@match.indeed.com", "x@notifications.joinhandshake.com", "news@mg.jobsite.example"):
        assert mod.kind({"label": "Job search", "from_addr": addr}) == "jobalert", addr
    assert mod.kind({"label": "Job search", "from_addr": "pat.lee@staffing.example"}) == "job"
    assert mod.kind({"label": "Job search", "from_addr": "alerts@linkedin.com", "pressing": "job reply"}) == "job"


# ── 0.12.6: events an email names become "Add to your calendar" cards (Hisho's own calendar, on Approve only) ──

def test_an_event_the_sort_names_is_checked_strictly(mod):
    ok = mod.parse_event({"title": "Interview with Acme", "start": "2026-11-12T10:00", "end": "2026-11-12T11:00",
                          "place": "Zoom https://zoom.us/j/123"})
    assert ok == {"title": "Interview with Acme", "start": "2026-11-12T10:00", "end": "2026-11-12T11:00", "place": "Zoom"}
    for bad in ({"title": "", "start": "2026-11-12T10:00"}, {"title": "x", "start": "next Tuesday"},
                {"title": "x", "start": "2026-11-12T10:00", "end": "2026-11-12T09:00"},
                {"title": "x", "start": "2026-11-12", "end": "2026-11-12T09:00"}, {"title": "x", "start": "2026-13-45"}, "x"):
        assert mod.parse_event(bad) is None, bad
    got = mod.parse_labels(json.dumps({"id": 1, "label": "Newsletter", "summary": "s",
                                       "event": {"title": "Webinar", "start": "2026-11-12T10:00"}}), [1])
    assert "event" not in got[1]   # never from a newsletter


def test_the_card_puts_the_event_on_the_calendar_only_through_approvals(mod, monkeypatch):
    monkeypatch.setattr(mod, "_tz", lambda: ZoneInfo("America/Los_Angeles"))
    t = (NOW - dt.timedelta(hours=2)).isoformat()
    msgs = [{"uid": 3, "from_name": "Pat Lee", "from_addr": "pat.lee@staffing.example", "subject": "Interview Thursday",
             "label": "Job search", "summary": "Interview Thursday 10 AM", "pressing": "job reply", "received": t,
             "excerpt": "Can you do Thursday at 10?", "event": {"title": "Interview with Acme", "start": "2026-11-12T10:00",
                                                                 "place": "Zoom"}},
            {"uid": 4, "from_addr": "x@spam.example", "subject": "s", "label": "Job search", "received": t, "junk": True,
             "event": {"title": "Fake", "start": "2026-11-12T10:00"}},
            {"uid": 5, "from_addr": "a@b.example", "subject": "old", "label": "Deadline", "received": t,
             "event": {"title": "Was last week", "start": "2026-10-01"}}]
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "messages": msgs})
    cards = [c for c in mod.proposals({"home": {**GMAIL}}, None) if c["action"]["type"] == "calendar_add"]
    assert len(cards) == 1
    c = cards[0]
    assert c["key"] == "event:home:1:3" and c["pressing"] is False and c["title"].startswith("Add to your calendar: Interview")
    assert c["action"]["payload"] == {"title": "Interview with Acme", "start": "2026-11-12T10:00", "end": "2026-11-12T11:00",
                                      "all_day": False, "company": "Personal", "place": "Zoom",
                                      "notes": "From an email by Pat Lee: Interview Thursday"}
    assert c["context"][0]["text"] == "Can you do Thursday at 10?" and {f["name"] for f in c["fields"]} >= {"title", "start"}


def test_the_sort_is_asked_for_events_in_the_owners_zone(mod, monkeypatch):
    monkeypatch.setattr(mod, "_tz", lambda: ZoneInfo("America/Los_Angeles"))
    seen = []
    mod.classify("Personal", [{"uid": 1, "from_addr": "a@b.c", "subject": "s", "body": "b", "received": "r"}], NOW,
                 lambda p: seen.append(p) or "", personal=True)
    assert '"event"' in seen[0] and "America/Los_Angeles" in seen[0] and "never a link" in seen[0]
