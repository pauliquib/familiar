# M17: okno Statistiky a úspěchy, `familiar statistiky`, odemčené doplňky na postavičce,
# oslava nové úrovně, nové klobouky a emoty ve všech skinech.
import json, os, subprocess, sys, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu, QRadioButton

from familiar import cli, config, dock, kwin, nabidka, nastaveni, progress, skin, sluzby, sprites, stats
from familiar import statistiky_okno as so
from familiar import upozorneni as up
from familiar.hub import Hub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_800_000_000.0
NOVE_KLOBOUKY = ("straw", "tophat", "crown", "nightcap", "laurel")
NOVE_EMOTY = ("star", "badge", "swarm")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def home(tmp_path, monkeypatch, app):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(kwin, "load", lambda: True)
    monkeypatch.setattr(kwin, "unload", lambda: None)
    return tmp_path


def msg(ts, hook, pid=7, **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": f"s{pid}", "cwd": f"/home/x/projekt{pid}", **raw}}


class Okno:
    pid = None

    def zastav(self):
        pass


class Dbus:
    na_akci = na_zavreni = None

    def zobraz(self, args):
        return 1

    def zavri(self, nid):
        pass


def mk(c=None):
    c = c or config.defaults()
    hub = Hub(reap=False, bind=False, cfg=c, transcripts=False)
    u = up.Upozorneni(c, dbus=Dbus(), prehravac=type("P", (), {"prehraj": lambda *a: True})())
    return hub, sluzby.Sluzby(hub, c, upozorneni=u, okno=Okno(), ikona=False)


def cfg_postup(**kw):
    c = config.defaults()
    c["postup"].update(kw)
    return c


# --- sprity a skiny ---

def test_doplnky_odkazuji_na_existujici_sprity():
    assert set(progress.SPRITY) == set(progress.DOPLNKY)
    for k, (druh, *_rest) in progress.DOPLNKY.items():
        assert progress.SPRITY[k] in (sprites.HATS if druh == "klobouk" else sprites.POPS), k
    assert set(NOVE_KLOBOUKY) <= set(sprites.HATS) and set(NOVE_EMOTY) <= set(sprites.POPS)
    # odemykatelné emoty jen barvami, které mají i převedené skiny a květina
    for e in NOVE_EMOTY:
        assert set(sprites.POPS[e][1].values()) <= {1, 8, 9, 10, 11, 13, 14, 15}


def _ids():
    return sorted(d for d in os.listdir(skin.PACKAGE_DIR) if os.path.isfile(os.path.join(skin.PACKAGE_DIR, d, "skin.toml")))


@pytest.mark.parametrize("sid", _ids())
def test_nove_emoty_a_klobouky_ve_vsech_skinech(sid, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    s = skin.load(sid)
    assert s.error is None
    anim = s.anim_for("idle")
    holy, _ = s.render(anim, 0, ("klid", None, None, 0, 0, 0))
    for e in NOVE_EMOTY:
        assert e in s.emote.tags, (sid, e)
        px, colors = s.render(anim, 0, ("klid", None, e, 1, 0, 0))
        assert px != holy and all(colors[v] is not None for v in px if v)
    for h in NOVE_KLOBOUKY:
        px, _ = s.render(anim, 0, ("klid", h, None, 0, 0, 0))
        if s.acc is None:       # skin bez klobouků (kvetina, převzaté) doplněk tiše ignoruje
            assert px == holy
        else:
            assert h in s.acc.tags and px != holy


def test_vestaveny_kresli_nove_klobouky_a_emoty():
    b = skin.builtin()
    holy = b.render("idle", 0, ("klid", None, None, 0, 0, 0))[0]
    for h in NOVE_KLOBOUKY:
        assert b.render("idle", 0, ("klid", h, None, 0, 0, 0))[0] != holy
        assert b.render("hop", 3, ("radost", h, "star", 1, 2, 1))[0]
    for e in NOVE_EMOTY:
        assert b.render("idle", 0, ("klid", None, e, 0, 0, 0))[0] != holy


# --- hub: doplňky, klidové emoty, oslava ---

def _fam(c=None):
    hub = Hub(reap=False, bind=False, cfg=c or config.defaults(), transcripts=False)
    hub.receive(msg(T0, "SessionStart"))
    return hub, hub.fams[7]


def test_klobouk_doplnku_kdyz_tema_nema_vlastni():
    hub, fam = _fam()
    assert fam.update(T0 + 1)[2][1] is None
    hub.nastav_doplnky("crown", ())
    assert fam.update(T0 + 2)[2][1] == "crown"
    fam.topic.advance = lambda now: "kod"
    fam.hats = {"kod": "headphones"}
    assert fam.update(T0 + 3)[2][1] == "headphones"      # téma má přednost …
    fam.klobouk_vzdy = True
    assert fam.update(T0 + 4)[2][1] == "crown"           # … dokud není klobouk_vzdy
    hub.receive(msg(T0 + 5, "SessionStart", pid=8))
    assert hub.fams[8].doplnky == ("crown", ())          # nová postavička dostane doplňky hned
    hub.nastav_doplnky(None, ())
    assert fam.update(T0 + 6)[2][1] == "headphones"


def test_klidove_emoty_se_stridaji():
    c = config.defaults()
    c["postup"]["klid_emote_s"] = 60.0
    hub, fam = _fam(c)
    hub.nastav_doplnky(None, ("star", "heart"))
    assert fam.update(T0 + 30)[2][2] is None
    assert fam.update(T0 + 61)[2][2] == "star"
    pops = [fam.update(T0 + t)[2][2] for t in range(62, 200)]
    assert "heart" in pops and pops.count(None) > 100      # zase až po klid_emote_s
    hub.receive(msg(T0 + 200, "UserPromptSubmit", prompt="x"))
    assert all(fam.update(T0 + t)[2][2] in (None, "star", "heart") for t in range(201, 230))
    fam.spi = True
    assert all(fam.update(T0 + t)[2][2] is None for t in range(400, 600, 5))


def test_oslava_ukaze_success():
    hub, fam = _fam()
    assert fam.update(T0 + 1)[0] == "idle"
    assert hub.oslav(7, now=T0 + 2) and not hub.oslav(999)
    assert fam.update(T0 + 2.1)[0] == fam.skin.anim_for("success")
    assert fam.update(T0 + 2 + 2)[0] == "idle"
    fam.oslav(T0 + 10)
    fam.spi = True
    assert fam.update(T0 + 10.1)[0] == fam.skin.anim_for("sleeping")


# --- služby: výběr doplňků, nová úroveň, přehled ---

def test_sluzby_vyberou_doplnky_podle_configu(home):
    hub, s = mk()
    assert hub.sluzby is s and s.doplnky() == (None, ()) and hub.doplnky == (None, ())
    s.postup.xp = progress.xp_na_uroven(8)        # kšiltovka, slamák, srdíčko, hvězdička
    s.tick(T0)
    assert hub.doplnky == (None, ("heart", "star"))     # výchozí: klobouk žádný, emoty ano
    for volba, cekam in (("auto", "straw"), ("klobouk_cepice", "cap"), ("klobouk_koruna", None), ("", None)):
        s.nastav(cfg_postup(doplnek_klobouk=volba))
        assert hub.doplnky[0] == cekam, volba         # zamčená koruna se nenosí
    s.nastav(cfg_postup(doplnek_klobouk="auto", emoty_v_klidu=False))
    assert hub.doplnky == ("straw", ())
    s.nastav(cfg_postup(zapnuto=False, doplnek_klobouk="auto"))
    assert hub.doplnky == (None, ())


def test_nova_uroven_oslava_a_bublina_jednou(home):
    hub, s = mk()
    hub.receive(msg(T0, "SessionStart"))
    s.postup.xp = progress.xp_na_uroven(5) - 1
    hub.receive(msg(T0 + 1, "PreToolUse", tool_name="Bash", tool_use_id="a"))
    fam = hub.fams[7]
    assert s.postup.uroven == 5
    assert fam.oslava_do > time.time() and fam.zprava[0] == "Úroveň 5!"
    hub.receive(msg(T0 + 2, "PreToolUse", tool_name="Bash", tool_use_id="b"))
    assert fam.zprava[0] == "Úroveň 5!"       # žádné další oznámení bez nové úrovně


def test_prehled_bere_zive_instance_bez_cteni_souboru(home):
    hub, s = mk()
    hub.receive(msg(T0, "UserPromptSubmit", prompt="tajne"))
    hub.receive(msg(T0 + 1, "PreToolUse", tool_name="Read", tool_use_id="a"))
    assert not os.path.exists(stats.soubor())      # nic se zatím neuložilo …
    d = s.prehled(T0 + 2)
    assert d["dnes"]["prompty"] == 1 and d["dnes"]["nastroje"] == {"Read": 1}     # … a čísla jsou aktuální
    assert d["postup"]["uroven"] == 1 and len(d["postup"]["uspechy"]) == len(progress.USPECHY)
    assert d["volba"] == {"doplnek_klobouk": "", "klobouk_vzdy": False, "emoty_v_klidu": True}
    assert "tajne" not in json.dumps(d, ensure_ascii=False)
    s.nastav(cfg_postup(zapnuto=False))
    assert s.prehled(T0)["postup"] is None


# --- okno ---

def test_okno_se_naplni_a_vybira_doplnky(app):
    w = so.StatistikyOkno()
    data = so.ukazka(T0)
    w.nastav(data, skin.load("robokun"))
    d = data["dnes"]
    assert w.dnes_d["prompty"].cislo.text() == str(d["prompty"]) != "0"
    assert w.dnes_d["aktivni_s"].cislo.text() == stats.cas(d["aktivni_s"])
    assert w.nastroje.data and w.nastroje.data[0][1] == max(d["nastroje"].values())
    assert w.graf_tyden.dny and w.uroven.text() == f"Úroveň {data['postup']['uroven']}"
    assert w.mriz_uspechu.count() == len(progress.USPECHY)
    zmeny = []
    w.zmena.connect(zmeny.append)
    radia = {r.text(): r for r in w.findChildren(QRadioButton)}
    assert {"žádný", "poslední odemčený", "nosit"} <= set(radia)
    radia["žádný"].click()
    assert zmeny == [{"postup.doplnek_klobouk": ""}]
    w.klobouk_vzdy.click()
    assert zmeny[-1] == {"postup.klobouk_vzdy": True}
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        assert not w.grab().isNull()
    w.nastav({"ted": T0})       # vypnuté statistiky i postup
    assert not w.dnes_vypnuto.isHidden() or not w.isVisible()
    assert w.uroven.text().startswith("Úrovně a úspěchy jsou vypnuté")
    w.close()


def test_nahled_skinu_bez_klobouku_je_z_vestaveneho():
    k = skin.load("kvetina")
    assert not so.umi(k, "klobouk", "crown") and so.umi(k, "emote", "star")
    assert so.umi(skin.builtin(), "klobouk", "crown")
    assert not so.nahled(skin.builtin(), "klobouk", "crown", sedy=True).isNull()


@pytest.fixture
def ui(home):
    hub = Hub(reap=False, bind=False, transcripts=False)
    hub.receive(msg(0, "SessionStart"))
    views = dock.Views(hub, None, config.load(), "dock")

    def written():
        views.apply(config.load())
        if hub.sluzby is not None:
            hub.sluzby.tick()
    u = nabidka.Ovladani(hub, views, written, tray=False)
    views.ui = u
    yield u
    if u.statistiky is not None:
        u.statistiky.close()
    views.view.close()


def test_nabidka_otevre_okno_s_daty_sluzeb(ui, app):
    hub = ui.hub
    for key in (7, None):
        m = QMenu()
        ui.naplnit(m, key)
        assert "Statistiky a úspěchy…" in [a.text() for a in m.actions()]
    u = up.Upozorneni(hub.cfg, dbus=Dbus(), prehravac=type("P", (), {"prehraj": lambda *a: True})())
    s = sluzby.Sluzby(hub, hub.cfg, upozorneni=u, okno=Okno(), ikona=False)
    hub.receive(msg(time.time(), "UserPromptSubmit", prompt="x"))     # okno ukazuje skutečný dnešek
    s.postup.xp = progress.xp_na_uroven(3)
    w = ui.otevri_statistiky()
    assert ui.otevri_statistiky() is w and w.timer.isActive()
    assert w.dnes_d["prompty"].cislo.text() == "1"
    # výběr klobouku v okně se zapíše do configu a postavička ho hned nosí
    [r for r in w.findChildren(QRadioButton) if r.text() == "nosit"][0].click()
    assert config.load()["postup"]["doplnek_klobouk"] == "klobouk_cepice"
    assert hub.doplnky[0] == "cap"
    w.close()
    app.processEvents()


def test_nabidka_v_demu_bez_statistik(home):
    hub = Hub(reap=False, bind=False, transcripts=False)
    views = dock.Views(hub, None, config.load(), "dock", demo=True)
    u = nabidka.Ovladani(hub, views, None, tray=False, demo=True)
    m = QMenu()
    u.naplnit(m, None)
    a = [a for a in m.actions() if a.text().startswith("Statistiky")][0]
    assert not a.isEnabled()
    views.view.close()


# --- CLI ---

def _zapis_stav(home):
    s = stats.Statistiky(tz=None)
    p = progress.Postup()
    for ev in ({"kind": "session.start", "ts": time.time() - 60, "pid": 1, "session": "a", "data": {}},
               {"kind": "user.prompt", "ts": time.time() - 50, "pid": 1, "session": "a", "data": {}},
               {"kind": "tool.start", "ts": time.time() - 40, "pid": 1, "session": "a", "data": {"tool": "Grep"}}):
        s.zapocti(ev)
        p.zapocti(ev)
    s.uloz(vynutit=True)
    p.uloz(vynutit=True)


def test_cli_statistiky_text_a_json(home, capsys):
    _zapis_stav(home)
    assert cli.main(["statistiky"]) == 0
    out = capsys.readouterr().out
    assert "Dnes" in out and "prompty 1" in out and "Grep 1" in out and "Úroveň 1" in out
    assert cli.main(["statistiky", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["dnes"]["prompty"] == 1 and d["dnes"]["nastroje"] == {"Grep": 1}
    assert d["postup"]["uspechy"][0]["odemceno"] and len(d["tyden"]["dny"]) == 7


def test_cli_statistiky_jen_cte_a_bez_qt(home):
    os.makedirs(os.path.dirname(stats.soubor()))
    with open(stats.soubor(), "w") as f:
        f.write("{rozbité")
    env = dict(os.environ, PYTHONPATH=ROOT)
    kod = "import sys; from familiar import cli; r = cli.main(['statistiky']); print('Qt' if 'PySide6' in sys.modules else 'bez Qt')"
    r = subprocess.run([sys.executable, "-c", kod], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip().endswith("bez Qt")
    assert os.listdir(os.path.dirname(stats.soubor())) == ["statistiky.json"]       # vadný soubor nechal být


# --- config a dialog ---

def test_config_doplnku(home):
    p = home / "cfg" / "familiar" / "config.toml"
    p.parent.mkdir(parents=True)
    p.write_text('[postup]\ndoplnek_klobouk = "klobouk_koruna"\nklobouk_vzdy = true\nklid_emote_s = 30\n')
    c = config.load(str(p))
    assert not c.errors and c["postup"]["doplnek_klobouk"] == "klobouk_koruna" and c["postup"]["klid_emote_s"] == 30
    p.write_text('[postup]\ndoplnek_klobouk = "emote_hvezda"\nklid_emote_s = 1\nemoty_v_klidu = "ano"\n')
    c = config.load(str(p))
    assert len(c.errors) == 3 and c["postup"] == config.defaults()["postup"]
    assert any("doplnek_klobouk" in e and "auto" in e for e in c.errors)


def test_dialog_ma_polozky_doplnku():
    klice = {p.klic: p for p in nastaveni.POLOZKY}
    for k in ("postup.doplnek_klobouk", "postup.klobouk_vzdy", "postup.emoty_v_klidu", "postup.klid_emote_s"):
        assert klice[k].zalozka == "Statistiky", k
    hodnoty = [h for h, _ in nastaveni._doplnky_klobouky()]
    assert hodnoty == list(config.ENUMS["postup.doplnek_klobouk"])
    assert set(NOVE_KLOBOUKY) <= set(nastaveni.HATS)
