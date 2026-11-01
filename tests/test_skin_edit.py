import os

import pytest

from familiar import skin, skin_edit, sprites
from familiar.skin import NONE, SkinError


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "familiar" / "skins"


def _package(sid):
    return skin.PackageSkin(os.path.join(skin.PACKAGE_DIR, sid), fallback=skin.builtin())


LOOKS = [(m, h, e, 1, d, 1) for m in sprites.MOOD for h, e, d in ((None, None, 0), ("cap", "heart", 2))]


def _same(a, b, looks=LOOKS):
    assert a.anims == b.anims
    for anim, an in a.anims.items():
        for i in range(an.frames):
            for look in looks:
                assert a.render(anim, i, look) == b.render(anim, i, look), (anim, i, look)


@pytest.mark.parametrize("sid", sorted(os.listdir(skin.PACKAGE_DIR)))
def test_balickovy_skin_projde_editorem_beze_zmeny(data_home, sid):
    orig = _package(sid)
    doc = skin_edit.load(os.path.join(skin.PACKAGE_DIR, sid))
    assert doc.source == skin.PACKAGE and doc.problems() == [] and doc.warnings == []
    _same(orig, doc.to_skin())                      # náhled v paměti
    dest = skin_edit.save(doc, sid + "-kopie")
    new = skin.PackageSkin(dest, fallback=skin.builtin())
    _same(orig, new)                                # a ze souborů
    assert (new.activity, new.moods, new.keep, new.facing, new.size, new.anchor) == \
        (orig.activity, orig.moods, orig.keep, orig.facing, orig.size, orig.anchor)
    if os.path.exists(os.path.join(skin.PACKAGE_DIR, sid, "CREDITS.txt")):
        assert os.path.exists(os.path.join(dest, "CREDITS.txt"))


def test_ulozeni_balickoveho_je_uzivatelska_kopie_a_smazani_ji_vrati(data_home):
    doc = skin_edit.load_id("robokun")
    doc.meta["name"] = "Můj Robo"
    dest = skin_edit.save(doc)
    assert dest == str(data_home / "robokun") and skin.find("robokun") == (dest, skin.USER)
    assert skin.load("robokun").name == "Můj Robo"
    assert skin_edit.load_id("robokun").source == skin.USER
    skin_edit.delete("robokun")
    assert skin.find("robokun")[1] == skin.PACKAGE and skin.load("robokun").name == "Robo-kun"
    with pytest.raises(SkinError):
        skin_edit.delete("kvetina")     # balíčkový smazat nejde


def test_komentare_v_toml_zustanou(data_home):
    doc = skin_edit.load_id("kvetina")
    doc.meta["author"] = "já"
    dest = skin_edit.save(doc, "kytka")
    text = open(os.path.join(dest, "skin.toml"), encoding="utf-8").read()
    assert text.startswith("# Vygenerováno: python3 -I tools/kvetina.py")
    assert 'author = "já"' in text and "# snímky tagu, kde výraz určuje animace" in text


def test_kresleni_a_snimky_se_ulozi(data_home):
    doc = skin_edit.load_id("robokun")
    idle = doc.body.get("idle")
    keep13 = idle.frames[13]
    assert keep13.keep == {"eyes"}          # mrknutí: oči určuje animace
    idle.frames[0].px[0] = 3
    doc.delete_frame("body", "idle", 1)
    doc.add_frame("body", "idle", 0, copy_from=0)
    doc.move_frame("body", "idle", 0, 5)
    skin_edit.save(doc, "test")
    s = skin.load("test")
    assert s.error is None and s.anims["idle"].frames == len(idle.frames)
    assert s.keep["eyes"]["idle"] == {idle.frames.index(keep13)} == {13}
    assert s.render("idle", 0, skin.NO_LOOK)[0][0] == 3 and s.render("idle", 5, skin.NO_LOOK)[0][0] == 3


def test_fx_a_kotvy_jdou_se_snimkem(data_home):
    doc = skin_edit.load_id("robokun")
    work = doc.body.get("work_bash")
    assert all(f.fx is not None for f in work.frames)
    last = work.frames[-1]
    doc.move_frame("body", "work_bash", len(work.frames) - 1, -99)
    assert work.frames[0] is last
    orig = _package("robokun")
    s = doc.to_skin()
    n = len(work.frames)
    for i in range(n):        # posunutý snímek kreslí totéž co původní (i s fx, obličejem a kloboukem)
        for look in (("frustrace", "cap", None, 0, 0, 0), ("radost", "hardhat", "heart", 0, 1, 0)):
            assert s.render("work_bash", i, look) == orig.render("work_bash", (i - 1) % n, look)


def test_prejmenovani_a_smazani_upravi_odkazy(data_home):
    doc = skin_edit.load_id("robokun")
    doc.rename_anim("body", "sleep", "spanek")
    assert doc.activity["sleeping"] == doc.activity["gone"] == "spanek"
    assert doc.layers["acc"].get("hardhat@spanek") and not doc.layers["acc"].get("hardhat@sleep")
    doc.rename_anim("body", "work_edit", "psani")
    assert doc.activity["working"]["Edit"] == "psani"
    doc.rename_anim("face", "eyes_angry", "eyes_zle")
    assert doc.moods["frustrace"]["eyes"] == "zle"
    doc.rename_anim("emote", "storm", "bourka")
    assert doc.moods["frustrace"]["emote"] == "bourka"
    doc.delete_anim("body", "spanek")
    assert "sleeping" not in doc.activity and not any("@spanek" in n for n in doc.layers["acc"].names())
    doc.delete_anim("face", "eyes_zle")
    doc.delete_anim("emote", "bourka")
    assert doc.moods["frustrace"] == {"mouth": "frown", "palette": "cold"}
    assert doc.problems() == []
    s = doc.to_skin()
    assert "sleeping: " not in " ".join(s.missing) and s.anim_for("sleeping") == "sleep"   # Robo-kun z kódu
    with pytest.raises(ValueError):
        doc.rename_anim("body", "idle", "listen")       # už existuje
    with pytest.raises(ValueError):
        doc.add_anim("face", "usmev")                   # výraz musí být eyes_ / mouth_
    with pytest.raises(ValueError):
        doc.add_anim("drone", "vcela")


def test_nova_vrstva_a_novy_skin(data_home):
    doc = skin_edit.new("muj", "Můj familiar")
    assert set(doc.layers) == {"body", "emote", "drone"} and doc.problems() == []
    doc.body.get("idle").frames[0].px[31 * 32 + 16] = 2
    a = doc.add_anim("acc", "cap")
    a.frames[0].px[5 * 32 + 10] = 4
    assert a.frames[0].anchors == {"head": (8, 6)}
    a = doc.add_anim("face", "eyes_wide")
    doc.moods["zvedavost"]["eyes"] = "wide"
    skin_edit.save(doc)
    s = skin.load("muj")
    assert s.error is None and s.name == "Můj familiar"
    px, _ = s.render("idle", 0, ("klid", "cap", None, 0, 0, 0))
    assert px[31 * 32 + 16] == 2 and px[5 * 32 + 10] == 4
    assert s.anim_for("thinking") == "think"        # chybí → vestavěný Robo-kun
    assert s.render("idle", 0, ("klid", None, "heart", 0, 1, 0))[0] != px


def test_vetsi_platno_zachova_kresbu_na_kotve(data_home):
    doc = skin_edit.load_id("robokun")
    doc.resize(48, 40)
    assert doc.size == (48, 40) and doc.anchor == (24, 39)
    skin_edit.save(doc, "velky")
    big, orig = skin.load("velky"), _package("robokun")
    assert big.error is None and big.size == (48, 40)
    for anim in ("idle", "work_bash"):
        for look in (("frustrace", "cap", "heart", 0, 2, 0),):
            px, cols = big.render(anim, 2, look)
            o, ocols = orig.render(anim, 2, look)
            assert cols == ocols
            assert [px[(y + 8) * 48 + x + 8] for y in range(32) for x in range(32)] == list(o)
    with pytest.raises(ValueError):
        doc.resize(20, 40)


def test_palety(data_home):
    doc = skin_edit.load_id("robokun")
    with pytest.raises(ValueError):
        doc.set_color("base", 2, doc.palettes["base"][3])       # dvě stejné barvy by v PNG splynuly
    with pytest.raises(ValueError):
        doc.set_color("base", 2, "#FF00FF")
    doc.set_color("warm", 2, doc.palettes["warm"][3])           # v paletách nálad smí
    doc.rename_palette("cold", "studena")
    assert doc.moods["frustrace"]["palette"] == "studena"
    doc.delete_palette("studena")
    assert doc.moods["frustrace"]["palette"] == "base"
    with pytest.raises(ValueError):
        doc.delete_palette("base")
    with pytest.raises(ValueError):
        doc.add_color()          # Robo-kun má plných 16
    with pytest.raises(ValueError):
        doc.remove_last_color()  # poslední barvu snímky používají
    doc.derive_palette("noc", "cold")
    body = doc.body_colors()
    assert all((doc.palettes["noc"][k] != doc.palettes["base"][k]) == (k in body) for k in range(1, 16)
               if doc.palettes["base"][k] not in ("#000000", "#ffffff"))
    doc.palettes["base"][4] = doc.palettes["base"][5]
    assert any("stejné" in p for p in doc.problems())
    with pytest.raises(SkinError):
        skin_edit.save(doc, "spatny")
    assert not os.path.exists(data_home / "spatny")


def test_nova_barva_a_premalovani(data_home):
    doc = skin_edit.new("b")
    doc.palettes = {"base": doc.palettes["base"][:4]}
    k = doc.add_color("#123456")
    assert k == 4 and doc.palettes["base"][4] == "#123456"
    px = doc.body.get("idle").frames[0].px
    px[0] = 4
    with pytest.raises(ValueError):
        doc.remove_last_color()
    doc.replace_color(4, 2)
    assert px[0] == 2
    doc.remove_last_color()
    assert len(doc.palettes["base"]) == 4


def test_vadny_dokument_neprepise_ulozeny(data_home):
    doc = skin_edit.new("x")
    skin_edit.save(doc)
    before = sorted(os.listdir(data_home / "x"))
    doc.body.get("idle").frames.clear()
    assert doc.problems()
    with pytest.raises(SkinError):
        skin_edit.save(doc)
    assert sorted(os.listdir(data_home / "x")) == before and skin.load("x").error is None
    assert [n for n in os.listdir(data_home) if n.startswith(".")] == []
    with pytest.raises(SkinError):
        skin_edit.save(skin_edit.new("ok"), "../ven")


def test_pixelove_pomucky():
    size = (4, 3)
    px = bytearray([0, 0, 1, 0,
                    0, 1, 1, 0,
                    0, 0, 0, 0])
    assert skin_edit.fill(px, size, 0, 0, 5) == 9 and px[2] == 1 and px[11] == 5
    assert skin_edit.shift(bytearray(range(12)), size, 1, 0, NONE)[:4] == bytearray([NONE, 0, 1, 2])
    assert skin_edit.flip(bytearray(range(12)), size)[:4] == bytearray([3, 2, 1, 0])
    assert skin_edit.line(0, 0, 3, 1) == [(0, 0), (1, 0), (2, 1), (3, 1)]
    assert len(skin_edit.rect(0, 0, 2, 2)) == 8
