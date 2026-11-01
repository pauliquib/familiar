# Vrstvy u postavičky (M14): bublina s činností, měřič kontextu, pomocníci, povolení z bubliny.
import json, os, socket, subprocess, sys, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from familiar import config, doctor, install, paths, vrstvy
from familiar.hub import Hub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMIT = os.path.join(ROOT, "familiar", "emit.py")


def msg(ts, hook, pid=7, session="s", **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": session, **raw}}


def ev(ts, kind, **data):
    return {"ts": ts, "kind": kind, "data": data}


def cfg(**sekce):
    c = config.defaults()
    for k, v in sekce.items():
        c[k] = {**c[k], **v} if isinstance(v, dict) else v
    return c


def hub_(c=None):
    return Hub(reap=False, bind=False, cfg=c or cfg(), transcripts=False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


# --- text činnosti ---

def test_program_z_prikazu():
    assert vrstvy.program("python3 -m pytest -q tests") == "pytest"
    assert vrstvy.program("cd /x && FOO=1 uv run pytest tests/test_hub.py") == "pytest"
    assert vrstvy.program("git status --short") == "git status"
    assert vrstvy.program("sudo -n dnf install x") == "dnf install"
    assert vrstvy.program("/usr/bin/ls -la | head") == "ls"
    assert vrstvy.program("echo ahoj; make test") == "make test"
    assert vrstvy.program("timeout 5 npx eslint .") == "eslint"
    assert vrstvy.program("cd x") is None and vrstvy.program(None) is None


def test_cinnost_text():
    t = lambda kind, **d: vrstvy.cinnost_text(ev(0, kind, **d))
    assert t("tool.start", tool="Read", file="hub.py") == "čte hub.py"
    assert t("tool.start", tool="Edit", file="config.py") == "upravuje config.py"
    assert t("tool.start", tool="Write") == "píše soubor"
    assert t("tool.start", tool="Bash", cmd="python3 -m pytest -q") == "spouští pytest"
    assert t("tool.start", tool="Grep", pattern="TODO") == "hledá TODO"
    assert t("tool.start", tool="Glob", pattern="**/*.py") == "hledá **/*.py"
    assert t("tool.start", tool="run_shell_command", cmd="npm test") == "spouští npm test"   # Gemini
    assert t("tool.start", tool="mcp__github__create_issue") == "používá create_issue"
    assert t("subagent.start", agent="a1", type="Explore") == "deleguje: Explore"
    assert t("agent.waiting", why="permission", tool="Bash") == "čeká na povolení: Bash"
    assert t("agent.waiting", why="question", tool="AskUserQuestion") == "čeká na odpověď"
    assert t("user.prompt", text="tajný prompt") == "přemýšlí…"
    assert t("tool.start", tool="Read", file="x.py", agent="a1") is None     # subagent: jen pomocník
    assert t("tool.end", tool="Read") is None
    dlouhe = t("tool.start", tool="Read", file="velmi_dlouhe_jmeno_souboru_ktere_se_nevejde.py")
    assert len(dlouhe) <= len("čte ") + vrstvy.MAX_JMENO and "…" in dlouhe


def test_bublina_pri_zmene_vzdy_nikdy():
    h = hub_()
    h.receive(msg(0, "UserPromptSubmit", prompt="ahoj"))
    h.receive(msg(1, "PreToolUse", tool_name="Read", tool_use_id="t1", tool_input={"file_path": "/a/b/hub.py"}))
    fam = h.fams[7]
    assert fam.bublina(1.5) == ("text", "čte hub.py")
    assert fam.bublina(1 + vrstvy.BUBLINA_S + 0.1) is None      # při změně: jen na chvíli
    h.receive(msg(5, "PreToolUse", tool_name="Read", tool_use_id="t2", tool_input={"file_path": "/a/b/hub.py"}))
    assert fam.bublina(5.1) is None                              # stejný text = žádná změna
    h.configure(cfg(bublina={"cinnost": "vzdy"}))
    assert fam.bublina(20) == ("text", "čte hub.py")             # pořád pracuje
    h.receive(msg(21, "PostToolUse", tool_name="Read", tool_use_id="t1"))
    h.receive(msg(21, "PostToolUse", tool_name="Read", tool_use_id="t2"))
    assert fam.bublina(30) == ("text", "přemýšlí…")
    h.receive(msg(31, "Stop"))
    assert fam.bublina(31.1) is None
    h.configure(cfg(bublina={"cinnost": "nikdy"}))
    h.receive(msg(40, "PreToolUse", tool_name="Bash", tool_use_id="t3", tool_input={"command": "ls"}))
    assert fam.bublina(40.1) is None


def test_tichy_rezim_a_soustredeni_bez_textu():
    for c in (cfg(tichy=True), cfg(soustredeni=True)):
        h = hub_(c)
        h.receive(msg(0, "PreToolUse", tool_name="Bash", tool_use_id="t", tool_input={"command": "ls"}))
        assert h.oznam(7, "úspěch!", now=0)
        assert h.fams[7].bublina(0.1) is None
        assert h.fams[7].pomocnici_ted(0.1) == ((), 0, ())


def test_oznam():
    h = hub_()
    assert not h.oznam(7, "nikdo")
    h.receive(msg(0, "UserPromptSubmit", prompt="x"))
    assert h.oznam(7, "úroveň 3!", sekund=2, now=1)
    fam = h.fams[7]
    assert fam.bublina(1.5) == ("text", "úroveň 3!")             # zpráva má přednost před činností
    assert fam.bublina(3.1) is None


# --- měřič kontextu ---

def test_kontext_prahy():
    assert vrstvy.kontext_procento({"used": 170_000, "window": 200_000}) == 85
    assert vrstvy.kontext_procento(None) is None
    assert vrstvy.kontext_uroven(50, 80) == "ok"
    assert vrstvy.kontext_uroven(60, 80) == "pozor"
    assert vrstvy.kontext_uroven(80, 80) == "plno"
    assert vrstvy.ukazat_meric("vzdy", 10, 80) and not vrstvy.ukazat_meric("nikdy", 99, 80)
    assert not vrstvy.ukazat_meric("nad_prahem", 79, 80) and vrstvy.ukazat_meric("nad_prahem", 80, 80)
    assert not vrstvy.ukazat_meric("vzdy", None, 80)


def test_kontext_varovani_jednou_a_po_compactu_znovu():
    h = hub_()
    h.receive(msg(0, "SessionStart", source="startup"))
    fam = h.fams[7]
    fam.nastav_kontext({"used": 100_000, "window": 200_000, "model": "m"}, 1)
    assert fam.meric() == (50, "ok") and fam.bublina(1.1) is None
    fam.nastav_kontext({"used": 170_000, "window": 200_000, "model": "m"}, 2)
    assert fam.meric() == (85, "plno") and fam.bublina(2.1) == ("text", "kontext 85 %, brzy compact")
    fam.zprava = None
    fam.nastav_kontext({"used": 180_000, "window": 200_000, "model": "m"}, 3)
    assert fam.bublina(3.1) is None                              # jen jednou
    fam.nastav_kontext({"used": 30_000, "window": 200_000, "model": "m"}, 4)     # compact
    fam.nastav_kontext({"used": 166_000, "window": 200_000, "model": "m"}, 5)
    assert fam.bublina(5.1) == ("text", "kontext 83 %, brzy compact")
    h.configure(cfg(kontext={"zobrazit": "nad_prahem", "prah": 90}))
    assert fam.meric() is None
    h.configure(cfg(kontext={"zobrazit": "nikdy"}))
    assert fam.meric() is None


def test_poll_kontext_z_transcriptu(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("")
    h = Hub(reap=False, bind=False, cfg=cfg())
    h.receive(msg(0, "SessionStart", source="startup", transcript_path=str(t)))
    line = {"type": "assistant", "message": {"model": "claude-sonnet-4-5", "usage": {"input_tokens": 120_000}}}
    t.write_text(json.dumps(line) + "\n")
    h.poll_transcripts(1)
    h.poll_kontext(1)
    assert h.fams[7].meric() == (60, "pozor")


STATUSLINE = {"session_id": "s", "transcript_path": "/neexistuje.jsonl", "model": {"id": "claude-opus-5-5"},
              "context_window": {"context_window_size": 1_000_000, "used_percentage": 3,
                                 "current_usage": {"input_tokens": 2, "output_tokens": 50,
                                                   "cache_creation_input_tokens": 14_000,
                                                   "cache_read_input_tokens": 19_998}}}


def test_statusline_context():
    from familiar.emit import statusline_context
    assert statusline_context(STATUSLINE) == {"used": 34_000, "window": 1_000_000, "model": "claude-opus-5-5"}
    bez = {"context_window": {"context_window_size": 200_000, "used_percentage": 50, "current_usage": None}}
    assert statusline_context(bez) == {"used": 100_000, "window": 200_000, "model": None}
    assert statusline_context({"context_window": {"context_window_size": 200_000, "current_usage": None,
                                                  "used_percentage": None}}) is None    # zatím žádná odpověď
    assert statusline_context({}) is None and statusline_context({"context_window": {}}) is None


def test_kontext_ze_statusline_bez_transcriptu():
    h = hub_()
    h.receive({"v": 1, "source": "claude-code", "pid": 7, "ts": 0,     # postavičku nezakládá
               "raw": {"hook_event_name": "StatusLine", "context": {"used": 1, "window": 2}}})
    assert not h.fams
    h.receive(msg(0, "SessionStart", source="startup"))
    stav = h.fams[7].fsm.state
    h.receive({"v": 1, "source": "claude-code", "pid": 99, "ts": 1, "raw": {
        "hook_event_name": "StatusLine", "session_id": "s",
        "context": {"used": 170_000, "window": 200_000, "model": "m"}}})     # jiný pid: podle session
    assert h.fams[7].meric() == (85, "plno") and h.fams[7].fsm.state == stav
    assert h.fams[7].bublina(1.1) == ("text", "kontext 85 %, brzy compact")
    for vadny in ({"used": "x", "window": 2}, {"used": 1, "window": 0}, None):
        h.receive({"v": 1, "source": "claude-code", "pid": 7, "ts": 2,
                   "raw": {"hook_event_name": "StatusLine", "context": vadny}})
    assert h.fams[7].meric() == (85, "plno")


def test_emit_statusline_posle_kontext_a_nic_nevypise(tmp_path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(str(tmp_path / "familiar.sock"))
    s.settimeout(5)
    env = {**os.environ, "XDG_RUNTIME_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-I", EMIT, "claude-code", "--statusline"],
                       input=json.dumps(STATUSLINE).encode(), capture_output=True, env=env, timeout=10)
    assert r.returncode == 0 and r.stdout == b""
    m = json.loads(s.recv(65536))
    s.close()
    assert m["raw"] == {"hook_event_name": "StatusLine", "session_id": "s",
                        "context": {"used": 34_000, "window": 1_000_000, "model": "claude-opus-5-5"}}


# --- pomocníci ---

def test_pomocnici_limit_prichod_odchod():
    p = vrstvy.Pomocnici()
    for i in range(5):
        p.feed(ev(i * 0.01, "subagent.start", agent=f"a{i}", type=f"T{i}"))
    out, dalsi, typy = p.ted(0.1, 3)
    assert [x[0]["typ"] for x in out] == ["T0", "T1", "T2"] and dalsi == 2 and typy == ("T3", "T4")
    assert {x[1] for x in out} == {"prichod"}
    assert {x[1] for x in p.ted(1, 3)[0]} == {"bezi"}
    p.feed(ev(2, "subagent.done", agent="a1", type="T1"))
    out, dalsi, _ = p.ted(2.3, 3)
    assert [x[1] for x in out] == ["bezi", "odchod", "bezi"] and dalsi == 2
    out, dalsi, _ = p.ted(2 + vrstvy.ODCHOD_S + 0.01, 3)
    assert [x[0]["typ"] for x in out] == ["T0", "T2", "T3"] and dalsi == 1
    p.feed(ev(3, "session.end"))
    assert p.ted(3, 3) == ([], 0, ())


def test_pomocnici_v_hubu():
    h = hub_(cfg(pomocnici={"limit": 1}))
    h.receive(msg(0, "SubagentStart", agent_id="a1", agent_type="Explore"))
    h.receive(msg(0, "SubagentStart", agent_id="a2", agent_type="Plan"))
    seznam, dalsi, typy = h.fams[7].pomocnici_ted(1)
    assert [s[0] for s in seznam] == ["Explore"] and seznam[0][3] == "bezi" and (dalsi, typy) == (1, ("Plan",))
    assert h.fams[7].update(1)[2][4] == 0       # drony nahrazené pomocníky


# --- povolení: párování a rušení ---

def shrnuti(nastroj="Bash", agent=False):
    return {"nastroj": nastroj, "co": "ls", "vzdy": None, "agent": agent}


def test_zadosti_paralelni_nastroje():
    z = vrstvy.Zadosti()
    z.udalost(ev(0, "tool.start", tool="Read", id="r1"))
    z.udalost(ev(0, "tool.start", tool="Bash", id="b1"))
    z.pridej(1, shrnuti("Bash"), 0.1)
    assert z.udalost(ev(0.2, "tool.end", tool="Read", id="r1")) == []       # jiný nástroj neruší
    assert z.udalost(ev(0.3, "agent.waiting", tool="Bash", why="permission")) == []
    assert z.prvni() == (1, shrnuti("Bash"))
    assert z.udalost(ev(5, "tool.end", tool="Bash", id="b1")) == [1]        # odpověď v terminálu
    assert not z


def test_zadosti_stejne_jmeno_ceka_na_vsechny_kandidaty():
    z = vrstvy.Zadosti()
    z.udalost(ev(0, "tool.start", tool="Read", id="r1"))
    z.udalost(ev(0, "tool.start", tool="Read", id="r2"))
    z.pridej(1, shrnuti("Read"), 0.1)
    assert z.udalost(ev(0.2, "tool.end", tool="Read", id="r1")) == []       # povolený souběžný Read
    assert z.udalost(ev(0.3, "tool.start", tool="Read", id="r3")) == []     # dávka startuje současně
    assert z.udalost(ev(4, "tool.end", tool="Read", id="r2")) == [1]


def test_zadosti_dalsi_start_schvaleno_a_bez_pretooluse():
    z = vrstvy.Zadosti()
    z.pridej(1, shrnuti("Bash"), 0)
    assert z.udalost(ev(0.5, "tool.end", tool="Edit", id="e")) == []
    assert z.udalost(ev(0.6, "tool.denied", tool="Bash", id="x")) == [1]    # PreToolUse nedorazil
    z.udalost(ev(1, "tool.start", tool="Bash", id="b1"))
    z.pridej(2, shrnuti("Bash"), 1)
    assert z.udalost(ev(3, "tool.start", tool="Bash", id="b2")) == [2]      # další Bash = Claude jede dál
    z.pridej(3, shrnuti("Bash"), 3)
    assert z.udalost(ev(3.1, "tool.start", tool="Bash", id="b3", schvaleno=True)) == [3]


def test_zadosti_subagent_a_konec_kola():
    z = vrstvy.Zadosti()
    z.udalost(ev(0, "tool.start", tool="Bash", id="h"))
    z.udalost(ev(0, "tool.start", tool="Bash", id="s", agent="a1"))
    z.pridej(1, shrnuti("Bash"), 0.1)
    z.pridej(2, shrnuti("Bash", agent=True), 0.1)
    assert z.udalost(ev(1, "tool.end", tool="Bash", id="s", agent="a1")) == [2]   # jen subagentův
    assert z.udalost(ev(2, "user.prompt", text="x")) == [1]
    z.pridej(3, shrnuti("Bash", agent=True), 3)
    assert z.udalost(ev(4, "agent.done")) == []                 # Stop hlavního neruší subagenta
    assert z.udalost(ev(5, "session.end")) == [3]


def test_hub_pozadavek_podle_pid_a_session_a_on_zrus():
    h = hub_()
    zruseno = []
    h.on_zrus = zruseno.append
    h.receive(msg(0, "PreToolUse", pid=7, session="s7", tool_name="Bash", tool_use_id="b1",
                  tool_input={"command": "rm -rf build"}))
    h.receive(msg(0, "SessionStart", pid=None, session="bez-pid", source="startup"))
    assert h.pozadavek(1, "s7", 7, shrnuti(), 0.1) == 7
    assert h.pozadavek(2, "bez-pid", 0, shrnuti("Edit"), 0.1) == "bez-pid"
    assert h.pozadavek(3, "cizi", 999, shrnuti(), 0.1) is None
    assert h.fams[7].bublina(0.2) == ("povoleni", 1, shrnuti())
    h.receive(msg(1, "PostToolUse", pid=7, session="s7", tool_name="Bash", tool_use_id="b1"))
    assert zruseno == [1] and h.fams[7].bublina(1.1) != ("povoleni", 1, shrnuti())
    assert h.vyrizeno(2) and not h.vyrizeno(2)


def test_povoleni_v_tichem_rezimu_i_ve_spanku():
    h = hub_(cfg(soustredeni=True))
    h.receive(msg(0, "PreToolUse", tool_name="Bash", tool_use_id="b1"))
    h.uspat()
    h.pozadavek(1, "s", 7, shrnuti(), 0)
    assert h.fams[7].bublina(0.1)[0] == "povoleni"


# --- Povolovani (Qt): zapnutí za běhu, požadavek, odpověď ---

@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_povolovani_s_falesnym_serverem(app):
    from PySide6.QtCore import QObject, Signal
    from familiar import dock

    class Srv(QObject):
        pozadavek = Signal(int, str, int, object)
        zruseno = Signal(int)
        vsechny = []

        def __init__(self, parent, t, ta):
            super().__init__(parent)
            self.t, self.odpovedi, self.zrusene, self.zavreno = (t, ta), [], [], False
            Srv.vsechny.append(self)

        def start(self):
            return True

        def configure(self, t, ta):
            self.t = (t, ta)

        def odpovez(self, i, v):
            self.odpovedi.append((i, v))
            return True

        def zrus(self, i):
            self.zrusene.append(i)
            self.zruseno.emit(i)

        def close(self):
            self.zavreno = True

    h = hub_()
    p = dock.Povolovani(h, factory=Srv)
    p.configure(cfg())
    assert p.srv is None                                        # výchozí vypnuto
    p.configure(cfg(povoleni={"zapnuto": True, "timeout_s": 60}))
    srv = p.srv
    assert srv is not None and srv.t == (60, 15)
    srv.pozadavek.emit(1, "s", 999, shrnuti())                  # neznámý proces → hned zrušit
    assert srv.zrusene == [1]
    h.receive(msg(0, "PreToolUse", tool_name="Bash", tool_use_id="b1"))
    srv.pozadavek.emit(2, "s", 7, shrnuti())
    assert h.fams[7].bublina(0.1)[:2] == ("povoleni", 2)
    p.odpovez(2, "allow")
    assert srv.odpovedi == [(2, "allow")] and h.fams[7].bublina(0.1) != ("povoleni", 2, shrnuti())
    srv.pozadavek.emit(3, "s", 7, shrnuti())
    h.receive(msg(1, "UserPromptSubmit", prompt="x"))          # odpověď v terminálu, nové kolo
    assert srv.zrusene == [1, 3]
    p.configure(cfg())                                          # vypnutí za běhu
    assert p.srv is None and srv.zavreno


def test_bublina_ocasek_na_vsechny_strany(app):
    from familiar import bublina
    b = bublina.Bublina(scale=2)
    b.text("čte hub.py")
    w, hh = b.width(), b.height()
    b.set_ocas(None, bublina.VPRAVO)
    assert (b.width(), b.height()) == (w + bublina.OCAS * 2, hh - bublina.OCAS * 2)
    b.set_ocas(None, bublina.VLEVO)
    assert b.telo.left() == bublina.OCAS * 2
    b.povoleni(5, shrnuti())
    got = []
    b.rozhodnuti.connect(lambda i, v: got.append((i, v)))
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, Qt
    klik(b, b.tlacitka[0][1])
    assert got == [(5, "allow")]


def klik(b, rect):
    """Stisk a uvolnění nad tlačítkem po uplynutí zámku bubliny."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    b.zamceno_do = float("-inf")
    pos = QPointF(rect.center() + b.telo.topLeft())
    b.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    b.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton,
                                    Qt.NoModifier))


def test_perch_okno_s_vrstvami_a_bublinou(app):
    from familiar import bublina, dock
    h = hub_()
    fam = type("Fam", (), {"key": 7, "term": 0, "name": "x"})
    got = []
    w = dock.Perch(h, fam, 2, "vpravo|120|4|8|navrchu|vpravo-dole", odpoved=lambda i, v: got.append((i, v)))
    frame = (h.skin, "idle", 0, None, None)
    anim = h.skin.anim_for("working")
    w.set(frame, "idle", ((85, "plno"), (("Explore", anim, 0, "bezi", 1.0),), 0, ()))
    assert w.width() > 64 and w.height() == 64
    w.set(frame, "idle")
    assert (w.width(), w.height()) == (64, 64)
    w.ukaz_bublinu(("povoleni", 3, shrnuti()))
    assert w.bublina.windowTitle().startswith(f"familiar-bublina|{w.cislo}|vlevo|")
    assert w.bublina.smer == bublina.VPRAVO and w.bublina.isVisible()
    klik(w.bublina, w.bublina.tlacitka[1][1])
    assert got == [(3, "deny")] and w.obsah is None and not w.bublina.isVisible()
    from PySide6.QtCore import Qt
    assert not w.bublina.windowHandle().flags() & Qt.WindowTransparentForInput
    w.ukaz_bublinu(("text", "čte hub.py"))
    assert w.bublina.isVisible() and w.bublina.rezim == bublina.TEXT
    assert w.bublina.windowHandle().flags() & Qt.WindowTransparentForInput     # klik projde do titulku
    w.ukaz_bublinu(("povoleni", 4, shrnuti()))
    assert not w.bublina.windowHandle().flags() & Qt.WindowTransparentForInput
    w.ukaz_bublinu(None)
    assert not w.bublina.isVisible()
    w.close()


def test_dock_bublina_pod_bunkou(app):
    from familiar import bublina, dock
    h = hub_()
    h.receive(msg(0, "PreToolUse", tool_name="Grep", tool_use_id="g", tool_input={"pattern": "TODO"}))
    d = dock.Dock(h, cfg=cfg())
    d.timer.stop()
    h.oznam(7, "hotovo!", sekund=60)
    d.tick()
    b = d.bubliny[7][0]
    assert d.bubliny[7][1] == ("text", "hotovo!") and b.smer == bublina.NAHORU
    assert b.y() >= d.cell_h and d.height() >= b.y() + b.height()
    h.fams[7].zprava = None
    d.tick()
    assert d.height() == d.cell_h
    d.close()


def test_dock_bubliny_povoleni_se_neprekryvaji(app):
    from familiar import dock
    h = hub_(cfg(prochazky={"zapnuto": False}))
    for pid in (7, 8, 9):
        h.receive(msg(0, "SessionStart", pid=pid, session=f"s{pid}", source="startup"))
    d = dock.Dock(h, cfg=cfg(prochazky={"zapnuto": False}))
    d.timer.stop()
    for i, pid in enumerate((7, 8, 9)):
        h.pozadavek(i + 1, f"s{pid}", pid, shrnuti(), 0.1)
    d.tick()
    bb = sorted((b for b, _ in d.bubliny.values()), key=lambda b: b.x())
    assert len(bb) == 3 and not any(b.isHidden() for b in bb)
    assert all(a.x() + a.width() <= b.x() for a, b in zip(bb, bb[1:]))
    assert d.width() >= bb[-1].x() + bb[-1].width()
    d.close()


def test_povolovani_odpoved_rusi_upozorneni(app):
    from familiar import dock
    h = hub_()
    zrusene = []
    h.sluzby = type("S", (), {"odpovezeno": lambda self, k: zrusene.append(k)})()
    h.receive(msg(0, "PreToolUse", tool_name="Bash", tool_use_id="b1"))
    p = dock.Povolovani(h)
    h.pozadavek(5, "s", 7, shrnuti(), 0.1)
    p.odpovez(5, "allow")
    assert zrusene == [7]
    p.odpovez(5, "allow")                   # už nikomu nepatří
    assert zrusene == [7]


def test_zacatek_kola_i_bez_promptu(app):
    h = hub_()
    h.receive(msg(10, "UserPromptSubmit", prompt="x"))
    f = h.fams[7]
    assert f.kolo_od == 10
    h.receive(msg(20, "PreToolUse", tool_name="Bash", tool_use_id="b1"))
    h.receive(msg(30, "Stop"))
    assert f.kolo_od == 10 and f.kolo_konec
    h.receive(msg(100, "SubagentStop", agent_id="a1", agent_type="Explore"))     # úloha na pozadí dobíhá
    h.receive(msg(110, "Stop"))
    assert f.kolo_od == 100


# --- rozvrh okna (perch) a buňky (dock) ---

def test_rozvrh_meric_a_pomocnici(app):
    from familiar import dock
    W, H, char, mr, sloty = dock.rozvrh((32, 32), 2, "vlevo", True, 3, (20, 26))
    assert char.right() == W - 1 and H == 64                    # postavička u kraje, vrstvy dovnitř
    assert mr.right() < char.left() and all(s.right() < mr.left() for s in sloty)
    assert [s.bottom() for s in sloty[:2]] != [H - 1, H - 1] and sloty[0].bottom() == H - 1
    assert sloty[2].x() < sloty[0].x()                          # třetí do dalšího sloupce
    W2, _, char2, mr2, sloty2 = dock.rozvrh((32, 32), 2, "vpravo", False, 0, (20, 26))
    assert (W2, char2.x(), mr2, sloty2) == (64, 0, None, [])


def test_rozvrh_necele_meritko(app):
    from familiar import dock
    W, H, char, mr, _ = dock.rozvrh((32, 32), 2.505, "vpravo", True, 0, (20, 26))
    assert (char.width(), H) == (80, 80)                        # 32 × 2,505 = 80,16 → 80 px
    assert mr.width() == dock.METER_W * 3 and mr.x() == 80 + 3  # měřič po celých px (jednotka 3)
    assert dock.mini_meritko(2.505) == 1 and dock.jednotka(1.2) == 1


# --- config a doctor ---

def test_config_klice_a_validace(home):
    d = config.defaults()
    assert d["bublina"] == {"cinnost": "zmena", "doba_s": 3.0}
    assert d["kontext"] == {"zobrazit": "vzdy", "prah": 80, "varovat": True}
    assert d["pomocnici"] == {"zapnuto": True, "limit": 3}
    assert d["povoleni"] == {"zapnuto": False, "timeout_s": 300, "timeout_agent_s": 15}
    path = paths.config_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write('[bublina]\ncinnost = "obcas"\ndoba_s = 0.1\n[kontext]\nprah = 101\n'
                '[pomocnici]\nlimit = 0\n[povoleni]\nzapnuto = true\ntimeout_agent_s = 30\n')
    c = config.load()
    assert len(c.errors) == 5, c.errors
    assert c["bublina"]["cinnost"] == "zmena" and c["kontext"]["prah"] == 80
    assert c["povoleni"] == {"zapnuto": True, "timeout_s": 300, "timeout_agent_s": 15}
    for key in ("bublina.cinnost", "kontext.zobrazit", "pomocnici.zapnuto", "povoleni.zapnuto"):
        assert key in config.COMMENTS


def test_nastaveni_polozky_jednoduche_a_pokrocile():
    from familiar import nastaveni
    rez = {p.klic: p.rezim for p in nastaveni.POLOZKY}
    for k in ("bublina.cinnost", "kontext.zobrazit", "pomocnici.zapnuto", "povoleni.zapnuto"):
        assert rez[k] == nastaveni.JEDNODUCHE, k
    for k in ("bublina.doba_s", "kontext.prah", "kontext.varovat", "pomocnici.limit",
              "povoleni.timeout_s", "povoleni.timeout_agent_s"):
        assert rez[k] == nastaveni.POKROCILE, k
    p = next(p for p in nastaveni.POLOZKY if p.klic == "povoleni.zapnuto")
    assert "familiar install --povoleni" in p.napoveda


def test_doctor_povoleni(home):
    c = config.defaults()
    assert doctor.povoleni_check(c)[0] is True
    c["povoleni"]["zapnuto"] = True
    ok, _, detail = doctor.povoleni_check(c)
    assert ok is None and "familiar install --povoleni" in detail       # jen varování
    s = {}
    install.add_povoleni(s)
    p = paths.claude_settings()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(s, f)
    assert doctor.povoleni_check(c) == (True, "povolení z bubliny", "zapnuto, hook nainstalován")


# --- emitter: jen jméno souboru a vzor ---

def test_emit_posila_jen_jmeno_souboru_a_vzor():
    d = tempfile.mkdtemp(prefix="fam", dir="/tmp")
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(os.path.join(d, "familiar.sock"))
        s.settimeout(2)
        for ti, want in (({"file_path": "/home/x/tajny/projekt/hub.py", "content": "OBSAH"}, {"file": "hub.py"}),
                         ({"pattern": "TODO\n  x", "path": "/home/x"}, {"pattern": "TODO x"})):
            hook = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Read", "tool_input": ti}
            r = subprocess.run([sys.executable, "-I", EMIT, "claude-code"], input=json.dumps(hook).encode(),
                               capture_output=True, env=dict(os.environ, XDG_RUNTIME_DIR=d), timeout=5)
            assert (r.returncode, r.stdout) == (0, b"")
            raw = json.loads(s.recv(65536))["raw"]
            assert {k: raw[k] for k in want} == want
            assert "OBSAH" not in json.dumps(raw) and "tajny" not in json.dumps(raw)
        s.close()
    finally:
        for name in os.listdir(d):
            os.unlink(os.path.join(d, name))
        os.rmdir(d)
