# Generátor skinu „Ptáček“: sýkorka modřinka na větvičce kreslená kódem (formát docs/skiny.md).
#
#   python3 -I tools/ptacek.py [cílový adresář]      (výchozí familiar/skins/ptacek)
#
# Stejná stavba jako tools/kvetina.py: kresba z geometrie (tělíčko je elipsa, křídla,
# ocásek a chocholka jsou čočky), každá část má vlastní obrys (index 1). Obličej (oči,
# zobáček) je na bílé tváři a nálada ho mění záplatami ve vrstvě face. Reakce jsou
# Robo-kunovy (sprites.POPS) přebarvené do palety, drony jsou ptáčata. Vlastní dílo, CC BY 4.0.
import argparse, math, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from familiar import skin, skin_export, sprites   # noqa: E402

W = H = 32
NONE = skin.NONE
(OUT, BLUE, BLUE_D, BLUE_L, FACE, YEL, YEL_D, WOOD, WOOD_D, LEAF, LEAF_D,
 GREY, RED, PINK, PINK_D) = range(1, 16)

BASE = [None,
        "#1f2238",   # 1 obrys, oči, zobáček
        "#3f8fe0",   # 2 čepička, křídla, ocásek
        "#2a5fb0",   # 3 modrá stín, obojek
        "#94cfff",   # 4 modrá světlo
        "#f7f5ee",   # 5 bílá tvář (i efekty: noty, Zzz, „…“)
        "#ffd23f",   # 6 žluté bříško („!“)
        "#e09a1f",   # 7 bříško stín
        "#9a6a48",   # 8 větvička
        "#64412e",   # 9 větvička stín
        "#5cc46a",   # 10 lístek
        "#2f8a4a",   # 11 lístek stín
        "#8fa3b8",   # 12 šedomodrá (nožky, reakce)
        "#e8434f",   # 13 červená (reakce, jazýček)
        "#f59ab0",   # 14 růžová (červíček)
        "#c9587a"]   # 15 růžová stín (červíček, spirála)


def _pal(base, **swap):
    p = list(base)
    for k, v in swap.items():
        idx = {"blue": (BLUE, BLUE_D, BLUE_L), "yel": (YEL, YEL_D), "wood": (WOOD, WOOD_D),
               "leaf": (LEAF, LEAF_D)}[k]
        for i, c in zip(idx, v):
            p[i] = c
    return p


PALETTES = {   # nálada mění peří (modrá a žlutá); indexy zůstávají
    "base": BASE,
    "warm": _pal(BASE, blue=("#2fb0d8", "#1f7fa8", "#8ee6ff"), yel=("#ffc02e", "#ec8a1c")),      # radost
    "red": _pal(BASE, blue=("#d9434b", "#9e2a38", "#ff9a9a"), yel=("#ffa94a", "#d9702a")),        # frustrace
    "cool": _pal(BASE, blue=("#8c7cf0", "#5a4cc0", "#cbc2ff"), yel=("#d8ef8a", "#a8c060")),       # zmatek
    "faded": _pal(BASE, blue=("#8ea4bf", "#64788f", "#c6d3e2"), yel=("#e6dba6", "#c2b27e"),       # únava
                  leaf=("#8fb388", "#5f7d5d")),
}

MOODS = {   # nálada → oči, zobáček, paleta, reakce při změně, tempo
    "klid": (None, None, "base", None, 1.0),
    "radost": (None, "smile", "warm", "heart", 1.0),
    "zvedavost": ("wide", "o", "base", "question", 1.0),
    "frustrace": ("angry", "frown", "red", "storm", 1.0),
    "zmatek": ("dazed", "wave", "cool", "spiral", 1.0),
    "unava": ("droopy", None, "faded", None, 0.6),
}

# reakce: barvy Robo-kuna → barvy ptáčka
POP_COLORS = {1: OUT, 8: FACE, 9: YEL, 10: RED, 11: LEAF, 13: GREY, 14: WOOD, 15: PINK_D}


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


def _lens(base, ang, length, width, power=0.7):
    """Čočka od bodu base ve směru ang (0° = dolů, 90° = doprava, 180° = nahoru)."""
    a = math.radians(ang)
    ux, uy = math.sin(a), math.cos(a)

    def inside(x, y):
        dx, dy = x - base[0], y - base[1]
        u, v = dx * ux + dy * uy, -dx * uy + dy * ux
        return 0 <= u <= length and abs(v) <= width * math.sin(math.pi * min(u / length, 1)) ** power
    return inside, (ux, uy)


# --- části ptáčka --------------------------------------------------------------------

BRANCH_Y = 29        # horní řádek dřeva větvičky (obrys nad ním)
BODY = (16.5, 19.3, 8.4, 7.6)      # střed a poloosy tělíčka v klidu
FACE_R = (6.4, 3.5)                 # poloosy bílé tváře


def _branch(g):
    wood = {(x, y) for x in range(7, 27) for y in (BRANCH_Y, BRANCH_Y + 1)}
    twig = {(24, 27), (25, 27), (25, 26), (26, 26), (26, 25), (27, 25)}           # větvička nahoru doprava
    g.part(wood | twig, lambda x, y: WOOD_D if y == BRANCH_Y + 1 or x == 7 and y == BRANCH_Y else WOOD)
    for x in (11, 19):                                                          # suky
        g.put(x, BRANCH_Y, WOOD_D)
    leaf, _ = _lens((27.5, 25.5), 135, 5.2, 1.7)
    cells = _cells(leaf)
    g.part(cells, lambda x, y: LEAF_D if x + y > 51 or (x, y) == (28, 24) else LEAF)


def _tail(g, cx, cy, ang=50, side=-1, length=8.0):
    """Ocásek za tělíčkem: vějíř, který vykukuje šikmo dolů do strany (ang 0 = rovně dolů)."""
    base = (cx + side * 2.5, cy + 2.5)
    a = math.radians(side * ang)
    ux, uy = math.sin(a), math.cos(a)

    def uv(x, y):
        dx, dy = x - base[0], y - base[1]
        return dx * ux + dy * uy, -dx * uy + dy * ux
    cells = _cells(lambda x, y: 0 <= uv(x, y)[0] <= length and abs(uv(x, y)[1]) <= 0.9 + 1.4 * uv(x, y)[0] / length)
    g.part(cells, lambda x, y: BLUE_D if uv(x + 0.5, y + 0.5)[0] > length - 1.6 else BLUE)


def _wing(g, cx, cy, rx, side, ang, length=6.6, width=2.1, clip=None):
    """Křídlo z ramene (side -1 levé, 1 pravé): ang 0 = složené dolů, 90 = do strany, 160 = nahoru.
    Složené křídlo se ořízne tělíčkem (clip), aby nevyčnívalo z obrysu; roztažené má bílou
    pásku a roztřepené letky."""
    folded = clip is not None
    base = (cx + side * (rx - (1.9 if folded else 1.8)), cy + (0.6 if folded else -0.5))
    a = math.radians(side * ang)
    ux, uy = math.sin(a), math.cos(a)

    def uv(x, y):
        dx, dy = x - base[0], y - base[1]
        return dx * ux + dy * uy, (-dx * uy + dy * ux) * side     # v < 0 = náběžná hrana

    def inside(x, y):
        u, v = uv(x, y)
        if not 0 <= u <= length:
            return False
        if folded:
            w = width * math.sin(math.pi * u / length) ** 0.55
            return abs(v) <= w
        k = length * 0.6
        w = width * (0.5 + 0.5 * u / k) if u < k else width * max(0.0, 1 - ((u - k) / (length - k)) ** 2) ** 0.5
        if v > 0.4 and u > length * 0.45 and int(u + 0.5) % 2 == 1:
            w *= 0.6                                            # zoubky mezi letkami
        return -w * 0.6 <= v <= w

    cells = _cells(inside)
    if folded:
        cells &= clip

    def color(x, y):
        u, v = uv(x + 0.5, y + 0.5)
        if folded:
            if u > length * 0.62:
                return BLUE_D
            return BLUE_L if v < -0.6 else BLUE
        if length * 0.3 <= u < length * 0.3 + 1.2 and v > -0.4:
            return FACE                                         # bílá páska
        if u > length * 0.55:
            return BLUE_D
        return BLUE_L if v < -0.5 else BLUE
    g.part(cells, color)


def _body(g, cx, cy, rx, ry, look, lookup):
    body = _cells(lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1)
    fcx, fcy = cx + look, cy - 0.5 + lookup
    face = {(x, y) for x, y in body if ((x + 0.5 - fcx) / FACE_R[0]) ** 2 + ((y + 0.5 - fcy) / FACE_R[1]) ** 2 <= 1}

    def color(x, y):
        if (x, y) in face:
            return FACE
        u, v = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
        if y + 0.5 < fcy + 1.5 or abs(u) > 0.8:     # čepička a boky hlavy
            if u < -0.1 and v < -0.55 and u + v > -1.25:
                return BLUE_L
            return BLUE_D if u > 0.55 and v > -0.6 else BLUE
        return YEL_D if u > 0.45 or v > 0.8 else YEL   # bříško
    g.part(body, color)
    for x, y in face:                       # obojek a proužek kolem bílé tváře
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in body and (nx, ny) not in face:
                g.put(nx, ny, BLUE_D)
    top = min(y for _, y in body)
    return top, max(y for _, y in body), body


def _crest(g, cx, top, lean=0):
    ix = math.floor(cx)
    cells = {(ix, top - 1), (ix + 1, top - 1), (ix + 1 + lean, top - 2)}
    g.part(cells, lambda x, y: BLUE)


def _legs(g, ix, bottom, mode):
    """Nožky: perch = drží větvičku, air = visí ve vzduchu, ground = stojí na spodní hraně plátna."""
    for lx in (ix - 2, ix + 2):
        if mode == "perch":
            for y in range(bottom + 1, BRANCH_Y - 1):
                g.put(lx, y, GREY)
            g.blit(["ggg"], lx - 1, BRANCH_Y - 1, {"g": GREY})
        elif mode == "air":
            g.blit(["g", "gg"], lx, bottom + 1, {"g": GREY})
        elif mode == "ground":
            for y in range(bottom + 1, H - 1):
                g.put(lx, y, GREY)
            g.blit(["ggg"], lx - 1, H - 1, {"g": GREY})


# --- obličej -------------------------------------------------------------------------
# Záplaty: oči 11×3 (levý horní roh = kotva − (5, 2)), zobáček 9×3 (kotva + (−4, 1)).
# „.“ = bílá tvář (smaže výchozí obličej), x = tmavá, r = jazýček, p = tvářička.

EYES_OFF, EYES_SIZE = (-5, -2), (11, 3)
MOUTH_OFF, MOUTH_SIZE = (-4, 1), (9, 3)
EYES = {
    "open": [" ......... ", ".xx.....xx.", ".xx.....xx."],
    "wide": [" xx.....xx ", ".xx.....xx.", ".xx.....xx."],
    "closed": [" ......... ", "...........", ".xx.....xx."],
    "happy": [" ......... ", "..x.....x..", ".x.x...x.x."],
    "x": ["x.x.....x.x", ".x.......x.", "x.x.....x.x"],
    "squeeze": [" x.......x ", "..x.....x..", ".x.......x."],      # > <
    "angry": ["xx.......xx", "..x.....x..", ".xx.....xx."],
    "droopy": [" ......... ", "xxx.....xxx", ".xx.....xx."],
    "dazed": ["xxx.....xxx", "x.x.....x.x", "xxx.....xxx"],
    "up": [" xx.....xx ", ".xx.....xx.", "..........."],
    "sleep": [" ......... ", "x..x...x..x", ".xx.....xx."],
}
MOUTHS = {   # mezera = mimo bílou tvář (záplata tam nekreslí)
    "line": ["...bbb...", "....b....", " ....... "],
    "smile": ["pp.bbb.pp", "...brb...", " ...b... "],
    "o": ["...bbb...", "...bxb...", " ...b... "],
    "frown": ["....b....", "...bbb...", " ....... "],
    "wave": ["...bbb...", "..b.b.b..", " ....... "],
    "sing": ["..bbbbb..", "...brb...", " ...b... "],
    "none": [".........", ".........", " ....... "],
}
FACE_COLORS = {".": FACE, "x": OUT, "b": YEL_D, "r": RED, "p": PINK}


def _face(g, ix, iy, eyes, mouth):
    g.blit(EYES[eyes], ix + EYES_OFF[0], iy + EYES_OFF[1], FACE_COLORS)
    g.blit(MOUTHS[mouth], ix + MOUTH_OFF[0], iy + MOUTH_OFF[1], FACE_COLORS)


# --- červíček ---------------------------------------------------------------------------

def _worm(g, pts):
    """Červíček podél lomené čáry pts (od hlavičky), tlustý 2 px, s obrysem a článkováním."""
    segs = list(zip(pts, pts[1:])) or [(pts[0], pts[0])]

    def near(x, y):
        best = (9e9, 0.0)
        for k, ((x0, y0), (x1, y1)) in enumerate(segs):
            dx, dy = x1 - x0, y1 - y0
            t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
            d = (x - x0 - t * dx) ** 2 + (y - y0 - t * dy) ** 2
            best = min(best, (d, k + t))
        return best
    mask = _cells(lambda x, y: near(x, y)[0] <= 0.62)
    g.part(mask, lambda x, y: PINK_D if int(near(x + 0.5, y + 0.5)[1] * 2.2) % 2 else PINK)
    hx, hy = pts[0]
    g.put(math.floor(hx), math.floor(hy), OUT)                      # očko na hlavičce


# --- efekty (vrstva fx) ------------------------------------------------------------------

def _glyph(g, rows, x, y, c):
    """Znak efektu s tmavým obrysem, aby byl čitelný na světlém i tmavém titulku."""
    g.part({(x + dx, y + dy) for dy, row in enumerate(rows) for dx, ch in enumerate(row) if ch == "x"},
           lambda *_: c)


def _dots(g, n):
    for k in range(n):
        _glyph(g, ["xx", "xx"], 21 + 4 * k, 1, FACE)


def _bang(g, on):
    if on:
        _glyph(g, ["xx", "xx", "xx", "xx", "  ", "xx"], 29, 1, YEL)


NOTES = (["  x  ", "  xx ", "  x x", "xxx  ", "xxx  "],          # ♪
         [" xxxx", " x  x", " x  x", "xx xx", "xx xx"])          # ♫


def _note(g, x, y, kind=0):
    _glyph(g, NOTES[kind], x, y, (FACE, YEL)[kind])


Z_SMALL = ["xxx", "  x", " x ", "xxx"]
Z_BIG = ["xxxx", "   x", "  x ", " x  ", "xxxx"]


def _zzz(g, i):
    _glyph(g, Z_SMALL, 22, 8 - i % 2, FACE)
    if i % 2 == 0:
        _glyph(g, Z_BIG, 26, 1, FACE)


def _sparkle(g, x, y, c=YEL):
    g.blit([" c ", "cwc", " c "], x - 1, y - 1, {"c": c, "w": FACE})


def _feather(g, x, y, flip=0):
    """Ulétnuté pírko s obrysem (vrstva fx), flip = natočené na druhou stranu."""
    rows = ["   oo", "  obo", " oblo", "oblo ", "olo  ", "o    "]
    if flip:
        rows = [r[::-1] for r in rows]
    g.blit(rows, x, y, {"o": OUT, "b": BLUE, "l": BLUE_L})


FX = {"dots": _dots, "bang": _bang, "zzz": _zzz, "sparkle": _sparkle,
      "note": _note, "feather": _feather}


# --- póza -----------------------------------------------------------------------------------

def draw(p):
    """(body, fx, kotva obličeje) jedné pózy."""
    g = Canvas()
    ground = p.get("ground", False)                     # bez větvičky (procházka po hraně okna)
    cx = BODY[0] + p.get("hdx", 0)
    cy = BODY[1] + p.get("hdy", 0) + (3 if ground else 0)
    fluff, sq = p.get("fluff", 0.0), p.get("sq", 0.0)
    rx, ry = BODY[2] + fluff + sq, BODY[3] + fluff * 0.6 - sq
    look, lookup = p.get("look", 0), p.get("lookup", 0)
    wl, wr = p.get("wings", (12, 12))
    fly = p.get("fly", False)
    open_ = [(side, ang) for side, ang in ((-1, wl), (1, wr)) if fly or ang > 40]
    _tail(g, cx, cy, p.get("tail_ang", 45), p.get("tail", -1))
    for side, ang in open_:                               # roztažená křídla za tělíčkem
        _wing(g, cx, cy, rx, side, ang, 9.0, 3.4)
    top, bottom, mask = _body(g, cx, cy, rx, ry, look, lookup)
    for ang in p.get("ruffle", ()):                       # načepýřené peří
        a = math.radians(ang)
        for d, c in ((0.5, BLUE if ang % 360 < 70 or ang % 360 > 290 else YEL), (1.5, OUT)):
            g.put(math.floor(cx + (rx + d) * math.sin(a)), math.floor(cy - (ry + d) * math.cos(a)), c)
    _crest(g, cx + look, top, p.get("crest", 0))
    for side, ang in ((-1, wl), (1, wr)):
        if (side, ang) not in open_:
            _wing(g, cx, cy, rx, side, ang, clip=mask)
    ix, iy = math.floor(cx) + look, math.floor(cy) - 1 + lookup
    _face(g, ix, iy, p.get("eyes", "open"), p.get("mouth", "line"))
    legs = p.get("legs", "perch")
    if ground:
        _legs(g, math.floor(cx), bottom, legs)
    elif p.get("behind"):                                 # sklouzl za větvičku
        _branch(g)
    else:
        _branch(g)
        _legs(g, math.floor(cx), bottom, legs)
    if p.get("worm"):
        _worm(g, p["worm"])
    fx = Canvas()
    for name, *args in p.get("fx", []):
        FX[name](fx, *args)
    return g.px, fx.px, (ix, iy)


# --- animace --------------------------------------------------------------------------------

def _idle():
    frames = []
    for i in range(32):                 # 8 s: dýchá, mrkne, natočí hlavičku, zazpívá
        p = {"sq": 0.3 if i % 4 in (1, 2) else 0.0}
        if i in (6, 29):
            p["eyes"] = "closed"
        if 9 <= i <= 14:                # natočí hlavičku doprava, pak doleva
            p.update(look=1 if i < 12 else -1, crest=1 if i < 12 else -1, sq=0.0)
        if 17 <= i <= 25:               # zpívá: hlavička nahoru, zobáček se otvírá, noty stoupají
            k = i - 17
            p.update(lookup=-1, eyes="happy", mouth="sing" if k % 2 == 0 else "line", lock=True,
                     fluff=0.3 if k % 2 == 0 else 0.1, crest=1,
                     fx=[("note", 25, 9 - k), ("note", 2, 12 - k, 1)][:1 + (k >= 2)] if k < 8 else [])
        frames.append(p)
    return frames


def _success():
    """Na větvičce vykoukne červíček: ptáček k němu skočí, klovne, vrátí se, vyhodí ho a spolkne."""
    air = {"legs": "air", "fly": True, "tail_ang": 35}
    poses = [
        {},
        {"look": 1, "lookup": 1, "eyes": "wide", "worm": [(21, 26), (21, 27.5)]},
        {"look": 1, "lookup": 1, "eyes": "wide", "sq": 0.5, "worm": [(22, 24.5), (21, 26), (21, 27.5)]},
        {"look": 1, "eyes": "wide", "hdx": 1, "hdy": -3, "wings": (125, 125), **air,
         "worm": [(20, 24.5), (21, 26), (21, 27.5)]},
        {"look": 2, "lookup": 3, "eyes": "closed", "mouth": "o", "hdx": 2, "hdy": 1, "sq": 0.5,
         "worm": [(21, 25), (21.5, 26.5), (22.5, 27.5)]},
        {"look": 1, "hdx": 2, "hdy": -1, "sq": -0.4, "eyes": "happy",
         "worm": [(19.5, 20), (20.5, 21.5), (20, 23), (19, 24.5)]},
        {"hdx": 1, "hdy": -3, "eyes": "happy", "wings": (115, 115), **air,
         "worm": [(17.5, 18), (16.5, 19.5), (17, 21), (18, 22.5)]},
        {"eyes": "happy", "worm": [(16.5, 21), (17.5, 22.5), (17, 24), (16, 25)]},
        {"lookup": -2, "eyes": "happy", "mouth": "sing", "sq": -0.3,
         "worm": [(13.5, 6), (15, 4.5), (16.5, 5.5), (18, 4.5)]},
        {"lookup": -2, "eyes": "closed", "mouth": "sing", "sq": -0.3,
         "worm": [(16, 14), (16, 16.5)]},
        {"eyes": "happy", "fluff": 0.6, "crest": 1},
        {"eyes": "happy", "fluff": 1.1, "crest": 1,
         "fx": [("sparkle", 4, 9), ("sparkle", 28, 12), ("sparkle", 26, 3, FACE)]},
        {"eyes": "happy", "fluff": 0.6, "crest": 1,
         "fx": [("sparkle", 5, 7, FACE), ("sparkle", 27, 9), ("sparkle", 25, 2)]},
        {},
    ]
    return poses


def _error():
    """Uklouzne, sjede za větvičku, vyškrábe se zpátky načepýřený a ulétne mu pírko."""
    flail = {"fly": True, "legs": "air"}
    rough = (300, 330, 25, 60, 95)
    return [
        {},
        {"hdx": -1, "hdy": 1, "sq": 0.3, "wings": (130, 100), "fly": True, "eyes": "wide", "mouth": "o"},
        {"hdx": -2, "hdy": 6, "behind": True, "wings": (160, 140), **flail, "eyes": "x", "mouth": "wave",
         "fx": [("feather", 24, 5)]},
        {"hdx": -2, "hdy": 5, "behind": True, "wings": (70, 90), **flail, "eyes": "x", "mouth": "wave",
         "fx": [("feather", 26, 7, 1)]},
        {"hdx": -1, "hdy": 1, "wings": (120, 150), "fly": True, "eyes": "squeeze", "mouth": "wave",
         "ruffle": rough, "fx": [("feather", 26, 9)]},
        {"fluff": 0.4, "eyes": "squeeze", "mouth": "wave", "ruffle": rough, "fx": [("feather", 27, 11, 1)]},
        {"hdx": 1, "fluff": 0.2, "eyes": "squeeze", "ruffle": rough[1:4], "fx": [("feather", 26, 13)]},
        {"hdx": -1, "eyes": "squeeze", "ruffle": rough[2:3], "fx": [("feather", 27, 15, 1)]},
        {},
    ]


def _fly():
    """Vznáší se nad větvičkou: plynulý cyklus mávání, tělíčko se zhoupne s každým úderem."""
    angs = (150, 125, 90, 55, 25, 50, 95, 130)
    lift = (0, 0, -1, -1, -1, 0, 0, 0)
    return [{"hdy": -7 + lift[i], "fly": True, "wings": (a, a), "legs": "air", "tail_ang": 30,
             "look": (0, 0, 0, 0, 1, 1, 1, 1)[i]} for i, a in enumerate(angs)]


def _walk():
    """Procházka po hraně okna bez větvičky: poskakování z profilu doprava."""
    base = {"ground": True, "look": 2, "crest": 1, "tail_ang": 70}
    return [{**base, **p} for p in ({"legs": "ground"},
                                     {"legs": "ground", "sq": 0.5, "hdy": 0.5},
                                     {"legs": "air", "hdy": -2, "wings": (60, 60), "fly": True},
                                     {"legs": "air", "hdy": -3, "wings": (100, 100), "fly": True},
                                     {"legs": "air", "hdy": -2, "wings": (60, 60), "fly": True},
                                     {"legs": "ground", "sq": 0.4})]


ANIMS = {   # tag → (fps, pózy, jednorázová)
    "idle": (4, _idle(), False),
    "listen": (8, [{}, {"sq": -0.3, "hdy": -1, "crest": 1, "eyes": "wide"},
                   {"sq": -0.6, "hdy": -2, "lookup": -1, "crest": 1, "eyes": "wide", "mouth": "o"},
                   {"sq": -0.6, "hdy": -2, "lookup": -1, "look": 1, "crest": 1, "eyes": "wide", "mouth": "o"},
                   {"sq": -0.3, "hdy": -1, "eyes": "wide"}], True),
    "think": (6, [{"look": -1, "lookup": -1, "crest": -1, "eyes": "up", "sq": 0.3 * (i % 2),
                   "fx": [("dots", i // 2 + 1)]} for i in range(6)], False),
    "work": (8, _fly(), False),
    "wave": (6, [{"wings": (12, w), "hdx": -1, "hdy": dy, "eyes": "wide", "mouth": "o", "fx": [("bang", i % 2 == 0)]}
                 for i, (w, dy) in enumerate(((145, 0), (105, -2), (145, 0), (105, -1)))], False),
    "hop": (7, _success(), True),
    "stumble": (8, _error(), True),
    "sleep": (2, [{"fluff": 0.8 + 0.3 * (i % 2), "hdy": 1, "sq": 0.4, "lookup": 1, "crest": -1,
                   "eyes": "sleep", "mouth": "none", "fx": [("zzz", i)]} for i in range(4)], False),
    "walk": (8, _walk(), False),
}

ACTIVITY = {"idle": "idle", "listening": "listen", "thinking": "think", "waiting": "wave",
            "success": "hop", "error": "stumble", "sleeping": "sleep", "gone": "sleep", "walking": "walk"}
LOCKED_EYES = {"closed", "x", "happy", "wide", "up", "squeeze", "sleep"}


# --- vrstvy a zápis ---------------------------------------------------------------------------

CHICK = (["oo       ",       # ptáče z profilu doprava: křídélko nahoru / dolů
          "oLo ooo  ",
          " oLobbbo ",
          "  obbwkn ",
          "  oyyyyo ",
          "   oyyo  ",
          "    oo   "],
         ["         ",
          "    ooo  ",
          "   obbbo ",
          "  oLbwkn ",
          " oLLyyyo ",
          "  ooyyo  ",
          "    oo   "])
CHICK_COLORS = {"o": OUT, "b": BLUE, "L": BLUE_L, "w": FACE, "k": OUT, "n": YEL_D, "y": YEL}


def _drone(k, phase):
    g = Canvas()
    flap = (phase + k) % 2
    g.blit(CHICK[flap], 0, 9 + k * 6 + flap, CHICK_COLORS)
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
            for s, key in (("eyes", (ix + EYES_OFF[0], iy + EYES_OFF[1], *EYES_SIZE)),
                           ("mouth", (ix + MOUTH_OFF[0], iy + MOUTH_OFF[1], *MOUTH_SIZE)),
                           ("head", (ix - 8, iy - 8, 17, 17))):
                if not keys[s] or keys[s][-1][1:] != key:
                    keys[s].append((f, *key))
            lock = p.get("lock") or p.get("worm") or p.get("ground")
            if lock or p.get("eyes", "open") in LOCKED_EYES:
                keep["eyes"].setdefault(anim, []).append(i)
            if lock or p.get("mouth", "line") != "line":
                keep["mouth"].setdefault(anim, []).append(i)

    ref = draw({})[2]
    face, face_tags = [], []
    for slot, table, off in (("eyes", EYES, EYES_OFF), ("mouth", MOUTHS, MOUTH_OFF)):
        for name, rows in table.items():
            g = Canvas()
            g.blit(rows, ref[0] + off[0], ref[1] + off[1], FACE_COLORS)
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
    lines = ["# Vygenerováno: python3 -I tools/ptacek.py (kresba kódem). Formát popisuje docs/skiny.md.",
             "# Vlastní dílo projektu Pixel Familiars, CC BY 4.0 (viz CREDITS.txt).", "",
             "[skin]", 'name = "Ptáček"', f"size = [{W}, {H}]", "anchor = [16, 31]",
             'facing = "right"', 'author = "Pixel Familiars"', 'license = "CC-BY-4.0"', "",
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


CREDITS = """Ptáček – skin pro Pixel Familiars

Grafika: vlastní dílo projektu Pixel Familiars, kreslené kódem (tools/ptacek.py).
Licence: Creative Commons Uveďte původ 4.0 Mezinárodní (CC BY 4.0)
         https://creativecommons.org/licenses/by/4.0/ (plné znění v LICENSES/CC-BY-4.0.txt)
Uveďte: Pixel Familiars (Pavel Švec), https://github.com/pauliquib/familiar

Reakce nad hlavou jsou Robo-kunovy (familiar/sprites.py) přebarvené do palety skinu,
drony subagentů jsou ptáčata. Skin znovu vygeneruje: python3 -I tools/ptacek.py
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
    ap = argparse.ArgumentParser(description="skin Ptáček kreslený kódem")
    ap.add_argument("dest", nargs="?", default=os.path.join(REPO, "familiar", "skins", "ptacek"))
    args = ap.parse_args(argv)
    export(args.dest)
    print(f"skin ptacek zapsán do {args.dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
