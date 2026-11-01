# Procházky a reakce na myš (M16): plán procházky, hranice, přerušení, gesta z událostí myši,
# napojení na hub (animace, výraz, emote) a renderer (titulek perch, klik, bublina v docku).
import os, random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from familiar import config, dock, kwin, pohyb, skin as skins
from familiar.hub import Hub
from familiar.pohyb import HLAZENI, NAVRAT_S, POHLED, STOUCHNUTI, ZAMOTANI, Gesta, Prochazka


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def cfg(**sekce):
    c = config.defaults()
    for k, v in sekce.items():
        c[k] = {**c[k], **v} if isinstance(v, dict) else v
    return c


def msg(ts, hook, pid=7, **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": "s", **raw}}


def prochazka(**c):
    return Prochazka({**pohyb.PROCHAZKY, **c}, rng=random.Random(3))


def projdi(p, od, do, meze=100, klid=True, krok=0.05):
    """[(čas, posun, jde, natočení)] po krocích."""
    out, t = [], od
    while t < do:
        out.append((t, *p.krok(t, klid, meze)))
        t = round(t + krok, 6)
    return out


# --- plán procházky ---

def test_prochazka_tam_zastavit_otocit_zpet():
    p = prochazka(interval_s=10, rychlost=40)
    stopa = projdi(p, 0, 60)
    start = next(t for t, x, jde, _ in stopa if jde)
    assert 5 <= start <= 15                                  # interval 10 s × 0,5–1,5
    assert all(x == 0 for t, x, *_ in stopa if t < start)
    domu = next(t for t, x, jde, smer in stopa if t > start + 1 and x == 0 and not jde)
    prvni = [s for s in stopa if start <= s[0] < domu]
    nejdal = max(x for _, x, *_ in prvni)
    assert 45 <= nejdal <= 100                               # 45–100 % meze
    assert all(x <= 100 + 1e-9 for _, x, *_ in stopa)
    # cestou ven kouká dovnitř (+1), domů ven (−1), mezitím zastavení s otočením
    smery = [smer for _, _, jde, smer in prvni if jde]
    assert smery[0] == 1 and smery[-1] == -1
    zastaveni = [smer for _, x, jde, smer in prvni if not jde and x > 0]
    assert 1 in zastaveni and -1 in zastaveni
    assert all(smer == 0 for t, _, _, smer in stopa if domu <= t < domu + 2)   # doma kouká obvykle
    # rychlost: na úseku nejvýš rychlost × krok
    for (_, x0, *_), (_, x1, *_) in zip(stopa, stopa[1:]):
        assert abs(x1 - x0) <= 40 * 0.05 + 1e-6


def test_prochazka_vypnuta_kratka_mez_a_dosah():
    assert all(x == 0 and not jde for _, x, jde, _ in projdi(prochazka(zapnuto=False, interval_s=5), 0, 30))
    assert all(x == 0 for _, x, *_ in projdi(prochazka(interval_s=5), 0, 30, meze=pohyb.MIN_DOSAH - 1))
    stopa = projdi(prochazka(interval_s=5, dosah=30), 0, 40, meze=500)
    assert 0 < max(x for _, x, *_ in stopa) <= 30            # dosah z configu omezí i širokou mez


def test_prochazka_zuzeny_titulek_vrati_domu():
    p = prochazka(interval_s=5, rychlost=40)
    stopa = projdi(p, 0, 20)
    t, x = next((t, x) for t, x, jde, _ in stopa if x > 40)
    x2, jde, smer = p.krok(t + 0.05, True, 20)              # titulek se zúžil pod polohu
    assert x2 <= 20 and smer == -1
    assert all(x <= 20 for _, x, *_ in projdi(p, t + 0.1, t + 10, meze=20))
    assert p.x == 0


def test_prochazka_preruseni_zustane_a_pak_dojde_domu():
    p = prochazka(interval_s=5, rychlost=40)
    stopa = projdi(p, 0, 20)
    t = next(t for t, x, jde, _ in stopa if jde and x > 20)
    x = p.x
    assert p.krok(t + 0.05, False, 100) == (x, False, 0)     # událost: stojí, kde je
    assert p.krok(t + 5, False, 100) == (x, False, 0)
    assert not p.probiha
    # zase klid: chvíli stojí, po NAVRAT_S jde domů
    assert p.krok(t + 6, True, 100) == (x, False, 0)
    assert p.krok(t + 6 + NAVRAT_S - 0.1, True, 100)[1:] == (False, 0)
    _, jde, smer = p.krok(t + 6 + NAVRAT_S, True, 100)
    assert jde and smer == -1
    assert min(x for _, x, *_ in projdi(p, t + 6 + NAVRAT_S, t + 12)) == 0
    # přerušení s užší mezí ji dodrží
    p.x = 80
    assert p.krok(100, False, 30)[0] == 30


# --- gesta myši ---

def test_gesta_klik_a_rychle_klikani():
    g = Gesta()
    assert [g.klik(t) for t in (0, 0.3, 0.6)] == [STOUCHNUTI] * 3
    assert g.klik(0.9) == ZAMOTANI                           # 4 kliky za 1,5 s
    assert g.klik(1.0) == STOUCHNUTI                         # počítá se znovu
    g2 = Gesta()
    assert {g2.klik(t) for t in (0, 1, 2, 3, 4, 5)} == {STOUCHNUTI}     # pomalé klikání


def tah(g, t0, body, dt):
    out = None
    for k, (x, y) in enumerate(body):
        out = g.pohyb(t0 + k * dt, x, y) or out
    return out


def test_gesta_hlazeni_najeti_a_mavnuti():
    tam_a_zpet = [(10 + 8 * (k % 6 if (k // 6) % 2 == 0 else 6 - k % 6), 20) for k in range(24)]
    g = Gesta()
    assert tah(g, 0, tam_a_zpet, 0.06) == HLAZENI            # ~130 px/s, obraty
    assert tah(g, 2, tam_a_zpet, 0.06) is None               # pauza mezi hlazeními
    assert tah(g, 7, tam_a_zpet, 0.06) == HLAZENI
    assert tah(Gesta(), 0, tam_a_zpet, 0.005) is None        # máchnutí: krátké a rychlé
    rovne = [(10 + 4 * k, 20) for k in range(30)]
    assert tah(Gesta(), 0, rovne, 0.06) is None              # bez obratů to není hlazení
    rychle = [(0 if k % 2 else 300, 20) for k in range(20)]
    assert tah(Gesta(), 0, rychle, 0.05) is None             # moc rychle
    g = Gesta()
    assert g.najeti(0) == POHLED and g.najeti(1) is None and g.najeti(5) == POHLED


# --- hub: animace, výraz, přerušení ---

def hub_(c=None):
    h = Hub(reap=False, bind=False, cfg=c or cfg(), transcripts=False)
    h.receive(msg(0, "SessionStart", cwd="/tmp/x"))
    fam = h.fams[7]
    fam.prochazka.rng = random.Random(3)
    return h, fam


def bez(fam, od, do, krok=0.1):
    out, t = [], od
    while t < do:
        out.append((t, fam.update(t), fam.chuze))
        t = round(t + krok, 6)
    return out


def do_chuze(fam, od=0, kroku=10):
    """Krokuje, dokud postavička kus neujde; vrací čas."""
    t, n = od, 0
    while n < kroku:
        t = round(t + 0.1, 6)
        assert t < od + 40, "procházka nezačala"
        a = fam.update(t)
        if fam.chuze[1]:
            n += 1
            assert a[0] == "walk" or fam.skin.walk_anim() is None
    return t


def test_familiar_prochazka_s_chuzi_a_preruseni():
    h, fam = hub_(cfg(prochazky={"interval_s": 5.0}))
    fam.meze = 100
    stopa = bez(fam, 0, 20)
    jde = [(t, a, ch) for t, a, ch in stopa if ch[1]]
    assert jde and all(a[0] == "walk" for _, a, _ in jde)    # Robo-kun má chůzi
    assert all(ch[3] == 0 for *_, ch in jde)                 # s vlastní chůzí bez poskoku
    h, fam = hub_(cfg(prochazky={"interval_s": 5.0}))
    fam.meze = 100
    t = do_chuze(fam)
    h.receive(msg(t + 0.05, "UserPromptSubmit", prompt="ahoj"))
    x = fam.chuze[0]
    later = bez(fam, t + 0.1, t + 3)
    assert all(ch == (x, False, 0, 0) for *_, ch in later)   # stojí na místě, nekráčí
    assert later[-1][1][0] != "walk"


def test_skin_bez_chuze_poskakuje_a_nepujci_si_robokuna():
    s = skins.load("kvetina")
    assert s.walk_anim() is None and s.facing is None
    assert skins.load("skejtak").walk_anim() == "ride" and skins.load("skejtak").facing == "right"
    assert skins.builtin().walk_anim() == "walk" and skins.load("robokun").walk_anim() == "walk"
    h, fam = hub_(cfg(skin="kvetina", prochazky={"interval_s": 5.0}))
    fam.meze = 100
    stopa = [(a, ch) for _, a, ch in bez(fam, 0, 20, 0.05) if ch[1]]
    assert stopa and all(a[0] == "idle" for a, _ in stopa)
    assert {ch[3] for _, ch in stopa} == {0, 1}


def test_reakce_na_mys():
    h, fam = hub_()
    assert h.reaguj(7, STOUCHNUTI, 1.0)
    assert fam.update(1.1)[0] == "hop"                       # poskočí
    assert fam.update(2.0)[0] == "idle"
    assert h.reaguj(7, ZAMOTANI, 3.0)
    anim, _, look = fam.update(3.1)
    assert anim == "stumble" and look[0] == "zmatek" and look[2] == "spiral"
    anim, _, look = fam.update(5.0)                          # pak se chvíli zlobí
    assert anim == "idle" and look[0] == "frustrace" and look[2] == "grawlix"
    assert not h.reaguj(7, STOUCHNUTI, 5.1)                  # rozzlobená na šťouchání nereaguje
    assert h.reaguj(7, HLAZENI, 5.2)                         # hlazení ji udobří
    look = fam.update(5.3)[2]
    assert look[0] == "radost" and look[2] == "heart"
    assert not h.reaguj(7, POHLED, 5.4)                      # najetí jinou reakci nepřeruší
    assert fam.update(9.0)[2][2] is None
    assert not h.reaguj(99, STOUCHNUTI, 10)                  # cizí klíč


def test_reakce_ticho_soustredeni_a_vypnuto():
    h, fam = hub_(cfg(tichy=True))
    assert h.reaguj(7, ZAMOTANI, 1.0)
    anim, _, look = fam.update(1.1)
    assert anim == "stumble" and look[2] is None             # v tichém režimu bez emotu
    for c in (cfg(soustredeni=True), cfg(mys={"zapnuto": False})):
        h, fam = hub_(c)
        assert not h.reaguj(7, STOUCHNUTI, 1.0)
    h, fam = hub_(cfg(mys={"hlazeni": False, "najeti": False}))
    assert not h.reaguj(7, HLAZENI, 1.0) and not h.reaguj(7, POHLED, 1.0)
    h.uspat(True, 7)
    assert not h.reaguj(7, STOUCHNUTI, 2.0)


def test_soustredeni_a_reakce_zastavi_prochazku():
    h, fam = hub_(cfg(soustredeni=True, prochazky={"interval_s": 5.0}))
    fam.meze = 100
    assert all(not ch[1] and ch[0] == 0 for *_, ch in bez(fam, 0, 30))
    h, fam = hub_(cfg(prochazky={"interval_s": 5.0}))
    fam.meze = 100
    t = do_chuze(fam)
    x = fam.chuze[0]
    assert h.reaguj(7, STOUCHNUTI, t + 0.05)
    assert fam.update(t + 0.1)[0] == "hop" and fam.chuze == (x, False, 0, 0)


def test_emote_na_prochazce_pocka():
    h, fam = hub_(cfg(prochazky={"interval_s": 5.0}))
    fam.meze = 100
    t = do_chuze(fam, kroku=1)
    fam.pops.append("flower")
    during, after = [], []
    while fam.prochazka.probiha:
        t = round(t + 0.1, 6)
        during.append(fam.update(t)[2][2])
    assert during and set(during) == {None}
    assert any(a[2][2] == "flower" for _, a, _ in bez(fam, t + 0.1, t + 3))


# --- renderer ---

class _Fam:
    def __init__(self, chuze):
        self.chuze = chuze


def test_poza_posun_po_pixelech_a_zrcadleni():
    robo, kvet = skins.builtin(), skins.load("kvetina")
    assert dock.poza(_Fam((14.2, True, 1, 0)), robo, 2, True) == (14, 0, True)     # perch vpravo: dovnitř = doleva
    assert dock.poza(_Fam((14.2, True, -1, 0)), robo, 2, True) == (14, 0, False)   # domů doprava
    assert dock.poza(_Fam((13.0, True, 1, 0)), robo, 3, False) == (12, 0, False)   # dock: dovnitř = doprava
    assert dock.poza(_Fam((13.0, True, -1, 1)), robo, 3, False) == (12, 3, True)
    assert dock.poza(_Fam((13.0, True, 1, 1)), kvet, 2, True)[2] is False         # zepředu se nezrcadlí
    assert dock.poza(_Fam((6.2, False, 0, 0)), robo, 2, True) == (6, 0, False)     # přerušená: obvykle


def mys(typ, tlacitko, buttons=None):
    return QMouseEvent(typ, QPointF(30, 30), QPointF(30, 30), tlacitko,
                       tlacitko if buttons is None else buttons, Qt.NoModifier)


def test_perch_titulek_s_posunem_a_klik(app):
    h, fam = hub_()
    w = dock.Perch(h, fam, 2, dock.placement(cfg()))
    w.set((h.skin, "idle", 0, None, None), "idle", None, (12, 0, False))
    assert w.windowTitle().endswith(f"|{w.cislo}|12")
    press = mys(QEvent.MouseButtonPress, Qt.LeftButton)
    w.mousePressEvent(press)                                 # výchozí oboji: přepne i šťouchne
    assert w.clicks == 1 and fam.reakce[0] == STOUCHNUTI
    fam.reakce = None
    w.mys = {**pohyb.MYS, "klik": "terminal"}
    w.mousePressEvent(press)
    assert w.clicks == 2 and fam.reakce is None
    w.mousePressEvent(mys(QEvent.MouseButtonPress, Qt.MiddleButton))
    assert fam.reakce[0] == STOUCHNUTI                       # prostřední šťouchne vždy
    fam.reakce = None
    w.mys = {**pohyb.MYS, "klik": "stouchnout"}
    w.gesta = Gesta()
    w.mousePressEvent(press)
    assert w.clicks == 2 and fam.reakce[0] == STOUCHNUTI
    w.mouseDoubleClickEvent(mys(QEvent.MouseButtonDblClick, Qt.LeftButton))
    assert w.clicks == 3                                     # na terminál dvojklik
    w.mys = {**pohyb.MYS, "zapnuto": False}
    fam.reakce = None
    w.mousePressEvent(press)
    assert w.clicks == 4 and fam.reakce is None              # bez myši jako dřív
    w.close()


def test_perch_bublina_ocasek_podle_skutecne_strany(app):
    h, fam = hub_()
    w = dock.Perch(h, fam, 2, dock.placement(cfg()))
    w.set((h.skin, "idle", 0, None, None), "idle")
    w.ukaz_bublinu(("text", "čte hub.py"))
    from familiar import bublina
    assert w.bublina.smer == bublina.VPRAVO                  # vlevo od postavičky, ocásek doprava
    assert "|vlevo|" in w.bublina.windowTitle()
    w.nastav_stranu_bubliny("vpravo")                        # perch.js ji přehodil
    assert w.bublina.smer == bublina.VLEVO and "|vlevo|" in w.bublina.windowTitle()
    w.close()


def test_dock_klik_stouchne_tazeni_ne(app):
    h, fam = hub_()
    d = dock.Dock(h, cfg=cfg())
    d.timer.stop()
    d.tick()
    r = d.bunky[0][2][2].translated(6, 0)
    pos = QPointF(r.center())
    ev = lambda typ, b, bs=None: QMouseEvent(typ, pos, pos, b, b if bs is None else bs, Qt.NoModifier)
    d.mousePressEvent(ev(QEvent.MouseButtonPress, Qt.LeftButton))
    d.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton))
    assert fam.reakce[0] == STOUCHNUTI
    fam.reakce = None
    opened = []
    d.panel = opened.append
    d.mouseDoubleClickEvent(ev(QEvent.MouseButtonDblClick, Qt.LeftButton))
    d.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton))
    assert opened == [7] and fam.reakce is None              # dvojklik = panel, ne šťouchnutí
    d.close()


def test_dock_misto_na_prochazku_a_bublina_u_kraje(app):
    h, fam = hub_()
    d = dock.Dock(h, cfg=cfg())
    d.timer.stop()
    d.tick()
    w = h.skin.size[0] * d.scale
    assert d.misto == w and d.bunky[0][1] >= d.cell_w + w    # buňka má místo na procházku
    d.close()
    d = dock.Dock(h, cfg=cfg(prochazky={"zapnuto": False}))
    assert d.misto == 0
    # bublina: dole pod buňkou; u spodního kraje obrazovky nad ní a okno se posune nahoru
    h.oznam(7, "ahoj, tohle je zpráva", 60)
    d.show()
    d.tick()
    b = d.bubliny[7][0]
    assert d.dy == 0 and b.y() > d.cell_h
    area = d.screen().availableGeometry()
    d.move(100, area.bottom() - d.cell_h - 5)
    top = d.y()
    d._fit()
    assert d.dy == b.height() + 1 and b.y() + b.height() < d.dy
    assert d.y() == top - d.dy                               # buňky zůstaly na místě
    from familiar import bublina
    assert b.smer == bublina.DOLU
    d.close()


def test_kwin_load_vlozi_dbus(monkeypatch):
    texts = []
    monkeypatch.setattr(kwin, "nahraj_text", lambda text, name: texts.append((name, text)) or True)
    monkeypatch.setattr(kwin, "nahraj", lambda path, name: texts.append((name, path)) or True)
    monkeypatch.setattr(kwin, "perch_dbus", {"sluzba": ":1.5", "cesta": "/familiar/perch", "rozhrani": "cz.x"})
    assert kwin.load()
    name, text = texts[-1]
    assert name == kwin.NAME and text.startswith('var DBUS = {"sluzba": ":1.5"') and "function layout" in text
    monkeypatch.setattr(kwin, "perch_dbus", None)
    assert kwin.load() and texts[-1] == (kwin.NAME, kwin.SCRIPT)


def test_perch_zpravy_sloty():
    z = dock.PerchZpravy()
    z.meze("3", "178")
    z.meze("4", "nesmysl")
    z.strana("3", "vpravo")
    z.strana("4", "hore")
    assert z.meze_px == {"3": 178} and z.strany == {"3": "vpravo", "4": None}
    z.orez("3", "0,12,64,52;28,0,10,22")
    z.orez("4", "1,2,x,4")
    z.orez("5", "1,2,3;4,5,6,7")
    z.orez("6", "")
    assert z.orezy == {"3": ((0, 12, 64, 52), (28, 0, 10, 22)), "4": (), "5": ((4, 5, 6, 7),), "6": ()}


def test_config_prochazky_a_mys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = config.defaults()
    assert d["prochazky"] == pohyb.PROCHAZKY and d["mys"] == pohyb.MYS
    path = tmp_path / "familiar" / "config.toml"
    path.parent.mkdir()
    path.write_text('[prochazky]\nrychlost = 1000\ndosah = 50\n[mys]\nklik = "nevim"\nhlazeni = false\n')
    c = config.load(str(path))
    assert c["prochazky"]["rychlost"] == pohyb.PROCHAZKY["rychlost"] and c["prochazky"]["dosah"] == 50
    assert c["mys"]["klik"] == "oboji" and c["mys"]["hlazeni"] is False
    assert len(c.errors) == 2
