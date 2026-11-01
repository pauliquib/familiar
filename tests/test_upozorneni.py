# M13a: notifikace a zvuky (familiar/upozorneni.py) – pravidla, D-Bus volání, zvuky, generátor.
import importlib.util, json, os, shutil, struct, subprocess, sys, time, wave, zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from familiar import upozorneni as up
from familiar.adapters.claude_code import translate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_800_000_000.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def nast(**kw):
    n = up.nastaveni({})
    n.update(kw)
    return n


def cekej(app, s):
    konec = time.monotonic() + s
    while time.monotonic() < konec:
        app.processEvents()
        time.sleep(0.005)


# --- pravidla ---

def test_nastaveni_doplni_vychozi_a_ticho():
    n = up.nastaveni({"soustredeni": True, "upozorneni": {"hlasitost": 10, "vlastni": {"chyba": "/x.wav"}}})
    assert n["hlasitost"] == 10 and n["ticho"] and n["zvuky"] == up.VYCHOZI["zvuky"]
    assert n["vlastni"]["chyba"] == "/x.wav" and n["vlastni"]["dokonceno"] == ""
    assert not up.nastaveni(None)["ticho"]


def test_zakladni_pripad_upozorni():
    assert up.pravidla(up.DOKONCENO, {"trvani_s": 60}, nast(), T0) == (True, True, "ok")


@pytest.mark.parametrize("druh, kontext, kw, duvod", [
    (up.COMPACT, {}, {}, "druh vypnutý"),                               # compact není ve výchozích druzích
    (up.DOKONCENO, {"aktivni": True}, {}, "terminál je aktivní"),
    (up.POVOLENI, {"ceka_s": 3}, {}, "čeká krátce"),
    (up.OTAZKA, {"ceka_s": 9.9}, {}, "čeká krátce"),
    (up.DOKONCENO, {"trvani_s": 5}, {}, "krátké kolo"),
    (up.DOKONCENO, {}, {"notifikace": False, "zvuky": False}, "notifikace i zvuky vypnuté"),
    (up.DOKONCENO, {}, {"notifikace": False, "hlasitost": 0}, "notifikace i zvuky vypnuté"),
    (up.CHYBA, {}, {"ticho": True}, "ticho"),                           # v_tichu = nalehave: jen čekání
    (up.POVOLENI, {"ceka_s": 20}, {"ticho": True, "v_tichu": "nic"}, "ticho"),
])
def test_pravidla_odmitnou(druh, kontext, kw, duvod):
    assert up.pravidla(druh, kontext, nast(**kw), T0) == (False, False, duvod)


def test_aktivni_terminal_jen_kdyz_se_ma_hlidat():
    assert up.pravidla(up.CHYBA, {"aktivni": True}, nast(jen_neaktivni=False), T0)[0]


def test_ticho_ztlumi_zvuk_naléhavé_projde():
    assert up.pravidla(up.POVOLENI, {"ceka_s": 20}, nast(ticho=True), T0) == (True, False, "ok")
    assert up.pravidla(up.CHYBA, {}, nast(ticho=True, v_tichu="bez_zvuku"), T0) == (True, False, "ok")


def test_nocni_klid_jako_ticho():
    lt = time.localtime(T0)
    h = lt.tm_hour
    okno = f"{h:02d}:00-{(h + 1) % 24:02d}:00"
    assert up.pravidla(up.CHYBA, {}, nast(nocni_klid=okno), T0)[2] == "ticho"
    okno = f"{(h + 1) % 24:02d}:00-{(h + 2) % 24:02d}:00"
    assert up.pravidla(up.CHYBA, {}, nast(nocni_klid=okno), T0)[2] == "ok"


def test_v_okne_pres_pulnoc():
    def at(hh, mm):
        lt = time.localtime(T0)
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
    assert up.v_okne("22:00-07:00", at(23, 30)) and up.v_okne("22:00-07:00", at(6, 59))
    assert not up.v_okne("22:00-07:00", at(7, 0)) and not up.v_okne("22:00-07:00", at(12, 0))
    assert up.v_okne("9:00-17:30", at(17, 29)) and not up.v_okne("9:00-17:30", at(17, 30))
    assert not up.v_okne("", at(1, 0)) and not up.v_okne("nesmysl", at(1, 0)) and not up.v_okne("8:00-8:00", at(8, 0))


def test_rate_limit():
    n = nast()
    hist = [(T0 - 10, "s1", up.CHYBA)]
    assert up.pravidla(up.CHYBA, {"session": "s1"}, n, T0, hist)[2] == "rozestup"
    assert up.pravidla(up.CHYBA, {"session": "s2"}, n, T0, hist)[2] == "ok"
    assert up.pravidla(up.CHYBA, {"session": "s1"}, n, T0 + 31, hist)[2] == "ok"
    # čekání rozestup nebrzdí (má vlastní prodlevu), celkový limit ano
    assert up.pravidla(up.POVOLENI, {"session": "s1", "ceka_s": 20}, n, T0, [(T0 - 1, "s1", up.POVOLENI)])[0]
    hist = [(T0 - i, f"s{i}", up.DOKONCENO) for i in range(1, 7)]
    assert up.pravidla(up.POVOLENI, {"session": "x", "ceka_s": 20}, n, T0, hist)[2] == "limit za minutu"
    assert up.pravidla(up.POVOLENI, {"session": "x", "ceka_s": 20}, n, T0 + 60, hist)[2] == "ok"


def test_text_bez_promptu():
    assert up.text_pro(up.DOKONCENO, {"trvani_s": 75}) == "Hotovo za 1 min 15 s"
    assert up.text_pro(up.DOKONCENO, {"trvani_s": 3725}) == "Hotovo za 1 h 2 min"
    assert up.text_pro(up.POVOLENI, {"nastroj": "mcp__git__status"}) == "Čeká na povolení: mcp__git__status"
    assert up.text_pro(up.POVOLENI, {"nastroj": "rm -rf / TAJNE"}) == "Čeká na povolení"
    assert up.text_pro(up.OTAZKA, {"prompt": "TAJNE"}) == "Má otázku"


def test_zvuk_pro(tmp_path):
    n = nast(sada="pipani")
    assert up.zvuk_pro(up.CHYBA, n) == os.path.join(up.ZVUKY_DIR, "pipani", "chyba.wav")
    vlastni = tmp_path / "moje.wav"
    vlastni.write_bytes(b"RIFF")
    n["vlastni"] = {**n["vlastni"], "chyba": str(vlastni), "otazka": str(tmp_path / "chybi.wav")}
    assert up.zvuk_pro(up.CHYBA, n) == str(vlastni)
    assert up.zvuk_pro(up.OTAZKA, n).endswith("pipani/otazka.wav")       # chybějící → sada
    n["sada"] = "neznama"
    assert up.zvuk_pro(up.OTAZKA, n) is None and up.zvuk_pro(up.CHYBA, n) == str(vlastni)
    n["zvuky"] = False          # vypnuté zvuky umlčí i vlastní
    assert up.zvuk_pro(up.CHYBA, n) is None and not up.pravidla(up.CHYBA, {}, n, T0)[1]


def test_urgence_kriticka_jen_volitelne():
    assert {up.urgence(d, nast()) for d in up.DRUHY} == {up.NORMAL}
    n = nast(nalehave_kriticke=True)
    assert [up.urgence(d, n) for d in (up.POVOLENI, up.OTAZKA, up.CHYBA)] == [up.KRITICKA, up.KRITICKA, up.NORMAL]


def _ev(hook, **raw):
    return translate({"hook_event_name": hook, "session_id": "s", **raw}, T0, 7)


def test_druh_udalosti_a_ruseni():
    assert [up.druh_udalosti(e) for e in _ev("Stop")] == [up.DOKONCENO]
    assert [up.druh_udalosti(e) for e in _ev("PermissionRequest", tool_name="Bash")] == [up.POVOLENI]
    assert [up.druh_udalosti(e) for e in _ev("PermissionRequest", tool_name="AskUserQuestion")] == [up.OTAZKA]
    assert [up.druh_udalosti(e) for e in _ev("StopFailure", error="x")] == [up.CHYBA]
    assert [up.druh_udalosti(e) for e in _ev("PreCompact", trigger="auto")] == [up.COMPACT]
    assert [up.druh_udalosti(e) for e in _ev("PreCompact", trigger="manual")] == [None]
    assert [up.druh_udalosti(e) for e in _ev("PermissionRequest", tool_name="Bash", agent_id="a")] == [None]
    assert all(up.rusi(e) for e in _ev("UserPromptSubmit", prompt="x") + _ev("PreToolUse", tool_name="Bash"))
    assert not any(up.rusi(e) for e in _ev("PreToolUse", tool_name="Bash", agent_id="a") + _ev("Stop"))
    konec = _ev("PostToolUse", tool_name="Bash") + _ev("PostToolUseFailure", tool_name="Bash", error="Exit code 1")
    assert all(up.rusi(e) for e in konec) and all(up.rusi(e, "Bash") for e in konec)
    assert not any(up.rusi(e, "Edit") for e in konec)          # paralelní nástroj čekání neruší
    assert not any(up.rusi(e) for e in _ev("PostToolUse", tool_name="Bash", agent_id="a"))


# --- sestavení D-Bus volání ---

def test_argumenty_notify():
    a = up.argumenty_notify(7, "/ik.png", "projekt", "a <b> & c", 2, 0)
    assert a == ["familiar", 7, "/ik.png", "projekt", "a &lt;b&gt; &amp; c",
                 ["default", up.AKCE_TEXT, up.AKCE, up.AKCE_TEXT], {"urgency": 2}, 0]
    assert up.argumenty_notify(0, "", "p", "t", 1, -1, akce=False)[5] == []


def test_prikaz_gdbus_escapuje():
    cmd = up.prikaz_gdbus(up.argumenty_notify(3, "", "it's \\ x", "t", 1, -1, akce=False))
    i = cmd.index("--")
    assert cmd[:3] == ["gdbus", "call", "--session"]
    assert cmd[i + 1:] == ["'familiar'", "3", "''", "'it\\'s \\\\ x'", "'t'", "@as []", "{'urgency': <byte 1>}", "-1"]


class FalesnyDbus:
    def __init__(self):
        self.na_akci = self.na_zavreni = None
        self.zobrazeno, self.zavreno, self.dalsi = [], [], 41

    def zobraz(self, args):
        self.zobrazeno.append(args)
        if args[1]:
            return args[1]
        self.dalsi += 1
        return self.dalsi

    def zavri(self, nid):
        self.zavreno.append(nid)


class FalesnyPrehravac:
    def __init__(self):
        self.hrane = []

    def prehraj(self, cesta, hlasitost):
        self.hrane.append((cesta, hlasitost))
        return True


def mk(app, **sek):
    cfg = {"upozorneni": {"cekani_po_s": 0, "kolo_nad_s": 0, "sada": "pipani", **sek}}
    d, p = FalesnyDbus(), FalesnyPrehravac()
    hodiny = [T0]
    u = up.Upozorneni(cfg, dbus=d, prehravac=p, cas=lambda: hodiny[0])
    return u, d, p, hodiny


def test_nahrazeni_zruseni_a_akce(app):
    u, d, p, hodiny = mk(app)
    prepnuto = []
    u.prepnout.connect(prepnuto.append)
    assert u.udalost("s1", up.POVOLENI, {"jmeno": "proj", "pid": 99, "nastroj": "Bash"}) == "ok"
    assert d.zobrazeno[-1][1] == 0 and d.zobrazeno[-1][3] == "proj" and d.zobrazeno[-1][6] == {"urgency": 1}
    assert d.zobrazeno[-1][7] == 0          # čekání nevyprší samo
    assert p.hrane == [(os.path.join(up.ZVUKY_DIR, "pipani", "povoleni.wav"), 60)]
    hodiny[0] += 1
    u.udalost("s1", up.DOKONCENO, {"jmeno": "proj", "pid": 99, "trvani_s": 40})
    assert d.zobrazeno[-1][1] == 42 and d.zobrazeno[-1][7] == -1      # nahradí notifikaci téže session
    u.udalost("s2", up.CHYBA, {"jmeno": "jiny", "pid": 5})
    assert d.zobrazeno[-1][1] == 0 and u.ids == {"s1": 42, "s2": 43}
    d.na_akci(42, "terminal")
    d.na_akci(43, "default")
    d.na_akci(999, "default")               # cizí notifikace na sběrnici
    d.na_akci(43, "jina-akce")
    assert prepnuto == [99, 5]
    u.zrus("s1")
    assert d.zavreno == [42] and "s1" not in u.ids and 42 not in u.notif
    u.zrus("s1")
    assert d.zavreno == [42]
    d.na_zavreni(43)                        # zavřel uživatel / vypršela
    assert u.ids == {} and u.notif == {}


def test_bez_notifikace_jen_zvuk(app):
    u, d, p, _ = mk(app, notifikace=False)
    assert u.udalost("s", up.CHYBA, {}) == "ok"
    assert d.zobrazeno == [] and len(p.hrane) == 1


def test_odlozene_cekani(app):
    u, d, p, _ = mk(app, cekani_po_s=0.05)
    aktivni = [False]
    assert u.udalost("s", up.POVOLENI, {"aktivni": lambda: aktivni[0]}) == "odloženo"
    assert d.zobrazeno == []
    cekej(app, 0.15)
    assert len(d.zobrazeno) == 1 and not u.cekajici
    # uživatel odpoví dřív: nic
    u.udalost("t", up.OTAZKA, {})
    u.zrus("t")
    cekej(app, 0.15)
    assert len(d.zobrazeno) == 1
    # mezitím přepnul do terminálu: aktivita se zjišťuje až po prodlevě
    u.udalost("v", up.OTAZKA, {"aktivni": lambda: aktivni[0]})
    aktivni[0] = True
    cekej(app, 0.15)
    assert len(d.zobrazeno) == 1
    # nová událost téže session ruší odložené čekání
    u.udalost("w", up.POVOLENI, {})
    u.udalost("w", up.CHYBA, {})
    cekej(app, 0.15)
    assert [a[4] for a in d.zobrazeno[1:]] == ["Kolo skončilo chybou"]


def test_rate_limit_v_tride(app):
    u, d, p, hodiny = mk(app)
    assert u.udalost("s", up.CHYBA, {}) == "ok"
    hodiny[0] += 5
    assert u.udalost("s", up.CHYBA, {}) == "rozestup"
    assert len(d.zobrazeno) == 1 and len(p.hrane) == 1


def test_oznam_bez_zvuku_a_ne_v_tichu(app):
    u, d, p, _ = mk(app)
    assert u.oznam("familiar", "Nový úspěch: Hotovo!")
    assert d.zobrazeno[-1][5] == [] and d.zobrazeno[-1][6] == {"urgency": 0} and p.hrane == []
    u.nastav({"tichy": True})
    assert not u.oznam("familiar", "x")
    u.nastav({"upozorneni": {"notifikace": False}})
    assert not u.oznam("familiar", "x") and len(d.zobrazeno) == 1


def test_nastav_a_ukonci(app):
    u, d, p, _ = mk(app)
    u.nastav({"tichy": True, "upozorneni": {"cekani_po_s": 0}})
    assert u.udalost("s", up.CHYBA, {}) == "ticho"
    u.udalost("s", up.POVOLENI, {})
    assert p.hrane == [] and len(d.zobrazeno) == 1
    u.nastav({"upozorneni": {"cekani_po_s": 30}})
    u.udalost("x", up.OTAZKA, {})
    u.ukonci()
    assert d.zavreno == [42] and not u.cekajici and not u.ids


# --- zvuky ---

def test_prikaz_prehrani():
    assert up.prikaz_prehrani("pw-play", "/a.wav", 60) == ["pw-play", "--media-role=Notification", "--volume=0.60", "/a.wav"]
    assert up.prikaz_prehrani("paplay", "/a.wav", 150) == ["paplay", "--volume=65536", "--property=media.role=event", "/a.wav"]


def test_prehravac_spusti_proces_bez_blokovani(app, tmp_path, monkeypatch):
    znak = tmp_path / "hralo"
    monkeypatch.setattr(up, "prikaz_prehrani", lambda z, c, h: ["sh", "-c", f'sleep 0.05; echo "$0 {h}" > {znak}', c])
    pr = up.Prehravac(zpusob="pw-play")
    t = time.monotonic()
    assert pr.prehraj("/x.wav", 30)
    assert time.monotonic() - t < 0.04
    cekej(app, 0.4)
    assert znak.read_text().strip() == "/x.wav 30" and pr._proc is None
    assert not pr.prehraj(None, 30) and not pr.prehraj("/x.wav", 0)
    assert not up.Prehravac(zpusob=None).prehraj("/x.wav", 30)


def test_prehravac_nespustitelny_program(app, monkeypatch):
    monkeypatch.setattr(up, "prikaz_prehrani", lambda z, c, h: ["/neexistuje/prehravac", c])
    pr = up.Prehravac(zpusob="pw-play")
    pr.prehraj("/x.wav", 30)
    cekej(app, 0.2)
    assert pr._proc is None


def _zvuky_gen():
    spec = importlib.util.spec_from_file_location("zvuky_gen", os.path.join(ROOT, "tools", "zvuky.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vzorky(path):
    with wave.open(str(path)) as w:
        return w.getparams(), struct.unpack(f"<{w.getnframes()}h", w.readframes(w.getnframes()))


def test_zvuky_v_balicku_aktualni_a_ve_formatu(tmp_path):
    gen = _zvuky_gen()
    assert set(gen.DRUHY) == set(up.DRUHY) and set(gen.SADY) == set(up.SADY)
    gen.export(str(tmp_path))
    for sada in gen.SADY:
        for druh in up.DRUHY:
            nove, balik = tmp_path / sada / f"{druh}.wav", os.path.join(up.ZVUKY_DIR, sada, f"{druh}.wav")
            (p1, s1), (p2, s2) = _vzorky(nove), _vzorky(balik)
            assert p1 == p2 and len(s1) == len(s2)
            assert max(abs(a - b) for a, b in zip(s1, s2)) <= 1      # libm smí zaokrouhlit jinak
            assert (p2.nchannels, p2.sampwidth, p2.framerate) == (1, 2, gen.RATE)
            assert 0.1 <= p2.nframes / p2.framerate <= 0.6
            assert abs(max(abs(x) for x in s2) / 32767 - gen.PEAK) < 0.01
            assert s2[0] == 0 and abs(s2[-1]) < 300        # náběh a konec bez lupnutí
    assert "CC0" in (tmp_path / "CREDITS.txt").read_text()
    assert (tmp_path / "CREDITS.txt").read_text() == open(os.path.join(up.ZVUKY_DIR, "CREDITS.txt")).read()


def test_wheel_obsahuje_zvuky(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "_build"))
    try:
        import familiar_build
    finally:
        sys.path.pop(0)
    name = familiar_build.build_wheel(str(tmp_path))
    names = zipfile.ZipFile(tmp_path / name).namelist()
    for sada in ("pipani", "jemne"):
        for druh in up.DRUHY:
            assert f"familiar/zvuky/{sada}/{druh}.wav" in names
    assert "familiar/zvuky/CREDITS.txt" in names


# --- skutečná sběrnice (dočasná) s falešným serverem notifikací ---

def _gi():
    try:
        return subprocess.run([sys.executable, "-c", "from gi.repository import Gio"], capture_output=True).returncode == 0
    except OSError:
        return False


@pytest.mark.skipif(not shutil.which("dbus-run-session") or not _gi(), reason="chybí dbus-run-session nebo PyGObject")
@pytest.mark.parametrize("rezim", ["anotace", "bez"])
def test_dbus_falesny_server(rezim):
    out = subprocess.run(["dbus-run-session", "--", sys.executable, os.path.join(ROOT, "tests", "upozorneni_dbus.py"),
                          "klient", rezim], capture_output=True, text=True, timeout=60)
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["typovane"] == (rezim == "anotace")
    assert r["vysledky"] == ["ok", "ok"] and r["prepnuto"] == [4242] and r["zbyva"] == {}
    notify = [v for v in r["volani"] if v["metoda"] == "Notify"]
    close = [v for v in r["volani"] if v["metoda"] == "CloseNotification"]
    assert [v["typ"] for v in notify] == ["(susssasa{sv}i)"] * 2
    nid = r["ids"][0]
    assert r["ids"] == [nid, nid]
    assert "uint32 0," in notify[0]["hodnoty"] and f"uint32 {nid}," in notify[1]["hodnoty"]
    assert "{'urgency': <byte 0x02>}, 0)" in notify[0]["hodnoty"] and "<byte 0x01>}, -1)" in notify[1]["hodnoty"]
    assert "'terminal'" in notify[0]["hodnoty"] and "Hotovo za 1 min 15 s" in notify[1]["hodnoty"]
    assert close == [{"metoda": "CloseNotification", "typ": "(u)", "hodnoty": f"(uint32 {nid},)"}]


def test_ulozit_ikonu(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    from familiar import skin
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cesta = up.ulozit_ikonu(skin.builtin())
    assert cesta == str(tmp_path / "familiar" / "ikona.png")
    img = QImage(cesta)
    assert not img.isNull() and img.width() == img.height() == 64
