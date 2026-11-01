# Exportér: Robo-kun ze sprites.py jako balíček skinu (formát v docs/skiny.md).
#
#   python3 -m familiar.skin_export <cílový adresář> [--variant rubin]
#
# Zapíše skin.toml, sheety body/fx/face/acc/emote/drone (PNG + JSON ve formátu
# Aseprite json-array s tagy a řezy) a palety pal/*.gpl. Balíčky ve familiar/skins/
# vznikly tímto skriptem; test hlídá, že jsou aktuální a kreslí stejně jako kód.
import argparse, json, os, struct, sys, zlib

from familiar import sprites
from familiar.skin import H, NONE, W

COLUMNS = 8         # snímků na řádek sheetu (jako aseprite --sheet-type rows --sheet-columns 8)
CUT = "#ff00ff"     # barva indexu 0: v překryvné vrstvě vyřízne pixel do průhledna
HEAD = (8, 6)       # levý horní roh hlavy v referenční póze (vrstvy face a acc)
EYES_AT, MOUTH_AT = (12, 9), (14, 13)       # kotvy obličeje v referenční póze (look = 0)
EYES_SIZE, MOUTH_SIZE = (9, 4), (4, 2)
SCREEN = 5          # barva obrazovky, na kterou se kreslí oči a pusa
MOUTHS = ("line", "smile", "o", "frown", "wave")


def _body_colors(base, warm, cold, faded, eyes, dim, screen):
    """Přebarvení Robo-kuna: tělo (2, 3, 4) podle nálady, oči (6, 7) a obrazovka (5) všude."""
    def pal(body):
        p = list(sprites.PALETTE)
        p[2:5], p[5], p[6], p[7] = body, screen, eyes, dim
        return p
    return {"base": pal(base), "warm": pal(warm), "cold": pal(cold), "faded": pal(faded)}


VARIANTS = {   # id → (název, palety)
    "robokun": ("Robo-kun", sprites.PALETTES),
    "rubin": ("Robo-kun Rubín", _body_colors(
        ["#c8344a", "#8c1f33", "#f08a99"], ["#e0603a", "#a8402a", "#f7b08a"],
        ["#7a3a8c", "#4f2260", "#b98ac8"], ["#a88088", "#7d5c63", "#d4bcc0"],
        eyes="#ffe08a", dim="#b08a3c", screen="#2b0f1a")),
    "smaragd": ("Robo-kun Smaragd", _body_colors(
        ["#3fb87a", "#26845a", "#94e6b8"], ["#8cc83c", "#5e9426", "#cdee96"],
        ["#2f8f8f", "#1d6266", "#7fcaca"], ["#8aa89a", "#66806f", "#c2d4ca"],
        eyes="#d4ff8a", dim="#6a9a4a", screen="#0f2a1e")),
    "safir": ("Robo-kun Safír", _body_colors(
        ["#3b5bdb", "#26399e", "#94a8f5"], ["#3f8fe0", "#2a66a8", "#9ccaf5"],
        ["#3a2f9e", "#251c6b", "#8a80d6"], ["#8890b8", "#666d8f", "#c2c7de"],
        eyes="#e8f0ff", dim="#7a88c0", screen="#0b1033")),
    "jantar": ("Robo-kun Jantar", _body_colors(
        ["#e8a33a", "#b0702a", "#ffd48a"], ["#f0c040", "#c08a20", "#ffe9a6"],
        ["#b8603a", "#86402a", "#e8a88a"], ["#c8b08a", "#9c8868", "#e6dac4"],
        eyes="#fff3c4", dim="#b09a5a", screen="#2a1a08")),
    "ametyst": ("Robo-kun Ametyst", _body_colors(
        ["#9b5de5", "#6a3aa8", "#cfa8f5"], ["#d65db1", "#a23a86", "#f2a8dc"],
        ["#4a4aa8", "#2f2f78", "#9494dc"], ["#a898b8", "#7f7090", "#d6cce0"],
        eyes="#ffb3f0", dim="#a0609a", screen="#1e0f2e")),
    "grafit": ("Robo-kun Grafit", _body_colors(
        ["#4e5360", "#33363f", "#828896"], ["#6e5c4e", "#4c3e34", "#a8968a"],
        ["#3a4a6a", "#26324a", "#7486a8"], ["#8a8c92", "#66686e", "#bcbec4"],
        eyes="#ff5a5a", dim="#8a2a2a", screen="#0c0c10")),
    "perla": ("Robo-kun Perla", _body_colors(
        ["#dcdde6", "#a9adc0", "#ffffff"], ["#f0dccb", "#c8a890", "#fff6ee"],
        ["#c4cce8", "#8e98bc", "#eef2ff"], ["#c8c8c8", "#9c9c9c", "#e8e8e8"],
        eyes="#3ad0ff", dim="#2a7a99", screen="#1a1c2c")),
    # klasický Robo-kun s vánoční výzdobou (viz _XMAS níže): barvy beze změny
    "vanoce": ("Robo-kun Vánoce", sprites.PALETTES, "xmas"),
}


# --- vánoční Robo-kun: čepice, šála, sněžení, dárky místo dronů --------------------
# Jen barvy mimo tělo (1, 8–15), takže nálady přebarvují tělo jako u Robo-kuna.

def _santa(g, x, y):
    """Santova čepice místo antény (x, y = levý horní roh hlavy), špička s bambulí visí vpravo.
    Ve výskoku (hlava u horního okraje) je zploštělá a špička vlaje do strany."""
    if y < 6:
        g.blit(["    oooooooooooo",
                "   orrrrrrrrrrrroooo oo",
                "  owwwswwwwwswwwworrowwo",
                "  owwwwwwwswwwwwoooowwo",
                "                     oo"], x - 2, y - 2, {"o": 1, "r": 10, "w": 8, "s": 13})
        return
    g.blit(["       oooooo         ",
            "     oorrrrrroo       ",
            "    orrrrrrrrrroo     ",
            "   orrrrrrrrrrrrro    ",
            "  owwwswwwwwswwwwrooo ",
            "  owwwwwwswwwwwwwo owo",
            "                  owwo",
            "                   oo "], x - 2, y - 6, {"o": 1, "r": 10, "w": 8, "s": 13})


def _scarf_tail(g, dy):
    """Konec šály přes hruď (pod rukama)."""
    g.blit(["ogo", "oro", "ogo", "oro", "oww"], 11, 20 + dy, {"o": 1, "r": 10, "g": 11, "w": 8})


def _scarf(g, dy):
    """Šála kolem krku (přes spodní okraj hlavy, když se hlava pohupuje)."""
    g.blit([" oooooooooooo ", "orrggrrggrrggo", " oooooooooooo "], 9, 17 + dy, {"o": 1, "r": 10, "g": 11})


def _xmas_body(p):
    """Tělo jako sprites.draw() (bez nálady a klobouku), anténu nahradí čepice."""
    g = sprites.Grid()
    dy, sit = p.get("dy", 0), p.get("sit", False)
    bdy = dy + (2 if sit else 0)
    sprites._legs(g, dy, sit, p.get("step", 0))
    sprites._body(g, bdy)
    _scarf_tail(g, bdy)
    sprites._arm(g, "L", p.get("left", "down"), bdy)
    sprites._arm(g, "R", p.get("right", "down"), bdy)
    hx, hy = p.get("hdx", 0), bdy + p.get("hdy", 0)
    sprites._head(g, hx, hy, p.get("eyes", "open"), p.get("mouth", "line"), None, p.get("look", 0))
    _scarf(g, bdy)
    _santa(g, *(a + b for a, b in zip(HEAD, (hx, hy))))
    return g.px


SNOW = ((3, 0), (28, 5), (12, 9), (24, 13), (6, 16))    # vločky v klidu: (x, start), padají 1 px na snímek


def _snow(g, i):
    for x, start in SNOW:
        y = (start + i) % 20 - 1
        x += (i + start) // 5 % 2                        # mírně se kolébá
        if 0 <= y < 18 and not 7 <= x <= 25:             # jen kolem hlavy, ne přes obličej
            g.put(x, y, 8)
            for ax, ay in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                g.put(ax, ay, 13)


def _gift(g, k, phase):
    """Dárek s vrtulkou místo dronu (vlevo dole, jako sprites._drones)."""
    y = 17 + k * 5 + (phase + k) % 2
    prop = " ppp " if (phase + k) % 2 else "p   p"
    box = (10, 11, 15)[k]
    g.blit([prop, "obybo", "oyyyo", "obybo"], 1, y, {"p": 13, "o": 1, "b": box, "y": 9})


_XMAS = {"body": _xmas_body, "fx": {"idle": _snow}, "drone": _gift, "acc": False}
DECOR = {"xmas": _XMAS}


CREDITS = """{name} – skin pro Pixel Familiars

Grafika: vlastní dílo projektu Pixel Familiars, kreslené kódem (familiar/sprites.py).
Licence: Creative Commons Uveďte původ 4.0 Mezinárodní (CC BY 4.0)
         https://creativecommons.org/licenses/by/4.0/ (plné znění v LICENSES/CC-BY-4.0.txt)
Uveďte: Pixel Familiars (Pavel Švec), https://github.com/pauliquib/familiar

Skin znovu vygeneruje: python3 -m familiar.skin_export familiar/skins/{variant} --variant {variant}
"""


# --- zápis souborů ---------------------------------------------------------------

def write_png(path, w, h, rgba):
    """8bitové RGBA PNG bez filtrů (stačí na pár kB pixel artu)."""
    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def write_gpl(path, name, colors):
    lines = ["GIMP Palette", f"Name: {name}", "Columns: 16", "#"]
    for k, c in enumerate(colors):
        c = c or CUT
        label = "pruhledna" if k == 0 else f"barva {k}"
        lines.append("%3d %3d %3d\t%s" % (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), label))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_sheet(dest, name, frames, tags, colors, overlay, slices=None, size=(W, H)):
    """frames: bytearray w×h indexů (NONE = nic, u překryvné vrstvy 0 = vyříznout);
    tags: [(jméno, počet snímků, fps, jednorázová[, směr])] po sobě; slices: {jméno: [(snímek, x, y, w, h)]};
    size: plátno skinu (výchozí W×H)."""
    W, H = size
    cols = min(COLUMNS, len(frames))
    rows = (len(frames) + cols - 1) // cols
    sw, sh = cols * W, rows * H
    rgba = bytearray(sw * sh * 4)
    table = {}
    for k, c in enumerate(colors):
        c = CUT if k == 0 else c
        table[k] = bytes.fromhex(c[1:]) + b"\xff"
    if not overlay:
        table[0] = b"\x00\x00\x00\x00"
    table[NONE] = b"\x00\x00\x00\x00"
    for n, px in enumerate(frames):
        fx, fy = (n % cols) * W, (n // cols) * H
        for y in range(H):
            o = ((fy + y) * sw + fx) * 4
            rgba[o:o + W * 4] = b"".join(table[v] for v in px[y * W:(y + 1) * W])
    write_png(os.path.join(dest, name + ".png"), sw, sh, rgba)

    durations, meta_tags, start = [100] * len(frames), [], 0
    for tag, count, fps, oneshot, *direction in tags:
        for k in range(start, start + count):
            durations[k] = round(1000 / fps)
        t = {"name": tag, "from": start, "to": start + count - 1,
             "direction": direction[0] if direction else "forward", "color": "#000000ff"}
        if oneshot:
            t["repeat"] = "1"
        meta_tags.append(t)
        start += count
    doc = {
        "frames": [{"filename": f"{name} {n}.aseprite",
                    "frame": {"x": (n % cols) * W, "y": (n // cols) * H, "w": W, "h": H},
                    "rotated": False, "trimmed": False,
                    "spriteSourceSize": {"x": 0, "y": 0, "w": W, "h": H},
                    "sourceSize": {"w": W, "h": H}, "duration": durations[n]} for n in range(len(frames))],
        "meta": {"app": "familiar.skin_export", "version": "1", "image": name + ".png",
                 "format": "RGBA8888", "size": {"w": sw, "h": sh}, "scale": "1",
                 "frameTags": meta_tags,
                 "slices": [{"name": s, "color": "#0000ffff",
                             "keys": [{"frame": f, "bounds": {"x": x, "y": y, "w": w, "h": h}}
                                      for f, x, y, w, h in keys]}
                            for s, keys in (slices or {}).items()]},
    }
    with open(os.path.join(dest, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")


# --- vrstvy ze sprites.py ---------------------------------------------------------

def _grid():
    g = sprites.Grid()
    g.px = bytearray([NONE]) * (W * H)
    return g


def _head_xy(p):
    """Levý horní roh hlavy, jak ho počítá sprites.draw()."""
    bdy = p.get("dy", 0) + (2 if p.get("sit") else 0)
    return HEAD[0] + p.get("hdx", 0), HEAD[1] + bdy + p.get("hdy", 0)


def _crop(src, at, size, keep=lambda x, v: True):
    """Z celého snímku nechá jen obdélník (pixely, které projdou keep); jinak NONE."""
    out = bytearray([NONE]) * (W * H)
    for y in range(at[1], at[1] + size[1]):
        for x in range(at[0], at[0] + size[0]):
            if keep(x - at[0], src[y * W + x]):
                out[y * W + x] = src[y * W + x]
    return out


def _antenna():
    """Pixely antény v referenční póze; klobouk, který ji schovává, je vyřízne."""
    a, b = sprites.Grid(), sprites.Grid()
    sprites._head(a, 0, 0, "open", "line", 10)
    sprites._head(b, 0, 0, "open", "line", None)
    return [k for k in range(W * H) if a.px[k] != b.px[k]]


def _hat(hat, lamp):
    g = _grid()
    sprites.HATS[hat](g, *HEAD, lamp)
    if hat in sprites.HIDES_ANTENNA:
        for k in _antenna():
            if g.px[k] == NONE:
                g.px[k] = 0
    return g.px


def layers(decor=None):
    """Vrstvy Robo-kuna: {jméno: (snímky, tagy, překryvná, řezy)} a zámky obličeje.
    decor: výzdoba z DECOR (vlastní tělo, efekty navíc, drony, bez klobouků)."""
    decor = decor or {}
    draw_body = decor.get("body") or (lambda p: sprites.draw(dict(p, fx=[])))
    body, fx, tags = [], [], []
    keys = {"eyes": [], "mouth": [], "head": []}
    keep = {"eyes": {}, "mouth": {}}
    for anim, (fps, poses) in sprites.ANIMS.items():
        tags.append((anim, len(poses), fps, anim in sprites.ONESHOT))
        for i, p in enumerate(poses):
            f = len(body)
            body.append(draw_body(p))
            g = _grid()
            for name, *args in p.get("fx", []):
                sprites.FX[name](g, *args)
            if anim in decor.get("fx", {}):
                decor["fx"][anim](g, i)
            fx.append(g.px)
            hx, hy = _head_xy(p)
            look = p.get("look", 0)
            for s, key in (("eyes", (hx + 4 + look, hy + 3, *EYES_SIZE)),
                           ("mouth", (hx + 6, hy + 7, *MOUTH_SIZE)), ("head", (hx, hy, 16, 12))):
                if not keys[s] or keys[s][-1][1:] != key:
                    keys[s].append((f, *key))
            if p.get("eyes", "open") in sprites.KEEP_EYES:
                keep["eyes"].setdefault(anim, []).append(i)
            if p.get("mouth", "line") != "line":
                keep["mouth"].setdefault(anim, []).append(i)

    # obličej: oči i s obrazovkou pod nimi (smažou výchozí oči), sloupec 8 jen oči
    face, face_tags = [], []
    for name in sprites.EYES:
        full = sprites.draw({"eyes": name})
        face.append(_crop(full, EYES_AT, EYES_SIZE, lambda x, v: x < 8 or v != SCREEN))
        face_tags.append((f"eyes_{name}", 1, 1, False))
    for name in MOUTHS:
        face.append(_crop(sprites.draw({"mouth": name}), MOUTH_AT, MOUTH_SIZE))
        face_tags.append((f"mouth_{name}", 1, 1, False))

    # klobouky: výchozí snímek, varianta hat@anim jen kde se liší (lampa barvy antény)
    acc, acc_tags = [], []
    for hat in sprites.HATS:
        base = _hat(hat, 10)
        acc.append(base)
        acc_tags.append((hat, 1, 1, False))
        for anim, (fps, poses) in sprites.ANIMS.items():
            cells = [_hat(hat, p.get("antenna", 10)) for p in poses]
            if any(c != base for c in cells):
                acc += cells
                acc_tags.append((f"{hat}@{anim}", len(cells), fps, False))

    emote, emote_tags = [], []
    for name in sprites.POPS:
        for phase in (0, 1):
            g = _grid()
            sprites._pop(g, name, phase)
            emote.append(g.px)
        emote_tags.append((name, 2, 3, False))

    drone, drone_tags = [], []
    for k in range(3):
        for phase in (0, 1):
            a, b = _grid(), _grid()
            if decor.get("drone"):
                decor["drone"](a, k, phase)
            else:
                sprites._drones(a, k + 1, phase)
                sprites._drones(b, k, phase)
            drone.append(bytearray(v if v != w else NONE for v, w in zip(a.px, b.px)))
        drone_tags.append((f"drone{k + 1}", 2, 3, False))

    one = lambda at, size: [(0, *at, *size)]
    out = {
        "body": (body, tags, False, keys),
        "fx": (fx, tags, True, None),
        "face": (face, face_tags, True, {"eyes": one(EYES_AT, EYES_SIZE), "mouth": one(MOUTH_AT, MOUTH_SIZE)}),
        "acc": (acc, acc_tags, True, {"head": one(HEAD, (16, 12))}),
        "emote": (emote, emote_tags, True, None),
        "drone": (drone, drone_tags, True, None),
    }
    if decor.get("acc") is False:      # výzdoba má vlastní pokrývku hlavy: klobouky témat se nekreslí
        del out["acc"]
    return out, keep


def _toml_value(v):
    if v is True:
        return "true"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(x)}" for k, x in v.items()) + " }"
    return repr(v)


def skin_toml(name, keep, pals, layer_names=("body", "fx", "face", "acc", "emote", "drone")):
    working = dict(sprites.TOOL_ANIM, default=sprites.anim_for("working", None))
    lines = ["# Vygenerováno: python3 -m familiar.skin_export (zdroj familiar/sprites.py).",
             "# Formát popisuje docs/skiny.md.", "",
             "[skin]", f"name = {_toml_value(name)}", f"size = [{W}, {H}]", "anchor = [16, 31]",
             f"facing = {_toml_value(sprites.FACING)}", 'author = "Pixel Familiars"', 'license = "CC-BY-4.0"',
             "", "[layers]"]
    lines += [f'{k} = "{k}.png"' for k in layer_names]
    lines += ["", "[palettes]"] + [f'{k} = "pal/{k}.gpl"' for k in pals]
    lines += ["", "[activity]"]
    lines += [f"{st} = {_toml_value(a)}" for st, a in sprites.STATE_ANIM.items()]
    lines += [f"working = {_toml_value(working)}", "", "[mood]"]
    for mood, (eyes, mouth, pal, emote, tempo) in sprites.MOOD.items():
        m = {k: v for k, v in (("eyes", eyes), ("mouth", mouth), ("palette", pal), ("emote", emote)) if v}
        if tempo != 1.0:
            m["tempo"] = tempo
        lines.append(f"{mood} = {_toml_value(m)}")
    lines += ["", "[face]", "# snímky tagu, kde výraz určuje animace a nálada ho nepřepíše (true = všechny)"]
    for slot, by_anim in keep.items():
        v = {a: True if len(ix) == len(sprites.ANIMS[a][1]) else ix for a, ix in by_anim.items()}
        lines.append(f"keep_{slot} = {_toml_value(v)}")
    return "\n".join(lines) + "\n"


def export(dest, variant="robokun"):
    name, pals, *decor = VARIANTS[variant]
    os.makedirs(os.path.join(dest, "pal"), exist_ok=True)
    out, keep = layers(DECOR[decor[0]] if decor else None)
    for layer, (frames, tags, overlay, slices) in out.items():
        write_sheet(dest, layer, frames, tags, pals["base"], overlay, slices)
    for k, colors in pals.items():
        write_gpl(os.path.join(dest, "pal", f"{k}.gpl"), k, colors)
    with open(os.path.join(dest, "skin.toml"), "w", encoding="utf-8") as f:
        f.write(skin_toml(name, keep, pals, [k for k in ("body", "fx", "face", "acc", "emote", "drone") if k in out]))
    with open(os.path.join(dest, "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write(CREDITS.format(name=name, variant=variant))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Robo-kun ze sprites.py jako balíček skinu")
    ap.add_argument("dest", help="cílový adresář (např. familiar/skins/robokun)")
    ap.add_argument("--variant", choices=sorted(VARIANTS), default="robokun", help="paleta (výchozí robokun)")
    args = ap.parse_args(argv)
    export(args.dest, args.variant)
    print(f"skin {args.variant} zapsán do {args.dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
