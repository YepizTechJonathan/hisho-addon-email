"""Proton Mail through Proton Mail Bridge: Proton lets other mail apps in only through Bridge (paid plans), a program
that serves IMAP and SMTP on 127.0.0.1 of the machine it runs on. Set up this mailbox > Proton Mail does it all:

1. Installs Bridge (Proton's official package, checksum pinned in addon.yaml, unpacked into Hisho's own folder: no
   root needed) on the machine the email add-on runs on (Core).
2. Signs in once through Bridge's own command line with the Proton address, password and 2FA code typed on the page
   (used once, never kept; Bridge keeps its session in this machine's keychain: the desktop's login keyring, or
   ``pass`` on a server).
3. Switches Bridge to SSL for IMAP and SMTP and reads its settings (``info``): the local address, ports and the Bridge
   password, which the mailbox entry gets (the Bridge password as a local secret).
4. Starts Bridge in the background (user unit hisho-proton-bridge.service, ``bridge --noninteractive``).
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import select
import shutil
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

HOME = Path(os.environ.get("HISHO_PROTON_BRIDGE_DIR") or "~/.local/share/hisho/proton-bridge").expanduser()
#: the Bridge release Hisho installs: Proton's official .deb (current_version_linux.json, 2026-10-13), its sha256
BRIDGE = {"version": "3.27.1", "url": "https://proton.me/download/bridge/protonmail-bridge_3.27.1-1_amd64.deb",
          "sha256": "d69eab5674335a41428bf77bde6a9f85667867e2083205625a710f6948e54d86"}
UNIT = "hisho-proton-bridge.service"


class BridgeError(RuntimeError):
    pass


# ── install ───────────────────────────────────────────────────────────────

def _ar_members(data: bytes) -> dict[str, bytes]:
    """The members of a .deb (an ``ar`` archive), without needing ``ar``."""
    if data[:8] != b"!<arch>\n":
        raise BridgeError("the downloaded Bridge package is not a .deb")
    out, i = {}, 8
    while i + 60 <= len(data):
        name = data[i:i + 16].decode().strip().rstrip("/")
        size = int(data[i + 48:i + 58].decode().strip())
        out[name] = data[i + 60:i + 60 + size]
        i += 60 + size + (size % 2)
    return out


def installed(version: str) -> Path | None:
    exe = HOME / version / "bridge"
    return exe if exe.is_file() and os.access(exe, os.X_OK) else None


def install(url: str, sha256: str, version: str, fetch: Callable[[str], bytes] | None = None) -> Path:
    """Proton's official .deb at ``url`` (checked against ``sha256``), its Bridge program unpacked into
    ~/.local/share/hisho/proton-bridge/<version>/. Nothing outside that folder is touched."""
    have = installed(version)
    if have:
        return have
    if not re.fullmatch(r"https://proton\.me/download/bridge/[\w.+-]+\.deb", url or ""):
        raise BridgeError("Bridge's package must come from proton.me/download/bridge")
    data = (fetch or (lambda u: urllib.request.urlopen(u, timeout=600).read()))(url)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise BridgeError("the downloaded Bridge package doesn't match its pinned checksum; nothing was installed")
    members = _ar_members(data)
    name = next((n for n in members if n.startswith("data.tar")), "")
    if not name:
        raise BridgeError("the Bridge package has no files in it")
    mode = {"data.tar.gz": "r:gz", "data.tar.xz": "r:xz", "data.tar.zst": None}.get(name, "r:*")
    if mode is None:
        raise BridgeError("this Bridge package is compressed with zstd, which this machine can't unpack here")
    dest = HOME / version
    tmp = HOME / f".{version}.new"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    prefix = "./usr/lib/protonmail/bridge/"
    with tarfile.open(fileobj=io.BytesIO(members[name]), mode=mode) as tar:
        for m in tar.getmembers():
            if not m.name.startswith(prefix) or not (m.isfile() or m.issym()):
                continue
            rel = m.name[len(prefix):]
            if not rel or ".." in Path(rel).parts or Path(rel).is_absolute():
                continue
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if m.isfile():
                with tar.extractfile(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o755 if m.mode & 0o111 else 0o644)
    if not (tmp / "bridge").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise BridgeError("the Bridge package has no bridge program in it")
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    current = HOME / "current"
    if current.is_symlink() or current.exists():
        current.unlink()
    current.symlink_to(dest.name)
    return dest / "bridge"


# ── the one-time sign-in, through Bridge's own command line ───────────────

class Pty:
    """Bridge's CLI on a pseudo-terminal: what it prints, and answers to its prompts."""

    def __init__(self, cmd: list[str], env: dict[str, str] | None = None) -> None:
        import pty
        self.pid, self.fd = pty.fork()
        if self.pid == 0:            # the child: Bridge itself
            try:
                os.execvpe(cmd[0], cmd, {**os.environ, **(env or {}), "TERM": "dumb"})
            finally:
                os._exit(127)
        self.seen = ""

    def expect(self, patterns: list[str], timeout: float = 60) -> tuple[int, str]:
        """Read until one of ``patterns`` (regexes) shows; returns its index and what was read since the last call."""
        end, buf = time.monotonic() + timeout, ""
        while time.monotonic() < end:
            for i, p in enumerate(patterns):
                m = re.search(p, buf)
                if m:
                    self.seen += buf
                    return i, buf
            r, _, _ = select.select([self.fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(self.fd, 4096).decode("utf-8", "replace")
                except OSError:
                    break
                if not chunk:
                    break
                buf += re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", chunk)
        self.seen += buf
        return -1, buf

    def send(self, text: str) -> None:
        os.write(self.fd, (text + "\n").encode())

    def close(self) -> None:
        try:
            self.send("exit")
            time.sleep(0.5)
        except OSError:
            pass
        try:
            os.kill(self.pid, 15)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


KEYCHAIN = r"(?i)no (supported )?(keychain|password manager)|secret.?service|could not .*keychain|pass.*not initiali[sz]ed"


def parse_info(text: str) -> dict[str, Any]:
    """The IMAP and SMTP settings Bridge's ``info`` prints."""
    out: dict[str, Any] = {}
    for block, key in (("IMAP Settings", "imap"), ("SMTP Settings", "smtp")):
        i = text.find(block)
        if i < 0:
            continue
        part = text[i:i + 600]
        host = re.search(r"Address:\s*(\S+)", part)
        port = re.search(rf"{key.upper()} port:\s*(\d+)", part)
        user = re.search(r"Username:\s*(\S+)", part)
        pw = re.search(r"Password:\s*(\S+)", part)
        sec = re.search(r"Security:\s*(\S+)", part)
        if host and port:
            out[key] = {"host": host.group(1), "port": int(port.group(1)), "user": user.group(1) if user else "",
                        "password": pw.group(1) if pw else "", "security": sec.group(1).upper() if sec else ""}
    return out


def sign_in(exe: Path | str, address: str, password: str, code: str = "", mailbox_password: str = "",
            spawn: Callable[[list[str]], Any] | None = None) -> dict[str, Any]:
    """Sign in to Proton once through Bridge's CLI, switch IMAP and SMTP to SSL, and read the settings a mail app
    uses. The password and code are typed into Bridge only; the result never contains them."""
    cli = (spawn or (lambda cmd: Pty(cmd)))([str(exe), "--cli"])
    try:
        i, out = cli.expect([r"interactive shell|>>>", KEYCHAIN], 120)
        if i != 0:
            raise BridgeError(_keychain_words() if i == 1 else f"Bridge didn't start: {out.strip()[-200:]}")
        if re.search(KEYCHAIN, out):                     # it may say so right under its welcome line
            raise BridgeError(_keychain_words())
        cli.send("login")
        i, out = cli.expect([r"Username", KEYCHAIN], 30)
        if i == 1 or re.search(KEYCHAIN, cli.seen):
            raise BridgeError(_keychain_words())
        if i != 0:
            raise BridgeError("Bridge didn't ask for the Proton address")
        cli.send(address)
        if cli.expect([r"Password"], 30)[0] != 0:
            raise BridgeError("Bridge didn't ask for the password")
        cli.send(password)
        while True:
            i, out = cli.expect([r"Two factor code", r"Mailbox password", r"was added successfully",
                                 r"Cannot login:?[^\n]*", KEYCHAIN], 120)
            if i == 0:
                if not code:
                    raise BridgeError("Proton asks for the 2FA code from your authenticator app: type it and try again")
                cli.send(code)
            elif i == 1:
                if not mailbox_password:
                    raise BridgeError("this Proton account uses a second (mailbox) password: type it and try again")
                cli.send(mailbox_password)
            elif i == 2:
                break
            elif i == 3:
                why = re.search(r"Cannot login:?\s*([^\n]*)", out)
                raise BridgeError("Proton refused the sign-in: " + ((why.group(1).strip() if why else "") or "check "
                                  "the address, password and 2FA code"))
            elif i == 4:
                raise BridgeError(_keychain_words())
            else:
                raise BridgeError("Bridge didn't answer the sign-in in time")
        settings = _info(cli)
        for key, cmd in (("imap", "change imap-security"), ("smtp", "change smtp-security")):
            if settings.get(key, {}).get("security") != "SSL":     # the command toggles: only when it isn't SSL yet
                cli.send(cmd)
                if cli.expect([r"(?i)are you sure"], 30)[0] == 0:
                    cli.send("yes")
                    cli.expect([r"(?i)\n"], 5)
        settings = _info(cli)
        if not settings.get("imap") or not settings.get("smtp"):
            raise BridgeError("Bridge signed in but didn't show its mail settings")
        return settings
    finally:
        cli.close()


def _info(cli: Any) -> dict[str, Any]:
    cli.send("info")
    _, out = cli.expect([r"SMTP Settings[\s\S]*Security:\s*\S+"], 30)
    return parse_info(out)


def _keychain_words() -> str:
    return ("Proton Bridge needs a keychain to keep its sign-in on this machine: on a desktop, the login keyring "
            "(already there on a Souko); on a server, `pass` (install it, then `gpg --quick-gen-key` and `pass init` "
            "with that key) and try again.")


# ── running in the background ─────────────────────────────────────────────

def unit_text(exe: Path | str) -> str:
    return (f"[Unit]\nDescription=Proton Mail Bridge for Hisho's email add-on (IMAP/SMTP on 127.0.0.1)\n\n"
            f"[Service]\nExecStart={exe} --noninteractive\nRestart=on-failure\nRestartSec=10\n\n"
            f"[Install]\nWantedBy=default.target\n")


def start(exe: Path | str, run: Callable[..., Any] = subprocess.run) -> None:
    unit = Path("~/.config/systemd/user").expanduser() / UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(unit_text(exe))
    for cmd in (["daemon-reload"], ["enable", "--now", UNIT], ["restart", UNIT]):
        run(["systemctl", "--user", *cmd], capture_output=True, text=True, timeout=60)


def wait_port(port: int, host: str = "127.0.0.1", timeout: float = 60) -> bool:
    """Bridge listening again after its restart (Core tests the mailbox right after setting it up)."""
    import socket
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def stop(run: Callable[..., Any] = subprocess.run) -> None:
    """Only one Bridge may run: the background one stops while the command line signs in."""
    run(["systemctl", "--user", "stop", UNIT], capture_output=True, text=True, timeout=60)
