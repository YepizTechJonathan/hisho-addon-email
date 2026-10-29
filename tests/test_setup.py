"""Set up this mailbox (addon.yaml connect:): the servers come from the address alone. Every lookup is stood in
for (no ISPDB, autoconfig or DNS is reached); the login test uses FakeIMAP-like stand-ins."""
import imaplib
import json
from pathlib import Path

import pytest

from hisho import addons, connect

HERE = Path(__file__).resolve().parents[1]

ISPDB_GMAIL = """<?xml version="1.0"?><clientConfig version="1.1"><emailProvider id="googlemail.com">
<incomingServer type="imap"><hostname>imap.gmail.com</hostname><port>993</port><socketType>SSL</socketType>
<username>%EMAILADDRESS%</username></incomingServer>
<incomingServer type="pop3"><hostname>pop.gmail.com</hostname><port>995</port><socketType>SSL</socketType></incomingServer>
<outgoingServer type="smtp"><hostname>smtp.gmail.com</hostname><port>465</port><socketType>SSL</socketType>
</outgoingServer></emailProvider></clientConfig>"""
OWN = """<clientConfig version="1.1"><emailProvider id="example.com">
<incomingServer type="imap"><hostname>imap.example.com</hostname><port>143</port><socketType>STARTTLS</socketType></incomingServer>
<incomingServer type="imap"><hostname>mail.%EMAILDOMAIN%</hostname><port>993</port><socketType>SSL</socketType></incomingServer>
<outgoingServer type="smtp"><hostname>mail.%EMAILDOMAIN%</hostname><port>587</port><socketType>STARTTLS</socketType></outgoingServer>
</emailProvider></clientConfig>"""


def dns(answers):
    return json.dumps({"Status": 0, "Answer": [{"type": 15, "data": f"{p} {h}."} for p, h in answers]})


@pytest.fixture
def conf(addon):
    return addons.provider(addon).mailconf


def web(pages):
    seen = []

    def get(url):
        seen.append(url)
        for start, text in pages.items():
            if url.startswith(start):
                return text
        return ""
    get.seen = seen
    return get


def test_the_manifest_offers_set_up_this_mailbox(addon):
    assert addons.validate_manifest(addon.manifest) == []
    c = addon.manifest["connect"]
    assert c["label"] == "Set up this mailbox" and c["form"] == ["company", "address", "password"] and c["fields"] == {}
    assert addon.manifest["entry_schema"]["password"] == "password"       # pasted = a local secret; a name still works
    assert connect.view(addon)["connect"]["form"] == ["company", "address", "password"]


def test_ispdb_first(conf):
    get = web({"https://autoconfig.thunderbird.net/v1.1/gmail.com": ISPDB_GMAIL})
    got = conf.lookup("alex@gmail.com", get=get, mx=lambda d: pytest.fail("no MX needed"))
    assert (got["imap_host"], got["imap_port"], got["smtp_host"], got["smtp_port"]) == ("imap.gmail.com", 993, "smtp.gmail.com", 465)
    assert got["provider"] == "google" and got["sent_folder"] == "[Gmail]/Sent Mail" and got["folders"] == ""
    assert got["app_password"] == "https://myaccount.google.com/apppasswords" and got["source"] == "Mozilla's ISPDB"


def test_then_the_domains_own_autoconfig_taking_only_tls_imap(conf):
    get = web({"https://autoconfig.example.com/mail/config-v1.1.xml?emailaddress=alex%40example.com": OWN})
    got = conf.lookup("alex@example.com", get=get, mx=lambda d: [])
    assert (got["imap_host"], got["imap_port"], got["smtp_host"], got["smtp_port"]) == ("mail.example.com", 993, "mail.example.com", 587)
    assert got["provider"] == "" and "sent_folder" not in got


@pytest.mark.parametrize("mx,key,imap,smtp,page", [
    ("aspmx.l.google.com", "google", "imap.gmail.com", ("smtp.gmail.com", 465), "https://myaccount.google.com/apppasswords"),
    ("smtp.google.com", "google", "imap.gmail.com", ("smtp.gmail.com", 465), "https://myaccount.google.com/apppasswords"),
    ("example-com.mail.protection.outlook.com", "microsoft", "outlook.office365.com", ("smtp.office365.com", 587),
     "https://account.microsoft.com/security"),
    ("mx.zoho.com", "zoho", "imap.zoho.com", ("smtp.zoho.com", 465), "https://accounts.zoho.com/home#security/app_password"),
    ("mx.zoho.eu", "zoho", "imap.zoho.eu", ("smtp.zoho.eu", 465), "https://accounts.zoho.eu/home#security/app_password"),
    ("mx.zoho.in", "zoho", "imap.zoho.in", ("smtp.zoho.in", 465), "https://accounts.zoho.in/home#security/app_password"),
    ("mx.zoho.com.au", "zoho", "imap.zoho.com.au", ("smtp.zoho.com.au", 465),
     "https://accounts.zoho.com.au/home#security/app_password"),
    ("mx.zohocloud.ca", "zoho", "imap.zohocloud.ca", ("smtp.zohocloud.ca", 465),
     "https://accounts.zohocloud.ca/home#security/app_password"),
    ("mx01.mail.icloud.com", "icloud", "imap.mail.me.com", ("smtp.mail.me.com", 587), "https://account.apple.com"),
    ("mta5.am0.yahoodns.net", "yahoo", "imap.mail.yahoo.com", ("smtp.mail.yahoo.com", 465),
     "https://login.yahoo.com/account/security"),
    ("in1-smtp.messagingengine.com", "fastmail", "imap.fastmail.com", ("smtp.fastmail.com", 465),
     "https://app.fastmail.com/settings/security"),
])
def test_then_the_mx_names_the_big_hosted_providers(conf, mx, key, imap, smtp, page):
    get = web({"https://cloudflare-dns.com/dns-query?name=example.com&type=MX": dns([(20, "backup.example.net"), (10, mx)])})
    got = conf.lookup("alex@example.com", get=get)
    assert got["provider"] == key and got["imap_host"] == imap and (got["smtp_host"], got["smtp_port"]) == smtp
    assert got["app_password"] == page and got["imap_port"] == 993
    assert mx in got["source"]


def test_an_unknown_mx_is_looked_up_in_the_ispdb_by_its_domain(conf):
    get = web({"https://cloudflare-dns.com/": dns([(10, "mx1.hostingco.example.net")]),
               "https://autoconfig.thunderbird.net/v1.1/example.net": OWN.replace("%EMAILDOMAIN%", "hostingco.example.net")})
    got = conf.lookup("alex@example.com", get=get)
    assert got["imap_host"] == "mail.hostingco.example.net" and got["provider"] == ""


def test_nothing_found_or_not_an_address_raises(conf):
    with pytest.raises(conf.NotFound):
        conf.lookup("alex@example.com", get=web({}))
    with pytest.raises(conf.NotFound):
        conf.lookup("not an address", get=web({}))


def test_mx_falls_back_to_a_second_resolver(conf):
    get = web({"https://dns.google/resolve?name=example.com&type=MX": dns([(5, "mx.zoho.eu")])})
    assert conf.mx_hosts("example.com", get) == ["mx.zoho.eu"]


# ── through Core: look up, test, save ─────────────────────────────────────

class Box:
    """The login stand-in: accepts only the right app password, records where it signed in."""
    seen = []

    def __init__(self, entry, password):
        Box.seen.append((entry["imap_host"], entry["imap_port"]))
        if password != "abcd efgh ijkl mnop":
            raise imaplib.IMAP4.error("b'[AUTHENTICATIONFAILED] Invalid credentials (Failure)'")

    def select(self, folder, readonly=False):
        return "OK", [b"3"]

    def logout(self):
        pass


@pytest.fixture
def core(addon, monkeypatch, conf, fleet):
    mod = addons.provider(addon)
    Box.seen = []
    monkeypatch.setattr(mod, "imap_connect", Box)
    monkeypatch.setattr(mod.sender, "smtp_login_test", lambda e, p: {"ok": True, "message": "SMTP accepts the login"})
    monkeypatch.setattr(conf, "fetch", web({"https://cloudflare-dns.com/": dns([(10, "mx.zoho.eu")])}))
    return mod


def test_set_up_this_mailbox_finds_the_servers_tests_and_saves_with_the_password_a_local_secret(addon, core):
    out = connect.connect(addon, "acme", {"company": "Acme", "address": "alex@example.com",
                                          "password": "abcd efgh ijkl mnop"})
    assert out["ok"], out
    assert "Zoho Mail" in out["message"] and "https://accounts.zoho.eu/home#security/app_password" in out["message"]
    assert "abcd efgh" not in out["message"]
    e = addons.read_config("email")["entries"]["acme"]
    assert e["imap_host"] == "imap.zoho.eu" and e["smtp_host"] == "smtp.zoho.eu" and e["smtp_port"] == 465
    assert e["password"] == "HISHO_ADDON_EMAIL_ACME_PASSWORD" and e["company"] == "Acme"
    assert "abcd efgh" not in Path(addons.config_path("email")).read_text()
    assert Box.seen[-1] == ("imap.zoho.eu", 993)


def test_a_refused_login_names_the_provider_and_its_app_password_page(addon, core):
    out = connect.connect(addon, "acme", {"company": "Acme", "address": "alex@example.com", "password": "my-normal-pw"})
    assert not out["ok"] and "my-normal-pw" not in json.dumps(out)
    assert "Zoho Mail refused the password" in out["explain"]
    assert "https://accounts.zoho.eu/home#security/app_password" in out["explain"]
    assert "acme" not in (addons.read_config("email").get("entries") or {})


def test_microsoft_is_told_plainly_it_will_likely_refuse(conf):
    get = web({"https://cloudflare-dns.com/": dns([(0, "example-com.mail.protection.outlook.com")])})
    got = conf.lookup("alex@example.com", get=get)
    assert "OAuth" in got["warning"]
    assert "OAuth" in conf.password_help({"imap_host": got["imap_host"]})


def test_a_lookup_that_finds_nothing_points_at_the_full_form(addon, core, conf, monkeypatch):
    monkeypatch.setattr(conf, "fetch", web({}))
    out = connect.connect(addon, "acme", {"company": "Acme", "address": "alex@example.com", "password": "x" * 16})
    assert not out["ok"] and "full form" in out["explain"]


def test_port_587_is_encrypted_with_starttls_before_the_login(addon, monkeypatch):
    sender = addons.provider(addon).sender
    log = []

    class Plain:
        def __init__(self, host, port, timeout=30):
            log.append(("connect", host, port))

        def starttls(self, context=None):
            log.append(("starttls",))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            log.append(("quit",))

        def login(self, user, password):
            log.append(("login", user))

        def close(self):
            pass
    monkeypatch.setattr(sender.smtplib, "SMTP", Plain)
    got = sender.smtp_login_test({"address": "alex@example.com", "smtp_host": "smtp.office365.com", "smtp_port": 587}, "pw")
    assert got["ok"] and log == [("connect", "smtp.office365.com", 587), ("starttls",), ("login", "alex@example.com"), ("quit",)]
