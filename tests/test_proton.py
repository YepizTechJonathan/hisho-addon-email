"""Proton Mail through Proton Mail Bridge (proton.py): install from Proton's official package (checksum pinned), the
one-time sign-in through Bridge's own command line (a stand-in program plays Bridge on a real pseudo-terminal), and
the mailbox entry it fills. No Proton account or network is used."""
import hashlib
import importlib.util
import io
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("proton_t", HERE / "proton.py")
proton = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proton)

FAKE = r'''#!{py}
"""Plays Proton Mail Bridge's --cli: the prompts and the info output of the real one (internal/frontend/cli)."""
import os, sys
mode = os.environ.get("FAKE_MODE", "ok")
state = {{"imap": "STARTTLS", "smtp": "STARTTLS", "in": False}}
print("Welcome to Proton Mail Bridge interactive shell", flush=True)
if mode == "keychain":
    print("Bridge cannot access the keychain: no supported password manager (secret-service or pass)", flush=True)
    sys.exit(1)
def ask(q):
    sys.stdout.write(q + ": "); sys.stdout.flush(); return sys.stdin.readline().strip()
def info():
    print("Configuration for alex@example.com")
    for k, port in (("IMAP", 1143), ("SMTP", 1025)):
        print(f"{{k}} Settings\nAddress:   127.0.0.1\n{{k}} port: {{port}}\nUsername:  alex@example.com\n"
              f"Password:  BriDgePw123\nSecurity:  {{state[k.lower()]}}", flush=True)
for line in sys.stdin:
    cmd = line.strip()
    if cmd == "login":
        ask("Username"); pw = ask("Password")
        if pw != "right":
            print("Cannot login: Incorrect login credentials.", flush=True); continue
        if ask("Two factor code") != "123456":
            print("Cannot login: Incorrect 2FA code", flush=True); continue
        print("Authenticating ... \nAccount alex@example.com was added successfully.", flush=True)
    elif cmd == "info":
        info()
    elif cmd in ("change imap-security", "change smtp-security"):
        k = cmd.split()[1][:4]
        new = "STARTTLS" if state[k] == "SSL" else "SSL"
        if ask(f'Are you sure you want to change {{k.upper()}} setting to "{{new}}"? yes/no') == "yes":
            state[k] = new
            print("ok", flush=True)
    elif cmd == "exit":
        break
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    exe = tmp_path / "bridge"
    exe.write_text(FAKE.format(py=sys.executable))
    exe.chmod(0o755)
    return exe


def test_sign_in_answers_bridges_prompts_switches_to_ssl_and_reads_its_settings(fake):
    got = proton.sign_in(fake, "alex@example.com", "right", "123456")
    assert got["imap"] == {"host": "127.0.0.1", "port": 1143, "user": "alex@example.com", "password": "BriDgePw123",
                           "security": "SSL"}
    assert got["smtp"]["port"] == 1025 and got["smtp"]["security"] == "SSL"


@pytest.mark.parametrize("pw,code,words", [("wrong", "123456", "refused the sign-in"),
                                           ("right", "", "2FA code"),
                                           ("right", "000000", "refused the sign-in")])
def test_a_refused_sign_in_says_why_and_never_repeats_the_password(fake, pw, code, words):
    with pytest.raises(proton.BridgeError, match=words) as e:
        proton.sign_in(fake, "alex@example.com", pw, code)
    assert pw not in str(e.value) or pw == "right"


def test_no_keychain_says_what_to_install(fake, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "keychain")
    with pytest.raises(proton.BridgeError, match="keychain"):
        proton.sign_in(fake, "alex@example.com", "right", "123456")


def _deb(files: dict[str, bytes]) -> bytes:
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), 0o755
            tar.addfile(info, io.BytesIO(body))
    out = b"!<arch>\n"
    for name, body in (("debian-binary", b"2.0\n"), ("data.tar.gz", data.getvalue())):
        hdr = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(body):<10}`\n".encode()
        out += hdr + body + (b"\n" if len(body) % 2 else b"")
    return out


def test_install_takes_only_the_bridge_program_from_the_checked_package(tmp_path, monkeypatch):
    monkeypatch.setattr(proton, "HOME", tmp_path / "pb")
    deb = _deb({"./usr/lib/protonmail/bridge/bridge": b"#!/bin/sh\n", "./etc/evil": b"x",
                "./usr/lib/protonmail/bridge/../../../../escape": b"x"})
    url = "https://proton.me/download/bridge/protonmail-bridge_9.9.9-1_amd64.deb"
    with pytest.raises(proton.BridgeError, match="checksum"):
        proton.install(url, "0" * 64, "9.9.9", fetch=lambda u: deb)
    exe = proton.install(url, hashlib.sha256(deb).hexdigest(), "9.9.9", fetch=lambda u: deb)
    assert exe == tmp_path / "pb" / "9.9.9" / "bridge" and exe.stat().st_mode & 0o111
    assert not (tmp_path / "pb" / "9.9.9" / "etc").exists() and not (tmp_path / "escape").exists()
    with pytest.raises(proton.BridgeError, match="proton.me"):
        proton.install("https://example.com/x.deb", "0" * 64, "1", fetch=lambda u: deb)


def test_set_up_proton_fills_the_entry_with_bridges_settings_and_restarts_it(monkeypatch):
    spec2 = importlib.util.spec_from_file_location("email_provider_t", HERE / "provider.py")
    mod = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod)
    calls = []

    class FakeBridge:
        BRIDGE = proton.BRIDGE
        BridgeError = proton.BridgeError
        install = staticmethod(lambda url, sha, ver: calls.append("install") or Path("/x/bridge"))
        stop = staticmethod(lambda: calls.append("stop"))
        start = staticmethod(lambda exe: calls.append("start"))
        sign_in = staticmethod(lambda exe, a, p, c, m: {
            "imap": {"host": "127.0.0.1", "port": 1143, "user": a, "password": "BriDgePw123", "security": "SSL"},
            "smtp": {"host": "127.0.0.1", "port": 1025, "user": a, "password": "BriDgePw123", "security": "SSL"}})
    out = mod.connect_proton("alex@example.com", {"proton_password": "right", "proton_code": "123456"}, bridge=FakeBridge)
    assert out["ok"] and calls == ["install", "stop", "start"]
    assert out["entry"]["password"] == "BriDgePw123" and out["entry"]["imap_port"] == 1143
    assert "right" not in out["message"]
    import ssl
    assert mod.tls_context("127.0.0.1").verify_mode == ssl.CERT_NONE
    assert mod.tls_context("imap.example.com").verify_mode == ssl.CERT_REQUIRED
