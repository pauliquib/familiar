# Generátor skinu „Květina“: květina v květináči kreslená kódem (formát docs/skiny.md).
#
#   python3 -I tools/kvetina.py [cílový adresář]      (výchozí familiar/skins/kvetina)
#
# Kresba je z geometrie: okvětní lístky jsou elipsy kolem středu květu, stonek je
# křivka, listy čočky. Každá část má vlastní obrys (index 1). Obličej (oči, pusa) je
# na středu květu a nálada ho mění záplatami ve vrstvě face. Reakce jsou Robo-kunovy
# (sprites.POPS) přebarvené do palety, drony jsou včelky. Vlastní dílo projektu, CC BY 4.0.
import argparse, math, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from familiar import skin, skin_export, sprites   # noqa: E402

W = H = 32
NONE = skin.NONE
OUT, PET, PET_D, PET_L, DISC, DISC_D, LEAF, LEAF_D, LEAF_L, POT, POT_D, WHITE, YELLOW, RED, GREY = range(1, 16)

BASE = [None,
        "#2b1d2e",   # 1 obrys, oči
        "#ff7eb0",   # 2 okvětí
        "#d9518a",   # 3 okvětí stín
        "#ffc4dc",   # 4 okvětí světlo
        "#ffd84d",   # 5 střed květu (obličej)
        "#e9a23b",   # 6 střed stín
        "#5cc46a",   # 7 list
        "#2f8a4a",   # 8 list stín
        "#a6e8a0",   # 9 list světlo
        "#d0703e",   # 10 květináč
        "#8e4428",   # 11 květináč stín
        "#f7f3ea",   # 12 bílá (efekty, odlesk v očích)
        "#ffe066",   # 13 žlutá („!“, včelky)
        "#e8434f",   # 14 červená (reakce, tvářičky)
        "#8fa3b8"]   # 15 šedomodrá (reakce, křídla včelek)


def _pal(base, **swap):
    p = list(base)
    for k, v in swap.items():
        idx = {"pet": (PET, PET_D, PET_L), "disc": (DISC, DISC_D), "leaf": (LEAF, LEAF_D, LEAF_L)}[k]
        for i, c in zip(idx, v):
            p[i] = c
    return p


PALETTES = {   # nálada mění barvy okvětí, středu a listů; indexy zůstávají
    "base": BASE,
    "warm": _pal(BASE, pet=("#ff4f93", "#c92a6c", "#ffa3cb"), disc=("#ffcc1f", "#e88a1c")),      # radost: sytější
    "red": _pal(BASE, pet=("#f0473f", "#b02a2e", "#ff9a8a"), disc=("#ffb340", "#d9772a")),        # frustrace
    "cool": _pal(BASE, pet=("#a99cff", "#7062d6", "#d6cfff"), disc=("#f0e27a", "#c9b25a")),       # zmatek
    "faded": _pal(BASE, pet=("#d9a9bb", "#b38494", "#ecd5de"), disc=("#e3d39a", "#c4ac78"),       # únava
                  leaf=("#8fb388", "#5f7d5d", "#bed4b8")),
}

MOODS = {   # nálada → oči, pusa, paleta, reakce při změně, tempo
    "klid": (None, None, "base", None, 1.0),
    "radost": (None, "smile", "warm", "heart", 1.0),
    "zvedavost": ("wide", "o", "base", "question", 1.0),
    "frustrace": ("angry", "frown", "red", "storm", 1.0),
    "zmatek": ("dazed", "wave", "cool", "spiral", 1.0),
    "unava": ("droopy", None, "faded", None, 0.6),
}

# reakce: barvy Robo-kuna → barvy květiny
POP_COLORS = {1: OUT, 8: WHITE, 9: YELLOW, 10: RED, 11: LEAF, 13: GREY, 14: POT_D, 15: PET_D}


class Canvas:
    def __init__(self):
        self.px = bytearray([NONE]) * (W * H)

    def put(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.px[y * W + x] = c

    def get(self, x, y):
        return self.px[y * W + x] if 0 <= x < W and 0 <= y < H else NONE

    def part(self, mask, color, outline=OUT):
        """Část s vlastním obrysem: obrys kolem masky, pak výplň color(x, y)."""
        for x, y in mask:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in mask:
                    self.put(nx, ny, outline)
        for x, y in mask:
            self.put(x, y, color(x, y))

    def blit(self, rows, x, y, colors):
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch in colors:
                    self.put(x + dx, y + dy, colors[ch])


def _cells(test):
    return {(x, y) for y in range(H) for x in range(W) if test(x + 0.5, y + 0.5)}


# --- části květiny ---------------------------------------------------------------

POT_TOP = 25         # horní řádek okraje květináče


def _pot(g):
    rim = {(x, y) for x in range(9, 24) for y in range(POT_TOP, POT_TOP + 2)}
    g.part(rim, lambda x, y: POT_D if x >= 21 else POT)
    body = {(x, y) for y in range(POT_TOP + 3, 31) for x in range(10 + (y - POT_TOP - 3), 23 - (y - POT_TOP - 3))}
    g.part(body, lambda x, y: POT_D if x >= 20 - (y - POT_TOP - 3) else POT)
    for x in range(9, 24):     # spára pod okrajem
        g.put(x, POT_TOP + 2, OUT)


def _bezier(p0, p1, p2, n=24):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (k / n for k in range(n + 1))]


def _stem(g, top, sway):
    pts = _bezier((16.5, POT_TOP + 0.5), (16.5 + sway, POT_TOP - 4), top)
    mask = _cells(lambda x, y: min((x - px) ** 2 + (y - py) ** 2 for px, py in pts) <= 0.45)
    g.part(mask, lambda x, y: LEAF)
    return pts


def _leaf(g, base, side, angle, length=7.0, width=2.3):
    """Čočka od bodu base na stranu side (-1 vlevo, 1 vpravo), angle ve stupních nad vodorovnou."""
    a = math.radians(angle)
    ux, uy = side * math.cos(a), -math.sin(a)
    vx, vy = -uy, ux

    def inside(x, y):
        dx, dy = x - base[0], y - base[1]
        u, v = dx * ux + dy * uy, dx * vx + dy * vy
        return 0 <= u <= length and abs(v) <= width * math.sin(math.pi * u / length) ** 0.7

    def color(x, y):
        dx, dy = x + 0.5 - base[0], y + 0.5 - base[1]
        u, v = dx * ux + dy * uy, (dx * vx + dy * vy) * side
        if abs(v) < 0.5 and 1.5 < u < length - 1.5:
            return LEAF_D                      # žilka
        return LEAF_L if v < -0.8 and u > length * 0.35 else LEAF
    g.part(_cells(inside), color)


def _head(g, cx, cy, petals=1.0, tilt=0.0):
    """Okvětí (6 lístků, každý s obrysem) a střed. petals = rozvinutí, tilt = otočení ve stupních."""
    n, d, a, b = 6, 4.6 * petals, 3.0 * petals, 2.5
    angs = [math.radians(tilt + 90 + k * 360 / n) for k in range(n)]
    for ang in sorted(angs, key=math.sin):            # odspodu nahoru: horní lístky překryjí spodní
        px, py = cx + d * math.cos(ang), cy - d * math.sin(ang)
        ca, sa = math.cos(ang), math.sin(ang)
        mask = _cells(lambda x, y: ((((x - px) * ca - (y - py) * sa) / a) ** 2
                                   + (((x - px) * sa + (y - py) * ca) / b) ** 2) <= 1)

        def pcol(x, y, px=px, py=py, ca=ca, sa=sa):
            u = (x + 0.5 - px) * ca - (y + 0.5 - py) * sa            # podél lístku ven
            v = (x + 0.5 - px) * sa + (y + 0.5 - py) * ca            # napříč
            if u > a * 0.35 and v < -0.3 and sa > -0.6:
                return PET_L                                         # světlo na konečku
            if sa < -0.3 or (u < -a * 0.2 and v > 0.6):
                return PET_D                                         # spodní lístky a stín u středu
            return PET
        g.part(mask, pcol)
    disc = _cells(lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= 4.0 ** 2)
    g.part(disc, lambda x, y: DISC_D if (x + 0.5 - cx) + (y + 0.5 - cy) > 3.6 else DISC)


def _bud(g, cx, cy, nod=0):
    """Zavřené poupě: kapka okvětí v zelených kališních lístcích."""
    bud = _cells(lambda x, y: ((x - cx) / 4.4) ** 2 + ((y - cy) / (4.6 if y < cy else 3.4)) ** 2 <= 1)
    g.part(bud, lambda x, y: PET_L if x < cx - 1.5 and y < cy - 1 else PET_D if x > cx + 1.5 else PET)
    for x in range(int(cx) - 3, int(cx) + 4):          # zavinuté lístky
        if (x + nod) % 3 == 0 and g.get(x, int(cy - 2)) == PET:
            g.put(x, int(cy - 2), PET_D)
    sep = _cells(lambda x, y: y > cy + 1 and ((x - cx) / 4.0) ** 2 + ((y - cy - 2.2) / 1.9) ** 2 <= 1
                 and not (abs(x - cx) < 1.6 and y < cy + 2.2))
    g.part(sep, lambda x, y: LEAF_D if y > cy + 3 else LEAF)


# --- obličej -------------------------------------------------------------------------
# Záplaty: oči 7×3 (levý horní roh = střed − (3, 2)), pusa 5×2 (střed + (−2, 1)).
# „.“ = podklad středu květu (smaže výchozí obličej), x = tmavá, w = odlesk, r = tvářička.

EYES_OFF, EYES_SIZE = (-3, -2), (7, 3)
MOUTH_OFF, MOUTH_SIZE = (-2, 1), (5, 2)
EYES = {
    "open": [".......", "wx...wx", "xx...xx"],
    "wide": ["wx...wx", "xx...xx", "xx...xx"],
    "closed": [".......", ".......", "xx...xx"],
    "happy": [".......", ".x...x.", "x.x.x.x"],
    "x": ["x.....x", ".x...x.", "x.....x"],      # > <
    "angry": ["x.....x", "xx...xx", "xx...xx"],
    "droopy": [".......", "xx...xx", "wx...wx"],
    "dazed": ["xxx.xxx", "x.x.x.x", "xxx.xxx"],
    "up": ["wx...wx", "xx...xx", "......."],
}
MOUTHS = {
    "line": [".xxx.", "....."],
    "smile": ["x...x", ".xxx."],
    "o": [".xxx.", ".xxx."],
    "frown": [".xxx.", "x...x"],
    "wave": [".x.x.", "x.x.x"],
}
FACE = {".": DISC, "x": OUT, "w": WHITE, "r": RED}


def _face(g, ix, iy, eyes, mouth, look=0):
    g.blit(EYES[eyes], ix + EYES_OFF[0] + look, iy + EYES_OFF[1], FACE)
    g.blit(MOUTHS[mouth], ix + MOUTH_OFF[0] + look, iy + MOUTH_OFF[1], FACE)


# --- efekty (vrstva fx) ------------------------------------------------------------------

def _dots(g, n):
    for k in range(n):
        g.blit(["ww", "ww"], 24 + 3 * k, 0, {"w": WHITE})


def _bang(g, on):
    if on:
        g.blit(["yy", "yy", "yy", "yy", "  ", "yy"], 29, 0, {"y": YELLOW})


Z_SMALL = ["xxx", "  x", " x ", "xxx"]
Z_BIG = ["xxxx", "   x", "  x ", " x  ", "xxxx"]


def _zzz(g, i):
    g.blit(Z_SMALL, 23, 7 - i % 2, {"x": WHITE})
    if i % 2 == 0:
        g.blit(Z_BIG, 27, 1, {"x": WHITE})


def _sparkle(g, x, y, c=YELLOW):
    g.blit([" c ", "cwc", " c "], x - 1, y - 1, {"c": c, "w": WHITE})


def _sweat(g, dy):
    g.blit([" w ", "www", "www"], 25, 6 + dy, {"w": GREY})


FX = {"dots": _dots, "bang": _bang, "zzz": _zzz, "sparkle": _sparkle, "sweat": _sweat}


# --- póza -----------------------------------------------------------------------------------

def draw(p):
    """(body, fx, kotva středu květu) jedné pózy."""
    g = Canvas()
    cx, cy = 16.5 + p.get("hdx", 0), 9.5 + p.get("hdy", 0)
    stem_top = (cx - p.get("tilt", 0) / 30, cy + 3)
    pts = _stem(g, stem_top, p.get("sway", 0))
    bx, by = pts[7]
    _leaf(g, (bx - 0.3, by), -1, p.get("left", 20))
    _leaf(g, (bx + 0.3, by - 0.5), 1, p.get("right", 20))
    _pot(g)
    ix, iy = math.floor(cx), math.floor(cy)
    if p.get("bud"):
        _bud(g, cx, cy + 2, p.get("nod", 0))
        g.blit(["xx...xx"], ix - 3, iy + 2, {"x": OUT})       # spí: zavřená očka na poupěti
    else:
        _head(g, cx, cy, p.get("petals", 1.0), p.get("tilt", 0))
        _face(g, ix, iy, p.get("eyes", "open"), p.get("mouth", "line"), p.get("look", 0))
    fx = Canvas()
    for name, *args in p.get("fx", []):
        FX[name](fx, *args)
    return g.px, fx.px, (ix, iy)


# --- animace --------------------------------------------------------------------------------

def _idle():
    frames = []
    sway = (0, 0, 1, 1, 1, 0, 0, -1, -1, -1)
    for i in range(20):                 # 5 s: pohupování stonku a listů, jednou mrkne
        s = sway[i % 10]
        frames.append({"hdx": s, "sway": s, "left": 20 + 6 * s, "right": 20 - 6 * s,
                       "eyes": "closed" if i == 13 else "open"})
    return frames


ANIMS = {   # tag → (fps, pózy, jednorázová)
    "idle": (4, _idle(), False),
    "listen": (8, [{"right": r, "hdy": h, "eyes": "wide", "mouth": "o"}
                   for r, h in ((20, 0), (55, 0), (75, 1), (40, 0))], True),
    "think": (6, [{"tilt": 18, "hdx": -1, "sway": -1, "eyes": "up", "look": -1, "left": 30, "right": 10,
                   "fx": [("dots", i // 2 + 1)]} for i in range(6)], False),
    "work": (8, [{"left": 20 + 25 * (i % 2), "right": 45 - 25 * (i % 2), "hdy": i % 2,
                  "look": (0, 1, 0, -1, 0, 1)[i]} for i in range(6)], False),
    "wave": (6, [{"right": (70, 40, 70, 40)[i], "left": 15, "eyes": "wide", "mouth": "o", "hdx": -(i % 2),
                  "fx": [("bang", i % 2 == 0)]} for i in range(4)], False),
    "hop": (8, [{"petals": f, "hdy": dy, "eyes": "happy", "mouth": "smile", "left": l, "right": l,
                 "fx": [("sparkle", 6, 4), ("sparkle", 27, 11), ("sparkle", 26, 2, WHITE)] if s else []}
                for f, dy, l, s in ((0.85, 0, 20, 0), (1.0, 0, 40, 0), (1.12, 0, 60, 1),
                                    (1.12, 0, 60, 1), (1.05, 0, 35, 0), (1.0, 0, 20, 0))], True),
    "stumble": (8, [{"tilt": t, "hdy": dy, "hdx": x, "sway": x, "petals": f, "eyes": "x", "mouth": "wave",
                     "left": l, "right": l, "fx": [("sweat", i // 2)] if 0 < i < 5 else []}
                    for i, (t, dy, x, f, l) in enumerate(((0, 0, 0, 1.0, 20), (-25, 2, 2, 0.9, -15),
                                                          (-35, 3, 1, 0.85, -25), (-35, 3, 3, 0.85, -25),
                                                          (-20, 2, 1, 0.9, -10), (0, 0, 0, 1.0, 20)))],
                True),
    "sleep": (2, [{"bud": True, "nod": i % 2, "hdy": 1 + i % 2, "hdx": 0, "left": -10, "right": -10,
                   "fx": [("zzz", i)]} for i in range(4)], False),
}

ACTIVITY = {"idle": "idle", "listening": "listen", "thinking": "think", "waiting": "wave",
            "success": "hop", "error": "stumble", "sleeping": "sleep", "gone": "sleep"}
LOCKED_EYES = {"closed", "x", "happy", "wide", "up"}


# --- vrstvy a zápis ---------------------------------------------------------------------------

BEE = ([" yoyo  ", "yyoyoo ", " yoyo  "],                 # tělo s proužky, hlavička vpravo
       (["  ww   ", " wwww  "], ["       ", "wwww   "]))      # křídla nahoře / dole


def _drone(k, phase):
    g = Canvas()
    flap = (phase + k) % 2
    y = 14 + k * 6 + flap
    g.blit(BEE[1][flap], 0, y, {"w": WHITE})
    g.blit(BEE[0], 0, y + 2, {"o": OUT, "y": YELLOW})
    return g.px


def layers():
    body, fx, tags, keys = [], [], [], {"eyes": [], "mouth": [], "head": []}
    keep = {"eyes": {}, "mouth": {}}
    for anim, (fps, poses, oneshot) in ANIMS.items():
        tags.append((anim, len(poses), fps, oneshot))
        for i, p in enumerate(poses):
            f = len(body)
            b, e, (ix, iy) = draw(p)
            body.append(b)
            fx.append(e)
            look = p.get("look", 0)
            for s, key in (("eyes", (ix + EYES_OFF[0] + look, iy + EYES_OFF[1], *EYES_SIZE)),
                           ("mouth", (ix + MOUTH_OFF[0] + look, iy + MOUTH_OFF[1], *MOUTH_SIZE)),
                           ("head", (ix - 8, iy - 8, 17, 17))):
                if not keys[s] or keys[s][-1][1:] != key:
                    keys[s].append((f, *key))
            if p.get("bud") or p.get("eyes", "open") in LOCKED_EYES:
                keep["eyes"].setdefault(anim, []).append(i)
            if p.get("bud") or p.get("mouth", "line") != "line":
                keep["mouth"].setdefault(anim, []).append(i)

    ref = draw({})[2]
    face, face_tags = [], []
    for slot, table, off in (("eyes", EYES, EYES_OFF), ("mouth", MOUTHS, MOUTH_OFF)):
        for name, rows in table.items():
            g = Canvas()
            g.blit(rows, ref[0] + off[0], ref[1] + off[1], FACE)
            face.append(g.px)
            face_tags.append((f"{slot}_{name}", 1, 1, False))

    emote, emote_tags = [], []
    for name in sprites.POPS:
        for phase in (0, 1):
            g = sprites.Grid()
            g.px = bytearray([NONE]) * (W * H)
            sprites._pop(g, name, phase)
            emote.append(bytearray(POP_COLORS[v] if v != NONE else NONE for v in g.px))
        emote_tags.append((name, 2, 3, False))

    drone, drone_tags = [], []
    for k in range(3):
        drone += [_drone(k, phase) for phase in (0, 1)]
        drone_tags.append((f"drone{k + 1}", 2, 3, False))

    one = lambda off, size: [(0, ref[0] + off[0], ref[1] + off[1], *size)]
    out = {
        "body": (body, tags, False, keys),
        "fx": (fx, tags, True, None),
        "face": (face, face_tags, True, {"eyes": one(EYES_OFF, EYES_SIZE), "mouth": one(MOUTH_OFF, MOUTH_SIZE)}),
        "emote": (emote, emote_tags, True, None),
        "drone": (drone, drone_tags, True, None),
    }
    return out, keep


def skin_toml(keep):
    tv = skin_export._toml_value
    lines = ["# Vygenerováno: python3 -I tools/kvetina.py (kresba kódem). Formát popisuje docs/skiny.md.",
             "# Vlastní dílo projektu Pixel Familiars, CC BY 4.0 (viz CREDITS.txt).", "",
             "[skin]", 'name = "Květina"', f"size = [{W}, {H}]", "anchor = [16, 31]",
             'author = "Pixel Familiars"', 'license = "CC-BY-4.0"', "",
             "[layers]"]
    lines += [f'{k} = "{k}.png"' for k in ("body", "fx", "face", "emote", "drone")]
    lines += ["", "[palettes]"] + [f'{k} = "pal/{k}.gpl"' for k in PALETTES]
    lines += ["", "[activity]"] + [f"{st} = {tv(a)}" for st, a in ACTIVITY.items()]
    lines += ['working = { default = "work" }', "", "[mood]"]
    for mood, (eyes, mouth, pal, emote, tempo) in MOODS.items():
        m = {k: v for k, v in (("eyes", eyes), ("mouth", mouth), ("palette", pal), ("emote", emote)) if v}
        if tempo != 1.0:
            m["tempo"] = tempo
        lines.append(f"{mood} = {tv(m)}")
    lines += ["", "[face]", "# snímky tagu, kde výraz určuje animace a nálada ho nepřepíše (true = všechny)"]
    for slot, by_anim in keep.items():
        v = {a: True if len(ix) == len(ANIMS[a][1]) else ix for a, ix in by_anim.items()}
        lines.append(f"keep_{slot} = {tv(v)}")
    return "\n".join(lines) + "\n"


CREDITS = """Květina – skin pro Pixel Familiars

Grafika: vlastní dílo projektu Pixel Familiars, kreslené kódem (tools/kvetina.py).
Licence: Creative Commons Uveďte původ 4.0 Mezinárodní (CC BY 4.0)
         https://creativecommons.org/licenses/by/4.0/ (plné znění v LICENSES/CC-BY-4.0.txt)
Uveďte: Pixel Familiars (Pavel Švec), https://github.com/pauliquib/familiar

Reakce nad hlavou jsou Robo-kunovy (familiar/sprites.py) přebarvené do palety skinu,
drony subagentů jsou včelky. Skin znovu vygeneruje: python3 -I tools/kvetina.py
"""


def export(dest):
    os.makedirs(os.path.join(dest, "pal"), exist_ok=True)
    out, keep = layers()
    for layer, (frames, tags, overlay, slices) in out.items():
        skin_export.write_sheet(dest, layer, frames, tags, PALETTES["base"], overlay, slices)
    for k, colors in PALETTES.items():
        skin_export.write_gpl(os.path.join(dest, "pal", f"{k}.gpl"), k, colors)
    with open(os.path.join(dest, "skin.toml"), "w", encoding="utf-8") as f:
        f.write(skin_toml(keep))
    with open(os.path.join(dest, "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write(CREDITS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="skin Květina kreslený kódem")
    ap.add_argument("dest", nargs="?", default=os.path.join(REPO, "familiar", "skins", "kvetina"))
    args = ap.parse_args(argv)
    export(args.dest)
    print(f"skin kvetina zapsán do {args.dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
