# Generátor skinu „Skejťák“: chibi skateboardista kreslený kódem (formát docs/skiny.md).
#
#   python3 -I tools/skejtak.py [cílový adresář]      (výchozí familiar/skins/skejtak)
#
# Kresba je z geometrie jako u Květiny (tools/kvetina.py): hlava je elipsa s kšiltovkou,
# mikina zaoblený obdélník, ruce a nohy úsečky s tloušťkou, prkno čára s koly. Každá část
# má vlastní obrys (index 1). Postavička stojí bokem na prkně, hrudí k divákovi, a kouká
# doprava, kam jede (facing = "right"). Obličej (oči, pusa) mění nálada záplatami ve vrstvě
# face. Reakce jsou Robo-kunovy (sprites.POPS) přebarvené do palety, drony jsou malá skate
# prkýnka. Vlastní dílo projektu, CC BY 4.0.
import argparse, math, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from familiar import skin, skin_export, sprites   # noqa: E402

W = H = 32
NONE = skin.NONE
(OUT, SKIN, SKIN_D, HOOD, HOOD_D, HOOD_L, PANTS, PANTS_D, CAP, CAP_D,
 YELLOW, WHITE, GREY, GREEN, HAIR) = range(1, 16)

BASE = [None,
        "#2b1d2e",   # 1 obrys, oči, grip prkna
        "#ffd2ad",   # 2 kůže
        "#e39b7b",   # 3 kůže stín
        "#3cbfae",   # 4 mikina
        "#1f7f7c",   # 5 mikina stín
        "#a3ecd9",   # 6 mikina světlo
        "#4f5bb8",   # 7 kalhoty
        "#343a7a",   # 8 kalhoty stín
        "#e8434f",   # 9 kšiltovka (a červená reakcí)
        "#a3283f",   # 10 kšiltovka stín
        "#ffd84d",   # 11 žlutá: prkno, „!“, jiskry
        "#f7f3ea",   # 12 bílá: boty, odlesk v očích, efekty
        "#8fa3b8",   # 13 šedomodrá: podrážky, osy, vítr, pot
        "#6fd36a",   # 14 zelená: kolečka (a fajfka)
        "#6b3e2a"]   # 15 vlasy (a káva)


def _pal(base, **swap):
    p = list(base)
    idx = {"hood": (HOOD, HOOD_D, HOOD_L), "cap": (CAP, CAP_D), "pants": (PANTS, PANTS_D),
           "skin": (SKIN, SKIN_D), "deck": (YELLOW,), "wheel": (GREEN,), "hair": (HAIR,)}
    for k, v in swap.items():
        for i, c in zip(idx[k], v):
            p[i] = c
    return p


PALETTES = {   # nálada mění barvy mikiny (a u únavy všeho); indexy zůstávají
    "base": BASE,
    "warm": _pal(BASE, hood=("#ff9440", "#c9552a", "#ffd08f")),                     # radost: teplá
    "red": _pal(BASE, hood=("#e5483f", "#9c2633", "#ff9e8a"), cap=("#b8233a", "#6e1a2c")),   # frustrace
    "cool": _pal(BASE, hood=("#8f86f0", "#5a4cc0", "#d0caff"), pants=("#3f6aa8", "#29467a")),  # zmatek
    "faded": _pal(BASE, hood=("#9cbcb5", "#6b8a86", "#cfe2dc"), cap=("#c48a8f", "#8f6670"),     # únava
                  pants=("#8589ad", "#62668a"), skin=("#efd8c6", "#c9a898"), deck=("#e5d59f",),
                  wheel=("#a3c79c",)),
}

MOODS = {   # nálada → oči, pusa, paleta, reakce při změně, tempo
    "klid": (None, None, "base", None, 1.0),
    "radost": (None, "smile", "warm", "heart", 1.0),
    "zvedavost": ("wide", "o", "base", "question", 1.0),
    "frustrace": ("angry", "frown", "red", "storm", 1.0),
    "zmatek": ("dazed", "wave", "cool", "spiral", 1.0),
    "unava": ("droopy", None, "faded", None, 0.6),
}

# reakce: barvy Robo-kuna → barvy skejťáka
POP_COLORS = {1: OUT, 8: WHITE, 9: YELLOW, 10: CAP, 11: GREEN, 13: GREY, 14: HAIR, 15: PANTS}


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
    return {(x, y) for y in range(-4, H + 4) for x in range(-4, W + 4) if test(x + 0.5, y + 0.5)}


def _seg_d2(px, py, ax, ay, bx, by):
    """Čtverec vzdálenosti bodu od úsečky."""
    vx, vy = bx - ax, by - ay
    t = 0.0 if vx == vy == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
    return (px - ax - t * vx) ** 2 + (py - ay - t * vy) ** 2


def _limb(pts, r):
    """Maska lomené čáry s poloměrem r (ruka, noha)."""
    segs = list(zip(pts, pts[1:]))
    return _cells(lambda x, y: min(_seg_d2(x, y, *a, *b) for a, b in segs) <= r * r)


# --- prkno ---------------------------------------------------------------------------------
# Prkno zboku: deska (žlutá, 1 px, nahoře grip = obrys), konce zvednuté, dvě kolečka 2×2.
# Kickflip: prkno se otáčí kolem podélné osy, takže je vidět spodek (žlutý), pak vzhůru
# nohama (kolečka nahoře), pak grip (tmavý) a zase zboku.

DECK = 7            # polovina délky desky (bez zvednutých konců)
WHEELS = (-5, 4)    # levý sloupec koleček vůči středu


def _wheel(g, x, y, spin):
    w = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
    g.part(w, lambda *_: GREEN)
    if spin is not None:
        hx, hy = ((0, 0), (1, 0), (1, 1), (0, 1))[spin % 4]
        g.put(x + hx, y + hy, WHITE)


def _board(g, cx, y, mode="flat", spin=None, tilt=0):
    """Prkno se středem desky (cx, y). tilt = o kolik px je nos výš než tail (manuál, pop)."""
    if mode == "flat":
        piv = cx - 4.0                 # zadní kolečka zůstávají na zemi, nos se zvedá

        def lift(x):
            return -tilt * (x - piv) / 9.0
        for wx in WHEELS:              # kolečka pod deskou
            _wheel(g, cx + wx, y + 2 + round(lift(cx + wx + 1)), spin)
        pts = [(x, yy + lift(x)) for x, yy in ((cx - DECK - 1.0, y - 0.5), (cx - DECK + 0.5, y + 0.5),
                                               (cx + DECK + 0.5, y + 0.5), (cx + DECK + 2.0, y - 0.5))]
        g.part(_limb(pts, 0.56), lambda *_: YELLOW)
        for wx in WHEELS:              # osy: šedá mezi deskou a kolečkem
            for dx in (0, 1):
                xx = cx + wx + dx
                yy = y + 1 + round(lift(cx + wx + 1))
                if g.get(xx, yy) == OUT and g.get(xx, yy + 1) == GREEN:
                    g.put(xx, yy, GREY)
    elif mode == "under":          # spodek desky čelem k divákovi, kolečka trčí nahoru a dolů
        top = {(x, yy) for x in range(cx - DECK, cx + DECK + 2) for yy in (y - 1, y, y + 1)}
        for wx in WHEELS:
            for wy in (y - 3, y + 2):
                g.part({(cx + wx, wy), (cx + wx + 1, wy), (cx + wx, wy + 1), (cx + wx + 1, wy + 1)},
                       lambda *_: GREEN)
        top |= {(cx - DECK - 1, y), (cx + DECK + 2, y)}
        g.part(top, lambda x, yy: CAP if abs(x - cx - 0.5) < 2 and yy == y else YELLOW)
    elif mode == "grip":           # grip (tmavý) čelem k divákovi
        top = {(x, yy) for x in range(cx - DECK, cx + DECK + 2) for yy in (y - 1, y, y + 1)}
        top |= {(cx - DECK - 1, y), (cx + DECK + 2, y)}
        g.part(top, lambda x, yy: GREY)
        for wx in WHEELS:          # šrouby os
            g.put(cx + wx, y, GREY)
            g.put(cx + wx + 1, y, GREY)
    elif mode == "upside":         # vzhůru nohama: kolečka nahoře
        pts = [(cx - DECK - 1.0, y + 1.5), (cx - DECK + 0.5, y + 0.5),
               (cx + DECK + 0.5, y + 0.5), (cx + DECK + 2.0, y + 1.5)]
        g.part(_limb(pts, 0.5), lambda *_: YELLOW)
        for wx in WHEELS:
            _wheel(g, cx + wx, y - 2, None)


# --- postavička ---------------------------------------------------------------------------------
# Neutrální póza: prkno na zemi (deska y = 27, kolečka 29–30), boty na desce (24–25),
# kalhoty 19–22, mikina 13–18, hlava 2–12 s kšiltovkou od řádku 1, kšilt doprava.

BOARD_Y = 27
HEAD_R = (6.6, 5.4)


def _shoe(g, x, y):
    """Bota se špičkou doprava; (x, y) = levý dolní roh."""
    m = {(x + dx, y - 1) for dx in range(0, 3)} | {(x + dx, y) for dx in range(0, 4)}
    g.part(m, lambda xx, yy: GREY if yy == y else WHITE)


def _knee(hip, foot, side, knees="out", L=5.4):
    """Koleno mezi kyčlí a kotníkem; při pokrčení se vychýlí ven (side = -1 / 1) nebo nahoru."""
    hx, hy = hip
    fx, fy = foot
    d = math.hypot(fx - hx, fy - hy)
    bend = math.sqrt(max(0.0, (L / 2) ** 2 - (d / 2) ** 2))
    mx, my = (hx + fx) / 2, (hy + fy) / 2
    px, py = ((-(fy - hy) / d, (fx - hx) / d) if d else (side, 0))
    if knees == "up":
        if py > 0:
            px, py = -px, -py
    elif px * side < 0:
        px, py = -px, -py
    return (mx + px * bend, my + py * bend)


def _legs(g, hipx, hipy, lfoot, rfoot, knees="out", L=5.4, lk=None, rk=None, seat=True):
    """Kalhoty jako jeden kus (bez obrysu mezi nohama): sedlo a dvě nohavice ke kotníkům."""
    lh, rh = (hipx - 1.2, hipy + 0.6), (hipx + 2.2, hipy + 0.6)
    la, ra = (lfoot[0] + 1.5, lfoot[1] - 1.5), (rfoot[0] + 1.6, rfoot[1] - 1.5)
    lk, rk = lk or _knee(lh, la, -1, knees, L), rk or _knee(rh, ra, 1, knees, L)
    m = _limb([lh, lk, la], 1.15) | _limb([rh, rk, ra], 1.15)
    if seat:
        m |= {(x, y) for x in range(math.floor(hipx - 2.5), math.ceil(hipx + 3.5))
              for y in range(math.floor(hipy - 0.5), math.floor(hipy + 1.5))}
    cx = hipx + 0.5

    def col(x, y):
        if y + 0.5 > hipy + 1.2 and abs(x + 0.5 - cx) < 1.6:
            return PANTS_D                                   # vnitřek nohavic
        if x + 0.5 > cx + 2.2 and y + 0.5 > hipy + 0.5:
            return PANTS_D                                   # stín vpravo
        return PANTS
    g.part(m, col)


def _arm(g, sh, hand):
    m = _limb([sh, hand], 0.95)
    g.part(m, lambda x, y: HOOD_D if y + 0.5 > sh[1] + 0.5 and x + 0.5 < sh[0] - 0.3 else HOOD)
    hx, hy = hand
    g.part(_cells(lambda x, y: (x - hx) ** 2 + (y - hy) ** 2 <= 1.1), lambda *_: SKIN)


def _torso(g, cx, top, bottom):
    def inside(x, y):
        if not top <= y <= bottom:
            return False
        w = 3.6 + min(1.0, (y - top) / 2.5) * 0.8
        if y < top + 1 and abs(x - cx) > w - 1.0:
            return False
        return abs(x - cx) <= w
    m = _cells(inside)

    def col(x, y):
        if y + 0.5 > bottom - 1:
            return HOOD_D                                  # lem
        if x + 0.5 > cx + 2.6:
            return HOOD_D                                  # stín vpravo
        if x + 0.5 < cx - 2.4 and y + 0.5 < top + 3:
            return HOOD_L
        return HOOD
    g.part(m, col)
    # kapsa klokanka
    py = int(bottom) - 2
    for x in range(int(cx) - 2, int(cx) + 2):
        g.put(x, py, HOOD_D)
    # tkaničky kapuce
    g.put(int(cx) - 1, int(top) + 1, WHITE)
    g.put(int(cx) + 1, int(top) + 1, WHITE)


def _head(g, cx, cy):
    rx, ry = HEAD_R
    head = _cells(lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1)

    def col(x, y):
        dx, dy = x + 0.5 - cx, y + 0.5 - cy
        if dx < -3.4 and -3 < dy < 1.5:
            return HAIR                                     # vlasy vzadu pod kšiltovkou
        if dx > 4.6 or dy > 4.3:
            return SKIN_D
        return SKIN
    g.part(head, col)
    # ucho vlevo (zezadu hlavy)
    ex, ey = int(cx - 4.0), int(cy + 0.5)
    g.put(ex, ey, SKIN_D)
    # kšiltovka: kopule přes horní část hlavy, kšilt doprava
    dome = _cells(lambda x, y: ((x - cx) / (rx + 0.3)) ** 2 + ((y - cy + 0.3) / (ry + 0.6)) ** 2 <= 1
                  and y < cy - 2.2)
    g.part(dome, lambda x, y: CAP_D if x + 0.5 < cx - 3.5 or y + 0.5 > cy - 3.2 else CAP)
    by = int(math.floor(cy - 2.5))
    brim = {(x, by) for x in range(int(cx) + 1, int(cx) + 10)}
    g.part(brim, lambda *_: CAP_D)
    g.put(int(cx) - 1, int(cy - 5.8), WHITE)              # knoflík / logo
    # g.put(int(cx), int(cy - 4.8), YELLOW)


# --- obličej -------------------------------------------------------------------------
# Záplaty: oči 7×3 (levý horní roh = kotva + (−3, −1)), pusa 5×2 (kotva + (−2, 3)).
# „.“ = kůže (smaže výchozí obličej), x = tmavá, w = odlesk, r = tvářička.

EYES_OFF, EYES_SIZE = (-3, -1), (7, 3)
MOUTH_OFF, MOUTH_SIZE = (-2, 3), (5, 2)
EYES = {
    "open": [".......", "wx...wx", "xx...xx"],
    "wide": ["wx...wx", "xx...xx", "xx...xx"],
    "closed": [".......", ".......", "xx...xx"],
    "happy": [".......", ".x...x.", "x.x.x.x"],
    "x": ["x.....x", ".x...x.", "x.....x"],      # > <
    "angry": ["x.....x", "xx...xx", "xx...xx"],
    "droopy": [".......", "xx...xx", "wx...wx"],
    "dazed": [".x...x.", "x.x.x.x", ".x...x."],
    "up": ["wx...wx", "xx...xx", "......."],
}
MOUTHS = {
    "line": ["..xx.", "....."],
    "smile": ["x...x", ".xxx."],
    "o": ["..xx.", "..xx."],
    "frown": [".xxx.", "x...x"],
    "wave": [".x.x.", "x.x.x"],
    "grin": ["xxxxx", ".xxx."],
}
FACE = {".": SKIN, "x": OUT, "w": WHITE, "r": CAP}


def _face(g, ix, iy, eyes, mouth, look=0):
    g.blit(EYES[eyes], ix + EYES_OFF[0] + look, iy + EYES_OFF[1], FACE)
    g.blit(MOUTHS[mouth], ix + MOUTH_OFF[0] + look, iy + MOUTH_OFF[1], FACE)


# --- efekty (vrstva fx) ------------------------------------------------------------------

def _shadowed(g, rows, x, y, c=WHITE):
    """Bílý efekt se stínem vpravo dole, aby byl vidět i na světlém titulku."""
    g.blit(rows, x + 1, y + 1, {k: OUT for k in "xw"})
    g.blit(rows, x, y, {"x": c, "w": c})


def _dots(g, n):
    for k in range(n):
        _shadowed(g, ["ww", "ww"], 23 + 3 * k, 1)


def _bang(g, on):
    if on:
        _shadowed(g, ["ww", "ww", "ww", "ww", "  ", "ww"], 29, 0, YELLOW)


Z_SMALL = ["xxx", "  x", " x ", "xxx"]
Z_BIG = ["xxxx", "   x", "  x ", " x  ", "xxxx"]


def _zzz(g, i):
    _shadowed(g, Z_SMALL, 22, 6 - i % 2)
    if i % 2 == 0:
        _shadowed(g, Z_BIG, 26, 0)


def _sparkle(g, x, y, c=YELLOW):
    g.blit([" c ", "cwc", " c "], x - 1, y - 1, {"c": c, "w": WHITE})


def _twinkle(g, x, y, c=WHITE):
    g.put(x, y, c)


def _sweat(g, x, y):
    g.blit([" w ", "www", "www"], x, y, {"w": GREY})


def _wind(g, i, y0=0):
    """Rychlostní čárky za jezdcem (vlevo), ujíždějí doleva."""
    for k, (y, ln) in enumerate(((12, 4), (18, 3), (24, 4))):
        x = 6 - ((i * 2 + k * 3) % 6)
        for dx in range(ln):
            g.put(x + dx, y + y0, GREY)


def _stars(g, i, cx=13, cy=9):
    """Hvězdičky kroužící nad hlavou po pádu."""
    for k in range(3):
        a = (i * 0.9 + k * 2.1)
        x, y = round(cx + 6 * math.cos(a)), round(cy + 1.6 * math.sin(a))
        g.blit([" c ", "ccc", " c "], x - 1, y - 1, {"c": YELLOW if k != 1 else WHITE})


def _dust(g, x, y, i):
    rows = (["w   w", " g g "], ["w     w", " g   g "])[i % 2]
    g.blit(rows, x - len(rows[0]) // 2, y, {"w": WHITE, "g": GREY})


FX = {"dots": _dots, "bang": _bang, "zzz": _zzz, "sparkle": _sparkle, "twinkle": _twinkle,
      "sweat": _sweat, "wind": _wind, "stars": _stars, "dust": _dust}


# --- póza -----------------------------------------------------------------------------------

def draw(p):
    """(body, fx, kotva obličeje) jedné pózy."""
    g = Canvas()
    X, Y = p.get("x", 0), p.get("y", 0)
    c = p.get("c", 0)                     # pokrčení kolen
    lean = p.get("lean", 0)
    # prkno
    mode = p.get("board", "flat")
    if mode:
        _board(g, 16 + X + p.get("bx", 0), BOARD_Y + Y + p.get("by", 0), mode, p.get("spin"), p.get("tilt", 0))
    # kostra
    hipx, hipy = 16 + X + p.get("hipx", 0), 18.5 + Y + c + p.get("hipy", 0)
    tx = hipx + lean
    lfx, lfy = p.get("lf", (0, 0))
    rfx, rfy = p.get("rf", (0, 0))
    lfoot = (11 + X + lfx, 25 + Y + lfy)          # levý dolní roh boty
    rfoot = (19 + X + rfx, 25 + Y + rfy)
    sh_y = 14.8 + Y + c + p.get("hipy", 0)
    lsh, rsh = (tx - 2.8, sh_y), (tx + 3.8, sh_y)
    la, ra = p.get("la", (-2.0, 3.5)), p.get("ra", (2.0, 3.5))
    _arm(g, lsh, (lsh[0] + la[0], lsh[1] + la[1]))           # zadní ruka
    def legs():
        kn = [(k[0] + X, k[1] + Y) if k else None for k in (p.get("lk"), p.get("rk"))]
        _legs(g, hipx, hipy, lfoot, rfoot, p.get("knees", "out"), p.get("legL", 5.4), *kn, not p.get("sit"))
        _shoe(g, *lfoot)
        _shoe(g, *rfoot)
    if not p.get("sit"):
        legs()
    _torso(g, tx + 0.5, 12.8 + Y + c + p.get("hipy", 0), hipy + 0.5)
    if p.get("sit"):               # vsedě jsou kolena před mikinou
        legs()
    hcx = tx + 0.5 + p.get("hdx", 0)
    hcy = 7.9 + Y + c + p.get("hipy", 0) + p.get("hdy", 0)
    if not p.get("front_over"):
        _arm(g, rsh, (rsh[0] + ra[0], rsh[1] + ra[1]))           # přední ruka
    _head(g, hcx, hcy)
    ix, iy = math.floor(hcx) + 1, math.floor(hcy)
    _face(g, ix, iy, p.get("eyes", "open"), p.get("mouth", "line"), p.get("look", 0))
    if p.get("front_over"):
        _arm(g, rsh, (rsh[0] + ra[0], rsh[1] + ra[1]))           # ruka před hlavou (na bradě)
    fx = Canvas()
    for name, *args in p.get("fx", []):
        FX[name](fx, *args)
    return g.px, fx.px, (ix, iy)


# --- animace --------------------------------------------------------------------------------

RIDE = {"c": 1, "la": (-3.5, 1.5), "ra": (3.0, 1.0), "look": 1}      # jízda: pokrčená kolena, ruce do stran


def _idle():
    """6 s: pohupování v kolenou, mrknutí, poklepání nohou o zem, zhoupnutí prkna."""
    frames = []
    for i in range(24):
        p = {"c": (0, 0, 1, 1)[i % 4] if i < 8 or i >= 20 else 0}
        if i == 6:
            p["eyes"] = "closed"
        if 9 <= i <= 15:               # zadní noha sleze na zem a dvakrát poklepe
            p.update(c=1, lean=-1, lf=(-3, (3, 5, 4, 5, 4, 5, 3)[i - 9]), la=(-2.5, 2.5), look=-1)
        if 16 <= i <= 19:              # zhoupne prkno: šlápne na tail, nos se zvedne a zase klesne
            t = (2, 3, 2, 0)[i - 16]
            p.update(tilt=t, rf=(0, -round(t * 0.9)), c=1 if t else 0, ra=(2.5, 2.5 - t), look=1)
        frames.append(p)
    return frames


def _road(g, i):
    """Kamínky na silnici ujíždějí doleva (pod koly)."""
    for k in range(3):
        x = 30 - ((i * 3 + k * 11) % 32)
        g.put(x, 31, GREY)


FX["road"] = _road


def _cruise():
    """Edit, Write: jede v podřepu, ruce do stran, vítr a silnice ujíždějí."""
    return [dict(RIDE, c=(1, 1, 2, 2, 1, 1)[i], ra=(3.0, (1.0, 0.5, 1.0, 1.5, 1.0, 0.5)[i]),
                 la=(-3.5, (1.5, 2.0, 1.5, 1.0, 1.5, 2.0)[i]), spin=i,
                 fx=[("wind", i), ("road", i)]) for i in range(6)]


def _push(wind=True):
    """Bash: odráží se zadní nohou od země."""
    feet = ((0, 0), (-1, 4), (-3, 5), (-5, 5), (-4, 3), (-1, 1))
    out = []
    for i, f in enumerate(feet):
        p = dict(RIDE, c=1 if f[1] < 4 else 2, lean=0 if f[1] < 4 else 1, lf=f, spin=i,
                 la=(-3.0, (1.5, 1.0, 0.5, 0.5, 1.0, 1.5)[i]), ra=(3.0, (1.5, 2.0, 2.5, 2.5, 2.0, 1.5)[i]))
        if wind:
            p["fx"] = [("wind", i), ("road", i)]
        out.append(p)
    return out


def _manual():
    """Read, Grep…: manuál – jede jen po zadních kolečkách, balancuje rukama, kouká dopředu."""
    tilts = (2, 2, 3, 3, 2, 2)
    return [dict(RIDE, tilt=t, rf=(0, -round(t * 0.9)), c=1, lean=-1 if t > 3 else 0, spin=i,
                 la=(-3.5, (-1.0, -0.5, -1.5, -0.5, 0.0, -0.5)[i]), ra=(3.5, (0.5, 0.0, 1.0, 0.0, -0.5, 0.0)[i]),
                 look=1, fx=[("wind", i), ("road", i)]) for i, t in enumerate(tilts)]


def _ride():
    """Procházka po hraně okna: odrazí se a pak jede (bez větru, pohyb dělá okno)."""
    push = _push(wind=False)
    return push[:5] + [dict(RIDE, spin=i, c=(1, 1, 2)[i % 3]) for i in range(3)]


def _wave():
    return [{"ra": ((5.0, -6.5), (6.5, -4.5))[i % 2], "front_over": True, "la": (-2.0, 3.0), "eyes": "wide",
             "mouth": "o", "fx": [("bang", i % 2 == 0)]} for i in range(4)]


def _kickflip():
    sp = [("sparkle", 6, 6), ("sparkle", 27, 12), ("sparkle", 26, 3, WHITE)]
    air = dict(y=-1, c=0, knees="out", la=(-4.0, -1.0), ra=(4.5, -1.0), look=1)
    return [
        {},                                                                     # 0 stojí
        dict(c=2, la=(-2.5, 1.5), ra=(2.5, 2.0), look=1),                     # 1 přikrčí se
        dict(tilt=4, rf=(0, -4), hipy=-1, la=(-3.0, -1.0), ra=(3.0, -2.0), look=1, eyes="wide", mouth="o"),  # 2 pop
        dict(air, board="under", by=-4, lf=(-1, -6), rf=(1, -7), eyes="wide", mouth="o"),    # 3 flip
        dict(air, board="upside", by=-5, lf=(-1, -7), rf=(1, -7), eyes="wide", mouth="o"),   # 4
        dict(air, board="grip", by=-4, lf=(-1, -6), rf=(1, -6), eyes="wide", mouth="o"),     # 5
        dict(air, by=-4, lf=(0, -4), rf=(0, -4), c=0, eyes="happy", mouth="smile"),           # 6 chytí prkno
        dict(c=2, la=(-3.0, 1.0), ra=(3.0, 1.0), eyes="happy", mouth="smile",
             fx=[("dust", 16, 29, 0)]),                                                        # 7 dopad
        dict(la=(-4.5, -7.5), ra=(4.0, -7.5), eyes="happy", mouth="grin", fx=sp),             # 8 hurá
        dict(eyes="happy", mouth="smile", fx=[("twinkle", 7, 9, YELLOW), ("twinkle", 27, 4, YELLOW)]),       # 9 stojí
    ]


def _bail():
    sit = dict(sit=True, hipx=-4, hipy=10, lf=(6, 5), rf=(9, 5), la=(-3.5, -1.0), ra=(3.5, 0.5), hdx=-1,
               eyes="x", mouth="o")
    return [
        {},                                                                                    # 0 stojí
        dict(bx=4, lf=(2, 0), rf=(4, 0), lean=-2, hdx=-1, la=(-3.0, -4.0), ra=(4.5, -3.0),
             eyes="wide", mouth="o"),                                                          # 1 prkno ujíždí
        dict(bx=9, hipx=-1, hipy=4, lf=(3, -2), rf=(6, -3), knees="up", lean=-2, hdx=-1,
             la=(-3.5, -4.0), ra=(4.5, -4.0), eyes="x", mouth="o", fx=[("sweat", 25, 2)]),      # 2 padá
        dict(sit, bx=13, hdy=1, fx=[("dust", 11, 29, 0), ("stars", 0)]),                       # 3 žuch
        dict(sit, bx=15, fx=[("stars", 1), ("sweat", 22, 8)]),
        dict(sit, bx=15, fx=[("stars", 2), ("sweat", 22, 9)]),
        dict(sit, bx=15, fx=[("stars", 3)]),
        dict(bx=8, hipx=-1, hipy=3, lf=(0, 5), rf=(2, 5), lean=-1, c=1, eyes="x", mouth="o"),     # 7 vstává
        dict(bx=2, c=1, eyes="closed"),                                                          # 8 naskočí
        {},
    ]


def _sleep():
    return [dict(bx=-5, hipx=-5, hipy=6, sit=True, lf=(6, 5), rf=(8, 5), lk=(17, 24.5), rk=(19, 25),
                 la=(-1.0, 3.0), ra=(1.5, 2.5), hdx=1, hdy=(1, 1, 2, 2)[i], eyes="closed",
                 mouth="o" if i >= 2 else "line", noface=True, fx=[("zzz", i)]) for i in range(4)]


def _think():
    return [{"ra": (-0.6, -2.4), "front_over": True, "eyes": "up", "look": 1, "la": (-1.5, 3.0),
             "hdx": (0, 0, -1, -1, 0, 0)[i] * 0, "fx": [("dots", i // 2 + 1)]} for i in range(6)]


def _listen():
    return [{}, {"c": 1, "eyes": "wide", "mouth": "o"},
            {"hipy": -1, "eyes": "wide", "mouth": "o", "la": (-3.0, 1.0), "ra": (3.0, 1.0)},
            {"hipy": -1, "eyes": "wide", "mouth": "o", "la": (-3.0, 1.5), "ra": (3.0, 1.5)},
            {"eyes": "wide", "mouth": "o"}]


ANIMS = {   # tag → (fps, pózy, jednorázová)
    "idle": (4, _idle(), False),
    "listen": (8, _listen(), True),
    "think": (6, _think(), False),
    "work_edit": (8, _cruise(), False),
    "work_bash": (8, _push(), False),
    "work_search": (8, _manual(), False),
    "ride": (8, _ride(), False),
    "wave": (6, _wave(), False),
    "kickflip": (8, _kickflip(), True),
    "bail": (8, _bail(), True),
    "sleep": (2, _sleep(), False),
}

ACTIVITY = {"idle": "idle", "listening": "listen", "thinking": "think", "waiting": "wave",
            "success": "kickflip", "error": "bail", "sleeping": "sleep", "gone": "sleep", "walking": "ride"}
WORKING = {"Bash": "work_bash", "Edit": "work_edit", "Write": "work_edit", "NotebookEdit": "work_edit",
           "Read": "work_search", "Grep": "work_search", "Glob": "work_search", "WebSearch": "work_search",
           "WebFetch": "work_search", "ToolSearch": "work_search", "default": "work_edit"}
LOCKED_EYES = {"closed", "x", "happy", "wide", "up"}


# --- vrstvy a zápis ---------------------------------------------------------------------------

def _drone(k, phase):
    """Mini skate prkýnko (deska se zvednutými konci, dvě kolečka), poskakuje."""
    g = Canvas()
    y = 13 + k * 5 + (phase + k) % 2
    deck = {(x, y) for x in range(1, 6)} | {(0, y - 1), (6, y - 1)}
    g.part(deck, lambda *_: YELLOW)
    for wx in (1, 4):
        g.part({(wx, y + 2)}, lambda *_: GREEN)
        g.put(wx, y + 1, GREY)
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
            if p.get("noface") or p.get("eyes", "open") in LOCKED_EYES:
                keep["eyes"].setdefault(anim, []).append(i)
            if p.get("noface") or p.get("mouth", "line") != "line":
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
    lines = ["# Vygenerováno: python3 -I tools/skejtak.py (kresba kódem). Formát popisuje docs/skiny.md.",
             "# Vlastní dílo projektu Pixel Familiars, CC BY 4.0 (viz CREDITS.txt).", "",
             "[skin]", 'name = "Skejťák"', f"size = [{W}, {H}]", "anchor = [16, 31]", 'facing = "right"',
             'author = "Pixel Familiars"', 'license = "CC-BY-4.0"', "",
             "[layers]"]
    lines += [f'{k} = "{k}.png"' for k in ("body", "fx", "face", "emote", "drone")]
    lines += ["", "[palettes]"] + [f'{k} = "pal/{k}.gpl"' for k in PALETTES]
    lines += ["", "[activity]"] + [f"{st} = {tv(a)}" for st, a in ACTIVITY.items()]
    lines += [f"working = {tv(WORKING)}", "", "[mood]"]
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


CREDITS = """Skejťák – skin pro Pixel Familiars

Grafika: vlastní dílo projektu Pixel Familiars, kreslené kódem (tools/skejtak.py).
Licence: Creative Commons Uveďte původ 4.0 Mezinárodní (CC BY 4.0)
         https://creativecommons.org/licenses/by/4.0/ (plné znění v LICENSES/CC-BY-4.0.txt)
Uveďte: Pixel Familiars (Pavel Švec), https://github.com/pauliquib/familiar

Reakce nad hlavou jsou Robo-kunovy (familiar/sprites.py) přebarvené do palety skinu,
drony subagentů jsou malá skate prkýnka. Skin znovu vygeneruje: python3 -I tools/skejtak.py
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
    ap = argparse.ArgumentParser(description="skin Skejťák kreslený kódem")
    ap.add_argument("dest", nargs="?", default=os.path.join(REPO, "familiar", "skins", "skejtak"))
    args = ap.parse_args(argv)
    export(args.dest)
    print(f"skin skejtak zapsán do {args.dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
