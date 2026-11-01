# Povolení z bubliny: klient hooku (bez daemonu, s falešným serverem), server v daemonu (Qt),
# widget bubliny a volitelná položka v install.py.
import json, os, socket, statistics, subprocess, sys, tempfile, threading, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from familiar import bublina, install, povoleni, povoleni_klient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = """import sys
sys.path.insert(0, {root!r})
sys.argv = ["familiar-emit", "claude-code", "--povoleni"] + {extra!r}
from familiar import emit
emit.main({ppid!r})
"""
PROMPT = "TAJNY TEXT PROMPTU"
HOOK = {"session_id": "s1", "transcript_path": "/x.jsonl", "cwd": "/w", "permission_mode": "default",
        "hook_event_name": "PermissionRequest", "tool_name": "Bash", "prompt": PROMPT,
        "tool_input": {"command": "rm -rf node_modules\n  && echo " + "x" * 300, "description": PROMPT},
        "permission_suggestions": [
            {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "rm -rf node_modules"}],
             "behavior": "allow", "destination": "localSettings"},
            {"type": "setMode", "mode": "bypassPermissions", "destination": "session"}]}


@pytest.fixture
def runtime(monkeypatch):
    d = tempfile.mkdtemp(prefix="fam", dir="/tmp")      # krátká cesta kvůli Unix socketu
    monkeypatch.setenv("XDG_RUNTIME_DIR", d)
    yield d
    for name in os.listdir(d):
        os.unlink(os.path.join(d, name))
    os.rmdir(d)


def client(runtime, hook=HOOK, extra=(), ppid="4242", wait=True):
    cmd = [sys.executable, "-I", "-S", "-c", CLIENT.format(root=ROOT, extra=list(extra), ppid=ppid)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=dict(os.environ, XDG_RUNTIME_DIR=runtime))
    data = hook if isinstance(hook, bytes) else json.dumps(hook).encode()
    if not wait:
        p.stdin.write(data)
        p.stdin.close()
        return p
    out, err = p.communicate(data, timeout=10)
    return p.returncode, out, err


class FakeServer:
    """Stream socket daemonu v Pythonu: přijme požadavek, odpoví podle reply (None = zavřít bez
    odpovědi, "visi" = neodpovídat)."""

    def __init__(self, runtime, reply):
        self.path = os.path.join(runtime, povoleni.SOCK)
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.bind(self.path)
        self.s.listen(1)
        self.s.settimeout(10)
        self.reply, self.request = reply, None
        self.t = threading.Thread(target=self.serve, daemon=True)
        self.t.start()

    def serve(self):
        c, _ = self.s.accept()
        with c:
            data = b""
            while b"\n" not in data:
                got = c.recv(65536)
                if not got:
                    return
                data += got
            self.request = json.loads(data)
            if self.reply == "visi":
                time.sleep(2)
            elif self.reply is not None:
                c.sendall(self.reply)

    def close(self):
        self.t.join(5)
        self.s.close()


# --- klient ---

def test_client_without_daemon_is_silent_and_fast(runtime):
    for _ in range(2):      # zahřátí (page cache)
        client(runtime)
    times = []
    for _ in range(7):
        t = time.perf_counter()
        rc, out, err = client(runtime)
        times.append(time.perf_counter() - t)
        assert (rc, out, err) == (0, b"", b"")
    assert statistics.median(times) < 0.05, times


def test_client_stale_socket_file_is_silent(runtime):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(os.path.join(runtime, povoleni.SOCK))       # soubor existuje, nikdo neposlouchá
    s.close()
    assert client(runtime) == (0, b"", b"")


@pytest.mark.parametrize("reply,decision", [
    ("allow", {"behavior": "allow"}),
    ("deny", {"behavior": "deny", "message": povoleni_klient.DUVOD}),
    ("allow_always", {"behavior": "allow", "updatedPermissions": [HOOK["permission_suggestions"][0]]}),
])
def test_client_prints_decision_only_from_server(runtime, reply, decision):
    srv = FakeServer(runtime, json.dumps({"rozhodnuti": reply}).encode() + b"\n")
    rc, out, err = client(runtime)
    srv.close()
    assert (rc, err) == (0, b"")
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}
    req = srv.request
    assert req["session"] == "s1" and req["pid"] == 4242 and req["agent"] is False
    assert req["shrnuti"]["nastroj"] == "Bash"
    assert req["shrnuti"]["co"] == "rm -rf node_modules\n&& echo " + "x" * 300     # celý, řádky zůstanou
    assert req["shrnuti"]["zkraceno"] is False and req["shrnuti"]["dotaz"] is False
    assert req["shrnuti"]["vzdy"] == "Bash(rm -rf node_modules) [projekt]"     # bypassPermissions se nenabízí
    assert req["bez_terminalu"] is False
    assert PROMPT not in json.dumps(req)


@pytest.mark.parametrize("reply", [None, b'{"rozhodnuti": "ano"}\n', b"nesmysl\n", b'{"rozhodnuti": "allow"}'])
def test_client_without_valid_answer_is_silent(runtime, reply):
    srv = FakeServer(runtime, reply)
    assert client(runtime) == (0, b"", b"")
    srv.close()


def test_client_timeout_is_silent(runtime):
    srv = FakeServer(runtime, "visi")
    t = time.perf_counter()
    assert client(runtime, extra=["--cekat=0.3"]) == (0, b"", b"")
    assert time.perf_counter() - t < 1.5
    srv.close()


@pytest.mark.parametrize("hook", [dict(HOOK, tool_name="AskUserQuestion"), b"{ rozbit", b"", b"[1, 2]"])
def test_client_skips_unsupported_and_invalid_input(runtime, hook):
    srv = FakeServer(runtime, json.dumps({"rozhodnuti": "allow"}).encode() + b"\n")
    assert client(runtime, hook=hook) == (0, b"", b"")
    assert srv.request is None
    srv.s.close()


def test_summary_is_short_and_safe(monkeypatch):
    monkeypatch.setenv("HOME", "/home/u")
    co = povoleni_klient.co
    assert co("Write", {"file_path": "/home/u/p/a.py", "content": PROMPT}) == "~/p/a.py"
    assert co("WebFetch", {"url": "https://x.cz/a?token=1#b", "prompt": PROMPT}) == "https://x.cz/a?token=1#b"
    assert co("mcp__x__y", {"text": PROMPT}) == ""
    assert co("Read", {"file_path": "/" + "d/" * 300 + "f.py"}).endswith("/d/f.py")
    assert povoleni_klient.vzdy_popis([{"type": "addDirectories", "directories": ["/home/u/x"],
                                        "destination": "session"}]) == "složky ~/x [session]"
    assert povoleni_klient.vzdy_popis([{"type": "addRules", "behavior": "deny", "rules": []}]) is None
    req = povoleni_klient.pozadavek(dict(HOOK, agent_id="a1"), 7)
    assert req["agent"] is True and PROMPT not in json.dumps(req)


def test_summary_flags_what_bubble_cannot_show(monkeypatch):
    monkeypatch.setenv("HOME", "/home/u")
    sv = povoleni_klient.shrnuti_vstupu
    dlouhy = "echo " + "a" * 600
    text, zkraceno, dotaz = sv("Bash", {"command": dlouhy})
    assert zkraceno and len(text) == povoleni_klient.CO_ZNAKU and text.endswith("…")
    assert sv("Bash", {"command": "ls\n\n  -la   x"}) == ("ls\n-la x", False, False)
    assert sv("WebFetch", {"url": "https://x.cz/a?token=1"}) == ("https://x.cz/a?token=1", False, True)
    assert sv("WebFetch", {"url": "https://x.cz/a#b"}) == ("https://x.cz/a#b", False, False)
    assert sv("mcp__x__y", {"text": PROMPT}) == ("", True, False)       # neumíme shrnout: jen zamítnout
    assert sv("Read", {"file_path": "/" + "d/" * 300 + "f.py"})[1] is True
    assert sv("WebSearch", {"query": "počasí brno"}) == ("počasí brno", False, False)
    hook = dict(HOOK, tool_input={"command": dlouhy})
    assert povoleni_klient.vystup("allow", hook) is None              # klient nepovolí ani při chybě daemonu
    assert povoleni_klient.vystup("allow_always", hook) is None
    assert json.loads(povoleni_klient.vystup("deny", hook))["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_navrhy_allowlist():
    nav = povoleni_klient._navrhy
    pravidlo = {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "npm test:*"}],
                "behavior": "allow", "destination": "localSettings"}
    ok = [pravidlo, dict(pravidlo, destination="session"), dict(pravidlo, destination="projectSettings"),
          {"type": "addDirectories", "directories": ["/tmp/x"], "destination": "session"},
          {"type": "setMode", "mode": "acceptEdits", "destination": "session"}]
    spatne = [dict(pravidlo, destination="userSettings"), dict(pravidlo, destination="cliArg"),
              dict(pravidlo, behavior="deny"), dict(pravidlo, behavior="ask"), dict(pravidlo, rules=[]),
              dict(pravidlo, rules=[{"ruleContent": "x"}]), dict(pravidlo, destination=None),
              {"type": "addDirectories", "directories": ["/"], "destination": "localSettings"},
              {"type": "setMode", "mode": "bypassPermissions", "destination": "session"},
              {"type": "setMode", "mode": "acceptEdits", "destination": "localSettings"},
              {"type": "setMode", "mode": "plan", "destination": "session"},
              {"type": "replaceRules", "rules": [{"toolName": "Bash"}], "behavior": "allow",
               "destination": "session"},
              {"type": "removeRules", "rules": [{"toolName": "Bash"}], "behavior": "deny",
               "destination": "session"}, "nesmysl"]
    assert nav(ok + spatne) == ok
    assert povoleni_klient.vzdy_popis(ok) == ("Bash(npm test:*) [projekt]; Bash(npm test:*) [session]; "
                                              "Bash(npm test:*) [projekt, sdílené]; složky /tmp/x [session]; "
                                              "režim acceptEdits [session]")
    assert povoleni_klient.vzdy_popis(spatne) is None
    mnoho = [dict(pravidlo, rules=[{"toolName": "Bash", "ruleContent": "x" * 400}])]
    assert povoleni_klient.vzdy_popis(mnoho) is None                 # popis by se nevešel: bez „Vždy“
    hook = dict(HOOK, permission_suggestions=mnoho)
    out = json.loads(povoleni_klient.vystup("allow_always", hook))
    assert out["hookSpecificOutput"]["decision"] == {"behavior": "allow"}


def test_bez_terminalu():
    assert povoleni_klient.bez_terminalu(2 ** 22 + 12345) is False   # neexistuje: interaktivní
    p = subprocess.Popen(["sleep", "5"], stdin=subprocess.PIPE)       # jako SDK: stdin roura
    try:
        assert povoleni_klient.bez_terminalu(p.pid) is True
    finally:
        p.kill()
        p.wait()


def test_bez_terminalu_podle_prikazu(monkeypatch):
    import posix, types
    fake = types.SimpleNamespace(**{k: getattr(posix, k) for k in ("open", "read", "close", "O_RDONLY")},
                                 readlink=lambda path: "/dev/pts/3")
    monkeypatch.setattr(povoleni_klient, "posix", fake)
    for args, vysledek in ((["-p"], True), (["--print"], True), (["--model", "x"], False)):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"] + args)
        try:
            deadline = time.monotonic() + 5
            while b"time.sleep" not in open(f"/proc/{p.pid}/cmdline", "rb").read() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert povoleni_klient.bez_terminalu(p.pid) is vysledek, args
        finally:
            p.kill()
            p.wait()


# --- server v daemonu ---

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    return cond()


@pytest.fixture
def server(app, runtime):
    srv = povoleni.Povoleni(timeout_s=30, timeout_agent_s=0.3)
    assert srv.start()
    assert os.stat(srv.path).st_mode & 0o777 == 0o600
    srv.got, srv.cancelled = [], []
    srv.pozadavek.connect(lambda *a: srv.got.append(a))
    srv.zruseno.connect(srv.cancelled.append)
    yield srv
    srv.close()


@pytest.mark.parametrize("reply", ["allow", "deny", "allow_always"])
def test_server_answer_reaches_client(app, runtime, server, reply):
    p = client(runtime, wait=False)
    assert wait_for(app, lambda: server.got)
    id_, session, pid, info = server.got[0]
    assert (session, pid, info["nastroj"], info["agent"]) == ("s1", 4242, "Bash", False)
    assert info["vzdy"] == "Bash(rm -rf node_modules) [projekt]" and info["jen_terminal"] is False
    assert info["co"] == "rm -rf node_modules\n&& echo " + "x" * 300
    assert server.odpovez(id_, reply)
    assert not server.odpovez(id_, reply)      # podruhé už neplatí
    out = p.stdout.read()
    assert p.wait(5) == 0
    assert json.loads(out)["hookSpecificOutput"]["decision"]["behavior"] == reply.split("_")[0]
    assert server.cancelled == [] and server.cekajici == {}


def test_server_client_gone_cancels(app, runtime, server):
    p = client(runtime, wait=False)
    assert wait_for(app, lambda: server.got)
    p.kill()
    p.wait(5)
    assert wait_for(app, lambda: server.cancelled == [server.got[0][0]])
    assert server.cekajici == {} and not server.odpovez(server.got[0][0], "allow")


def test_server_timeout_for_subagent_and_zrus_pid(app, runtime, server):
    p = client(runtime, hook=dict(HOOK, agent_id="a1"), wait=False)
    assert wait_for(app, lambda: server.cancelled)          # timeout_agent_s 0.3 s
    assert p.stdout.read() == b"" and p.wait(5) == 0
    p = client(runtime, ppid="777", wait=False)
    assert wait_for(app, lambda: len(server.got) == 2)
    assert server.zrus_pid(777) == 1 and server.cancelled[-1] == server.got[1][0]
    assert p.stdout.read() == b"" and p.wait(5) == 0


def test_server_long_command_only_deny(app, runtime, server):
    p = client(runtime, hook=dict(HOOK, tool_input={"command": "echo " + "a" * 600}), wait=False)
    assert wait_for(app, lambda: server.got)
    id_, _, _, info = server.got[0]
    assert info["jen_terminal"] is True and info["vzdy"]
    assert not server.odpovez(id_, "allow") and not server.odpovez(id_, "allow_always")
    assert server.odpovez(id_, "deny")
    out = p.stdout.read()
    assert p.wait(5) == 0 and json.loads(out)["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_server_shrnuti_sanitizes():
    sh = povoleni.shrnuti
    base = {"v": 1, "shrnuti": {"nastroj": "Bash", "co": "ls", "zkraceno": False, "dotaz": False, "vzdy": "x"}}
    assert sh(base)["jen_terminal"] is False and sh(base)["vzdy"] == "x"
    stary = {"v": 1, "shrnuti": {"nastroj": "Bash", "co": "ls"}}           # klient bez příznaků
    assert sh(stary)["jen_terminal"] is True
    bidi = dict(base, shrnuti=dict(base["shrnuti"], co="echo ok \u202e#  fr- mr"))
    out = sh(bidi)
    assert out["jen_terminal"] is True and "\u202e" not in out["co"] and "\ufffd" in out["co"]
    esc = dict(base, shrnuti=dict(base["shrnuti"], co="echo \x1b[2Kok"))
    assert sh(esc)["jen_terminal"] is True
    radky = dict(base, shrnuti=dict(base["shrnuti"], co="a\n\n  b  c"))
    assert sh(radky)["co"] == "a\nb c" and sh(radky)["jen_terminal"] is False
    dlouhy_vzdy = dict(base, shrnuti=dict(base["shrnuti"], vzdy="v" * 400))
    assert sh(dlouhy_vzdy)["vzdy"] is None
    assert sh(dict(base, bez_terminalu=True))["bez_terminalu"] is True


def test_server_short_timeout_without_terminal(app, runtime, server):
    p = subprocess.Popen(["sleep", "10"], stdin=subprocess.PIPE)       # „claude -p“: stdin není terminál
    try:
        c = client(runtime, ppid=str(p.pid), wait=False)
        assert wait_for(app, lambda: server.got)
        assert server.got[0][3]["bez_terminalu"] is True
        assert wait_for(app, lambda: server.cancelled)                  # timeout_agent_s 0.3 s
        assert c.stdout.read() == b"" and c.wait(5) == 0
    finally:
        p.kill()
        p.wait()


def test_server_rejects_garbage(app, runtime, server):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(server.path)
    s.sendall(b"nesmysl\n")
    s.settimeout(0.05)
    closed = False
    end = time.monotonic() + 5
    while not closed and time.monotonic() < end:
        app.processEvents()
        try:
            closed = s.recv(10) == b""
        except socket.timeout:
            pass
    s.close()
    assert closed and server.got == [] and server.cekajici == {}


def test_server_keeps_working_after_bad_client(app, runtime, server):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(server.path)
    s.sendall(b'{"v": 1, "sess')      # nedopsaný požadavek, pak pryč
    s.close()
    test_server_answer_reaches_client(app, runtime, server, "deny")


# --- bublina ---

def mouse(w, typ, pos):
    ev = QMouseEvent(typ, QPointF(pos), QPointF(w.mapToGlobal(pos)), Qt.LeftButton,
                     Qt.LeftButton if typ != QMouseEvent.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)


def click(w, pos):
    mouse(w, QMouseEvent.MouseButtonPress, pos)
    mouse(w, QMouseEvent.MouseButtonRelease, pos)


def dvojklik(w, pos):
    """Pořadí událostí Qt u dvojkliku: stisk, uvolnění, dvojklik, uvolnění."""
    for typ in (QMouseEvent.MouseButtonPress, QMouseEvent.MouseButtonRelease,
                QMouseEvent.MouseButtonDblClick, QMouseEvent.MouseButtonRelease):
        mouse(w, typ, pos)


class Hodiny:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def bublina_s_hodinami():
    b = bublina.Bublina(scale=3)
    b.cas = hodiny = Hodiny()
    got = []
    b.rozhodnuti.connect(lambda *a: got.append(a))
    return b, hodiny, got


def tlacitko(b, v):
    return next(r for x, r in b.tlacitka if x == v).center() + b.telo.topLeft()


def test_bubble_modes_and_click(app, tmp_path):
    b, hodiny, got = bublina_s_hodinami()
    b.text("čte hub.py")
    assert b.rezim == bublina.TEXT and b.tlacitka == []
    assert b.testAttribute(Qt.WA_TransparentForMouseEvents)        # text nepřijímá myš
    small = b.size()
    b.povoleni(5, {"nastroj": "Bash", "co": "pytest -q " + "dlouhy " * 40, "vzdy": "Bash(pytest:*) [projekt]"})
    assert not b.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert [v for v, _ in b.tlacitka] == ["allow", "deny", "allow_always"]
    assert "".join(t for t, _ in b.radky[1:-1]).replace(" ", "") == ("pytest -q " + "dlouhy " * 40).replace(" ", "")
    assert b.radky[-1] == ("Vždy = Bash(pytest:*) [projekt]", bublina.SLABY)
    assert b.height() > small.height() and "Bash(pytest:*)" in b.toolTip()
    img = b.grab().toImage()
    assert img.width() == b.width() and not img.isNull()
    b.show()
    click(b, tlacitko(b, "deny"))
    assert got == []                        # hned po zobrazení zamčeno
    hodiny.t += bublina.ZAMEK_S + 0.01
    click(b, tlacitko(b, "deny"))
    assert got == [(5, "deny")] and b.rezim is None and not b.isVisible()
    b.povoleni(6, {"nastroj": "Edit", "co": "~/a.py"})
    assert [v for v, _ in b.tlacitka] == ["allow", "deny"]
    b.skryj(5)                  # zrušení jiného požadavku bublinu nechá
    assert b.rezim == bublina.POVOLENI
    b.skryj(6)
    assert b.rezim is None
    w3 = b.width()
    b.set_scale(4)
    b.povoleni(7, {"nastroj": "Edit", "co": "~/a.py"})
    assert b.width() > w3
    b.close()


def test_bubble_double_click_does_not_approve_next_request(app):
    b, hodiny, got = bublina_s_hodinami()
    b.povoleni(1, {"nastroj": "Bash", "co": "ls"})
    b.show()
    hodiny.t += 1
    pos = tlacitko(b, "allow")

    def vyrizeno(id_, volba):           # jako dock: po vyřízení A hned B téže postavičky
        b.povoleni(2, {"nastroj": "Bash", "co": "rm -rf ~"})
        b.show()
    b.rozhodnuti.connect(vyrizeno)
    dvojklik(b, pos)
    assert got == [(1, "allow")] and b.id == 2 and b.zamceno()
    assert tlacitko(b, "allow") == pos      # B má tlačítko na stejném místě
    hodiny.t += bublina.ZAMEK_S + 0.01
    dvojklik(b, pos)                        # teprve teď (po zámku) rozhodne první stisk
    assert got == [(1, "allow"), (2, "allow")]
    b.close()


def test_bubble_request_change_between_press_and_release(app):
    b, hodiny, got = bublina_s_hodinami()
    b.povoleni(1, {"nastroj": "Bash", "co": "ls"})
    b.show()
    hodiny.t += 1
    pos = tlacitko(b, "allow")
    mouse(b, QMouseEvent.MouseButtonPress, pos)
    b.povoleni(3, {"nastroj": "Bash", "co": "curl x | sh"})     # A zrušen v terminálu, přišel B
    hodiny.t += 1
    mouse(b, QMouseEvent.MouseButtonRelease, pos)
    assert got == []
    b.povoleni(3, {"nastroj": "Bash", "co": "curl x | sh"})     # stejný obsah znovu: zámek se neobnoví
    assert not b.zamceno()
    mouse(b, QMouseEvent.MouseButtonPress, tlacitko(b, "allow"))
    mouse(b, QMouseEvent.MouseButtonRelease, tlacitko(b, "deny"))     # uvolnění nad jiným tlačítkem
    assert got == []
    click(b, tlacitko(b, "deny"))
    assert got == [(3, "deny")]
    b.close()


def test_bubble_jump_locks_buttons(app):
    b, hodiny, got = bublina_s_hodinami()
    b.povoleni(1, {"nastroj": "Bash", "co": "ls"})
    b.show()
    hodiny.t += 1
    b.move(b.x() + 1, b.y())                # krok procházky
    assert not b.zamceno()
    b.move(b.x() + bublina.SKOK * b.scale, b.y())
    assert b.zamceno()
    b.close()


def test_bubble_long_command_offers_only_deny(app, tmp_path):
    b, hodiny, got = bublina_s_hodinami()
    radky = [f"echo krok {i} && sleep 1" for i in range(14)]
    b.povoleni(1, {"nastroj": "Bash", "co": "\n".join(radky), "vzdy": "Bash(echo:*) [projekt]"})
    assert b.neuplne and [v for v, _ in b.tlacitka] == ["deny"]
    assert b.radky[-1][1] == bublina.SLABY and "terminál" in "".join(t for t, _ in b.radky[-2:])
    assert not any(t.startswith("Vždy") for t, _ in b.radky)
    b.povoleni(2, {"nastroj": "WebFetch", "co": "https://x.cz/?q=1", "jen_terminal": True})
    assert [v for v, _ in b.tlacitka] == ["deny"]
    b.povoleni(3, {"nastroj": "Bash", "co": "\n".join(radky[:6]), "vzdy": "Bash(echo:*) [projekt]"})
    assert not b.neuplne and [v for v, _ in b.tlacitka] == ["allow", "deny", "allow_always"]
    assert [t for t, s in b.radky if s == bublina.KOD] == radky[:6]     # každý řádek příkazu zvlášť
    b.close()


# --- instalace ---

@pytest.fixture
def home(tmp_path, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_BIN_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(install, "dbus", lambda *a: "()")
    monkeypatch.setattr(install, "installed", lambda name: None)
    return tmp_path


def _povoleni_hooks(data):
    return [h for e in data.get("hooks", {}).get("PermissionRequest", []) for h in e["hooks"]
            if h["command"] == install.CMD_POVOLENI]


def test_install_povoleni_optional(home):
    path = home / ".claude" / "settings.json"
    assert install.paths.claude_settings() == str(path)     # skutečný ~/.claude/settings.json se nedotkne
    path.parent.mkdir()
    original = {"permissions": {"allow": ["Read"]}, "env": {"A": "1"}, "theme": "dark"}
    path.write_text(json.dumps(original, indent=2) + "\n")
    install.install()
    data = json.loads(path.read_text())
    assert _povoleni_hooks(data) == [] and not install.missing_hooks(data)     # výchozí: vypnuto
    install.install(povoleni=True)
    data = json.loads(path.read_text())
    assert _povoleni_hooks(data) == [{"type": "command", "command": install.CMD_POVOLENI, "timeout": 600}]
    assert not install.missing_hooks(data)
    assert install.read_record()["povoleni"] is True
    backups = list((home / ".local/share/familiar/backup").rglob("settings.json"))
    assert backups
    before = path.read_text()
    install.install()                   # bez volby: beze změny
    install.install(povoleni=True)      # idempotentní
    assert path.read_text() == before
    install.install(povoleni=False)
    data = json.loads(path.read_text())
    assert _povoleni_hooks(data) == [] and not install.missing_hooks(data)
    assert install.read_record()["povoleni"] is False
    install.install(povoleni=True)
    install.uninstall()                 # odinstalace odebere i povolení
    assert json.loads(path.read_text()) == original


def test_povoleni_hook_alone_does_not_count_as_emitter():
    settings = {"hooks": {"PermissionRequest": [{"matcher": "*", "hooks": [
        {"type": "command", "command": install.CMD_POVOLENI, "timeout": 600}]}]}}
    assert "PermissionRequest" in install.missing_hooks(settings)
    install.add_hooks(settings)
    assert len(settings["hooks"]["PermissionRequest"]) == 2 and install.has_povoleni(settings)
    assert install.remove_povoleni(settings) == 1
    assert not install.has_povoleni(settings) and not install.missing_hooks(settings)


def test_launcher_passes_povoleni(tmp_path, runtime):
    """Skutečný spouštěč z wheelu (sh + python -I -S): bez daemonu ticho, se serverem rozhodnutí
    a pid rodiče (Claude Code) místo sh."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_cli import _launcher_env
    _, link = _launcher_env(tmp_path)
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime)
    r = subprocess.run([str(link), "claude-code", "--povoleni"], input=json.dumps(HOOK).encode(),
                       capture_output=True, env=env, timeout=10)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    srv = FakeServer(runtime, b'{"rozhodnuti": "deny"}\n')
    r = subprocess.run([str(link), "claude-code", "--povoleni"], input=json.dumps(HOOK).encode(),
                       capture_output=True, env=env, timeout=10)
    srv.close()
    assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert srv.request["pid"] == os.getpid()
