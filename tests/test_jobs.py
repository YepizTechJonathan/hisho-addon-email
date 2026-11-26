"""0.19.0: the job hunt. Job emails are read again for their listings and links, Claude rates each listing against the
owner's own Job search note, and Today.md, the overview card and the page show the good ones first; the rest are
counted, never deleted. Run with Hisho's venv at the repository's top: ~/code/hisho/.venv/bin/python -m pytest -q"""
import datetime as dt
import email
import email.policy
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hisho import addons

NOW = dt.datetime(2026, 11, 20, 18, 0, tzinfo=dt.timezone.utc)
GMAIL = {"company": "Personal", "address": "a@gmail.com", "password": "GMAIL_APP_PASSWORD", "imap_host": "imap.gmail.com"}
NOTE = """# Job search

## Roles I want
- Junior software developer, full stack or backend
- IT support or sysadmin

## Where
Near Riverton, CA, or remote.

## Never show me
Sales, warehouse, retail.
"""
ALERT_HTML = """<html><body><h2>Jobs for you</h2>
<p><a href="https://www.indeed.com/viewjob?jk=1&amp;from=alert">Junior Software Developer</a> New York Jets, Remote, $85k</p>
<p><a href="https://www.indeed.com/viewjob?jk=2">Payroll Specialist</a> Lecangs, Perris CA</p>
<p><a href="https://www.indeed.com/unsubscribe?u=1">Unsubscribe</a></p></body></html>"""


@pytest.fixture
def mod(addon, monkeypatch, tmp_path):
    m = addons.provider(addon)
    monkeypatch.setenv("HISHO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(m, "_now", lambda: NOW)
    monkeypatch.setattr(m, "_tz", lambda: ZoneInfo("America/Los_Angeles"))
    return m


def note_file(text=NOTE) -> Path:
    path = Path(os.environ["HISHO_ROOT"]) / "Companies/Personal/Job search.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def alert_msg(html_body=ALERT_HTML):
    raw = ("From: Indeed <donotreply@match.indeed.com>\r\nSubject: Junior Software Developer @ New York Jets\r\n"
           "Content-Type: text/html; charset=utf-8\r\n\r\n" + html_body).encode()
    return email.message_from_bytes(raw, policy=email.policy.default)


def test_listing_text_numbers_the_jobs_links_and_skips_unsubscribe(mod):
    text, links = mod.jobs.listing_text(alert_msg())
    assert "Junior Software Developer [L1]" in text and "Payroll Specialist [L2]" in text
    assert links == ["https://www.indeed.com/viewjob?jk=1&from=alert", "https://www.indeed.com/viewjob?jk=2"]
    assert "Unsubscribe [L" not in text


def test_rating_uses_his_note_and_only_links_from_the_email(mod):
    note_file()
    text, links = mod.jobs.listing_text(alert_msg())
    m = {"uid": 5, "from_addr": "donotreply@match.indeed.com", "subject": "s", "listing": text, "links": links}
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return "\n".join([
            json.dumps({"id": 1, "title": "Junior Software Developer", "company": "New York Jets", "place": "Remote",
                        "pay": "$85k", "fit": "good", "why": "Junior dev, remote", "link": "L1"}),
            json.dumps({"id": 1, "title": "Payroll Specialist", "company": "Lecangs", "fit": "no", "why": "Not tech",
                        "link": "L9"}),                                       # no such link: dropped, row kept
            json.dumps({"id": 1, "title": "Cash mover", "company": "x", "fit": "great"}),   # unknown fit: dropped
            json.dumps({"id": 2, "title": "Ghost", "fit": "good"})])                       # unknown email: dropped
    got = mod.jobs.rate(mod.jobs.read_note(GMAIL), [m], ask)
    assert "Junior software developer, full stack" in seen[0] and "Never show me" in seen[0]
    assert [(j["title"], j["fit"], j["url"]) for j in got[5]] == [
        ("Junior Software Developer", "good", "https://www.indeed.com/viewjob?jk=1&from=alert"),
        ("Payroll Specialist", "no", "")]
    assert mod.jobs.rate("", [m], ask) == {}           # no note: nothing rated


def test_the_note_key_ignores_comments_and_his_button_log(mod):
    k = mod.jobs.note_key(NOTE)
    assert k and mod.jobs.note_key(NOTE + "\n<!-- a comment -->\n") == k
    assert mod.jobs.note_key(NOTE + "\n## What you pressed\n- 2026-11-20 Applied: X at Y\n") == k
    assert mod.jobs.note_key(NOTE.replace("Riverton", "Lakeview")) != k
    assert mod.jobs.note_key("") == ""


def _rated(uid, title, company, fit, hours=2, frm="Indeed", addr="donotreply@match.indeed.com", **extra):
    return {"uid": uid, "from_name": frm, "from_addr": addr, "subject": f"{title} @ {company}", "label": "Job search",
            "summary": "alert", "pressing": "", "received": (NOW - dt.timedelta(hours=hours)).isoformat(),
            "listing": "x", "links": [], "jobs_for": mod_key(),
            "jobs": [{"key": key(title, company), "title": title, "company": company, "place": "Remote", "pay": "$85k",
                      "fit": fit, "why": "why " + title, "url": f"https://jobs.example/{uid}"}], **extra}


def mod_key():
    from hashlib import sha1
    import re
    text = "\n".join(l.rstrip() for l in re.sub(r"(?s)<!--.*?-->", "", NOTE).splitlines() if l.strip())
    return sha1(text.encode()).hexdigest()[:12]


def key(title, company):
    from hashlib import sha1
    import re
    n = lambda s: " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())
    return sha1(f"{n(title)}|{n(company)}".encode()).hexdigest()[:12]


def board_state(mod):
    note_file()
    assert mod.jobs.note_key(NOTE) == mod_key()
    msgs = [_rated(1, "Junior Software Developer", "New York Jets", "good"),
            _rated(2, "Junior Software Developer", "New York Jets", "good", hours=30, frm="LinkedIn",
                   addr="jobalerts-noreply@linkedin.com"),               # same job, another board: once
            _rated(3, "IT Support Specialist", "US Navy", "maybe"),
            _rated(4, "Payroll Specialist", "Lecangs", "no"),
            _rated(5, "Reship packages from home", "Easy Co", "scam"),
            _rated(6, "Help Desk Tech", "Old Co", "good", hours=24 * 20),   # older than two weeks
            _rated(7, "Gone Dev", "Deleted Co", "good", gone=NOW.isoformat()),  # he deleted it
            {"uid": 8, "from_name": "Pat Recruiter", "from_addr": "pat@acme-staffing.example", "subject": "Interview Tuesday?",
             "label": "Job search", "summary": "interview", "pressing": "job reply",
             "received": (NOW - dt.timedelta(hours=1)).isoformat()}]
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "messages": msgs})


def test_today_shows_good_matches_with_links_and_counts_the_rest(mod):
    board_state(mod)
    lines = mod.job_lines({"home": {**GMAIL}}, NOW, ZoneInfo("America/Los_Angeles"))
    assert lines[0] == "- **Job search** ([[Companies/Personal/Job search|what you want]])"
    assert lines[1].startswith("    - **waiting on your reply**: Pat Recruiter")
    assert lines[2] == "    - ⭐ **1 good match**"
    assert lines[3] == ("        - [Junior Software Developer, New York Jets](https://jobs.example/1): Remote, $85k. "
                        "why Junior Software Developer (Indeed, today, in 2 alerts)")
    assert lines[4] == "    - Maybe (1): IT Support Specialist, US Navy"
    assert lines[5] == "    - Left out: 1 not a fit, 1 look fake (still in your mailbox; all listed on Add-ons > Email)"
    assert not any("Help Desk" in l or "Gone Dev" in l for l in lines)


def test_without_his_note_today_says_where_to_write_it(mod):
    board_state(mod)
    (Path(os.environ["HISHO_ROOT"]) / "Companies/Personal/Job search.md").unlink()
    lines = mod.job_lines({"home": {**GMAIL}}, NOW, ZoneInfo("America/Los_Angeles"))
    assert lines[-1].startswith("    - 5 job board emails not sorted for you: write what jobs you want in "
                                "[[Companies/Personal/Job search]]")


def test_buttons_write_to_his_note_and_change_the_lists(mod):
    board_state(mod)
    entries = {"home": {**GMAIL}}
    ctx = type("C", (), {"input": "too far"})()
    res = mod.act(entries, ctx, "home", f"job-{key('IT Support Specialist', 'US Navy')}", "hide")
    assert res["ok"], res
    res = mod.act(entries, type("C", (), {"input": ""})(), "home",
                  f"job-{key('Junior Software Developer', 'New York Jets')}", "applied")
    assert res["ok"], res
    text = (Path(os.environ["HISHO_ROOT"]) / "Companies/Personal/Job search.md").read_text()
    assert text.startswith(NOTE.rstrip("\n"))                                   # his words untouched
    assert "- 2026-11-20 Not for me: IT Support Specialist at US Navy — too far" in text
    assert "- 2026-11-20 Applied: Junior Software Developer at New York Jets" in text
    lines = mod.job_lines(entries, NOW, ZoneInfo("America/Los_Angeles"))
    assert "    - Applied (1): Junior Software Developer, New York Jets" in lines
    assert not any("good match" in l and "⭐" in l for l in lines)
    assert any("1 you said no to" in l for l in lines)
    assert mod.act(entries, ctx, "home", "job-nope", "hide")["ok"] is False


def test_page_card_and_clean_up_guard(mod):
    board_state(mod)
    entries = {"home": {**GMAIL}}
    sec = mod.details(entries, None)[0]
    assert sec["title"] == "Job search"
    assert [i["name"] for i in sec["items"]][:2] == ["⭐ Junior Software Developer, New York Jets", "❔ IT Support Specialist, US Navy"]
    assert sec["items"][0]["url"] == "https://jobs.example/1" and [a["id"] for a in sec["items"][0]["actions"]] == ["applied", "hide"]
    card = mod.summary(entries, type("C", (), {"secret": lambda s, n: "pw"})())["card"]
    assert card["title"] == "Job search" and card["rows"][1]["label"] == "Good matches" and card["rows"][1]["value"] == "1"
    assert card["rows"][2]["url"] == "https://jobs.example/1"
    msgs = {m["uid"]: m for m in mod.load_state("home")["messages"]}
    alert = {"group": "Newsletters", "from_addr": "donotreply@match.indeed.com", "subject": "New jobs"}
    assert mod.never_clean(alert, msgs[1], {}) == "has a job that fits you"
    assert mod.never_clean(alert, msgs[3], {}) == "has a job that fits you"     # a maybe too
    assert mod.never_clean(alert, msgs[4], {}) == ""                            # not a fit: may go once a week old


def test_a_poll_reads_job_mail_again_and_rates_it(mod):
    note_file()
    t = (NOW - dt.timedelta(hours=3)).isoformat()
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "last_uid": 9, "messages": [
        {"uid": 9, "from_name": "Indeed", "from_addr": "donotreply@match.indeed.com", "subject": "Jobs", "label": "Job search",
         "summary": "alert", "pressing": "", "received": t, "tries": 1, "message_id": "<9@x>"}]})
    raw = ("From: Indeed <donotreply@match.indeed.com>\r\nSubject: Jobs\r\nMessage-ID: <9@x>\r\n"
           "Content-Type: text/html; charset=utf-8\r\n\r\n" + ALERT_HTML).encode()

    class Box:
        def __init__(self):
            self.fetched = []

        def login(self, *a): return "OK", [b""]
        def capability(self): return "OK", [b"IMAP4rev1"]
        def list(self, *a): return "OK", [b'(\\HasNoChildren) "/" "INBOX"']
        def select(self, folder, readonly=False): return "OK", [b"1"]
        def response(self, what): return "OK", [b"1"]
        def noop(self): return "OK", [b""]
        def logout(self): return "BYE", [b""]

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                return "OK", [b"9"]
            self.fetched.append(args[-1])
            if "BODY.PEEK[]" in args[-1]:
                return "OK", [(b"9 (UID 9 BODY[]<0> {%d}" % len(raw), raw), b")"]
            return "OK", [None]

    asked = []

    def ask(prompt):
        if "You help the owner find a job" in prompt:
            asked.append(prompt)
            return json.dumps({"id": 1, "title": "Junior Software Developer", "company": "New York Jets", "fit": "good",
                               "why": "fits", "link": "L1"})
        return ""
    box = Box()
    mod.poll("home", {**GMAIL, "folders": ""}, type("C", (), {"secret": lambda s, n: "pw"})(), now=NOW, ask=ask,
             connect_fn=lambda e, p: box)
    m = {m["uid"]: m for m in mod.load_state("home")["messages"]}[9]
    assert asked and "Junior Software Developer [L1]" in asked[0]
    assert m["jobs"][0]["url"] == "https://www.indeed.com/viewjob?jk=1&from=alert" and m["jobs_for"] == mod_key()


def test_an_unknown_sender_with_several_jobs_is_an_alert_not_a_person(mod):
    note_file()
    m = _rated(1, "Junior System Administrator", "Asm", "good", frm="Job Digest", addr="digest-team@jobsite.example")
    m["from_addr"] = "kim@jobsite.example"
    m["jobs"].append({**m["jobs"][0], "key": key("Help Desk", "Asm"), "title": "Help Desk"})
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "messages": [m]})
    lines = mod.job_lines({"home": {**GMAIL}}, NOW, ZoneInfo("America/Los_Angeles"))
    assert lines[1] == "    - ⭐ **2 good matches**"
    assert mod.kind({"label": "Job search", "from_addr": "kimble@kimblegroup.com"}) == "jobalert"


def test_an_alert_hisho_archived_is_rated_again_when_the_note_changes(mod):
    held = {"uid": 1, "listing": "x", "links": [], "jobs_for": "old", "gone": NOW.isoformat(), "held_in_hisho": True}
    deleted = {"uid": 2, "listing": "x", "links": [], "jobs_for": "old", "gone": NOW.isoformat()}
    assert [m["uid"] for m in mod.jobs.to_rate([held, deleted], "new")] == [1]


def _tasks_note(vault):
    """Where Hisho keeps the owner's tasks: Tasks.md since Core split Today.md (11-25), Today.md before."""
    return vault / "Tasks.md" if (vault / "Tasks.md").exists() else vault / "Today.md"


def test_ready_jobs_and_people_waiting_go_on_today_once_and_applied_ticks_them(mod, monkeypatch):
    """0.33.0: job alerts are archived once their jobs are kept in Hisho, so the jobs themselves go on Today's task list
    (checked ones, a few a day) and a person writing about a job who waits on a reply goes there at once."""
    board_state(mod)
    import hisho.today
    vault = Path(os.environ["HISHO_ROOT"])
    (vault / "Today.md").write_text(hisho.today.skeleton([]))
    good = key("Junior Software Developer", "New York Jets")
    mod._state_file("job-prep").parent.mkdir(parents=True, exist_ok=True)
    mod._state_file("job-prep").write_text(json.dumps({good: {"verdict": "looks real", "web": "likely real",
                                                               "note": "Companies/Personal/Job applications/New York Jets - Junior Software Developer"}}))
    entries = {"home": {**GMAIL}}
    tz = ZoneInfo("America/Los_Angeles")
    mod.jobs_to_today(entries, NOW, tz)
    mod.jobs_to_today(entries, NOW, tz)                       # each once
    tasks = [t["text"] for t in hisho.today.tasks(_tasks_note(vault).read_text())]
    assert tasks == [
        "Personal: reply to Pat Recruiter about a job: Interview Tuesday? (email of today; Add-ons > Email)",
        "Personal: apply to Junior Software Developer, New York Jets (Remote, $85k); likely real on their site, notes and "
        "cover letter ready: [[Companies/Personal/Job applications/New York Jets - Junior Software Developer|ready to apply]]"]
    assert mod.act(entries, type("C", (), {"input": ""})(), "home", f"job-{good}", "applied")["ok"]
    after = {t["text"]: t["done"] for t in hisho.today.tasks(_tasks_note(vault).read_text())}
    assert after[tasks[1]] is True and after[tasks[0]] is False


def test_unchecked_jobs_wait_and_only_a_few_go_on_today_a_day(mod, monkeypatch):
    note_file()
    import hisho.today
    vault = Path(os.environ["HISHO_ROOT"])
    (vault / "Today.md").write_text(hisho.today.skeleton([]))
    msgs = [_rated(i, f"Developer {i}", f"Co {i}", "good") for i in range(1, 9)]
    mod.save_state("home", {"status": "ok", "uidvalidity": "1", "messages": msgs})
    prep = {key(f"Developer {i}", f"Co {i}"): {"note": f"Companies/Personal/Job applications/Co {i}",
                                              "web": "can't tell" if i == 1 else "confirmed" if i == 8 else "likely real"}
            for i in range(1, 9)}
    mod._state_file("job-prep").parent.mkdir(parents=True, exist_ok=True)
    mod._state_file("job-prep").write_text(json.dumps(prep))
    tz = ZoneInfo("America/Los_Angeles")
    mod.jobs_to_today({"home": {**GMAIL}}, NOW, tz)
    tasks = [t["text"] for t in hisho.today.tasks(_tasks_note(vault).read_text())]
    assert len(tasks) == mod.JOB_TASKS_PER_DAY and "Developer 8" in tasks[0]       # confirmed first
    assert not any("Developer 1," in t for t in tasks)                              # not found on their site: not a task
    mod.jobs_to_today({"home": {**GMAIL}}, NOW + dt.timedelta(hours=1), tz)
    assert len(hisho.today.tasks(_tasks_note(vault).read_text())) == mod.JOB_TASKS_PER_DAY   # the day's share is used
    mod.jobs_to_today({"home": {**GMAIL}}, NOW + dt.timedelta(days=1), tz)
    assert len(hisho.today.tasks(_tasks_note(vault).read_text())) == 7              # the rest the next day
