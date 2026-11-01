# Backend oken (familiar/okna.py): volba podle prostředí, config, doctor, instalace rozšíření
# GNOME Shellu a jeho logika v QJSEngine (perch.js nad falešným Mutterem musí dát totéž co nad
# napodobeným KWinem z test_perch.py), X11 backend ve vlastním Xvfb (tests/x11_perch.py).
import json, os, shutil, subprocess, sys, zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

from familiar import config, dock, gnome, install, nastaveni, okna, paths
from familiar.hub import Hub

import test_perch as tp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extras", "gnome-shell")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --- volba backendu ---

@pytest.mark.parametrize("env, cekam", [
    ({"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}, "kwin"),
    ({"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, "kwin"),
    ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "wayland"}, "gnome"),
    ({"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, "x11"),
    ({"XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, "x11"),
    ({"DISPLAY": ":1"}, "x11"),
    ({"XDG_CURRENT_DESKTOP": "sway", "XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, "zadny"),
    ({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "zadny"),
    ({}, "zadny"),
])
def test_volba_backendu_podle_prostredi(env, cekam):
    assert okna.zvol("auto", env)[0] == cekam
    assert okna.zvol("x11", env) == ("x11", "nastaveno v configu")     # config přebije prostředí


def test_config_backend(tmp_path):
    assert config.defaults()["okno"]["backend"] == "auto"
    assert config.OKNA_BACKENDY == ("auto", *okna.BACKENDY)
    p = tmp_path / "c.toml"
    p.write_text('[okno]\nbackend = "x11"\n')
    assert config.load(str(p))["okno"]["backend"] == "x11"
    p.write_text('[okno]\nbackend = "wayland"\n')
    c = config.load(str(p))
    assert c["okno"]["backend"] == "auto" and "okno.backend" in c.errors[0]
    polozka = next(p for p in nastaveni.POLOZKY if p.klic == "okno.backend")
    assert polozka.rezim == nastaveni.POKROCILE and {v for v, _ in polozka.volby} == set(config.OKNA_BACKENDY)


class Bez(okna.Zadny):
    """Backend bez perch (zadny), počítá volání."""
    def __init__(self):
        self.volani = []

    def perch_start(self, zpravy):
        self.volani.append("start")
        return False


def test_auto_bez_backendu_je_dock_a_vynuceny_perch_spadne_do_docku(app):
    cfg = config.Config(config.defaults(), None)
    b = Bez()
    views = dock.Views(Hub(reap=False, bind=False, transcripts=False), None, cfg, okna_=b)
    assert views.mode == "dock" and b.volani == []
    views.view.close()
    views = dock.Views(Hub(reap=False, bind=False, transcripts=False), None, cfg, forced_mode="perch", okna_=b)
    assert views.mode == "dock" and views.kwin_failed and b.volani == ["start"]
    views.view.close()
    views.quit()


def test_aktivni_okno_a_prepnuti_bez_backendu(app):
    from familiar import sluzby
    o = sluzby.AktivniOkno(backend=okna.Zadny())
    assert not o.spust() and o.pid is None and o.bus is None
    assert not sluzby.prepnout_na_terminal(4321, okna.Zadny())


def test_aktivni_okno_x11_cte_casovacem(app):
    from familiar import sluzby

    class Spojeni:
        def podporuje(self, name):
            return name == "_NET_ACTIVE_WINDOW"

        def aktivni_pid(self):
            return 4242
    b = okna.X11()
    b._spojeni = Spojeni()
    o = sluzby.AktivniOkno(backend=b)
    assert o.spust() and o.pid == 4242 and b._casovac.isActive()
    o.zastav()
    assert b._casovac is None and o.pid is None


# --- doctor ---

def test_doctor_kontroly_podle_backendu(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    rows = okna.kontroly("zadny")
    assert rows[0] == (True, "backend oken", "zadny (nastaveno v configu)") and "dock" in rows[1][2]
    monkeypatch.setattr(install, "dbus", lambda *a: None)
    rows = okna.kontroly("gnome")
    assert rows[1][0] is None and "--gnome-rozsireni" in rows[1][2]
    (tmp_path / ".local/share/gnome-shell/extensions" / gnome.UUID).mkdir(parents=True)
    (tmp_path / ".local/share/gnome-shell/extensions" / gnome.UUID / "metadata.json").write_text("{}")
    assert "neběží" in okna.kontroly("gnome")[1][2]
    monkeypatch.setattr(install, "dbus", lambda *a: "('1',)")
    assert okna.kontroly("gnome")[1][0] is True
    monkeypatch.setenv("DISPLAY", ":999")          # neexistující server: jen varování, dock
    rows = okna.kontroly("x11")
    assert rows[1][0] is None and "dock" in rows[1][2]


# --- instalace ---

@pytest.fixture
def home(tmp_path, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_BIN_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(install, "dbus", lambda *a: "()")
    monkeypatch.setattr(install, "installed", lambda name: None)
    monkeypatch.setattr(install, "_gnome_extensions", lambda *a: False)
    return tmp_path


def test_pravidlo_kwinu_jen_na_kde(home, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    install.install()
    assert not os.path.exists(paths.kwinrules())
    assert "--gnome-rozsireni" in capsys.readouterr().out        # na GNOME nabídne rozšíření
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    install.install()
    assert install.has_rule(open(paths.kwinrules()).read())


def test_instalace_rozsireni_gnome(home, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    zapnuto = []
    monkeypatch.setattr(install, "_gnome_extensions", lambda *a: zapnuto.append(a) or True)
    install.install(gnome_rozsireni=True)
    d = home / ".local/share/gnome-shell/extensions" / gnome.UUID
    assert sorted(os.listdir(d)) == ["extension.js", "metadata.json", "okna.js", "perch.js"]
    assert json.loads((d / "metadata.json").read_text())["uuid"] == gnome.UUID
    assert (d / "perch.js").read_text().startswith("// Vygenerováno") and "function layout" in (d / "perch.js").read_text()
    assert zapnuto == [("enable", gnome.UUID)] and "zapnuto" in capsys.readouterr().out
    install.install(gnome_rozsireni=True)        # idempotentní
    assert "vše už je v pořádku" in capsys.readouterr().out
    install.uninstall()
    assert not d.exists() and zapnuto[-1] == ("disable", gnome.UUID)


def test_rozsireni_bez_gnome_extensions_vypise_navod(home, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    install.install(gnome_rozsireni=True)
    assert f"gnome-extensions enable {gnome.UUID}" in capsys.readouterr().out


def test_wheel_obsahuje_rozsireni(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "_build"))
    try:
        import familiar_build
    finally:
        sys.path.pop(0)
    name = familiar_build.build_wheel(str(tmp_path))
    with zipfile.ZipFile(tmp_path / name) as z:
        names = set(z.namelist())
    assert {f"familiar/gnome_shell/{f}" for f in gnome.SOUBORY} <= names


# --- rozšíření GNOME Shellu: syntaxe a logika ---

@pytest.mark.skipif(not shutil.which("node"), reason="chybí node")
def test_rozsireni_je_platny_es_modul(tmp_path):
    (tmp_path / "perch.mjs").write_text(gnome.perch_modul())
    for path in (os.path.join(EXT, "extension.js"), os.path.join(EXT, "okna.js"), str(tmp_path / "perch.mjs")):
        text = open(path, encoding="utf-8").read()
        r = subprocess.run(["node", "--input-type=module", "--check"], input=text, text=True, capture_output=True)
        assert r.returncode == 0, (path, r.stderr)


HARNESS = r"""
import {spustPerch, spustAktivni, aktivujPid} from "./okna.js";
import {spust} from "./perch.js";

var WT = {NORMAL: 0, DOCK: 1, DIALOG: 3, MODAL_DIALOG: 4};

function signaly(o) {
    o._sig = {}; o._n = 0;
    o.connect = function (s, f) { var id = ++o._n; o._sig[id] = [s, f]; return id; };
    o.disconnect = function (id) { delete o._sig[id]; };
    o.emit = function (s) { for (var k in o._sig) if (o._sig[k][0] === s) o._sig[k][1](o); };
    o.pocet = function () { return Object.keys(o._sig).length; };
}

export function scenar(text) {
    var S = JSON.parse(text), volani = [], casovace = {}, nc = 0;
    var plochy = {};
    S.plochy.forEach(function (n) {
        plochy[n] = {jmeno: n, activate: function () { aktivni = plochy[n]; volani.push(["plocha", n]); },
                     get_work_area_for_monitor: function () { return S.area; }};
    });
    var aktivni = plochy[S.plochy[0]];
    var okna = S.okna.map(function (d, i) {
        var mw = {frame: d.frame, posun: [d.client.x - d.frame.x, d.client.y - d.frame.y,
                                          d.client.width - d.frame.width, d.client.height - d.frame.height],
            minimized: !!d.minimized, vsude: false, nahore: false,
            aktor: {visible: true, hide: function () { this.visible = false; }, show: function () { this.visible = true; }},
            titulek: d.titulek,
            get_id: function () { return 100 + i; }, get_wm_class: function () { return d.trida; },
            get_title: function () { return mw.titulek; }, get_pid: function () { return d.pid; },
            get_window_type: function () { return WT[d.typ]; },
            get_frame_rect: function () { return mw.frame; },
            frame_rect_to_client_rect: function (r) {
                return {x: r.x + mw.posun[0], y: r.y + mw.posun[1], width: r.width + mw.posun[2],
                        height: r.height + mw.posun[3]};
            },
            move_frame: function (u, x, y) { mw.frame = {x: x, y: y, width: mw.frame.width, height: mw.frame.height}; },
            is_on_all_workspaces: function () { return mw.vsude; }, stick: function () { mw.vsude = true; },
            is_above: function () { return mw.nahore; }, make_above: function () { mw.nahore = true; },
            get_workspace: function () { return plochy[d.plocha]; },
            get_compositor_private: function () { return mw.aktor; },
            minimize: function () { mw.minimized = true; },
            unminimize: function () { mw.minimized = false; volani.push(["odminimalizuj", i]); },
            get_work_area_current_monitor: function () { return S.area; }};
        signaly(mw);
        return mw;
    });
    var display = {list_all_windows: function () { return okna.slice(); },
        sort_windows_by_stacking: function (l) { return l.slice().sort(function (a, b) { return okna.indexOf(a) - okna.indexOf(b); }); },
        get_current_monitor: function () { return 0; }, focus_window: null};
    signaly(display);
    var wm = {get_active_workspace: function () { return aktivni; }};
    signaly(wm);
    var env = {display: display, workspaceManager: wm, WindowType: WT,
        aktivuj: function (mw) { volani.push(["aktivuj", okna.indexOf(mw)]); }, cas: function () { return 0; },
        casovac: function (ms, fn) { casovace[++nc] = fn; return nc; },
        zrusCasovac: function (id) { delete casovace[id]; },
        volej: function (s, c, r, m, a) { volani.push([m].concat(a)); }};
    var stop = spustPerch(env, spust, S.dbus || null);
    var polohy = okna.map(function (mw) { return mw.aktor.visible ? [mw.frame.x, mw.frame.y] : [-20000, -20000]; });
    var vsude = okna.map(function (mw) { return mw.vsude && mw.nahore; });
    if (S.klik !== undefined) {     // klik na postavičku: titulek s dalším počtem kliků
        var f = okna[S.klik];
        var p = f.titulek.split("|"); p[3] = String(parseInt(p[3]) + 1); f.titulek = p.join("|");
        f.emit("notify::title");
    }
    for (var k in casovace) casovace[k]();      // časovač perch.js (pojistka)
    var spojeni = okna.reduce(function (n, mw) { return n + mw.pocet(); }, display.pocet() + wm.pocet());
    stop();
    var po = okna.reduce(function (n, mw) { return n + mw.pocet(); }, display.pocet() + wm.pocet());
    var aktivni_volani = [];
    display.focus_window = okna[S.fokus || 0];
    var stopA = spustAktivni({display: display, volej: function (s, c, r, m, a) { aktivni_volani.push([s, c, r, m].concat(a)); }},
                             {sluzba: ":1.7", cesta: "/familiar/aktivni", rozhrani: "cz.familiar.Aktivni"});
    stopA();
    return JSON.stringify({polohy: polohy, volani: volani, vsude: vsude, spojeni: spojeni, po: po,
        casovacu: Object.keys(casovace).length, viditelne: okna.every(function (mw) { return mw.aktor.visible; }),
        aktivni: aktivni_volani, pocet_po_aktivnim: display.pocet(), aktivuj: aktivujPid(env, S.pid_aktivuj || 0)});
}
"""


def meta(w):
    """Okno KWinu z test_perch → falešné okno Mutteru."""
    typ = "NORMAL" if w.get("normalWindow") else "DIALOG" if w.get("dialog") else "DOCK"
    return {"trida": w["resourceClass"], "titulek": w["caption"], "pid": w["pid"], "typ": typ,
            "minimized": w.get("minimized", False), "plocha": (w.get("desktops") or ["d1"])[0],
            "frame": w["frameGeometry"], "client": w.get("clientGeometry", w["frameGeometry"])}


@pytest.fixture(scope="module")
def harness(app, tmp_path_factory):
    d = tmp_path_factory.mktemp("gnome")
    shutil.copy(os.path.join(EXT, "okna.js"), d / "okna.js")
    (d / "perch.js").write_text(gnome.perch_modul())
    (d / "harness.mjs").write_text(HARNESS)
    eng = QJSEngine()
    mod = eng.importModule(str(d / "harness.mjs"))
    assert not mod.isError(), mod.toString()
    fn = mod.property("scenar")
    assert fn.isCallable()

    def run(windows, term=None, cover=None, above=(), dbus=None, **kw):
        t, c = {**tp.TERM, **(term or {})}, {**tp.COVER, **(cover or {})}
        W = [t, c, *above, *windows]
        r = fn.call([json.dumps({"okna": [meta(w) for w in W], "area": tp.AREA, "plochy": ["d1", "d2"],
                                 "dbus": dbus, **kw})])
        assert not r.isError(), r.toString()
        out = json.loads(r.toString())
        out["polohy"] = out["polohy"][2 + len(above):]
        return out
    run.eng = eng       # engine musí žít, dokud se volá
    return run


SCENARE = [     # (okna postaviček a bublin, změny terminálu, zakrývající okno)
    ([tp.fam()], None, None),
    ([tp.fam()], None, {"frameGeometry": tp.FULL}),
    ([tp.fam("waiting")], None, {"frameGeometry": tp.FULL}),
    ([tp.fam(place="vpravo|120|4|8|schovat|vlevo-nahore")], None, None),
    ([tp.fam(place="vpravo|120|4|8|rada|vpravo-dole"), tp.fam(place="vpravo|120|4|8|rada|vpravo-dole")], None, None),
    ([tp.fam()], {"minimized": True}, None),
    ([tp.fam()], {"desktops": ["d2"]}, None),
    ([tp.fam("waiting", "vpravo|120|4|8|rada|vlevo-nahore|3"), tp.bub(3)], {"minimized": True}, None),
    ([tp.fam(place="vpravo|120|4|8|navrchu|vpravo-dole|7|50"), tp.bub(7)], None, None),
    ([tp.fam(place="vlevo|120|4|8|navrchu|vpravo-dole|7|40")], None, {"minimized": True}),
    ([tp.fam(term=999)], None, None),
]


@pytest.mark.parametrize("n", range(len(SCENARE)))
def test_rozsireni_perch_jako_kwin(harness, n):
    windows, term, cover = SCENARE[n]
    tp.STROJ[0] = "perch.js"
    assert harness(windows, term, cover)["polohy"] == tp.perch(*windows, term=term, cover=cover)


def test_rozsireni_zpravy_klik_a_uklid(harness):
    dbus = {"sluzba": ":1.5", "cesta": "/familiar/perch", "rozhrani": "cz.familiar.Perch"}
    place = "vpravo|120|4|8|navrchu|vpravo-dole|7|50"
    r = harness([tp.fam("idle", place), tp.bub(7)], cover={"minimized": True}, dbus=dbus, klik=2,
                pid_aktivuj=100)
    assert ["meze", "7", "178"] in r["volani"] and ["strana", "7", "vlevo"] in r["volani"]
    assert ["aktivuj", 0] in r["volani"]                     # klik → aktivace terminálu
    assert r["vsude"][2:] == [True, True]                    # postavička i bublina: všude a navrchu
    assert r["spojeni"] > 0 and r["po"] == 0 and r["casovacu"] == 0      # zastavení vše odpojí
    assert r["aktivni"] == [[":1.7", "/familiar/aktivni", "cz.familiar.Aktivni", "aktivni", 100]]
    assert r["pocet_po_aktivnim"] == 0 and r["aktivuj"] is True
    # bez dbus jen umisťuje; schované okno se po zastavení zase ukáže
    r = harness([tp.fam(place="vpravo|120|4|8|schovat|vpravo-dole")], pid_aktivuj=12345)
    assert r["polohy"] == [tp.HIDDEN] and r["volani"] == [] and r["viditelne"] and r["aktivuj"] is False


def test_klik_na_terminal_na_jine_plose(harness):
    r = harness([tp.fam()], term={"desktops": ["d2"], "minimized": True}, klik=2)
    assert ["odminimalizuj", 0] in r["volani"] and ["plocha", "d2"] in r["volani"] and ["aktivuj", 0] in r["volani"]


@pytest.mark.skipif(not shutil.which("gjs"), reason="chybí gjs")
def test_rozsireni_v_gjs(harness, tmp_path):
    """Totéž v GJS (SpiderMonkey jako GNOME Shell): okna.js a vygenerovaný perch.js jako ES moduly."""
    shutil.copy(os.path.join(EXT, "okna.js"), tmp_path / "okna.js")
    (tmp_path / "perch.js").write_text(gnome.perch_modul())
    (tmp_path / "harness.js").write_text(HARNESS)
    dbus = {"sluzba": ":1.5", "cesta": "/familiar/perch", "rozhrani": "cz.familiar.Perch"}
    W = [{**tp.TERM}, {**tp.COVER, "minimized": True}, tp.fam("idle", "vpravo|120|4|8|navrchu|vpravo-dole|7|50"),
         tp.bub(7)]
    setup = {"okna": [meta(w) for w in W], "area": tp.AREA, "plochy": ["d1", "d2"], "dbus": dbus, "klik": 2,
             "pid_aktivuj": 100}
    (tmp_path / "main.js").write_text('import {scenar} from "./harness.js";\n'
                                      f"print(scenar({json.dumps(json.dumps(setup))}));\n")
    r = subprocess.run(["gjs", "-m", str(tmp_path / "main.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    v = json.loads(r.stdout.strip().splitlines()[-1])
    q = harness(W[2:], cover={"minimized": True}, dbus=dbus, klik=2, pid_aktivuj=100)
    assert v["polohy"][2:] == q["polohy"] == [[662, 138], [662 - 150, 138 + 64 - 70]]
    assert v["volani"] == q["volani"] and v["po"] == 0 and v["aktivuj"] is True


# --- X11 v izolovaném Xvfb ---

@pytest.mark.skipif(not shutil.which("Xvfb"), reason="chybí Xvfb")
def test_x11_perch_v_xvfb():
    """Celý perch na X11 (backend x11, Perches, rozmisteni.py, libX11) proti falešnému správci
    oken ve vlastním Xvfb; uživatelův displej se nepoužije (DISPLAY jen na ten Xvfb)."""
    r, w = os.pipe()
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(w), "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                            pass_fds=(w,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(w)
    try:
        with os.fdopen(r) as f:
            cislo = f.readline().strip()
        assert cislo.isdigit()
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env.update(DISPLAY=f":{cislo}", QT_QPA_PLATFORM="xcb", XDG_SESSION_TYPE="x11", XDG_CURRENT_DESKTOP="test",
                   PYTHONPATH=ROOT)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "x11_perch.py")], env=env,
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr[-3000:]
        v = json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        xvfb.terminate()
        xvfb.wait()
    assert v["backend"] == "x11" and v["rezim"] == "perch" and v["umi"]
    assert v["na_titulku"] == [712, 138]                 # jako ON_TITLE v test_perch (64px okno)
    assert v["x_server"] == [712, 138]                   # skutečná poloha okna na X serveru
    assert v["meze"] == 178 and v["vsude"]               # mez procházky (titulek „kitty“), na všech plochách
    assert v["minimalizovany"] is False and v["jina_plocha"] is False and v["zpet"] is True
    assert v["bublina"] and v["strana"] == "vlevo" and v["bublina_pryc"]
    assert v["ramecek"] == [98, 170, 805, 634]          # klient 100,200 800×600 + okraje 2,3,30,4
    assert v["csd"] == [110, 210, 780, 580]             # bez neviditelných okrajů GTK
    assert v["zakryty"] is False                          # úplně zakrytý terminál (navrchu) ji schová
    assert v["klik"] == [v["terminal"], 1]               # klik → _NET_CURRENT_DESKTOP 1 + _NET_ACTIVE_WINDOW
    assert v["aktivni_pid"] == 4242 and v["prepnuti"] is True
    assert v["obnova_ms"] < 50, v["obnova_ms"]           # stav 40 oken z X serveru
