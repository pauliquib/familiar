import filecmp, importlib.util, json, os, shutil

import pytest

from familiar import skin, skin_export, sprites

ROBOKUN = os.path.join(skin.PACKAGE_DIR, "robokun")
STATES = ("idle", "listening", "thinking", "waiting", "success", "error", "sleeping", "gone")


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "familiar" / "skins"


@pytest.fixture(scope="module")
def robokun():
    return skin.PackageSkin(ROBOKUN, fallback=skin.builtin())


def _looks():
    """Reprezentativní vzorek: všechny nálady, všechny klobouky, emoty, drony."""
    for mood in sprites.MOOD:
        yield (mood, None, None, 0, 0, 0)
    for hat in sprites.HATS:
        for mood in ("klid", "frustrace", "unava"):
            yield (mood, hat, None, 0, 0, 0)
    for k, pop in enumerate(sprites.POPS):
        yield ("radost", "cap", pop, k % 2, k % 4, (k // 2) % 2)


def test_package_matches_sprites_pixel_for_pixel(robokun):
    n = 0
    for anim, (_, poses) in sprites.ANIMS.items():
        for i, p in enumerate(poses):
            for look in _looks():
                px, colors = robokun.render(anim, i, look)
                assert px == bytes(sprites.draw(p, look)), (anim, i, look)
                assert colors == sprites.palette(look[0])
                n += 1
    assert n > 1000


def test_package_metadata_matches_builtin(robokun):
    b = skin.builtin()
    assert robokun.anims == b.anims
    for state in STATES:
        assert robokun.anim_for(state) == b.anim_for(state)
    for tool in [*sprites.TOOL_ANIM, "Neznamy", None]:
        expected = sprites.anim_for("working", tool)
        assert robokun.anim_for("working", tool) == b.anim_for("working", tool) == expected
    for mood, (*_, emote, tempo) in sprites.MOOD.items():
        assert robokun.mood_emote(mood) == b.mood_emote(mood) == emote
        assert robokun.mood_tempo(mood) == b.mood_tempo(mood) == tempo
    for anim in sprites.ANIMS:
        for t in (0, 0.3, 1.7, 9.1):
            assert robokun.frame_at(anim, t, 0.6) == b.frame_at(anim, t, 0.6) == sprites.frame_at(anim, t, 0.6)


def test_builtin_renders_like_sprites():
    look = ("zmatek", "beret", "spiral", 1, 2, 1)
    assert skin.builtin().render("think", 3, look) == (sprites.frame("think", 3, look), sprites.palette("zmatek"))


def test_committed_packages_are_up_to_date(tmp_path):
    for variant in skin_export.VARIANTS:
        dest = tmp_path / variant
        skin_export.export(str(dest), variant)
        cmp = filecmp.dircmp(dest, os.path.join(skin.PACKAGE_DIR, variant))
        assert not (cmp.left_only or cmp.right_only or cmp.diff_files), variant
        assert not filecmp.dircmp(dest / "pal", os.path.join(skin.PACKAGE_DIR, variant, "pal")).diff_files


def test_vanoce_is_classic_robokun_with_decorations(data_home):
    s = skin.load("vanoce")
    assert s.error is None and s.acc is None                     # čepice místo klobouků témat
    assert s.palettes == skin.load("robokun").palettes           # barvy klasického Robo-kuna
    assert s.anims == skin.builtin().anims
    for anim, (_, poses) in sprites.ANIMS.items():
        for i in range(len(poses)):
            px, _ = s.render(anim, i)
            assert px != bytes(sprites.draw(poses[i])), (anim, i)
            assert px.count(10) > 20, (anim, i)                  # červená čepice je vidět i ve výskoku
            assert s.render(anim, i, ("klid", "hardhat", None, 0, 0, 0))[0] == px
    assert len(s.drones) == 3


OWN = ("kvetina", "ptacek", "skejtak", "skejtak2")     # vlastní dílo projektu kreslené kódem v tools/<id>.py (bez url)


def _generator(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(skin.PACKAGE_DIR), "..",
                                                                     "tools", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("sid", OWN)
def test_own_package_is_up_to_date(tmp_path, sid):
    _generator(sid).export(str(tmp_path))
    cmp = filecmp.dircmp(tmp_path, os.path.join(skin.PACKAGE_DIR, sid))
    assert not (cmp.left_only or cmp.right_only or cmp.diff_files)
    assert not filecmp.dircmp(tmp_path / "pal", os.path.join(skin.PACKAGE_DIR, sid, "pal")).diff_files


@pytest.mark.parametrize("sid", ("ptacek", "skejtak", "skejtak2"))
def test_own_skins_have_face_moods_emotes_and_drones(data_home, sid):
    s = skin.load(sid)
    assert s.error is None and len(s.palettes["base"]) <= skin.MAX_COLORS
    assert set(s.emote.tags) == set(sprites.POPS) and len(s.drones) == 3
    calm = s.render("idle", 0, ("klid", None, None, 0, 0, 0))
    for mood in ("radost", "zvedavost", "frustrace", "zmatek", "unava"):
        px, colors = s.render("idle", 0, (mood, None, None, 0, 0, 0))
        assert px != calm[0] or colors != calm[1], mood         # obličej nebo barvy
    for anim, a in s.anims.items():
        assert 2 <= a.frames and 2 <= a.fps <= 8, anim


def test_kvetina_has_face_moods_emotes_and_bees(data_home):
    s = skin.load("kvetina")
    assert s.error is None and s.name == "Květina" and len(s.palettes["base"]) <= skin.MAX_COLORS
    assert set(s.emote.tags) == set(sprites.POPS) and len(s.drones) == 3
    calm = s.render("idle", 0, ("klid", None, None, 0, 0, 0))
    for mood in ("radost", "zvedavost", "frustrace", "zmatek", "unava"):
        px, colors = s.render("idle", 0, (mood, None, None, 0, 0, 0))
        assert px != calm[0] or colors != calm[1], mood         # obličej nebo barvy
    assert s.render("sleep", 0, ("radost", None, None, 0, 0, 0))[0] == \
        s.render("sleep", 0, ("klid", None, None, 0, 0, 0))[0]  # poupě spí bez obličeje nálady
    for anim, a in s.anims.items():
        assert 2 <= a.frames and 2 <= a.fps <= 8, anim


def test_skin_without_flower_emote_still_works(data_home):
    dest = data_home / "robokun"
    shutil.copytree(ROBOKUN, dest)
    _patch_json(dest / "emote.json", lambda d: d["meta"].update(
        frameTags=[t for t in d["meta"]["frameTags"] if t["name"] != "flower"]))
    s = skin.load("robokun")
    assert s.error is None and s.source == skin.USER and "flower" not in s.emote.tags
    assert s.render("idle", 0, ("radost", None, "flower", 1, 0, 0)) == s.render("idle", 0, ("radost", None, None, 0, 0, 0))
    assert s.render("idle", 0, ("radost", None, "heart", 1, 0, 0)) != s.render("idle", 0, ("radost", None, None, 0, 0, 0))


def _rgb(px, colors):
    return [colors[v] for v in px]


def test_switching_skins_changes_the_picture():
    a, b = skin.load("robokun"), skin.load("rubin")
    assert (a.name, b.name) == ("Robo-kun", "Robo-kun Rubín")
    for anim, look in (("idle", None), ("hop", ("radost", None, None, 0, 0, 0)),
                       ("sleep", ("unava", "hardhat", None, 0, 1, 0))):
        pa, pb = a.render(anim, 0, look), b.render(anim, 0, look)
        assert pa[0] == pb[0]                       # stejné tvary
        assert _rgb(*pa) != _rgb(*pb)               # jiné barvy


def test_png_roundtrip(tmp_path):
    rgba = bytes(range(256)) * 3
    path = tmp_path / "x.png"
    skin_export.write_png(path, 8, 24, rgba)
    assert skin.read_png(path) == (8, 24, bytearray(rgba))


def test_reads_png_saved_by_qt(tmp_path):
    """Dekodér zvládne filtry a indexované PNG z jiného kodéru."""
    gui = pytest.importorskip("PySide6.QtGui")
    img = gui.QImage(13, 7, gui.QImage.Format_Indexed8)
    img.setColorTable([gui.qRgba(0, 0, 0, 0), gui.qRgba(255, 0, 0, 255), gui.qRgba(10, 200, 30, 255)])
    for y in range(7):
        for x in range(13):
            img.setPixel(x, y, (x * y + x) % 3)
    for fmt in (None, gui.QImage.Format_ARGB32):
        out = img if fmt is None else img.convertToFormat(fmt)
        path = str(tmp_path / f"q{fmt}.png")
        assert out.save(path)
        w, h, px = skin.read_png(path)
        assert (w, h) == (13, 7)
        for y in range(7):
            for x in range(13):
                c = gui.QColor.fromRgba(img.pixel(x, y))
                got = tuple(px[(y * w + x) * 4:(y * w + x) * 4 + 4])
                assert got[3] == c.alpha() and (c.alpha() == 0 or got[:3] == (c.red(), c.green(), c.blue()))


def _mini_skin(path, colors=("#ff00ff", "#000000", "#ff8800"), toml_extra=""):
    """Nejmenší skin: jen animace idle (1 snímek, oranžový čtverec)."""
    os.makedirs(path / "pal", exist_ok=True)
    skin_export.write_gpl(path / "pal" / "base.gpl", "base", [None, *colors[1:]])
    px = bytearray(32 * 32)
    for y in range(10, 20):
        for x in range(10, 20):
            px[y * 32 + x] = 2
    skin_export.write_sheet(str(path), "body", [px], [("idle", 1, 4, False)], [None, *colors[1:]], False)
    (path / "skin.toml").write_text('[skin]\nname = "Čtverec"\n[layers]\nbody = "body.png"\n'
                                    '[palettes]\nbase = "pal/base.gpl"\n[activity]\nidle = "idle"\n' + toml_extra)
    return px


def test_missing_animations_fall_back_to_builtin(data_home):
    px = _mini_skin(data_home / "ctverec")
    s = skin.load("ctverec")
    assert isinstance(s, skin.PackageSkin) and s.source == skin.USER and s.name == "Čtverec"
    assert s.render("idle", 0)[0] == bytes(px)
    assert s.render("idle", 0)[1] == [None, "#000000", "#ff8800"]
    assert s.anim_for("idle") == "idle"
    assert s.anim_for("thinking") == "think"            # chybí → vestavěná animace i s paletou
    assert s.render("think", 2, None) == skin.builtin().render("think", 2, None)
    assert s.frame_at("think", 1.0) == sprites.frame_at("think", 1.0)
    assert s.anim_for("working", "Bash") == "work_bash"
    assert s.mood_tempo("unava") == 1.0 and s.mood_emote("radost") is None


def _big_skin(path, size=(48, 40), toml_extra=""):
    """Skin s větším plátnem: idle (čtverec u spodní hrany) a reakce heart v pravém horním rohu."""
    w, h = size
    colors = [None, "#000000", "#ff8800"]
    os.makedirs(path / "pal", exist_ok=True)
    skin_export.write_gpl(path / "pal" / "base.gpl", "base", colors)
    px = bytearray(w * h)
    for y in range(h - 10, h):
        for x in range(w - 10, w):
            px[y * w + x] = 2
    pop = bytearray([skin.NONE]) * (w * h)
    pop[w - 1] = 1
    skin_export.write_sheet(str(path), "body", [px], [("idle", 1, 4, False)], colors, False, size=size)
    skin_export.write_sheet(str(path), "emote", [pop, pop], [("heart", 2, 4, False)], colors, True, size=size)
    (path / "skin.toml").write_text(f'[skin]\nname = "Velký"\nsize = [{w}, {h}]\n[layers]\nbody = "body.png"\n'
                                    'emote = "emote.png"\n[palettes]\nbase = "pal/base.gpl"\n'
                                    '[activity]\nidle = "idle"\n' + toml_extra)
    return px


def test_bigger_canvas(data_home, tmp_path):
    px = _big_skin(data_home / "velky")
    s = skin.load("velky")
    assert s.error is None and s.size == (48, 40) and s.anchor == (24, 39)
    out, colors = s.render("idle", 0, ("klid", None, "heart", 0, 0, 0))
    assert len(out) == 48 * 40 and out[47] == 1 and out[:47] == bytes(47) and out[48:] == bytes(px[48:])
    # chybějící animace kreslí vestavěný Robo-kun, posazený kotvou (16, 31) na kotvu skinu
    robo, robo_colors = skin.builtin().render("think", 2, None)
    big, big_colors = s.render("think", 2, None)
    assert len(big) == 48 * 40 and big_colors == robo_colors
    for y in range(40):
        for x in range(48):
            rx, ry = x - 8, y - 8
            want = robo[ry * 32 + rx] if 0 <= rx < 32 and 0 <= ry < 32 else 0
            assert big[y * 48 + x] == want
    skin.save_preview(s, str(tmp_path / "n.png"))
    assert skin.read_png(str(tmp_path / "n.png"))[:2] == (8 * 48 * 4, 6 * 40 * 4)


def test_bigger_canvas_custom_anchor_keeps_fallback_inside(data_home):
    _big_skin(data_home / "kotva", (40, 40), "")
    toml = data_home / "kotva" / "skin.toml"
    toml.write_text(toml.read_text().replace("size = [40, 40]", "size = [40, 40]\nanchor = [2, 39]"))
    s = skin.load("kotva")
    assert s.anchor == (2, 39)
    big = s.render("think", 0, None)[0]
    robo = skin.builtin().render("think", 0, None)[0]
    assert [big[(8 + y) * 40:(8 + y) * 40 + 32] for y in range(32)] == [robo[y * 32:(y + 1) * 32] for y in range(32)]


@pytest.mark.parametrize("size", ["[16, 40]", "[40, 16]", "[65, 40]", "[40]", '"40x40"', "[40.5, 40]"])
def test_bigger_canvas_rejects_bad_size(data_home, size):
    _big_skin(data_home / "spatny")
    toml = data_home / "spatny" / "skin.toml"
    toml.write_text(toml.read_text().replace("size = [48, 40]", f"size = {size}"))
    with pytest.raises(skin.SkinError) as e:
        skin.PackageSkin(str(data_home / "spatny"))
    assert "size musí být" in str(e.value)


def test_bigger_canvas_sheet_must_match_size(data_home):
    _big_skin(data_home / "nesedi")
    toml = data_home / "nesedi" / "skin.toml"
    toml.write_text(toml.read_text().replace("size = [48, 40]", "size = [40, 40]"))
    with pytest.raises(skin.SkinError) as e:
        skin.PackageSkin(str(data_home / "nesedi"))
    assert "plátno skinu musí být 40×40" in str(e.value)


def test_bigger_canvas_in_dock_and_perch(data_home):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from familiar import dock
    QApplication.instance() or QApplication([])
    _big_skin(data_home / "velky")
    s = skin.load("velky")
    img = dock.Images().get(s, "idle", 0, None)
    assert (img.width(), img.height()) == (48, 40)
    img = dock.Images().get(s, "think", 0, None)        # vestavěná animace na velkém plátně
    assert (img.width(), img.height()) == (48, 40)


BROKEN = {   # popis → (úprava skinu, kus očekávané chyby)
    "toml": (lambda p: (p / "skin.toml").write_text("[skin\n"), "chyba TOML"),
    "bez body": (lambda p: (p / "skin.toml").write_text('[palettes]\nbase = "pal/base.gpl"\n'),
                 "[layers] musí mít body"),
    "chybí png": (lambda p: (p / "body.png").unlink(), "body.png"),
    "barva mimo paletu": (lambda p: skin_export.write_gpl(p / "pal" / "base.gpl", "base", [None, "#000000"]),
                          "není v paletě base"),
    "tag mimo": (lambda p: _patch_json(p / "body.json", lambda d: d["meta"]["frameTags"][0].update(to=5)),
                 "odkazuje na snímky 0–5"),
    "bez tagů": (lambda p: _patch_json(p / "body.json", lambda d: d["meta"].update(frameTags=[])),
                 "žádné tagy"),
    "velikost": (lambda p: _patch_json(p / "body.json", lambda d: d["frames"][0]["sourceSize"].update(w=16)),
                 "plátno skinu musí být 32×32"),
    "nálada": (lambda p: p.joinpath("skin.toml").write_text(
        p.joinpath("skin.toml").read_text() + '[mood]\nradost = { palette = "warm" }\n'), "paletu warm"),
}


def _patch_json(path, fn):
    doc = json.loads(path.read_text())
    fn(doc)
    path.write_text(json.dumps(doc))


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_skin_falls_back_with_readable_error(data_home, case):
    path = data_home / "vadny"
    _mini_skin(path)
    edit, msg = BROKEN[case]
    edit(path)
    with pytest.raises(skin.SkinError) as e:
        skin.PackageSkin(str(path))
    assert msg in str(e.value)
    s = skin.load("vadny")
    assert isinstance(s, skin.BuiltinSkin) and msg in s.error
    assert s.render("idle", 0) == skin.builtin().render("idle", 0)


def test_unknown_skin_falls_back(data_home):
    for sid in ("neexistuje", "../robokun"):
        s = skin.load(sid)
        assert isinstance(s, skin.BuiltinSkin) and "nenalezen" in s.error
    assert skin.load(skin.BUILTIN) is skin.builtin()


def test_available_lists_user_package_and_builtin(data_home):
    _mini_skin(data_home / "muj")
    shutil.copytree(ROBOKUN, data_home / "robokun")      # uživatel přebije balíček
    (data_home / "robokun" / "skin.toml").write_text(
        (data_home / "robokun" / "skin.toml").read_text().replace('name = "Robo-kun"', 'name = "Můj Robo"'))
    (data_home / "neni-skin").mkdir()
    found = skin.available()
    assert ("muj", "Čtverec", skin.USER) in found
    assert ("robokun", "Můj Robo", skin.USER) in found
    assert ("rubin", "Robo-kun Rubín", skin.PACKAGE) in found
    assert found[-1] == (skin.BUILTIN, "Robo-kun (kreslený kódem)", skin.CODE)
    assert [f[0] for f in found].count("robokun") == 1
    assert "neni-skin" not in [f[0] for f in found]
    s = skin.load("robokun")
    assert s.name == "Můj Robo" and s.source == skin.USER


def test_available_without_user_dir(data_home):
    ids = [f[0] for f in skin.available()]
    assert ids[:-1] == sorted(_package_ids()) and ids[-1] == skin.BUILTIN
    assert {"robokun", "rubin"} <= set(ids)


def _package_ids():
    return [d for d in os.listdir(skin.PACKAGE_DIR) if os.path.isfile(os.path.join(skin.PACKAGE_DIR, d, "skin.toml"))]


@pytest.mark.parametrize("sid", sorted(_package_ids()))
def test_package_skins_load_without_error(data_home, sid):
    s = skin.load(sid)
    assert s.error is None and isinstance(s, skin.PackageSkin) and s.source == skin.PACKAGE
    assert s.missing == []                  # všechny stavy kreslí skin sám, ne vestavěný Robo-kun
    for state in (*STATES, "working"):
        anim = s.anim_for(state, "Bash")
        assert anim in s.anims
        for i in range(s.anims[anim].frames):
            for look in (("klid", None, None, 0, 0, 0), ("unava", "cap", "heart", 1, 3, 1)):
                px, colors = s.render(anim, i, look)
                assert len(px) == s.size[0] * s.size[1] and colors[0] is None
                assert any(px) and all(colors[v] is not None for v in px if v)


@pytest.mark.parametrize("sid", _package_ids())
def test_package_skins_are_own_work_under_cc_by(sid):
    path = os.path.join(skin.PACKAGE_DIR, sid)
    meta = skin.read_toml(os.path.join(path, "skin.toml"))["skin"]
    assert meta["license"] == "CC-BY-4.0" and meta["author"] == "Pixel Familiars"
    with open(os.path.join(path, "CREDITS.txt"), encoding="utf-8") as f:
        text = f.read()
    assert "CC BY 4.0" in text and "vlastní dílo projektu" in text
    assert sid in OWN or sid in skin_export.VARIANTS            # v balíčku jen vlastní skiny, žádné převzaté


def test_license_files():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert open(os.path.join(root, "LICENSE"), encoding="utf-8").read().startswith("MIT License")
    assert "Attribution 4.0 International" in open(os.path.join(root, "LICENSES", "CC-BY-4.0.txt"), encoding="utf-8").read()


def test_cli_preview(data_home, tmp_path, capsys):
    out = tmp_path / "nahled.png"
    skin.main(["rubin", "--nahled", str(out)])
    w, h, _ = skin.read_png(out)
    assert (w, h) == (8 * 32 * 4, 6 * 32 * 4)
    skin.main([])
    assert "rubin" in capsys.readouterr().out
