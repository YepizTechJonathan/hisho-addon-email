"""Finding a mailbox's servers from its address alone (the "Set up this mailbox" button, addon.yaml connect:).

Where it looks, in order, the way Thunderbird does:

1. Mozilla's ISPDB: ``https://autoconfig.thunderbird.net/v1.1/<domain>`` (the big providers and many ISPs).
2. The domain's own autoconfig: ``https://autoconfig.<domain>/mail/config-v1.1.xml`` (a host that publishes one).
3. The domain's MX records: a mailbox on Google Workspace, Microsoft 365, Zoho (by region), iCloud, Yahoo or
   Fastmail is known by where its mail is delivered; anything else is looked up in the ISPDB by the MX's domain.

Only IMAP over TLS (port 993) is taken, as the add-on reads only that way; SMTP over TLS (465) or STARTTLS (587).
Every network call goes through ``fetch(url) -> text`` (and MX through ``mx_hosts``), so tests stand in for them.
Nothing here signs in: the provider's Test does, once, with the app password typed.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable

UA = "Hisho email add-on (mail server lookup)"

#: what Hisho knows about the big hosted providers. ``hosts``: IMAP host names that mean this provider (from any
#: source); ``mx``: the end of an MX host name that means it. ``app_password``: where the owner makes one.
PROVIDERS: dict[str, dict[str, Any]] = {
    "google": {
        "name": "Google (Gmail / Google Workspace)",
        "imap": ("imap.gmail.com", 993), "smtp": ("smtp.gmail.com", 465),
        "sent_folder": "[Gmail]/Sent Mail", "trash_folder": "[Gmail]/Trash", "folders": "",
        "hosts": ("gmail.com", "googlemail.com"), "mx": ("google.com", "googlemail.com"),
        "app_password": "https://myaccount.google.com/apppasswords",
        "steps": "Google Account > Security > 2-Step Verification must be on; then App passwords, name it Hisho, "
                 "Create, and copy the 16 letters (a Workspace admin may have to allow app passwords first)",
    },
    "microsoft": {
        "name": "Microsoft (Outlook.com / Microsoft 365)",
        "imap": ("outlook.office365.com", 993), "smtp": ("smtp.office365.com", 587),
        "sent_folder": "Sent Items", "trash_folder": "Deleted Items", "folders": "",
        "hosts": ("office365.com", "outlook.com", "hotmail.com", "live.com"),
        "mx": ("mail.protection.outlook.com", "olc.protection.outlook.com", "outlook.com", "hotmail.com"),
        "app_password": "https://account.microsoft.com/security",
        "steps": "Microsoft account > Security > Advanced security options > App passwords",
        "warning": "Microsoft has stopped letting mail apps sign in with a password (Outlook.com since September "
                   "2024; Microsoft 365 work mailboxes earlier): it wants a Microsoft sign-in (OAuth), which this "
                   "add-on doesn't do yet, so the login will most likely be refused.",
    },
    "zoho": {
        "name": "Zoho Mail",
        "imap": ("imap.zoho.com", 993), "smtp": ("smtp.zoho.com", 465),
        "sent_folder": "Sent", "trash_folder": "Trash",          # folders: Zoho's smart filters, the add-on's default
        "hosts": ("zoho.com", "zoho.eu", "zoho.in", "zoho.com.au", "zoho.jp", "zoho.sa", "zohocloud.ca"),
        "mx": ("zoho.com", "zoho.eu", "zoho.in", "zoho.com.au", "zoho.jp", "zoho.sa", "zohocloud.ca", "zohomail.com"),
        "app_password": "https://accounts.zoho.com/home#security/app_password",
        "steps": "Zoho Accounts > Security > App Passwords > Generate New Password, name it Hisho",
    },
    "icloud": {
        "name": "iCloud Mail",
        "imap": ("imap.mail.me.com", 993), "smtp": ("smtp.mail.me.com", 587),
        "sent_folder": "Sent Messages", "trash_folder": "Deleted Messages", "folders": "",
        "hosts": ("mail.me.com",), "mx": ("mail.icloud.com",),
        "app_password": "https://account.apple.com",
        "steps": "Apple Account > Sign-In and Security > App-Specific Passwords > +, name it Hisho",
    },
    "yahoo": {
        "name": "Yahoo Mail",
        "imap": ("imap.mail.yahoo.com", 993), "smtp": ("smtp.mail.yahoo.com", 465),
        "sent_folder": "Sent", "trash_folder": "Trash", "folders": "",
        "hosts": ("mail.yahoo.com",), "mx": ("yahoodns.net",),
        "app_password": "https://login.yahoo.com/account/security",
        "steps": "Yahoo Account Security > Generate app password (or Manage app passwords), name it Hisho",
    },
    "fastmail": {
        "name": "Fastmail",
        "imap": ("imap.fastmail.com", 993), "smtp": ("smtp.fastmail.com", 465),
        "sent_folder": "Sent", "trash_folder": "Trash", "folders": "",
        "hosts": ("fastmail.com", "messagingengine.com"), "mx": ("messagingengine.com", "fastmail.com"),
        "app_password": "https://app.fastmail.com/settings/security",
        "steps": "Settings > Privacy & Security > Manage app passwords and access > New app password, "
                 "access IMAP and SMTP",
    },
}

#: Zoho serves each region from its own domain: the MX says which (mx.zoho.eu = the EU data centre).
ZOHO_REGIONS = ("zoho.com.au", "zohocloud.ca", "zoho.eu", "zoho.in", "zoho.jp", "zoho.sa", "zoho.com")


class NotFound(RuntimeError):
    pass


def fetch(url: str, timeout: float = 8) -> str:
    """One GET; "" when there is nothing there (404, no such host, not XML...)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml, application/dns-json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(262144).decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def mx_hosts(domain: str, get: Callable[[str], str] | None = None) -> list[str]:
    """The domain's MX hosts, most preferred first, over DNS-over-HTTPS (Cloudflare, then Google)."""
    get = get or fetch
    for base in ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"):
        raw = get(f"{base}?name={urllib.parse.quote(domain)}&type=MX")
        try:
            answers = json.loads(raw).get("Answer") or []
        except (ValueError, AttributeError):
            continue
        rows = []
        for a in answers:
            if a.get("type") == 15:
                parts = str(a.get("data") or "").split()
                if len(parts) == 2 and parts[0].isdigit():
                    rows.append((int(parts[0]), parts[1].rstrip(".").lower()))
        if rows:
            return [h for _, h in sorted(rows)]
    return []


def _ends(host: str, suffixes: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in suffixes)


def provider_for_host(imap_host: str) -> str:
    """Which known provider an IMAP host belongs to ("" when none)."""
    for key, p in PROVIDERS.items():
        if _ends(imap_host, p["hosts"]):
            return key
    return ""


def zoho_region(host: str) -> str:
    """The Zoho domain an MX or IMAP host is in: zoho.com, zoho.eu, zoho.in, zoho.com.au, zohocloud.ca..."""
    for r in ZOHO_REGIONS:
        if _ends(host, (r,)):
            return r
    return "zoho.com"


def app_password_page(key: str, host: str = "") -> str:
    """Where the owner makes an app password for this provider (Zoho: the region's own accounts site)."""
    if key == "zoho":
        return f"https://accounts.{zoho_region(host)}/home#security/app_password"
    return str((PROVIDERS.get(key) or {}).get("app_password") or "")


def parse_config(xml: str, address: str) -> dict[str, Any]:
    """The IMAP (TLS) and SMTP servers from a Thunderbird autoconfig file; {} when it has no usable pair."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    local, _, domain = address.partition("@")

    def fill(text: str) -> str:
        return (text.replace("%EMAILADDRESS%", address).replace("%EMAILLOCALPART%", local)
                .replace("%EMAILDOMAIN%", domain).strip())
    imap = smtp = None
    for s in root.iter("incomingServer"):
        if s.get("type") == "imap" and (s.findtext("socketType") or "").upper() == "SSL" and imap is None:
            imap = (fill(s.findtext("hostname") or ""), int(s.findtext("port") or 993), fill(s.findtext("username") or ""))
    for s in root.iter("outgoingServer"):
        sock = (s.findtext("socketType") or "").upper()
        if s.get("type") == "smtp" and sock in ("SSL", "STARTTLS"):
            cand = (fill(s.findtext("hostname") or ""), int(s.findtext("port") or (465 if sock == "SSL" else 587)))
            if smtp is None or (sock == "SSL" and smtp[1] != 465):   # implicit TLS first, STARTTLS when that's all
                smtp = cand
    if not imap or not imap[0] or not smtp or not smtp[0]:
        return {}
    out: dict[str, Any] = {"imap_host": imap[0], "imap_port": imap[1], "smtp_host": smtp[0], "smtp_port": smtp[1]}
    if imap[2] and imap[2] != address:
        out["login_hint"] = imap[2]
    return out


def _known(key: str, mx: str = "") -> dict[str, Any]:
    p = PROVIDERS[key]
    out = {"imap_host": p["imap"][0], "imap_port": p["imap"][1], "smtp_host": p["smtp"][0], "smtp_port": p["smtp"][1]}
    if key == "zoho":
        region = zoho_region(mx)
        if region == "zohocloud.ca":
            out.update(imap_host="imap.zohocloud.ca", smtp_host="smtp.zohocloud.ca")
        else:
            out.update(imap_host=f"imap.{region}", smtp_host=f"smtp.{region}")
    return out


def _base_domain(host: str) -> str:
    parts = host.lower().rstrip(".").split(".")
    keep = 3 if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("com", "co", "net", "org") else 2
    return ".".join(parts[-keep:])


def lookup(address: str, get: Callable[[str], str] | None = None,
           mx: Callable[[str], list[str]] | None = None) -> dict[str, Any]:
    """The mailbox's servers: ``{"imap_host", "imap_port", "smtp_host", "smtp_port", "provider", "source", ...}``
    plus the provider's Sent/Trash folder names when it is a known one. Raises NotFound when nothing is found."""
    address = address.strip()
    if not re.fullmatch(r"[^@\s]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", address):
        raise NotFound("that isn't an email address (like alex@example.com)")
    get = get or fetch
    domain = address.split("@", 1)[1].lower()
    found, source, mx_list = {}, "", None
    for url, name in ((f"https://autoconfig.thunderbird.net/v1.1/{domain}", "Mozilla's ISPDB"),
                      (f"https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress={urllib.parse.quote(address)}",
                       f"{domain}'s own settings")):
        found = parse_config(get(url), address)
        if found:
            source = name
            break
    key = provider_for_host(found.get("imap_host", "")) if found else ""
    if not found or not key:
        mx_list = (mx or (lambda d: mx_hosts(d, get)))(domain)
        top = mx_list[0] if mx_list else ""
        by_mx = next((k for k, p in PROVIDERS.items() if top and _ends(top, p["mx"])), "")
        if by_mx and not found:
            found, key, source = _known(by_mx, top), by_mx, f"its mail servers ({top})"
        elif by_mx and not key:
            key = by_mx
        elif not found and top:
            found = parse_config(get(f"https://autoconfig.thunderbird.net/v1.1/{_base_domain(top)}"), address)
            source = f"Mozilla's ISPDB for {_base_domain(top)}" if found else ""
            key = provider_for_host(found.get("imap_host", "")) if found else ""
    if not found:
        raise NotFound(f"couldn't find the mail servers for {domain}")
    out = {**found, "provider": key, "source": source}
    if key:
        p = PROVIDERS[key]
        out.update({k: p[k] for k in ("sent_folder", "trash_folder", "folders") if k in p})
        out["name"] = p["name"]
        out["app_password"] = app_password_page(key, out["imap_host"])   # Zoho: its host names the region
        out["steps"] = p["steps"]
        if p.get("warning"):
            out["warning"] = p["warning"]
    return out


def password_help(entry: dict[str, Any]) -> str:
    """Where to make an app password for this mailbox, in words: the provider's name and its exact page."""
    host = str(entry.get("imap_host") or "imap.zoho.com")
    key = provider_for_host(host)
    if not key:
        return ("Make an app password in your mail provider's security settings (it's a separate password just for "
                "Hisho, not your normal one) and paste it.")
    p = PROVIDERS[key]
    text = (f"{p['name']} needs an app password, not your normal one: make one at {app_password_page(key, host)} "
            f"({p['steps']}) and paste it.")
    return text + (" " + p["warning"] if p.get("warning") else "")
