"""0.6.0: an HTML sign-off (his Zoho signature) in the HTML part of sent mail, with a plain-text twin.
Run with Hisho's venv at the repository's top: ~/code/hisho/.venv/bin/python -m pytest -q"""
import email
import email.policy
from pathlib import Path

import pytest

from hisho import addons

SIG = ("Alex Rivera\nOwner / Technology Consultant\nRivera Tech LLC\nEmail: Alex@example.com\n"
       "Website: https://example.com")
HTML = """<div style="color: rgb(31, 41, 55);"><b>Alex Rivera</b>
<!-- phone --><div><b>Phone:</b> <a href="tel:{phone_tel}">{phone}</a></div><!-- /phone -->
<div><a href="https://example.com">example.com</a></div></div>"""
mod = None


@pytest.fixture(autouse=True)
def _mod(addon):
    global mod
    mod = addons.provider(addon)


@pytest.fixture
def entry(tmp_path):
    (tmp_path / "email-signatures").mkdir()
    (tmp_path / "email-signatures" / "yt.html").write_text(HTML)
    return {"company": "Acme", "address": "alex@example.com", "from_name": "Alex Rivera",
            "signature": SIG, "signature_html": "email-signatures/yt.html"}, tmp_path


def test_the_phone_line_shows_only_once_a_phone_is_set(entry):
    e, base = entry
    assert "Phone" not in mod.sender.signature_html(e, base) and "Phone" not in mod.sender.plain_signature(e)
    e = {**e, "phone": "(951) 555-0100"}
    assert "<b>Phone:</b> <a href=\"tel:+19515550100\">(951) 555-0100</a>" in mod.sender.signature_html(e, base)
    assert mod.sender.tel_link("+1 951.555.0100") == "+19515550100"
    assert mod.sender.plain_signature(e).split("\n")[3] == "Phone: (951) 555-0100"     # just before Email:


def test_the_signature_is_sanitized():
    dirty = ('<div onclick="x()">Hi<script>steal()</script><img src="https://track.example/p.gif">'
             '<a href="javascript:alert(1)">x</a><iframe src="https://evil"></iframe>'
             '<span style="background: url(https://track.example/x)">y</span><style>a{}</style></div>')
    clean = mod.sender.sanitize(dirty)
    for bad in ("onclick", "<script", "steal", "<img", "javascript:", "<iframe", "url(", "<style"):
        assert bad not in clean, bad
    assert "Hi" in clean and "<span" in clean


def test_only_a_html_file_inside_the_settings_folder(entry, tmp_path):
    e, base = entry
    (tmp_path / "secret.txt").write_text("x")
    assert mod.sender.signature_html({**e, "signature_html": "../secret.txt"}, base) == ""
    assert mod.sender.signature_html({**e, "signature_html": "/etc/passwd"}, base) == ""
    assert mod.sender.signature_html({**e, "signature_html": "missing.html"}, base) == ""


def test_mail_goes_as_text_plus_html_with_the_html_sign_off(entry, monkeypatch):
    e, base = entry
    monkeypatch.setattr(mod.sender, "signature_html", lambda en, b=None: mod.sender.__dict__["sanitize"](HTML.replace(
        "<!-- phone --><div><b>Phone:</b> <a href=\"tel:{phone_tel}\">{phone}</a></div><!-- /phone -->", "")))
    body = "Hi Ann,\n\nYes <b>I</b> can help & will.\n\n" + SIG
    msg = mod.sender.build(e, {"to": ["ann@shop.com"], "cc": [], "subject": "Re: x", "body": body,
                               "in_reply_to": "", "references": []})
    parsed = email.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    assert parsed.get_content_type() == "multipart/alternative"
    assert parsed.get_body(("plain",)).get_content().replace("\r\n", "\n").strip() == body
    h = parsed.get_body(("html",)).get_content()
    assert "Yes &lt;b&gt;I&lt;/b&gt; can help &amp; will." in h          # his words are text, never markup
    assert "Owner / Technology Consultant" not in h and "example.com</a>" in h   # the HTML sign-off replaces the plain one


def test_without_the_sign_off_at_the_end_it_stays_plain(entry):
    e, base = entry
    assert mod.sender.html_version(e, "Hi Ann, thanks!", base) == ""
    assert mod.sender.html_version({**e, "signature_html": ""}, "Hi\n\n" + SIG, base) == ""
    assert mod.sender.html_version(e, "Hi\n\n" + SIG.replace("\n", "  \n"), base)   # spacing doesn't matter
