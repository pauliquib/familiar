import json, os, struct, zlib

import pytest

from familiar import cli, skin, skin_export, skin_import, sprites

STATES = ("idle", "listening", "thinking", "working", "waiting", "success", "error", "sleeping", "gone")
INK, BODY, EYE, HIDDEN = (20, 20, 40, 255), (80, 170, 90, 255), (250, 250, 250, 255), (255, 0, 0, 255)


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "familiar" / "skins"


def figure(n, w=16, h=16):
    """Malá postavička w×h (RGBA): obrys, tělo, oči; n posune oči (rozliší snímky)."""
    px = bytearray(w * h * 4)
    for y in range(h // 4, h):
        for x in range(w // 4, w - w // 4):
            edge = y in (h // 4, h - 1) or x in (w // 4, w - w // 4 - 1)
            px[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(INK if edge else BODY)
    for ex in (w // 2 - 2 + n % 2, w // 2 + 1 + n % 2):
        k = ((h // 2) * w + ex) * 4
        px[k:k + 4] = bytes(EYE)
    return px


TAGS = [("Idle", 0, 1, "forward", 250), ("Run", 2, 5, "pingpong", 100), ("Hurt", 6, 7, "forward", 125),
        ("Spánek", 8, 9, "reverse", 500)]


def make_sheet(dest, fmt="array", w=16, h=16, frames=None):
    """Export Sprite Sheet: sheet.png + sheet.json (json-array nebo json-hash) s tagy a délkami."""
    n = 10
    frames = frames or [figure(i, w, h) for i in range(n)]
    sw = w * len(frames)
    rgba = bytearray(sw * h * 4)
    for i, f in enumerate(frames):
        for y in range(h):
            rgba[(y * sw + i * w) * 4:(y * sw + i * w + w) * 4] = f[y * w * 4:(y + 1) * w * 4]
    skin_export.write_png(str(dest / "sheet.png"), sw, h, rgba)
    dur = {k: d for _, a, b, _, d in TAGS for k in range(a, b + 1)}
    items = [(f"sheet {i}.aseprite", {"frame": {"x": i * w, "y": 0, "w": w, "h": h}, "rotated": False,
                                      "trimmed": False, "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
                                      "sourceSize": {"w": w, "h": h}, "duration": dur.get(i, 100)})
             for i in range(len(frames))]
    tags = [{"name": t, "from": a, "to": b, "direction": d, "color": "#000000ff"} for t, a, b, d, _ in TAGS]
    tags[2]["repeat"] = "1"
    doc = {"frames": dict(items) if fmt == "hash" else [dict(v, filename=k) for k, v in items],
           "meta": {"app": "https://www.aseprite.org/", "image": "sheet.png", "frameTags": tags,
                    "layers": [{"name": "Layer 1", "opacity": 255, "blendMode": "normal"}]}}
    (dest / "sheet.json").write_text(json.dumps(doc))
    return dest / "sheet.json"


# --- minimální .aseprite podle docs/ase-file-specs.md --------------------------------

def _chunk(kind, data):
    return struct.pack("<IH", 6 + len(data), kind) + data


def _str(s):
    b = s.encode()
    return struct.pack("<H", len(b)) + b


def _layer(name, flags=1, ltype=0, level=0):
    return _chunk(0x2004, struct.pack("<HHHHHHB3x", flags, ltype, level, 0, 0, 0, 255) + _str(name))


def _cel(layer, x, y, w, h, px, kind=2):
    head = struct.pack("<HhhBHh5x", layer, x, y, 255, kind, 0)
    return _chunk(0x2005, head + struct.pack("<HH", w, h) + (zlib.compress(px) if kind == 2 else px))


def _link(layer, frame):
    return _chunk(0x2005, struct.pack("<HhhBHh5x", layer, 0, 0, 255, 1, 0) + struct.pack("<H", frame))


def make_aseprite(path, depth=32):
    """3 snímky 16×16: vrstva telo (viditelná), skrytá predloha, skrytá skupina s vnořenou vrstvou;
    snímek 2 je linked cel snímku 0; tagy idle (0–1) a chyba (2, ping-pong)."""
    w = h = 16
    pal = [(0, 0, 0, 0), INK, BODY, EYE, HIDDEN]

    def pixels(rgba):
        if depth == 32:
            return bytes(rgba)
        return bytes(pal.index(tuple(rgba[k:k + 4])) if rgba[k + 3] else 0 for k in range(0, len(rgba), 4))

    full = bytes(HIDDEN) * (w * h)
    frames = []
    for f in range(3):
        chunks = []
        if f == 0:
            chunks += [_layer("telo"), _layer("predloha", flags=0), _layer("skupina", flags=0, ltype=1),
                       _layer("ve skupine", level=1)]
            entries = b"".join(struct.pack("<H", 0) + bytes(c) for c in pal)
            chunks.append(_chunk(0x2019, struct.pack("<III8x", len(pal), 0, len(pal) - 1) + entries))
            tags = [(0, 1, 0, 0, "idle"), (2, 2, 2, 0, "Chyba")]
            chunks.append(_chunk(0x2018, struct.pack("<H8x", len(tags)) + b"".join(
                struct.pack("<HHBH6x3sx", a, b, d, r, b"\0\0\0") + _str(n) for a, b, d, r, n in tags)))
        if f == 2:
            chunks.append(_link(0, 0))
        else:
            img = figure(f)
            if f == 0:      # raw cel přes celé plátno
                chunks.append(_cel(0, 0, 0, w, h, pixels(img), kind=0))
            else:           # zlib cel jen s obsahem (řádky 4–15), posunutý na y = 4
                chunks.append(_cel(0, 0, 4, w, h - 4, pixels(img[4 * w * 4:])))
        chunks.append(_cel(1, 0, 0, w, h, pixels(full)))        # skrytá vrstva
        chunks.append(_cel(3, 0, 0, w, h, pixels(full)))        # vrstva ve skryté skupině
        body = b"".join(chunks)
        frames.append(struct.pack("<IHHH2xI", 16 + len(body), 0xF1FA, len(chunks), 100 * (f + 1), len(chunks)) + body)
    data = b"".join(frames)
    header = struct.pack("<IHHHHHIH8xB3xHBBhhHH84x", 128 + len(data), 0xA5E0, 3, w, h, depth, 1, 100,
                         0, len(pal), 1, 1, 0, 0, 16, 16)
    assert len(header) == 128
    path.write_bytes(header + data)
    return path


# --- testy -----------------------------------------------------------------------------

def _render_all(s):
    for state in STATES:
        anim = s.anim_for(state, "Bash")
        assert anim in s.anims, (state, anim)
        for i in range(s.anims[anim].frames):
            for mood in sprites.MOOD:
                px, colors = s.render(anim, i, (mood, None, s.mood_emote(mood), i % 2, 1, 0))
                assert len(px) == 32 * 32 and colors[0] is None
                assert any(px)


@pytest.mark.parametrize("fmt", ["array", "hash"])
def test_import_sheet(data_home, tmp_path, fmt):
    js = make_sheet(tmp_path, fmt)
    dest, report, warn = skin_import.importuj(str(js), "hrdina")
    assert dest == str(data_home / "hrdina")
    s = skin.load("hrdina")
    assert s.error is None and s.source == skin.USER and not s.missing
    assert s.anim_for("idle") == "Idle" and s.anim_for("working", "Read") == "Run"
    assert s.anim_for("error") == "Hurt" and s.anim_for("sleeping") == s.anim_for("gone") == "Spánek"
    assert s.anims["Idle"] == skin.Anim(4, 2, False)
    assert s.anims["Run"] == skin.Anim(10, 6, False)         # ping-pong 2-3-4-5-4-3
    assert s.anims["Hurt"].oneshot and s.anims["Hurt"].fps == 8
    assert s.anims["Spánek"].fps == 2
    for st in ("listening", "thinking", "waiting", "success"):
        assert report[st][1], st                              # odvozené z idle
    assert s.anims[s.anim_for("listening")].oneshot and s.anims[s.anim_for("success")].oneshot
    assert any("zvětšuji 2×" in w for w in warn)
    # postava 8×12 px zvětšená 2× sedí na spodní hraně, uprostřed
    px, colors = s.render("Idle", 0)
    rows = [k // 32 for k, v in enumerate(px) if v]
    cols = [k % 32 for k, v in enumerate(px) if v]
    assert max(rows) == 31 and min(rows) == 32 - 24 and (min(cols), max(cols)) == (8, 23)
    assert {colors[v] for v in px if v} == {"#141428", "#50aa5a", "#fafafa"}
    assert set(s.palettes) == {"base", "warm", "cold", "faded"}
    assert s.render("Idle", 0, ("radost",) + skin.NO_LOOK[1:])[1] != colors
    _render_all(s)


def test_import_from_png_path_and_overwrite(data_home, tmp_path):
    make_sheet(tmp_path)
    png = str(tmp_path / "sheet.png")
    skin_import.importuj(png)
    assert skin.load("sheet").error is None
    with pytest.raises(skin.SkinError, match="už existuje"):
        skin_import.importuj(png)
    with pytest.raises(skin.SkinError, match="už existuje"):     # ani skin z balíčku
        skin_import.importuj(png, "robokun")
    (data_home / "sheet" / "navic.txt").write_text("x")
    skin_import.importuj(png, prepsat=True)
    assert not (data_home / "sheet" / "navic.txt").exists()
    assert sorted(p for p in os.listdir(data_home)) == ["sheet"]   # žádné dočasné adresáře


def test_mapa(data_home, tmp_path):
    js = make_sheet(tmp_path)
    mapa = tmp_path / "mapa.toml"
    mapa.write_text('name = "Můj hrdina"\nmeritko = 1\noneshot = ["Spánek"]\nnalady = false\n'
                    '[stavy]\nchyba = "Run"\nworking = { Bash = "Hurt", default = "Idle" }\nsuccess = "Hurt"\n')
    skin_import.importuj(str(js), "m", str(mapa))
    s = skin.load("m")
    assert s.error is None and s.name == "Můj hrdina"
    assert s.anim_for("error") == "Run" and s.anim_for("success") == "Hurt"
    assert s.anim_for("working", "Bash") == "Hurt" and s.anim_for("working", "Edit") == "Idle"
    assert s.anims["Spánek"].oneshot and not s.anims["Run"].oneshot      # oneshot z mapy nahradí výchozí
    assert set(s.palettes) == {"base"}
    rows = [k // 32 for k, v in enumerate(s.render("Idle", 0)[0]) if v]
    assert min(rows) == 32 - 12                                         # bez zvětšení
    mapa.write_text('[stavy]\nidle = "Neni"\n')
    with pytest.raises(skin.SkinError, match="Neni"):
        skin_import.importuj(str(js), "m2", str(mapa))


def test_tag_names_cz_en():
    g = skin_import.guess_state
    assert g("Idle") == ("idle", None) and g("Přemýšlí") == ("thinking", None)
    assert g("work_edit") == ("working", "work_edit") and g("Run 2") == ("working", None)
    assert g("Zakopnutí") == ("error", None) and g("trip") == ("error", None)
    assert g("Mávání") == ("waiting", None) and g("spí") == ("sleeping", None)
    assert g("Ninja Idle") == ("idle", None) and g("xyz") == (None, None)


def test_work_tags_per_tool(data_home, tmp_path):
    global TAGS
    old = TAGS
    TAGS = [("idle", 0, 1, "forward", 250), ("work_bash", 2, 3, "forward", 125), ("work_search", 4, 5, "forward", 125),
            ("work_edit", 6, 7, "forward", 125), ("sleep", 8, 9, "forward", 500)]
    try:
        skin_import.importuj(str(make_sheet(tmp_path)), "nastroje")
    finally:
        TAGS = old
    s = skin.load("nastroje")
    assert s.anim_for("working", "Bash") == "work_bash" and s.anim_for("working", "Grep") == "work_search"
    assert s.anim_for("working", "Write") == "work_edit" and s.anim_for("working", "Nic") == "work_bash"


def test_many_colors_and_big_sprite(data_home, tmp_path):
    w = h = 64
    frames = []
    for i in range(10):
        px = bytearray(w * h * 4)
        for y in range(8, 64):
            for x in range(8, 56):
                px[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(((x * 4 + i) % 256, y * 4 % 256, 120, 255))
        frames.append(px)
    js = make_sheet(tmp_path, w=w, h=h, frames=frames)
    _, _, warn = skin_import.importuj(str(js), "velky")
    assert any("zmenšuji 2×" in x for x in warn) and any("sloučeny na 15" in x for x in warn)
    s = skin.load("velky")
    assert s.error is None and len(s.palettes["base"]) == 16
    px = s.render("Idle", 0)[0]
    assert sum(1 for v in px if v) == 24 * 28
    _render_all(s)


@pytest.mark.parametrize("depth", [32, 8])
def test_import_aseprite(data_home, tmp_path, depth):
    src, warn = skin_import.read_aseprite(str(make_aseprite(tmp_path / "Postava.aseprite", depth)))
    assert (src.w, src.h, len(src.frames), src.durations) == (16, 16, 3, [100, 200, 300])
    assert [t.name for t in src.tags] == ["idle", "Chyba"] and src.tags[1].direction == "pingpong"
    assert src.frames[0] == figure(0) and src.frames[1] == figure(1)    # skryté vrstvy se nekreslí
    assert src.frames[2] == src.frames[0]                                # linked cel
    assert warn == []
    dest, report, _ = skin_import.importuj(str(tmp_path / "Postava.aseprite"))
    assert os.path.basename(dest) == "postava"
    s = skin.load("postava")
    assert s.error is None and s.name == "Postava"
    assert s.anim_for("idle") == "idle" and s.anim_for("error") == "Chyba" and s.anims["Chyba"].oneshot
    assert s.anims["idle"].fps == 7          # (100 + 200) / 2 ms
    assert report["working"][1] and report["sleeping"][1]
    _render_all(s)


def test_aseprite_rejects_garbage(tmp_path):
    p = tmp_path / "x.aseprite"
    p.write_bytes(b"\0" * 200)
    with pytest.raises(skin.SkinError, match="není soubor Aseprite"):
        skin_import.read_aseprite(str(p))
    data = make_aseprite(tmp_path / "y.ase").read_bytes()
    (tmp_path / "y.ase").write_bytes(data[:300])
    with pytest.raises(skin.SkinError):
        skin_import.read_aseprite(str(tmp_path / "y.ase"))


def test_cli_skin_import(data_home, tmp_path, capsys):
    js = make_sheet(tmp_path)
    out = tmp_path / "nahled.png"
    assert cli.main(["skin-import", str(js), "--id", "cli", "--nahled", str(out)]) == 0
    text = capsys.readouterr().out
    assert "skin 'cli' vytvořen" in text and "odvozeno z idle" in text
    w, h, _ = skin.read_png(str(out))
    assert (w, h) == (8 * 32 * 4, len(sprites.MOOD) * 32 * 4)
    assert cli.main(["skin-import", str(js), "--id", "cli"]) == 1
    assert "--prepsat" in capsys.readouterr().err
    assert cli.main(["skin-import", str(js), "--id", "cli", "--prepsat"]) == 0
