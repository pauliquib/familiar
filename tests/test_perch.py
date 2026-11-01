# Režim perch: titulek pro perch.js, logika perch.js (QJSEngine s napodobeným KWinem)
# a kreslení oken bez ducha předchozího snímku. Každý test test_perch_js_* běží dvakrát:
# proti perch.js a proti jeho přepisu familiar/rozmisteni.py (X11 backend), se stejnými okny.
import json, os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication

from familiar import config, dock, rozmisteni
from familiar.hub import Hub

PERCH_JS = os.path.join(os.path.dirname(dock.__file__), "perch.js")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


STROJ = ["perch.js"]     # kdo počítá polohy v perch() a perch_zpravy()


def pytest_generate_tests(metafunc):
    if metafunc.function.__name__.startswith("test_perch_js"):
        metafunc.parametrize("stroj", ["perch.js", "rozmisteni.py"], indirect=True)


@pytest.fixture(autouse=True)
def stroj(request):
    STROJ[0] = getattr(request, "param", "perch.js")
    yield STROJ[0]
    STROJ[0] = "perch.js"


def py_perch(windows, pruchodu=1):
    """Totéž co perch.js nad napodobeným KWinem (KWIN níže), ale přes rozmisteni.py:
    → [(metoda, číslo, hodnota)] ohlášených změn; polohy zůstanou ve windows."""
    for i, w in enumerate(windows):
        w["internalId"] = "w" + str(i)
        w.setdefault("desktops", ["d1"])
        w.setdefault("activities", [])
    calls = []
    r = rozmisteni.Rozmisteni(hlas=lambda *a: calls.append(a))
    ws = rozmisteni.Plocha(windows, plocha="d1", aktivita="a1", oblast=AREA)
    for _ in range(pruchodu):
        r.layout(ws)
    return calls


# --- titulek ---

def test_titulek_nese_zakryti_a_roh(app):
    cfg = config.defaults()
    assert dock.placement(cfg) == "vpravo|120|4|8|navrchu|vpravo-dole"
    cfg["okno"].update(zakryti="rada", rada_roh="vlevo-nahore")
    hub = Hub(reap=False, bind=False, transcripts=False)
    fam = type("Fam", (), {"key": 1, "term": 42, "name": "x"})
    w = dock.Perch(hub, fam, 2, dock.placement(cfg))
    w.set((hub.skin, "idle", 0, None, None), "idle")
    assert w.windowTitle() == f"familiar|42|idle|0|vpravo|120|4|8|rada|vlevo-nahore|{w.cislo}|0"
    w.close()


# --- perch.js ---

KWIN = """
var sig = {connect: function () {}};
function QTimer() { this.timeout = sig; this.start = function () {}; }
var KWin = {MaximizeArea: 2};
var workspace = {currentDesktop: "d1", currentActivity: "a1", activeScreen: "s1", activeWindow: null,
    windowAdded: sig, windowRemoved: sig, windowActivated: sig, currentDesktopChanged: sig,
    currentActivityChanged: sig, stackingOrder: W,
    windowList: function () { return W; },
    clientArea: function () { return AREA; }};
W.forEach(function (w, i) {
    w.internalId = "w" + i; w.captionChanged = sig; w.frameGeometryChanged = sig;
    if (!w.desktops) w.desktops = ["d1"];
    if (!w.activities) w.activities = [];
});
"""
AREA = {"x": 0, "y": 0, "width": 1920, "height": 1050}     # pod ní panel
TERM = {"resourceClass": "kitty", "caption": "kitty", "pid": 100, "normalWindow": True, "minimized": False,
        "frameGeometry": {"x": 100, "y": 170, "width": 800, "height": 630},
        "clientGeometry": {"x": 100, "y": 200, "width": 800, "height": 600}}
COVER = {"resourceClass": "dolphin", "caption": "dolphin", "pid": 200, "normalWindow": True, "minimized": False,
         "frameGeometry": {"x": 0, "y": 0, "width": 1920, "height": 250},       # zakryje titulek, zbytek vidět
         "clientGeometry": {"x": 0, "y": 30, "width": 1920, "height": 220}}
FULL = {"x": 0, "y": 0, "width": 1920, "height": 1050}     # zakryje celý terminál
ON_TITLE = [712, 138]           # 100 + 800 - 120 - (64 + 4), 200 - 64 + 2
HIDDEN = [-20000, -20000]


def fam(state="working", place="vpravo|120|4|8|navrchu|vpravo-dole", term=100):
    return {"resourceClass": "familiar", "caption": f"familiar|{term}|{state}|0|{place}", "pid": 300,
            "normalWindow": False, "minimized": False,
            "frameGeometry": {"x": 0, "y": 0, "width": 64, "height": 64}}


def win(geo, **kw):
    """Další okno nad terminálem (normální, na ploše d1)."""
    return {"resourceClass": "x", "caption": "x", "pid": 201, "normalWindow": True, "minimized": False,
            "frameGeometry": geo, **kw}


def perch(*windows, term=None, cover=None, above=(), below=()):
    """Spustí perch.js nad okny (pořadí = stackingOrder: okna below, terminál, zakrývající okno,
    okna above, postavičky) a vrátí polohy postaviček [x, y]."""
    t = {**TERM, **(term or {})}
    c = {**COVER, **(cover or {})}
    n = len(below) + 2 + len(above)
    if STROJ[0] == "rozmisteni.py":
        ws = json.loads(json.dumps([*below, t, c, *above, *windows]))
        py_perch(ws)
        return [[w["frameGeometry"]["x"], w["frameGeometry"]["y"]] for w in ws[n:]]
    eng = QJSEngine()
    eng.globalObject().setProperty("SETUP", json.dumps({"W": [*below, t, c, *above, *windows], "AREA": AREA}))
    r = eng.evaluate("var S = JSON.parse(SETUP), W = S.W, AREA = S.AREA;" + KWIN)
    assert not r.isError(), r.toString()
    with open(PERCH_JS, encoding="utf-8") as f:
        r = eng.evaluate(f.read(), PERCH_JS)
    assert not r.isError(), r.toString()
    out = eng.evaluate(f"JSON.stringify(W.slice({n}).map(function (w) {{ "
                       "return [w.frameGeometry.x, w.frameGeometry.y, w.onAllDesktops === true]; }))")
    return [p[:2] for p in json.loads(out.toString())]


def test_perch_js_odkryty_titulek_ve_vsech_rezimech():
    for mode in ("navrchu", "schovat", "rada"):
        assert perch(fam(place=f"vpravo|120|4|8|{mode}|vpravo-dole"),
                     cover={"minimized": True}) == [ON_TITLE], mode


def test_perch_js_navrchu_zustane_na_zakrytem_titulku():
    assert perch(fam()) == [ON_TITLE]
    assert perch(fam(place="vpravo|120|4|8")) == [ON_TITLE]      # starý titulek = výchozí navrchu
    assert perch(fam(place="vpravo|120|4|8|nesmysl|x")) == [ON_TITLE]


def test_perch_js_schovat_jako_dřív():
    place = "vpravo|120|4|8|schovat|vlevo-nahore"
    assert perch(fam(place=place)) == [HIDDEN]
    assert perch(fam("waiting", place)) == [[1920 - 8 - 64, 1050 - 64 - 8]]    # roh na své straně, ne roh řady


def test_perch_js_rada_v_rohu_nad_panelem():
    rada = "vpravo|120|4|8|rada|"
    assert perch(fam(place=rada + "vpravo-dole"), fam(place=rada + "vpravo-dole")) == \
        [[1848, 978], [1848 - 68, 978]]
    assert perch(fam(place=rada + "vlevo-nahore")) == [[8, 8]]
    assert perch(fam(place=rada + "vpravo-nahore")) == [[1848, 8]]
    assert perch(fam(place=rada + "vlevo-dole")) == [[8, 978]]


def test_perch_js_schovany_terminal_schova_ve_vsech_rezimech():
    for mode in ("navrchu", "schovat", "rada"):
        place = f"vpravo|120|4|8|{mode}|vlevo-nahore"
        for term in ({"minimized": True}, {"desktops": ["d2"]}, {"activities": ["a2"]}):
            assert perch(fam(place=place), term=term) == [HIDDEN], (mode, term)
        waiting = perch(fam("waiting", place), term={"minimized": True})
        assert waiting == ([[8, 8]] if mode == "rada" else [[1848, 978]]), mode
    assert perch(fam(), term={"activities": ["a1", "a2"]}) == [ON_TITLE]


def test_perch_js_navrchu_uplne_zakryty_schova():
    corner = [[1848, 978]]
    assert perch(fam(), cover={"frameGeometry": FULL}) == [HIDDEN]                 # jedno okno
    assert perch(fam("waiting"), cover={"frameGeometry": FULL}) == corner          # čekající do rohu
    # složení dvou oken: horní polovina + dolní polovina terminálu
    top = {"x": 50, "y": 100, "width": 900, "height": 400}
    bottom = {"x": 90, "y": 500, "width": 820, "height": 400}
    assert perch(fam(), cover={"frameGeometry": top}, above=[win(bottom)]) == [HIDDEN]
    # levá a pravá půlka, mezi nimi 2px škvíra (pod tolerancí) = zakryté
    lh = {"x": 0, "y": 0, "width": 499, "height": 1050}
    rh = {"x": 501, "y": 0, "width": 1419, "height": 1050}
    assert perch(fam(), cover={"frameGeometry": lh}, above=[win(rh)]) == [HIDDEN]
    # škvíra 10 px je vidět → navrchu
    rh10 = {**rh, "x": 509}
    assert perch(fam(), cover={"frameGeometry": lh}, above=[win(rh10)]) == [ON_TITLE]
    # dialog se počítá jako normální okno
    assert perch(fam(), cover={"frameGeometry": top},
                 above=[win(bottom, normalWindow=False, dialog=True)]) == [HIDDEN]


def test_perch_js_navrchu_castecne_zakryty_zustane():
    assert perch(fam()) == [ON_TITLE]                                               # zakrytý jen titulek
    almost = {"x": 0, "y": 0, "width": 1920, "height": 790}                         # vidět 10 px dole
    assert perch(fam(), cover={"frameGeometry": almost}) == [ON_TITLE]


def test_perch_js_nepocita_okna_mimo_plochu_panely_postavicky():
    top = {"x": 50, "y": 100, "width": 900, "height": 400}
    bottom = {"x": 90, "y": 500, "width": 820, "height": 400}
    for other in ({"desktops": ["d2"]}, {"activities": ["a2"]}, {"minimized": True}, {"hidden": True},
                  {"normalWindow": False, "dock": True},                  # panel Plasmy
                  {"normalWindow": False, "desktopWindow": True},         # plocha
                  {"resourceClass": "familiar", "normalWindow": True}):   # postavička
        assert perch(fam(), cover={"frameGeometry": top}, above=[win(bottom, **other)]) == [ON_TITLE], other
    # okno pod terminálem ve stackingOrder ho nezakrývá
    assert perch(fam(), cover={"frameGeometry": top}, below=[win(bottom)]) == [ON_TITLE]


def test_perch_js_uplne_zakryty_v_rezimech_schovat_a_rada():
    full = {"frameGeometry": FULL}
    place = "vpravo|120|4|8|{}|vlevo-nahore"
    assert perch(fam(place=place.format("schovat")), cover=full) == [HIDDEN]
    assert perch(fam("waiting", place.format("schovat")), cover=full) == [[1848, 978]]
    assert perch(fam(place=place.format("rada")), cover=full) == [[8, 8]]          # zůstane v řadě
    assert perch(fam("waiting", place.format("rada")), cover=full) == [[8, 8]]


def test_perch_js_bez_terminalu_sedi_v_rohu():
    assert perch(fam(term=999)) == [[1848, 978]]
    assert perch(fam(term=999, place="vlevo|120|4|8|rada|vpravo-nahore")) == [[1848, 8]]


# --- kreslení bez ducha ---

def backing(app, w):
    """Obsah bufferu okna, jak ho uvidí kompozitor (grab() kreslí znovu a ducha neukáže)."""
    app.processEvents()
    return app.primaryScreen().grabWindow(w.winId()).toImage().convertToFormat(QImage.Format_ARGB32)


def frames(sk):
    return [(sk, "idle", 0, ("klid", None, None, 0, 0, 0), None),
            (sk, "hop", 1, ("radost", "hardhat", "heart", 1, 0, 0), None),          # póza, klobouk, emote
            (sk, "work_bash", 2, ("zvedavost", "beret", None, 0, 3, 1), None),      # drony
            (sk, "wave", 0, ("frustrace", None, None, 0, 0, 0), ("radost", 2)),     # přechod palety
            (sk, "sleep", 0, ("klid", None, None, 0, 0, 0), None)]


@pytest.mark.parametrize("scale", [1, 2, 3])
def test_perch_snimek_prepise_cele_okno(app, scale):
    hub = Hub(reap=False, bind=False, transcripts=False)
    fam_ = type("Fam", (), {"key": 1, "term": 0, "name": "x"})
    seq = frames(hub.skin)
    w = dock.Perch(hub, fam_, scale, "vpravo")
    w.set(seq[0], "idle")
    w.show()
    for n, frame in enumerate(seq[1:], 1):
        backing(app, w)
        w.set(frame, "working")
        clean = dock.Perch(hub, fam_, scale, "vpravo")
        clean.set(frame, "working")
        clean.show()
        got, want = backing(app, w), backing(app, clean)
        clean.close()
        assert got == want, f"snímek {n}: v okně zůstal předchozí snímek"
        alphas = {QImage.pixel(got, x, y) >> 24 for y in range(got.height()) for x in range(got.width())}
        assert alphas <= {0, 255}, "poloprůhledné okraje"
    w.close()


def test_perch_orez_nekresli_zakrytou_cast(app):
    hub = Hub(reap=False, bind=False, transcripts=False)
    fam_ = type("Fam", (), {"key": 1, "term": 0, "name": "x"})
    w = dock.Perch(hub, fam_, 2, "vpravo")
    w.set(frames(hub.skin)[0], "idle")
    w.show()
    full = backing(app, w)
    h = w.height() // 2

    def alfa(img, horni):
        return {QImage.pixel(img, x, y) >> 24 for y in (range(h) if horni else range(h, img.height()))
                for x in range(img.width())}
    assert alfa(full, False) != {0}                     # spodní půlka postavičky je vidět
    w.nastav_orez([(0, h, w.width(), w.height() - h)])
    got = backing(app, w)
    assert alfa(got, False) == {0} and alfa(got, True) == alfa(full, True)
    assert w._oblast().intersected(dock.QRegion(0, h, w.width(), w.height() - h)).isEmpty()
    w.nastav_orez([])
    assert backing(app, w) == full
    w.close()


def test_dock_snimek_prepise_cele_okno(app):
    hub = Hub(reap=False, bind=False, transcripts=False)
    seq = frames(hub.skin)

    def show(cells):
        d = dock.Dock(hub, cfg=config.defaults())
        d.timer.stop()
        d.cells = cells
        d._fit(len(cells))
        d.show()
        return d
    w = show([(1, "a", seq[0], "idle"), (2, "b", seq[1], "waiting")])
    for frame in seq[2:]:
        backing(app, w)
        w.cells = [(1, "a", frame, "working")]
        w._fit(1)
        w.update()
        clean = show(list(w.cells))
        assert backing(app, w) == backing(app, clean)
        clean.close()
    w.close()


# --- bublina vedle postavičky (perch.js) ---

def bub(num, side="vlevo", w=150, h=70):
    return {"resourceClass": "familiar", "caption": f"familiar-bublina|{num}|{side}|{w}x{h}", "pid": 300,
            "normalWindow": False, "minimized": False, "frameGeometry": {"x": 0, "y": 0, "width": w, "height": h}}


def test_perch_js_bublina_vedle_postavicky():
    f = fam(place="vpravo|120|4|8|navrchu|vpravo-dole|7")
    assert perch(f, bub(7)) == [ON_TITLE, [712 - 150, 138 + 64 - 70]]      # vlevo, spodky zarovnané
    assert perch(f, bub(7, "vpravo"))[1] == [712 + 64, 138 + 64 - 70]
    assert perch(f, bub(8))[1] == HIDDEN                                   # cizí bublina
    assert perch(fam(place="vpravo|120|4|8|schovat|vpravo-dole|7"), bub(7)) == [HIDDEN, HIDDEN]
    # čekající v levém rohu: vlevo by vyjela z obrazovky → přehodí se doprava od postavičky
    assert perch(fam("waiting", "vpravo|120|4|8|rada|vlevo-nahore|3"), bub(3), term={"minimized": True}) == \
        [[8, 8], [8 + 64, 2]]


def test_perch_js_bublina_nezakryva_titulek():
    """Okno bubliny (resourceClass familiar) se nepočítá jako okno zakrývající titulek."""
    tall = {**bub(7, h=300), "normalWindow": True}
    place = "vpravo|120|4|8|schovat|vpravo-dole|7"
    assert perch(fam(place=place), cover={"minimized": True}, above=[tall])[0] == ON_TITLE


def _velky_skin(base, size=(48, 40)):
    """Uživatelský skin s větším plátnem: jen idle (pruh u spodní hrany)."""
    from familiar import skin_export
    w, h = size
    path = base / "familiar" / "skins" / "velky"
    os.makedirs(path / "pal")
    colors = [None, "#000000", "#ff8800"]
    skin_export.write_gpl(path / "pal" / "base.gpl", "base", colors)
    px = bytearray(w * h)
    for k in range(w * (h - 8), w * h):
        px[k] = 2
    skin_export.write_sheet(str(path), "body", [px], [("idle", 1, 4, False)], colors, False, size=size)
    (path / "skin.toml").write_text(f'[skin]\nname = "Velký"\nsize = [{w}, {h}]\n[layers]\nbody = "body.png"\n'
                                    '[palettes]\nbase = "pal/base.gpl"\n[activity]\nidle = "idle"\n')


def test_vetsi_platno_v_docku_a_perch(app, tmp_path, monkeypatch):
    from familiar import skin
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _velky_skin(tmp_path)
    hub = Hub(reap=False, bind=False, transcripts=False)
    d = dock.Dock(hub, cfg=config.defaults())
    d.timer.stop()
    s = d.scale
    assert d.cell_w == 32 * s + 12
    hub.skin = skin.load("velky")           # výměna skinu za běhu: buňky docku se přizpůsobí
    assert hub.skin.size == (48, 40)
    d.tick()
    assert (d.cell_w, d.cell_h) == (48 * s + 12, 40 * s + 18) and d.width() == d.cell_w
    d.close()
    fam_ = type("Fam", (), {"key": 1, "term": 0, "name": "x"})
    w = dock.Perch(hub, fam_, 2, "vpravo")
    assert (w.width(), w.height()) == (96, 80)
    w.set((hub.skin, "idle", 0, None, None), "idle")
    w.set((hub.skin, "think", 0, None, None), "thinking")    # vestavěná animace na větším plátně
    assert (w.width(), w.height()) == (96, 80)
    w.close()


# --- procházka a přehození bubliny (M16) ---

def perch_zpravy(*windows, term=None, pruchodu=1):
    """Jako perch(), ale s `var DBUS` a napodobeným callDBus: → (polohy, [(metoda, číslo, hodnota)])."""
    t = {**TERM, **(term or {})}
    if STROJ[0] == "rozmisteni.py":
        ws = json.loads(json.dumps([t, *windows]))
        calls = py_perch(ws, pruchodu)
        return [[w["frameGeometry"]["x"], w["frameGeometry"]["y"]] for w in ws[1:]], calls
    eng = QJSEngine()
    eng.globalObject().setProperty("SETUP", json.dumps({"W": [t, *windows], "AREA": AREA}))
    r = eng.evaluate("var S = JSON.parse(SETUP), W = S.W, AREA = S.AREA, CALLS = [];"
                     "var DBUS = {sluzba: ':1.5', cesta: '/familiar/perch', rozhrani: 'cz.familiar.Perch'};"
                     "function callDBus(s, c, i, m, a, b) { CALLS.push([s, c, i, m, a, b]); }" + KWIN)
    assert not r.isError(), r.toString()
    with open(PERCH_JS, encoding="utf-8") as f:
        r = eng.evaluate(f.read(), PERCH_JS)
    assert not r.isError(), r.toString()
    for _ in range(pruchodu - 1):
        eng.evaluate("layout();")
    pos = json.loads(eng.evaluate("JSON.stringify(W.slice(1).map(function (w) { "
                                  "return [w.frameGeometry.x, w.frameGeometry.y]; }))").toString())
    calls = json.loads(eng.evaluate("JSON.stringify(CALLS)").toString())
    assert all(c[:3] == [":1.5", "/familiar/perch", "cz.familiar.Perch"] for c in calls)
    return pos, [tuple(c[3:]) for c in calls]


def test_perch_js_posun_prochazky_a_mez():
    # titulek „kitty“: text ~ 5 × 7 + 2 × 16 px kolem středu (500) → doleva smí do 533,5
    place = "vpravo|120|4|8|navrchu|vpravo-dole|7"
    pos, calls = perch_zpravy(fam("idle", place + "|50"))
    assert pos == [[712 - 50, 138]] and ("meze", "7", "178") in calls
    assert perch_zpravy(fam("idle", place + "|500"))[0] == [[712 - 178, 138]]      # dál nesmí
    assert perch_zpravy(fam("idle", place))[0] == [ON_TITLE]                        # starý titulek = 0
    assert perch_zpravy(fam("idle", place + "|-30"))[0] == [ON_TITLE]               # ven k tlačítkům ne
    # vlevo: od 220 doprava k textu (466,5) → mez 466,5 − 284
    pos, calls = perch_zpravy(fam("idle", "vlevo|120|4|8|navrchu|vpravo-dole|7|40"))
    assert pos == [[220 + 40, 138]] and ("meze", "7", "182") in calls
    # dlouhý titulek přes celou šířku: nechodí; bez titulku až ke kraji okna
    assert perch_zpravy(fam("idle", place + "|50"), term={"caption": "x" * 200})[0] == [ON_TITLE]
    pos, calls = perch_zpravy(fam("idle", place + "|50"), term={"caption": ""})
    assert ("meze", "7", "612") in calls
    # v rohu (schovaný terminál) se posun nepoužije
    assert perch_zpravy(fam("waiting", place + "|50"), term={"minimized": True})[0] == [[1848, 978]]


def test_perch_js_bublina_jde_s_postavickou_a_u_kraje_se_prehodi():
    pos, calls = perch_zpravy(fam("idle", "vpravo|120|4|8|navrchu|vpravo-dole|7|50"), bub(7))
    assert pos[1] == [712 - 50 - 150, 138 + 64 - 70] and ("strana", "7", "vlevo") in calls
    # v pravém rohu by bublina vpravo vyjela z obrazovky → vlevo od postavičky
    corner = "vpravo|120|4|8|rada|vpravo-dole|3"
    pos, calls = perch_zpravy(fam("waiting", corner), bub(3, "vpravo"), term={"minimized": True})
    assert pos == [[1848, 978], [1848 - 150, 978 + 64 - 70]] and ("strana", "3", "vlevo") in calls
    # nevejde se na žádnou stranu: jen zarovná k okraji
    pos, _ = perch_zpravy(fam("waiting", corner), bub(3, "vpravo", w=1900), term={"minimized": True})
    assert pos[1][0] == 1920 - 1900


def test_perch_js_hlasi_jen_zmeny():
    calls = perch_zpravy(fam("idle", "vpravo|120|4|8|navrchu|vpravo-dole|7|50"), bub(7), pruchodu=3)[1]
    assert sorted(calls) == [("meze", "7", "178"), ("orez", "7", ""),
                             ("strana", "7", "vlevo")]   # 3 průchody, zprávy jednou


def orez(calls):
    return [c[2] for c in calls if c[:2] == ("orez", "7")]


def test_perch_js_navrchu_orez_zakrytych_casti():
    place = "vpravo|120|4|8|navrchu|vpravo-dole|7"
    # postavička na [712, 138] 64×64; okno nad terminálem zakryje její spodek od y = 150
    pos, calls = perch_zpravy(win({"x": 700, "y": 150, "width": 300, "height": 500}), fam("idle", place))
    assert pos[1] == ON_TITLE and orez(calls) == ["0,12,64,52"]
    # dvě okna; zlomkové souřadnice (škálování) se zaokrouhlí ven
    pos, calls = perch_zpravy(win({"x": 700, "y": 150, "width": 300, "height": 500}),
                              win({"x": 740.5, "y": 0, "width": 10, "height": 159.5}), fam("idle", place))
    assert orez(calls) == ["0,12,64,52;28,0,11,22"]
    # okno mimo postavičku, dialog se počítá, panel ne
    assert orez(perch_zpravy(win({"x": 0, "y": 0, "width": 100, "height": 100}), fam("idle", place))[1]) == [""]
    dialog = win({"x": 0, "y": 0, "width": 1920, "height": 150}, normalWindow=False, dialog=True)
    assert orez(perch_zpravy(dialog, fam("idle", place))[1]) == ["0,0,64,12"]
    panel = win({"x": 0, "y": 0, "width": 1920, "height": 150}, normalWindow=False, dock=True)
    assert orez(perch_zpravy(panel, fam("idle", place))[1]) == [""]


def test_perch_js_orez_jen_na_titulku_v_rezimu_navrchu():
    cover = win({"x": 0, "y": 0, "width": 1920, "height": 150})
    # schovat: zakrytá zmizí, ořez není potřeba; v rohu (schovaný terminál) taky ne
    assert orez(perch_zpravy(cover, fam("idle", "vpravo|120|4|8|schovat|vpravo-dole|7"))[1]) == [""]
    assert orez(perch_zpravy(cover, fam("waiting", "vpravo|120|4|8|navrchu|vpravo-dole|7"),
                             term={"minimized": True})[1]) == [""]


# --- fokus: nové okno postavičky ho terminálu nebere ---

FOKUS_KWIN = """
var H = {};     // jméno signálu → handlery
function sig(name) { return {connect: function (f) { (H[name] = H[name] || []).push(f); }}; }
function emit(name, a) { (H[name] || []).forEach(function (f) { f(a); }); }
var nic = {connect: function () {}};
function QTimer() { var t = this; t.timeout = sig("timer"); t.start = function () { if (t.singleShot) PENDING.push(t); }; }
var PENDING = [];
var T = 0;
Date.now = function () { return T; };
function flush() { var p = PENDING; PENDING = []; p.forEach(function () { emit("timer"); }); }
var KWin = {MaximizeArea: 2};
var workspace = {currentDesktop: "d1", currentActivity: "a1", activeScreen: "s1", activeWindow: W[0],
    windowAdded: sig("added"), windowRemoved: sig("removed"), windowActivated: sig("activated"),
    currentDesktopChanged: nic, currentActivityChanged: nic, stackingOrder: W,
    windowList: function () { return W; },
    clientArea: function () { return AREA; }};
function prepare(w, i) {
    w.internalId = "w" + i; w.captionChanged = nic; w.frameGeometryChanged = nic;
    if (!w.desktops) w.desktops = ["d1"];
    if (!w.activities) w.activities = [];
}
W.forEach(prepare);
function aktivuj(w) { workspace.activeWindow = w; emit("activated", w); }
function pridej(w, aktivniPred) {     // KWin: nové okno aktivuje (před windowAdded, nebo po)
    prepare(w, W.length); W.push(w);
    if (aktivniPred) aktivuj(w);
    emit("added", w);
    if (!aktivniPred) aktivuj(w);
}
"""


def fokus(kroky):
    """perch.js nad napodobeným KWinem se signály; kroky = JS po nahrání skriptu.
    → resourceClass a titulek aktivního okna."""
    eng = QJSEngine()
    eng.globalObject().setProperty("SETUP", json.dumps({"W": [TERM], "AREA": AREA}))
    r = eng.evaluate("var S = JSON.parse(SETUP), W = S.W, AREA = S.AREA;" + FOKUS_KWIN)
    assert not r.isError(), r.toString()
    with open(PERCH_JS, encoding="utf-8") as f:
        r = eng.evaluate(f.read(), PERCH_JS)
    assert not r.isError(), r.toString()
    r = eng.evaluate(kroky + "; flush(); workspace.activeWindow.caption")
    assert not r.isError(), r.toString()
    return r.toString()


@pytest.mark.parametrize("pred", [True, False])
def test_nova_postavicka_vrati_fokus_terminalu(pred):
    assert fokus(f"pridej({json.dumps(fam())}, {str(pred).lower()})") == "kitty"
    bublina = {**fam(), "caption": "familiar-bublina|1|vlevo|100x40"}
    assert fokus(f"pridej({json.dumps(bublina)}, {str(pred).lower()})") == "kitty"


def test_fokus_vraci_jen_novym_oknum_postavicek():
    # jiné nové okno (i nastavení familiara) fokus dostane
    nastaveni = {**fam(), "caption": "Familiar – nastavení", "normalWindow": True}
    assert fokus(f"pridej({json.dumps(nastaveni)}, true)") == "Familiar – nastavení"
    # klik na existující postavičku ji nechá aktivní (terminál aktivuje layout podle kliků)
    assert fokus(f"pridej({json.dumps(fam())}, true); flush(); T += 2000; aktivuj(W[1])").startswith("familiar|")
    # uživatel mezitím klikl jinam: nepřebíjet
    jine = win({"x": 0, "y": 0, "width": 10, "height": 10}, caption="jine")
    assert fokus(f"pridej({json.dumps(jine)}, false); pridej({json.dumps(fam())}, true); "
                 "aktivuj(W[1])") == "jine"
