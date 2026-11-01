# M15: služby na událostech hubu – posluchači, notifikace podle aktivního okna, statistiky,
# postup, ukládání, agenti, config, nabídka, doctor, D-Bus (dbus-run-session).
import json, os, shutil, subprocess, sys, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from familiar import config, doctor, dock, hub as hubmod, kwin, nabidka, okna, paths, sluzby, upozorneni as up
from familiar.hub import Hub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_800_000_000.0
SECRET = "TAJNY-PROMPT-5c1e"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch, app):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(kwin, "load", lambda: True)
    monkeypatch.setattr(kwin, "unload", lambda: None)
    return tmp_path


def msg(ts, hook, pid=7, source="claude-code", **raw):
    return {"v": 1, "source": source, "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": f"s{pid}", "cwd": f"/home/x/projekt{pid}", **raw}}


class FalesnyDbus:
    def __init__(self):
        self.na_akci = self.na_zavreni = None
        self.zobrazeno, self.zavreno, self.dalsi = [], [], 41

    def zobraz(self, args):
        self.zobrazeno.append(args)
        self.dalsi += 1
        return args[1] or self.dalsi

    def zavri(self, nid):
        self.zavreno.append(nid)


class Ticho:
    def __init__(self):
        self.hrane = []

    def prehraj(self, cesta, hlasitost):
        self.hrane.append(cesta)
        return True


class Okno:
    def __init__(self, pid=None):
        self.pid, self.zastaveno = pid, False

    def zastav(self):
        self.zastaveno = True


def cfg(**sekce):
    c = config.defaults()
    c["upozorneni"].update(cekani_po_s=0.0, kolo_nad_s=30.0)
    for k, v in sekce.items():
        c[k].update(v)
    return c


def mk(home, c=None, okno=None, ikona=False, views=None):
    c = c or cfg()
    hub = Hub(reap=False, bind=False, cfg=c, transcripts=False)
    d, p = FalesnyDbus(), Ticho()
    u = up.Upozorneni(c, dbus=d, prehravac=p)
    s = sluzby.Sluzby(hub, c, views=views, upozorneni=u, okno=okno or Okno(), ikona=ikona)
    return hub, s, d, p


def texty(d):
    return [(a[3], a[4]) for a in d.zobrazeno]


# --- hub: posluchači a agenti ---

def test_posluchaci_dostanou_prijate_udalosti():
    hub = Hub(reap=False, bind=False, transcripts=False)
    seen = []
    hub.posluchaci.append(lambda fam, ev: seen.append((fam.key, ev["kind"])))
    hub.posluchaci.append(lambda fam, ev: 1 / 0)        # chyba posluchače nic nezastaví
    hub.receive(msg(0, "UserPromptSubmit", prompt="x"))
    hub.receive(msg(1, "PostToolUseFailure", tool_name="Bash", error="x", is_interrupt=True))
    hub.receive(msg(2, "PostToolUseFailure", tool_name="Bash", error="x", is_interrupt=True))
    # druhé přerušení v tomtéž kole Familiar.feed odmítne → posluchač ho nedostane
    assert seen == [(7, "user.prompt"), (7, "tool.error"), (7, "agent.interrupted"), (7, "tool.error")]
    assert hub.fams[7].fsm.state != "gone"


def test_posluchac_dostane_i_konec_mrtveho_procesu():
    hub = Hub(bind=False, transcripts=False)
    seen = []
    hub.posluchaci.append(lambda fam, ev: seen.append(ev["kind"]))
    hub.receive(msg(0, "SessionStart", pid=999999999))
    hub.tick(hubmod.REAP_S)
    assert seen == ["session.start", "session.end"]


def test_vypnuty_agent_se_ignoruje():
    c = config.defaults()
    c["agenti"]["gemini"] = False
    hub = Hub(reap=False, bind=False, cfg=c, transcripts=False)
    hub.receive(msg(0, "BeforeAgent", pid=8, source="gemini", prompt="x"))
    hub.receive(msg(0, "SessionStart", pid=9, source="codex"))
    hub.receive(msg(0, "SessionStart", pid=10))
    assert sorted(hub.fams) == [9, 10]
    c2 = config.defaults()
    c2["agenti"]["codex"] = False
    hub.configure(c2)
    assert hub.fams[9].fsm.state == "gone" and hub.fams[10].fsm.state != "gone"
    hub.receive(msg(1, "BeforeAgent", pid=8, source="gemini", prompt="x"))
    assert 8 in hub.fams


def test_pid_alive_podle_zdroje():
    me = os.getpid()        # python, ne claude
    assert not hubmod.pid_alive(me) and not hubmod.pid_alive(me, "claude-code")
    assert hubmod.pid_alive(me, "gemini") and hubmod.pid_alive(me, "codex")
    assert not hubmod.pid_alive(999999999, "gemini")


# --- služby ---

def test_zapocti_pres_hub_a_ukladani(home):
    hub, s, d, _ = mk(home)
    hub.receive(msg(T0, "SessionStart"))
    hub.receive(msg(T0 + 1, "UserPromptSubmit", prompt=SECRET))
    hub.receive(msg(T0 + 2, "PreToolUse", tool_name="Bash", tool_use_id="a", tool_input={"command": "ls"}))
    hub.receive(msg(T0 + 3, "PostToolUse", tool_name="Bash", tool_use_id="a"))
    hub.receive(msg(T0 + 50, "Stop"))
    den = s.stats.den(time.strftime("%Y-%m-%d", time.localtime(T0)))
    assert den["session"] == 1 and den["prompty"] == 1 and den["nastroje"] == {"Bash": 1} and den["aktivni_s"] == 50
    assert s.postup.c["kola_cista"] == 1 and "prvni_kolo" in s.postup.odemceno
    st, po = s.stats.cesta, s.postup.cesta
    assert not os.path.exists(st)
    s.tick(T0 + 100)
    assert os.path.exists(st) and os.path.exists(po)
    assert oct(os.stat(st).st_mode & 0o777) == "0o600"
    hub.receive(msg(T0 + 101, "UserPromptSubmit", prompt="y"))
    s.tick(T0 + 110)                    # do ukladat_s (60 s) se znovu nezapisuje
    assert json.load(open(st))["dny"][den["datum"]]["prompty"] == 1
    s.ukonci()                          # při konci hned
    assert json.load(open(st))["dny"][den["datum"]]["prompty"] == 2
    assert s.okno.zastaveno
    for f in (st, po):
        assert SECRET not in open(f).read()


def test_vzorek_nalady_z_historie(home):
    hub, s, _, _ = mk(home)
    hub.receive(msg(T0, "SessionStart"))
    fam = hub.fams[7]
    fam.update(T0)
    s.tick(T0)
    s.tick(T0 + 1)                      # stejný bod historie se nezapočte dvakrát
    fam.update(T0 + hubmod.HIST_S)
    s.tick(T0 + hubmod.HIST_S)
    h = str(time.localtime(T0).tm_hour)
    d = s.stats.dny[time.strftime("%Y-%m-%d", time.localtime(T0))]
    assert d["nalada"][h][2] == 2


def test_notifikace_podle_aktivniho_okna(home):
    okno = Okno(pid=555)
    hub, s, d, p = mk(home, okno=okno)
    hub.receive(msg(T0, "UserPromptSubmit", prompt=SECRET))
    hub.fams[7].term = 555
    hub.receive(msg(T0 + 60, "Stop"))
    assert all(titulek != "projekt7" for titulek, _ in texty(d))      # terminál aktivní
    okno.pid = 1                        # uživatel je v jiném okně
    hub.receive(msg(T0 + 70, "UserPromptSubmit", prompt="x"))
    hub.receive(msg(T0 + 140, "Stop"))
    assert ("projekt7", "Hotovo za 1 min 10 s") in texty(d)
    assert p.hrane and all(SECRET not in str(a) for a in d.zobrazeno)
    okno.pid = None                     # bez KWinu: neznámé = neaktivní
    hub.receive(msg(T0 + 200, "UserPromptSubmit", prompt="x"))
    hub.receive(msg(T0 + 205, "Stop"))   # krátké kolo
    assert sum(t.startswith("Hotovo za") for _, t in texty(d)) == 1


def test_cekani_a_zruseni_odpovedi(home):
    hub, s, d, _ = mk(home)
    hub.receive(msg(T0, "PermissionRequest", tool_name="Bash"))
    assert texty(d) == [("projekt7", "Čeká na povolení: Bash")]
    assert d.zobrazeno[0][6] == {"urgency": 1} and d.zobrazeno[0][7] == 0
    nid = s.upoz.ids[7]
    hub.receive(msg(T0 + 5, "PreToolUse", tool_name="Bash", tool_use_id="a"))
    assert d.zavreno == [nid] and 7 not in s.upoz.ids


def test_cekani_zrusi_konec_nastroje_i_odpoved_v_bubline(home, app):
    c = cfg()
    c["upozorneni"]["cekani_po_s"] = 0.05
    hub, s, d, _ = mk(home, c)
    hub.receive(msg(T0, "PreToolUse", tool_name="Bash", tool_use_id="b1"))
    hub.receive(msg(T0 + 0.1, "PermissionRequest", tool_name="Bash"))
    assert 7 in s.upoz.cekajici
    hub.receive(msg(T0 + 1, "PostToolUse", tool_name="Read", tool_use_id="r1"))    # paralelní Read
    assert 7 in s.upoz.cekajici
    hub.receive(msg(T0 + 2, "PostToolUse", tool_name="Bash", tool_use_id="b1"))    # povoleno v terminálu
    assert 7 not in s.upoz.cekajici
    hub.receive(msg(T0 + 3, "PermissionRequest", tool_name="Bash"))
    assert 7 in s.upoz.cekajici
    p = dock.Povolovani(hub)
    hub.pozadavek(9, "s7", 7, {"nastroj": "Bash", "co": "ls", "vzdy": None, "agent": False}, T0 + 3)
    p.odpovez(9, "allow")                       # odpověď v bublině
    assert 7 not in s.upoz.cekajici
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        app.processEvents()
    assert d.zobrazeno == []                    # „Čeká na povolení“ nepřišlo po odpovědi


def test_hotovo_od_zacatku_skutecneho_kola(home):
    hub, s, d, _ = mk(home)
    hub.receive(msg(T0, "UserPromptSubmit", prompt="x"))
    hub.receive(msg(T0 + 10, "Stop"))
    hub.receive(msg(T0 + 1000, "SubagentStop", agent_id="a1", agent_type="Explore"))   # úloha na pozadí
    hub.receive(msg(T0 + 1040, "Stop"))
    assert ("projekt7", "Hotovo za 40 s") in texty(d)


def test_uspechy_oznameni_a_notifikace(home):
    oznameno = []

    def oznam(pid, text, sekund=4):
        oznameno.append((pid, text, sekund))
        return True
    hub, s, d, _ = mk(home)
    hub.oznam = oznam
    hub.receive(msg(T0, "SessionStart"))
    assert (7, "Nový úspěch: První krůček", 4) in oznameno
    assert any(t.startswith("familiar – projekt7") and "První krůček" in b for t, b in texty(d))
    assert any(a[6] == {"urgency": 0} and a[5] == [] for a in d.zobrazeno)
    assert s.odemcene() == []
    s.postup.xp = 1000
    assert {x["id"] for x in s.odemcene()} >= {"emote_srdicko", "klobouk_cepice"}
    # oznamovat_uspechy = false: jen se počítá
    hub2, s2, d2, _ = mk(home, cfg(postup={"oznamovat_uspechy": False}))
    hub2.oznam = oznam
    oznameno.clear()
    hub2.receive(msg(T0, "SessionStart", pid=8))
    assert oznameno == [] and d2.zobrazeno == [] and s2.postup.c["session"] >= 1


def test_oznam_jde_na_postavicku_v_hubu(home):
    hub, s, _, _ = mk(home)
    assert not s.oznam(7, "ahoj")           # postavička ještě není
    hub.receive(msg(T0, "SessionStart"))
    assert s.oznam(7, "ahoj")


def test_vypnute_statistiky_a_postup(home):
    c = cfg(statistiky={"zapnuto": False}, postup={"zapnuto": False})
    hub, s, _, _ = mk(home, c)
    hub.receive(msg(T0, "SessionStart"))
    s.tick(T0 + 100)
    s.ukonci()
    assert s.stats is None and s.postup is None
    assert not os.path.exists(home / "state" / "familiar")
    # zapnutí za běhu: hub.cfg se změní (Views.apply → hub.configure), služby to poznají v časovači
    hub.configure(cfg())
    s.tick(T0 + 200)
    hub.receive(msg(T0 + 201, "UserPromptSubmit", prompt="x"))
    assert s.stats.dny and s.postup.c["prompty"] == 1
    c3 = cfg(statistiky={"zapnuto": False, "ukladat_s": 30.0})
    hub.configure(c3)
    s.tick(T0 + 202)                    # vypnutí uloží, co se nasbíralo
    assert os.path.exists(s.stats.cesta) and s.stats.interval_s == 30.0
    hub.receive(msg(T0 + 203, "UserPromptSubmit", prompt="x"))
    assert sum(d["prompty"] for d in s.stats.dny.values()) == 1


def test_nastav_config_upozorneni_za_behu(home):
    hub, s, d, _ = mk(home)
    hub.configure(cfg(upozorneni={"notifikace": False, "zvuky": False}))
    s.tick(T0)
    hub.receive(msg(T0, "PermissionRequest", tool_name="Bash"))
    assert d.zobrazeno == []


def test_ikona_notifikaci_podle_skinu(home):
    hub, s, _, _ = mk(home, ikona=True)
    s.tick(T0)
    assert s.upoz.ikona == str(home / "cache" / "familiar" / "ikona.png") and os.path.exists(s.upoz.ikona)


def test_prepnuti_do_terminalu(home, monkeypatch):
    nahrano, odebrano = [], []
    monkeypatch.setattr(kwin, "nahraj_text", lambda text, name: nahrano.append((name, text)) or True)
    monkeypatch.setattr(kwin, "odeber", odebrano.append)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")          # backend oken kwin
    monkeypatch.setattr(okna, "PREPNOUT_ODEBRAT_MS", 0)
    hub, s, d, _ = mk(home)
    hub.receive(msg(T0, "PermissionRequest", tool_name="Bash"))
    hub.fams[7].term = 4321
    d.na_akci(s.upoz.ids[7], "default")          # klik na notifikaci
    assert nahrano and nahrano[0][0] == kwin.PREPNOUT and "=== 4321 &&" in nahrano[0][1]
    QApplication.processEvents()
    assert odebrano == [kwin.PREPNOUT]


def test_kwin_skripty_jsou_platny_text():
    t = kwin.js_aktivni(":1.42", sluzby.CESTA, sluzby.ROZHRANI)
    assert 'callDBus(":1.42", "/familiar/aktivni", "cz.familiar.Aktivni", "aktivni", w ? w.pid : 0)' in t
    assert "workspace.windowActivated.connect(hlas)" in t
    assert "ws[i].pid === 77 &&" in kwin.js_prepnout(77) and "workspace.activeWindow = w" in kwin.js_prepnout(77)
    node = shutil.which("node")
    if node:        # syntaxe JS (bez KWinu: jen kontrola)
        for text in (t, kwin.js_prepnout(77)):
            assert subprocess.run([node, "--check", "-"], input=text, text=True, capture_output=True).returncode == 0


def test_aktivni_okno_mimo_kde(monkeypatch, app):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    o = sluzby.AktivniOkno()
    assert not o.spust() and o.pid is None
    o.zastav()


# --- config, nabídka, doctor ---

def _load(home, text):
    p = home / "cfg" / "familiar" / "config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return config.load(str(p))


def test_config_vychozi_a_validace(home):
    d = config.defaults()
    assert d["upozorneni"]["nalehave_kriticke"] is False and d["upozorneni"]["zvuky"] is True
    assert d["statistiky"] == {"zapnuto": True, "retence_dni": 365, "ukladat_s": 60.0}
    assert d["postup"] == {"zapnuto": True, "oznamovat_uspechy": True, "ukladat_s": 60.0, **config.POSTUP_DOPLNKY}
    assert d["agenti"] == {"gemini": True, "codex": True}
    assert up.VYCHOZI is config.UPOZORNENI and set(up.VYCHOZI["vlastni"]) == set(up.DRUHY)
    c = _load(home, '[upozorneni]\nnocni_klid = "22:00-07:00"\nsada = "pipani"\nhlasitost = 30\n'
                    'druhy = ["chyba", "compact"]\n[upozorneni.vlastni]\nchyba = "~/a.wav"\n'
                    '[statistiky]\nretence_dni = 30\n[agenti]\ngemini = false\n')
    assert not c.errors and not c.warnings
    u = c["upozorneni"]
    assert (u["nocni_klid"], u["sada"], u["hlasitost"], u["druhy"]) == ("22:00-07:00", "pipani", 30, ["chyba", "compact"])
    assert u["vlastni"]["chyba"] == "~/a.wav" and c["statistiky"]["retence_dni"] == 30 and not c["agenti"]["gemini"]
    c = _load(home, '[upozorneni]\nnocni_klid = "25:00-07:00"\nsada = "vypnuto"\nhlasitost = 101\n'
                    'druhy = ["chyba", "nesmysl"]\nzvuky = "jemne"\n[statistiky]\nukladat_s = 1\n'
                    '[agenti]\ncodex = "ne"\nclaude = true\n')
    assert len(c.errors) == 7 and len(c.warnings) == 1
    assert any("nocni_klid" in e and "HH:MM-HH:MM" in e for e in c.errors)
    assert any("druhy" in e and "nesmysl" in e for e in c.errors)
    assert c["upozorneni"] == config.UPOZORNENI and c["statistiky"]["ukladat_s"] == 60.0 and c["agenti"]["codex"]
    for ok in ("", "8:00-9:30", " 22:00 - 07:00 "):
        assert not _load(home, f'[upozorneni]\nnocni_klid = "{ok}"\n').errors


def test_dialog_ma_nove_polozky(home):
    from PySide6.QtWidgets import QLineEdit
    from familiar import nastaveni
    d = nastaveni.Nastaveni()
    for path in ("upozorneni.notifikace", "upozorneni.zvuky", "upozorneni.sada", "upozorneni.hlasitost",
                 "upozorneni.nocni_klid", "statistiky.zapnuto", "postup.oznamovat_uspechy"):
        f = d.fields[path]
        assert f.polozka.rezim == nastaveni.JEDNODUCHE and f.form.isRowVisible(f.widget), path
    for path in ("upozorneni.nalehave_kriticke", "upozorneni.druhy", "agenti.gemini", "upozorneni.vlastni.chyba"):
        assert d.fields[path].polozka.rezim == nastaveni.POKROCILE, path
    w = d.fields["upozorneni.nocni_klid"]
    assert isinstance(w.widget, QLineEdit)
    w.put(" 22:00-07:00 ")
    d.fields["upozorneni.nalehave_kriticke"].put(True)
    assert d.ulozit()
    c = config.load()
    assert c["upozorneni"]["nocni_klid"] == "22:00-07:00" and c["upozorneni"]["nalehave_kriticke"] is True
    d = nastaveni.Nastaveni()
    d.fields["upozorneni.nocni_klid"].put("pozdě večer")
    assert not d.ulozit()


def test_nabidka_prepinace_notifikace_a_zvuky(home):
    hub = Hub(reap=False, bind=False, transcripts=False)
    hub.receive(msg(0, "SessionStart"))
    views = dock.Views(hub, None, config.load(), "dock")
    ui = nabidka.Ovladani(hub, views, lambda: views.apply(config.load()), tray=False)
    try:
        def akce(key):
            m = QMenu()
            ui.naplnit(m, key)
            return m, {a.text(): a for a in m.actions() if a.text()}
        m, a = akce(7)
        assert "Notifikace" not in a and "Zvuky" not in a       # jen v liště
        m, a = akce(None)
        assert a["Notifikace"].isChecked() and a["Zvuky"].isChecked()
        a["Zvuky"].trigger()
        QApplication.processEvents()
        assert config.load()["upozorneni"]["zvuky"] is False and hub.cfg["upozorneni"]["zvuky"] is False
        m, a = akce(None)
        assert not a["Zvuky"].isChecked()
        a["Notifikace"].trigger()
        QApplication.processEvents()
        text = open(paths.config_file(), encoding="utf-8").read()
        assert "notifikace = false" in text and "zvuky = false" in text
    finally:
        views.view.close()


def test_doctor_zvuky(home, monkeypatch):
    monkeypatch.setattr(up, "zpusob_prehravani", lambda: None)
    assert doctor.zvuky()[0] is False
    monkeypatch.setattr(up, "zpusob_prehravani", lambda: "pw-play")
    assert doctor.zvuky() == (True, "pw-play")


# --- D-Bus na dočasné session sběrnici ---

def _gi():
    try:
        return subprocess.run([sys.executable, "-c", "from gi.repository import Gio"], capture_output=True).returncode == 0
    except OSError:
        return False


AKTIVNI_KLIENT = r"""
import os, subprocess, sys, time
sys.path.insert(0, sys.argv[1])
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"
from PySide6.QtCore import QCoreApplication
from familiar import kwin, sluzby
app = QCoreApplication([])
nahrano = []
kwin.nahraj_text = lambda text, name: nahrano.append(text) or True     # KWin tu není
kwin.odeber = lambda name: None
o = sluzby.AktivniOkno()
ok = o.spust()
from PySide6.QtDBus import QDBusConnection
svc = QDBusConnection.sessionBus().baseService()
p = subprocess.Popen(["gdbus", "call", "--session", "--dest", svc, "--object-path", sluzby.CESTA,
                      "--method", sluzby.ROZHRANI + ".aktivni", "4321"], stdout=subprocess.DEVNULL)
konec = time.monotonic() + 5
while o.pid is None and time.monotonic() < konec:
    app.processEvents()
    time.sleep(0.01)
p.wait()
print(ok, o.pid, svc in nahrano[0])
o.zastav()
"""


@pytest.mark.skipif(not shutil.which("dbus-run-session") or not shutil.which("gdbus"), reason="chybí dbus-run-session")
def test_aktivni_okno_prijme_pid_pres_dbus():
    out = subprocess.run(["dbus-run-session", "--", sys.executable, "-c", AKTIVNI_KLIENT, ROOT],
                         capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["True", "4321", "True"], out.stderr[-2000:]


@pytest.mark.skipif(not shutil.which("dbus-run-session") or not _gi(), reason="chybí dbus-run-session nebo PyGObject")
def test_sluzby_proti_falesnemu_serveru(tmp_path):
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path), XDG_CACHE_HOME=str(tmp_path), QT_QPA_PLATFORM="offscreen")
    out = subprocess.run(["dbus-run-session", "--", sys.executable, os.path.join(ROOT, "tests", "upozorneni_dbus.py"),
                          "sluzby", "anotace"], capture_output=True, text=True, timeout=60, env=env)
    r = json.loads(out.stdout.strip().splitlines()[-1])
    notify = [v["hodnoty"] for v in r["volani"] if v["metoda"] == "Notify"]
    assert any("'akce'" in n and "Hotovo za 1 min 9 s" in n and "<byte 0x01>}, -1)" in n for n in notify)
    assert any("Čeká na povolení: Bash" in n for n in notify)
    assert any("První krůček" in n and "<byte 0x00>" in n for n in notify)
    assert set(r["prepnuto"]) == {7} and r["kwin"] == len(r["prepnuto"]) and not any(SECRET in n for n in notify)
    assert [v["metoda"] for v in r["volani"]].count("CloseNotification") >= 1     # ukonci() zavře zbylé
