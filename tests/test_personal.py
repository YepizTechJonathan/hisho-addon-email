"""0.12.0: a personal mailbox (company Personal, or personal: true) is sorted for a person, not a business, and gets no
reply drafts unless drafts: true. Folder names with spaces (Gmail's "[Gmail]/Sent Mail") go quoted on the wire.
Run with Hisho's venv at the repository's top: ~/code/hisho/.venv/bin/python -m pytest -q"""
import datetime as dt
import json

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
    assert not mod.is_personal({"company": "YepizTech"}) and mod.drafts_on({"company": "YepizTech"})
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
