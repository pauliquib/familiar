# Generátor skinu „Skejťák v0.2“: štíhlý skateboardista z profilu kreslený kódem (formát docs/skiny.md).
#
#   python3 -I tools/skejtak2.py [cílový adresář]      (výchozí familiar/skins/skejtak2)
#
# Komiksový styl: silné černé obrysy, ploché syté barvy, realističtější proporce (malá hlava,
# dlouhé nohy). Postava je kostra (kyčel, trup, ramena, kotníky, ruce): kolena a lokty dopočítá
# inverzní kinematika, končetiny jsou úsečky s tloušťkou, triko mnohoúhelník, hlava ručně
# kreslená předloha z profilu. Animace jsou klíčové pózy s dopočítanými mezisnímky; vlasy
# a lem trika se zpožďují za pohybem hlavy a vlají ve větru při jízdě. Prkno je 3D otočné
# kolem podélné osy (kickflip) i kolem kol (pop, manuál). Obličej (oko a pusa z profilu) mění
# nálada záplatami ve vrstvě face. Reakce jsou Robo-kunovy (sprites.POPS) přebarvené do
# palety, drony jsou malá prkýnka. Vlastní dílo projektu, CC BY 4.0.
import argparse, math, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from familiar import skin, skin_export, sprites   # noqa: E402

W, H = 48, 56
GY = H - 1          # spodní řádek koleček = kotva (hrana okna)
NONE = skin.NONE
(OUT, SKIN, SKIN_D, TEE, TEE_D, TEE_L, PANTS, PANTS_D, HAIR, HAIR_D,
 YELLOW, WHITE, SILVER, DARK, MID) = range(1, 16)

BASE = [None,
        "#16121c",   # 1 obrys, oko, pusa
        "#ffe4d2",   # 2 kůže (bledá)
        "#e8ab93",   # 3 kůže stín
        "#2ee6f0",   # 4 triko (tyrkysové)
        "#1597bd",   # 5 triko stín
        "#b8fcff",   # 6 triko světlo
        "#e01818",   # 7 kalhoty (červené)
        "#8c0e22",   # 8 kalhoty stín, manžety
        "#f6dc7c",   # 9 vlasy (blond)
        "#c9952f",   # 10 vlasy stín, značka na kolečku
        "#ffd400",   # 11 žlutá: kolečka, „!“, jiskry
        "#f7f6f0",   # 12 bílá: podrážky, pruh na botách, efekty
        "#aeb8c8",   # 13 stříbrná: trucky, prach, vítr
        "#36303f",   # 14 černá výplň: kšiltovka, boty, deska, spodní triko
        "#6c7088"]   # 15 šedá: bok desky, stín trucků, kamínky


def _pal(base, **swap):
    p = list(base)
    idx = {"tee": (TEE, TEE_D, TEE_L), "pants": (PANTS, PANTS_D), "skin": (SKIN, SKIN_D),
           "hair": (HAIR, HAIR_D), "wheel": (YELLOW,), "black": (DARK, MID)}
    for k, v in swap.items():
        for i, c in zip(idx[k], v):
            p[i] = c
    return p


PALETTES = {   # nálada mění hlavně triko (a u frustrace a únavy i kalhoty); indexy zůstávají
    "base": BASE,
    "warm": _pal(BASE, tee=("#ffb12e", "#d9691c", "#ffe9a8")),                                  # radost
    "red": _pal(BASE, tee=("#ff5a5f", "#b8263f", "#ffb3a8"), pants=("#a3122c", "#5c0a1e")),    # frustrace
    "cool": _pal(BASE, tee=("#a796ff", "#6750d1", "#e0d9ff"), pants=("#c4246a", "#7a1446")),   # zmatek
    "faded": _pal(BASE, tee=("#93c9cb", "#64979f", "#d3ecec"), pants=("#b86a68", "#7d4a52"),   # únava
                  skin=("#f2e2d8", "#cfae9f"), hair=("#e3d6a6", "#ad9466"), wheel=("#e6d77e",)),
}

MOODS = {   # nálada → oko, pusa, paleta, reakce při změně, tempo
    "klid": (None, None, "base", None, 1.0),
    "radost": (None, "smile", "warm", "heart", 1.0),
    "zvedavost": ("wide", "o", "base", "question", 1.0),
    "frustrace": ("angry", "frown", "red", "storm", 1.0),
    "zmatek": ("dazed", "wave", "cool", "spiral", 1.0),
    "unava": ("droopy", None, "faded", None, 0.6),
}

# reakce: barvy Robo-kuna → barvy skejťáka
POP_COLORS = {1: OUT, 8: WHITE, 9: YELLOW, 10: PANTS, 11: TEE, 13: SILVER, 14: HAIR_D, 15: TEE_D}
POP_AT = (3, 1)          # posun reakce (kreslené pro 32×32 vlevo nahoře)


class Canvas:
    def __init__(self):
        self.px = bytearray([NONE]) * (W * H)

    def put(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.px[y * W + x] = c

    def get(self, x, y):
        return self.px[y * W + x] if 0 <= x < W and 0 <= y < H else NONE

    def part(self, mask, color, outline=OUT, protect=()):
        """Část s vlastním obrysem: obrys kolem masky, pak výplň color(x, y). Pixely v protect
        (např. obličej pod vlasy) zůstanou, jak jsou."""
        for x, y in mask:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in mask and (nx, ny) not in protect:
                    self.put(nx, ny, outline)
        for x, y in mask:
            if (x, y) not in protect:
                self.put(x, y, color(x, y))

    def blit(self, rows, x, y, colors):
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch in colors:
                    self.put(x + dx, y + dy, colors[ch])


# --- geometrie ------------------------------------------------------------------------------

def _cells(test, box=(0, 0, W, H)):
    x0, y0, x1, y1 = (max(-2, math.floor(box[0])), max(-2, math.floor(box[1])),
                      min(W + 2, math.ceil(box[2]) + 1), min(H + 2, math.ceil(box[3]) + 1))
    return {(x, y) for y in range(y0, y1) for x in range(x0, x1) if test(x + 0.5, y + 0.5)}


def _seg_d2(px, py, ax, ay, bx, by):
    """Čtverec vzdálenosti bodu od úsečky."""
    vx, vy = bx - ax, by - ay
    t = 0.0 if vx == vy == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
    return (px - ax - t * vx) ** 2 + (py - ay - t * vy) ** 2


def _limb(pts, r, r2=None):
    """Maska lomené čáry s poloměrem r (u konce r2: zúžení)."""
    segs = list(zip(pts, pts[1:]))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    rr = max(r, r2 or r)
    box = (min(xs) - rr - 1, min(ys) - rr - 1, max(xs) + rr + 1, max(ys) + rr + 1)
    if r2 is None:
        return _cells(lambda x, y: min(_seg_d2(x, y, *a, *b) for a, b in segs) <= r * r, box)
    n = len(segs)

    def test(x, y):
        for k, (a, b) in enumerate(segs):
            rk = r + (r2 - r) * (k + 0.5) / n
            if _seg_d2(x, y, *a, *b) <= rk * rk:
                return True
        return False
    return _cells(test, box)


def _poly(pts):
    """Maska mnohoúhelníku (sudá-lichá pravidla)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]

    def inside(x, y):
        c = False
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                c = not c
        return c
    return _cells(inside, (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1))


def _ik(a, b, l1, l2, pref):
    """Kloub (koleno, loket) mezi a a b s délkami l1, l2; z obou řešení to blíž směru pref."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy) or 0.01
    ux, uy = dx / d, dy / d
    d = min(d, l1 + l2 - 0.05)
    along = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, l1 * l1 - along * along))
    px, py = -uy, ux
    if px * pref[0] + py * pref[1] < 0:
        px, py = -px, -py
    return (a[0] + ux * along + px * h, a[1] + uy * along + py * h)


def _lerp(a, b, t):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return a + (b - a) * t
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
        return tuple(_lerp(x, y, t) for x, y in zip(a, b))
    return a if t < 1 else b


def _ease(t):
    return t * t * (3 - 2 * t)


# --- prkno ----------------------------------------------------------------------------------
# Prkno z boku: černá deska (2 px, nahoře grip, dole šedý bok) se zvednutým nosem a tailem,
# stříbrné trucky, žlutá kolečka 3×3 s nábojem a značkou, která se při jízdě točí.
# Kickflip: deska se otáčí kolem podélné osy (flip, stupně), takže se ukáže spodek s grafikou,
# kolečka nahoře a grip. Pitch (stupně, nos nahoru) otáčí prkno kolem zadního nebo předního kola.

DECK_Y = 49.0       # osa desky (řádky 48–49), kolečka 52–54, spodní obrys koleček = GY
BOARD_X = 26.0
WHEEL_DY = 4.5      # střed kolečka pod osou desky
WHEEL_U = 7.0       # kolečka vůči středu desky
RING = ((0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2), (0, 1))   # značka na kolečku po směru hodin


def _board_xf(p):
    """Převod místních souřadnic prkna (u podél, v dolů) do plátna."""
    bx, by = p["bx"], DECK_Y + p["by"]
    a = math.radians(p["pitch"])
    pu, pv = {"tail": (-WHEEL_U, WHEEL_DY + 1.5), "nose": (WHEEL_U, WHEEL_DY + 1.5),
              "mid": (0.0, 0.0)}[p["pivot"]]
    ca, sa = math.cos(a), math.sin(a)

    def xf(u, v):
        du, dv = u - pu, v - pv
        return (bx + pu + du * ca + dv * sa, by + pv - du * sa + dv * ca)
    return xf


def _wheel(g, cx, cy, spin, mark=True):
    x, y = math.floor(cx) - 1, math.floor(cy) - 1
    m = {(x + i, y + j) for i in range(3) for j in range(3)}
    g.part(m, lambda *_: YELLOW)
    g.put(x + 1, y + 1, SILVER)
    if mark and spin is not None:
        dx, dy = RING[round(spin) % 8]
        g.put(x + dx, y + dy, HAIR_D)


def draw_board(g, p):
    if p["board"] is None:
        return
    xf = _board_xf(p)
    th = math.radians(p["flip"])
    c, s = math.cos(th), math.sin(th)
    flex, spin = p["flex"], p["spin"]
    kick = 1.7 * c
    t = max(0.95, 2.6 * abs(s))                         # tloušťka pásu desky (spodek / grip se ukáže)
    deck = [(-11.0, -kick), (-9.0, 0.0), (-3.0, flex), (3.0, flex), (9.0, 0.0), (11.0, -kick)]
    pts = [xf(u, v) for u, v in deck]
    edge = abs(s) < 0.35
    wheels = []
    for u in (-WHEEL_U, WHEEL_U):
        if edge:
            wheels.append((u, WHEEL_DY * c, 0))
        else:
            for side in (-1, 1):
                wheels.append((u, WHEEL_DY * c + 2.3 * side * s, side))
    behind = s < 0 or (edge and c < 0)                  # kolečka za deskou (vidět grip / vzhůru nohama)

    def draw_wheels():
        for u, v, side in wheels:
            wx, wy = xf(u, v)
            if not edge:                                 # truck mezi deskou a kolečky
                g.part(_limb([xf(u, 0.0), xf(u, WHEEL_DY * c)], 0.7), lambda *_: SILVER)
            _wheel(g, wx, wy, spin + (u > 0) * 3, mark=side >= 0)

    if behind:
        draw_wheels()
    mask = _limb(pts, t)
    ax, ay = xf(0, 0)
    nx, ny = xf(0, -1)
    nx, ny = nx - ax, ny - ay                            # „nahoru“ desky v plátně

    def col(x, y):
        up = (x + 0.5 - ax) * nx + (y + 0.5 - ay) * ny   # kladné = horní polovina
        if edge:
            return DARK if up > 0 else MID
        if s > 0:                                        # spodek: grafika (žlutý blesk) na černé
            along = (x + 0.5 - ax) * ny - (y + 0.5 - ay) * nx
            return YELLOW if abs(along * 0.5 + up * 1.2) < 0.6 and abs(along) < 6 else DARK
        return DARK if (x + y) % 3 else MID              # grip (zrnitý)
    g.part(mask, col)
    if edge and not behind:                              # trucky z profilu: stříbrné pod deskou
        for u in (-WHEEL_U, WHEEL_U):
            for v, w in ((1.6, 1.4), (2.6, 0.9)):
                tx, ty = xf(u, v * c)
                for dx in range(-math.floor(w), math.floor(w) + 1):
                    g.put(math.floor(tx) + dx, math.floor(ty), SILVER if dx >= 0 else MID)
    if not behind:
        draw_wheels()


# --- postava --------------------------------------------------------------------------------
# Hlava je ručně kreslená předloha 12×10 z profilu doprava: kšiltovka kšiltem dozadu (vlevo),
# vzadu blond vlasy (y), ucho (d), oko (e), nos vpravo, pusa (m). b = obrys vlasů (vlasy
# přes něj smějí přerůst do pramenů).

HEAD = ["....oooo....",
        "...occchho..",
        "oooccccccco.",
        "occoooooooo.",
        ".obyyysssso.",
        "..byydsseso.",
        "..byysssssso",
        "...byssssmo.",
        "....bosssso.",
        "......oooo.."]
HEAD_COLORS = {"o": OUT, "b": OUT, "c": DARK, "h": MID, "y": HAIR, "s": SKIN, "d": SKIN_D,
               "e": OUT, "m": OUT}
HEAD_NECK = (7.0, 9.6)          # bod krku v předloze
HEAD_EYE = (8, 5)               # oko v předloze = kotva obličeje
HAIR_ROOTS = ((3.2, 4.2, 6.4, 0), (3.4, 5.6, 7.4, 0), (3.6, 7.0, 6.2, 1), (4.2, 8.0, 4.4, 1))   # x, y, délka, stín

THIGH, SHIN = 9.8, 9.6
UPPER, FORE = 5.6, 5.4


def _shoe(g, ax, ay, ang):
    """Černá skate bota špičkou doprava: bílá podrážka a bílý pruh. (ax, ay) = kotník, ang = sklon
    špičky dolů (stupně)."""
    a = math.radians(ang)
    ux, uy, vx, vy = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)

    def loc(x, y):
        dx, dy = x - ax, y - ay
        return dx * ux + dy * uy, dx * vx + dy * vy

    def inside(x, y):
        lx, ly = loc(x, y)
        if not (-2.0 <= lx <= 4.4 and -1.1 <= ly <= 2.0):
            return False
        if lx > 2.0 and ly < -1.1 + (lx - 2.0) * 0.8:          # špička se svažuje
            return False
        return not (lx < -1.3 and ly < -0.4)                   # zakulacená pata

    def col(x, y):
        lx, ly = loc(x + 0.5, y + 0.5)
        if ly > 0.95:
            return WHITE
        if -0.6 < ly < 0.95 and 0.2 < lx + ly * 0.9 < 1.5:
            return WHITE
        return DARK
    g.part(_cells(inside, (ax - 6, ay - 6, ax + 6, ay + 6)), col)


def _leg(g, hip, ankle, ang, far, pref=(1.0, -0.2)):
    """Bota a široká nohavice s ohrnutou manžetou. far = vzdálenější noha (tmavší)."""
    _shoe(g, ankle[0], ankle[1], ang)
    knee = _ik(hip, ankle, THIGH, SHIN, pref)
    kx, ky = knee
    sx, sy = ankle[0] - kx, ankle[1] - ky
    sl = math.hypot(sx, sy) or 1.0
    cuff = (ankle[0] - sx / sl * 1.7, ankle[1] - sy / sl * 1.7)
    m = _limb([hip, knee], 2.1) | _limb([knee, cuff], 1.8) | _limb([cuff, cuff], 2.05)
    base, shade = (PANTS_D, PANTS_D) if far else (PANTS, PANTS_D)

    def col(x, y):
        px, py = x + 0.5, y + 0.5
        t = ((px - kx) * sx + (py - ky) * sy) / (sl * sl)
        if t > 0.66:
            return PANTS if far else PANTS_D                    # manžeta
        if not far and _seg_d2(px, py, hip[0] - 1.3, hip[1], kx - 1.6, ky + 0.8) < 0.5:
            return shade                                        # záhyb vzadu na stehně
        if not far and t > 0.0 and (px - kx) * sy - (py - ky) * sx > 1.0 * sl:
            return shade                                        # stín na zadní straně holeně
        return base
    g.part(m, col)
    return knee


def _arm(g, sh, hand, far, pref=(-0.5, 1.0), sleeve_dir=None):
    """Holá světlá paže, široký krátký rukáv trika a pod ním černý rukáv spodního trika."""
    el = _ik(sh, hand, UPPER, FORE, pref)
    skin_c = SKIN_D if far else SKIN
    g.part(_limb([sh, el, hand], 0.8), lambda *_: skin_c)
    hx, hy = hand
    g.part(_cells(lambda x, y: (x - hx) ** 2 + (y - hy) ** 2 <= 1.25, (hx - 2, hy - 2, hx + 2, hy + 2)),
           lambda *_: skin_c)
    ex, ey = el[0] - sh[0], el[1] - sh[1]
    l = math.hypot(ex, ey) or 1.0
    ex, ey = ex / l, ey / l
    if sleeve_dir:                                    # rukáv vlaje
        ex, ey = ex + sleeve_dir[0], ey + sleeve_dir[1]
        l = math.hypot(ex, ey) or 1.0
        ex, ey = ex / l, ey / l
    under = (sh[0] + ex * 3.2, sh[1] + ey * 3.2)
    g.part(_limb([sh, under], 1.15), lambda *_: DARK)
    tip = (sh[0] + ex * 2.3, sh[1] + ey * 2.3)
    g.part(_limb([(sh[0] - ex * 0.4, sh[1] - ey * 0.4), tip], 1.75),
           lambda x, y: TEE_D if far or (x + 0.5 - sh[0]) * -ey + (y + 0.5 - sh[1]) * ex < -0.6 else TEE)
    return el


def _torso(g, hip, lean, tl, flut, cx_mid):
    """Volné triko: mnohoúhelník podél osy trupu (u nahoru, v dopředu); flut = vlání lemu."""
    a = math.radians(lean)
    upx, upy = math.sin(a), -math.cos(a)
    fx, fy = math.cos(a), math.sin(a)

    def P(u, v):
        return (hip[0] + upx * u + fx * v, hip[1] + upy * u + fy * v)
    fu, fv = flut
    pts = [P(tl + 0.4, -1.2), P(tl - 0.6, -2.8), P(tl - 3.5, -3.4), P(2.0, -3.6),
           P(-1.4 + fu, -4.1 - fv), P(-2.2 + fu * 0.5, -2.6 - fv * 0.4), P(-2.0, 0.0), P(-1.8, 2.6),
           P(-1.2, 3.9), P(2.0, 3.6), P(tl - 4.0, 3.5), P(tl - 1.2, 2.8), P(tl + 0.4, 1.0)]
    m = _poly(pts)

    def col(x, y):
        dx, dy = x + 0.5 - hip[0], y + 0.5 - hip[1]
        u, v = dx * upx + dy * upy, dx * fx + dy * fy
        if u < -1.0 or v < -2.6:
            return TEE_D                                        # lem a záda ve stínu
        if v > 1.9 and u > tl - 5.5:
            return TEE_L                                        # světlo na prsou
        if abs(v - (u - 4.5) * 0.45 + 0.6) < 0.45 and 0 < u < tl - 3:
            return TEE_D                                        # záhyb pod paží
        return TEE
    g.part(m, col)
    return P


def _hair(g, hx, hy, alpha, wave, protect):
    """Rovné blond vlasy zpod kšiltovky; alpha = úhel od svislice dozadu (0 visí, 1.3 vlají)."""
    m, dark = set(), set()
    for k, (rx, ry, ln, sh) in enumerate(HAIR_ROOTS):
        a1 = min(1.35, alpha + 0.12 * k)
        a2 = min(1.55, a1 + 0.25 + wave * (0.35 if k % 2 else -0.3))
        x0, y0 = hx + rx, hy + ry
        x1, y1 = x0 - math.sin(a1) * ln * 0.55, y0 + math.cos(a1) * ln * 0.55
        x2, y2 = x1 - math.sin(a2) * ln * 0.45, y1 + math.cos(a2) * ln * 0.45
        strand = _limb([(x0, y0), (x1, y1), (x2, y2)], 1.05, 0.55)
        m |= strand
        if sh:
            dark |= strand
    for dy, row in enumerate(HEAD):
        for dx, ch in enumerate(row):
            if ch == "y":
                m.add((hx + dx, hy + dy))
    m -= protect
    g.part(m, lambda x, y: HAIR_D if (x, y) in dark else HAIR, protect=protect)


def _head(g, hx, hy, cap):
    g.blit(HEAD, hx, hy, HEAD_COLORS)
    if cap:                                             # kšiltovka posunutá (úprava rukou)
        cx, cy = cap
        rows = HEAD[:4]
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch in "och" and dy < 3:
                    g.put(hx + dx, hy + dy, SKIN if dy == 3 else NONE)
        g.blit(rows, hx + cx, hy + cy, {"o": OUT, "c": DARK, "h": MID})
        for dx in range(3, 10):
            if g.get(hx + dx, hy + 3 + cy) == NONE:
                g.put(hx + dx, hy + 3 + cy, OUT)


def _protect(hx, hy):
    return {(hx + dx, hy + dy) for dy, row in enumerate(HEAD) for dx, ch in enumerate(row)
            if ch not in ".yb"}


# --- obličej (záplaty) ----------------------------------------------------------------------
# Oko: 3×3 kolem oka (řádek obočí, oko, líce). Pusa: 2×2 (vpravo je obrys tváře).
# „.“ = kůže (smaže výchozí), x = tmavá, w = bílá.

EYES_OFF, EYES_SIZE = (-1, -1), (3, 3)
MOUTH_OFF, MOUTH_SIZE = (-1, 2), (3, 2)
EYES = {
    "open": ["...", ".x.", "..."],
    "wide": [".x.", "wx.", "wx."],
    "closed": ["...", "...", "xx."],
    "happy": ["...", ".x.", "x.x"],
    "x": ["x.x", ".x.", "x.x"],
    "angry": ["xx.", ".xx", "..."],
    "droopy": ["...", "xxx", ".x."],
    "dazed": ["xx.", "..x", "xx."],
    "up": [".x.", "...", "..."],
    "squeeze": ["x..", ".xx", "x.."],
    "down": ["...", "...", ".x."],
}
MOUTHS = {
    "line": ["..x", "..."],
    "smile": ["x..", ".xx"],
    "o": ["..x", "..x"],
    "frown": [".xx", "x.."],
    "wave": ["x.x", ".x."],
    "grin": ["xxx", ".xw"],
    "flat": [".xx", "..."],
}
FACE = {".": SKIN, "x": OUT, "w": WHITE}
LOCKED_EYES = {"closed", "x", "happy", "wide", "up", "squeeze", "down"}


def _face(g, ix, iy, eyes, mouth):
    g.blit(EYES[eyes], ix + EYES_OFF[0], iy + EYES_OFF[1], FACE)
    g.blit(MOUTHS[mouth], ix + MOUTH_OFF[0], iy + MOUTH_OFF[1], FACE)


# --- efekty (vrstva fx) ---------------------------------------------------------------------

def _glyph(g, rows, x, y, c):
    """Znak s tmavým obrysem: čitelný na světlém i tmavém titulku."""
    g.part({(x + dx, y + dy) for dy, row in enumerate(rows) for dx, ch in enumerate(row) if ch == "x"},
           lambda *_: c)


def _dots(g, n, x=30, y=6):
    for k in range(n):
        _glyph(g, ["xx", "xx"], x + 4 * k, y, WHITE)


def _bang(g, on, x=34, y=4):
    if on:
        _glyph(g, ["xx", "xx", "xx", "xx", "  ", "xx"], x, y, YELLOW)


Z_SMALL = ["xxx", "  x", " x ", "xxx"]
Z_BIG = ["xxxx", "   x", "  x ", " x  ", "xxxx"]


def _zzz(g, i):
    _glyph(g, Z_SMALL, 33, 22 - i % 2, WHITE)
    if i % 2 == 0:
        _glyph(g, Z_BIG, 38, 14, WHITE)


def _sparkle(g, x, y, c=YELLOW, big=True):
    if big:
        g.blit(["  o  ", " oco ", "occco", " oco ", "  o  "], x - 2, y - 2, {"o": OUT, "c": c})
        g.put(x, y, WHITE)
    else:
        g.blit([" o ", "oco", " o "], x - 1, y - 1, {"o": OUT, "c": c})


def _star(g, x, y, c=YELLOW):
    g.blit([" c ", "ccc", " c "], x - 1, y - 1, {"c": c})


def _stars(g, i, cx, cy):
    """Hvězdičky kroužící kolem hlavy po pádu."""
    for k in range(3):
        a = i * 0.9 + k * 2.1
        _star(g, round(cx + 6.5 * math.cos(a)), round(cy + 1.8 * math.sin(a)), YELLOW if k != 1 else WHITE)


def _sweat(g, x, y):
    g.blit([" o ", "owo", "owo", " o "], x, y, {"o": OUT, "w": WHITE})


def _speed(g, i, rows=((20, 6), (28, 4), (35, 5), (42, 3))):
    """Rychlostní čárky za jezdcem: ujíždějí doleva."""
    for k, (y, ln) in enumerate(rows):
        x = 12 - ((i * 3 + k * 5) % 12)
        for dx in range(ln):
            g.put(x + dx, y, SILVER if dx < ln - 1 else MID)


def _road(g, i):
    """Kamínky a spáry na silnici ujíždějí doleva."""
    for k in range(4):
        x = W - 1 - ((i * 3 + k * 13) % (W + 4))
        g.put(x, GY, MID)
        g.put(x + 1, GY, MID if k % 2 else SILVER)


def _dust(g, x, y, k):
    """Obláček prachu (k = fáze 0, 1, 2)."""
    rows = (["  ww ", " wwww", "  gg "], [" w  w  ", "ww  ww ", " g   g "], ["w     w", "       ", "g     g"])[k]
    g.blit(rows, x - len(rows[0]) // 2, y - 2, {"w": SILVER, "g": MID})


def _puff(g, x, y, k):
    """Malý obláček od odrážející se boty (doleva dozadu)."""
    rows = (["ss ", "sws"], [" s  ", "s ws"], ["s   ", "   s"])[k]
    g.blit(rows, x - len(rows[0]) + 1, y - 1, {"s": SILVER, "w": WHITE})


def _clack(g, x, y):
    """Náraz prkna: krátké čárky."""
    for dx, dy in ((0, -2), (2, -1), (-2, -1), (3, 1), (-3, 1)):
        g.put(x + dx, y + dy, WHITE)


FX = {"dots": _dots, "bang": _bang, "zzz": _zzz, "sparkle": _sparkle, "stars": _stars,
      "sweat": _sweat, "speed": _speed, "road": _road, "dust": _dust, "puff": _puff, "clack": _clack}


# --- póza -----------------------------------------------------------------------------------
# Neutrální póza: stojí bokem, přední (levá, vzdálenější) noha na prknu nad předním truckem,
# zadní (pravá, bližší) na zemi u tailu. Tou se odráží.

NEUTRAL = dict(
    hip=(20.0, 34.4), lean=6.0, tl=10.6, head=(0.0, 0.0),
    ff=(32.0, 46.0, 0.0), fb=(11.8, 53.0, 0.0),           # kotníky (x, y, sklon špičky)
    hn=(1.8, 10.0), hf=(2.6, 9.8),                          # ruce vůči ramenům
    kn=(1.0, -0.2), kf=(1.0, -0.2), en=(-0.5, 1.0), ef=(-0.5, 1.0),   # kam míří kolena a lokty
    bx=BOARD_X, by=0.0, pitch=0.0, pivot="tail", flip=0.0, flex=0.0, spin=0, board="side",
    eyes="open", mouth="line", wind=0.0, cap=None, legs_front=False, arm_front=True,
    hair_extra=0.0, fx=(),
)


def draw(p, hair=(0.3, 0.0), flut=(0.0, 0.0)):
    """(body, fx, kotva obličeje) jedné pózy; hair = (úhel vlasů, vlnění), flut = vlání lemu trika."""
    g = Canvas()
    draw_board(g, p)
    hip, lean, tl = p["hip"], p["lean"], p["tl"]
    a = math.radians(lean)
    upx, upy, fx_, fy_ = math.sin(a), -math.cos(a), math.cos(a), math.sin(a)
    top = (hip[0] + upx * tl, hip[1] + upy * tl)

    def rel(u, v):
        return (hip[0] + upx * u + fx_ * v, hip[1] + upy * u + fy_ * v)
    sh_n, sh_f = rel(tl - 1.6, -0.4), rel(tl - 1.9, 0.6)
    hn = (sh_n[0] + p["hn"][0], sh_n[1] + p["hn"][1])
    hf = (sh_f[0] + p["hf"][0], sh_f[1] + p["hf"][1])
    wind = p["wind"]
    sleeve = (-0.5 * wind, -0.2 * wind) if wind else None
    _arm(g, sh_f, hf, True, p["ef"], sleeve)
    ff, fb = p["ff"], p["fb"]
    _leg(g, hip, (ff[0], ff[1] - 0.6), ff[2], True, p["kf"])
    if not p["legs_front"]:
        _leg(g, (hip[0] - 0.6, hip[1] + 0.4), (fb[0], fb[1] - 0.6), fb[2], False, p["kn"])
    neck = rel(tl + 0.9, 0.6)
    hx = round(neck[0] - HEAD_NECK[0] + p["head"][0])
    hy = round(neck[1] - HEAD_NECK[1] + p["head"][1])
    g.part(_limb([rel(tl - 1.0, 0.4), (hx + HEAD_NECK[0], hy + HEAD_NECK[1] - 1.0)], 1.1),
           lambda x, y: SKIN_D if x + 0.5 < hx + HEAD_NECK[0] - 0.6 else SKIN)
    _torso(g, hip, lean, tl, flut, None)
    if p["legs_front"]:
        _leg(g, (hip[0] - 0.6, hip[1] + 0.4), (fb[0], fb[1] - 0.6), fb[2], False, p["kn"])
    if not p["arm_front"]:
        _arm(g, sh_n, hn, False, p["en"], sleeve)
    _head(g, hx, hy, p["cap"])
    _hair(g, hx, hy, hair[0], hair[1], _protect(hx, hy))
    ix, iy = hx + HEAD_EYE[0], hy + HEAD_EYE[1]
    _face(g, ix, iy, p["eyes"], p["mouth"])
    if p["arm_front"]:
        _arm(g, sh_n, hn, False, p["en"], sleeve)
    fx = Canvas()
    for name, *args in p["fx"]:
        FX[name](fx, *args)
    return g.px, fx.px, (ix, iy)


# --- animace --------------------------------------------------------------------------------

def P(*base, **kw):
    """Póza: neutrální, přes ni základy (slovníky) a pak jednotlivé hodnoty."""
    d = dict(NEUTRAL)
    for b in base:
        d.update(b)
    d.update(kw)
    return d


def tween(keys):
    """keys = [(póza, počet snímků k další klíčové), …]; poslední klíčová se přidá jednou.
    Čísla a n-tice se plynule prolínají, ostatní (oči, efekty) platí od své klíčové pózy."""
    out = []
    for (a, n), (b, _) in zip(keys, keys[1:]):
        for j in range(n):
            t = _ease(j / n)
            out.append({k: _lerp(a[k], b[k], t) if k not in ("fx", "eyes", "mouth", "board", "pivot", "cap")
                        else a[k] for k in a})
    out.append(dict(keys[-1][0]))
    return out


def secondary(frames, loop):
    """Vlasy a lem trika: vítr při jízdě a zpoždění za pohybem hlavy (setrvačnost)."""
    heads = []
    for p in frames:
        hip, a, tl = p["hip"], math.radians(p["lean"]), p["tl"]
        heads.append((hip[0] + math.sin(a) * tl + p["head"][0], hip[1] - math.cos(a) * tl + p["head"][1]))
    out = []
    for i, p in enumerate(frames):
        j = (i - 1) % len(frames) if loop else max(0, i - 1)
        vx, vy = heads[i][0] - heads[j][0], heads[i][1] - heads[j][1]
        w = p["wind"]
        alpha = 0.25 + 0.95 * w + max(-0.4, min(0.6, vx * 0.22)) - max(-0.3, min(0.4, vy * 0.18)) + p["hair_extra"]
        wave = (1 if i % 2 else -1) * (0.5 * w + min(0.5, abs(vy) * 0.15))
        flut = (0.8 * w + max(-1.0, min(1.0, -vy * 0.4)), 1.2 * w + max(-1.0, min(1.2, vx * 0.5)) + (0.5 if (i % 2 and w) else 0))
        out.append((p, (alpha, wave), flut))
    return out


FRONT = 32.0            # přední noha na prknu (nad předním truckem)
TAIL = 19.0             # zadní noha na prknu (nad zadním truckem)
ON = 46.0               # kotník nohy na prknu (podrážka na desce)
GROUND = 53.0           # kotník nohy na zemi


def _feet_on(lift=0.0, front=FRONT, tail=TAIL, ang=0.0):
    """Obě nohy na prknu (lift = o kolik je prkno výš)."""
    return dict(ff=(front, ON - lift, ang), fb=(tail, ON - lift, ang))


RIDE = dict(_feet_on(), hip=(25.0, 30.4), lean=14.0, hn=(5.0, 5.0), hf=(-4.0, 6.0), en=(-0.2, 1.0),
            ef=(-0.2, 1.0), wind=1.0)


def _roll(frames, fx=True, start=0):
    """Jízda: kolečka se točí; za jezdcem rychlostní čárky a ujíždějící silnice."""
    for i, p in enumerate(frames):
        p["spin"] = (start + i) * 3
        p["wind"] = 1.0
        if fx:
            p["fx"] = [("speed", i), ("road", i)] + list(p["fx"])
    return frames


def _idle():
    """Dlouhá smyčka (11 s): dýchá, mrkne, přešlápne, upraví si kšiltovku, kouká na prkno
    a zhoupne ho pod přední nohou, znovu mrkne."""
    n = P()
    br = P(tl=10.3, hip=(20.0, 34.7), hn=(1.7, 9.8), hf=(2.5, 9.6))     # výdech
    cap = dict(en=(-1.0, 0.3), head=(0.0, 0.0))
    keys = [(n, 2), (br, 2), (n, 2), (P(eyes="closed"), 1), (n, 2), (br, 2),
            # přešlápne: zadní noha se zvedne, popojde a dopadne
            (n, 1), (P(fb=(12.6, 50.6, -12.0), hip=(20.8, 34.0), lean=4.0), 1),
            (P(fb=(13.8, GROUND, 0.0), hip=(21.0, 34.6), lean=7.0, tl=10.4), 2),
            (P(fb=(13.8, GROUND, 0.0), hip=(21.0, 34.8), lean=7.0, tl=10.3), 1),
            (P(fb=(12.6, 50.8, -10.0), hip=(20.6, 34.0)), 1), (n, 2),
            # upraví si kšiltovku: ruka nahoru, kšilt se nadzvedne a posadí
            (P(cap, hn=(-2.6, -2.0)), 1),
            (P(cap, hn=(-4.6, -8.6), head=(0.0, 0.0)), 1),
            (P(cap, hn=(-4.4, -9.6), cap=(0, -1), eyes="closed"), 1),
            (P(cap, hn=(-5.2, -9.0), cap=(-1, -1)), 1),
            (P(cap, hn=(-4.8, -8.4), cap=(-1, 0)), 1),
            (P(cap, hn=(-2.6, -2.4)), 1), (n, 2), (br, 2),
            # kouká dolů na prkno a zhoupne ho: šlápne na nos, prkno se kolébá a popojede
            (P(eyes="down", head=(0.0, 1.0), lean=9.0), 1),
            (P(eyes="down", head=(0.0, 1.0), lean=10.0, pitch=-5.0, pivot="nose", ff=(FRONT, 47.4, 6.0),
               hip=(20.4, 35.0), tl=10.4), 1),
            (P(eyes="down", head=(0.0, 1.0), lean=9.0, pitch=4.0, pivot="tail", ff=(FRONT + 0.6, 45.0, -5.0),
               bx=BOARD_X + 0.6, spin=1, hip=(20.2, 34.2)), 1),
            (P(eyes="down", head=(0.0, 1.0), lean=10.0, pitch=-4.0, pivot="nose", ff=(FRONT + 1.0, 47.0, 4.0),
               bx=BOARD_X + 1.0, spin=2, hip=(20.4, 34.9), tl=10.4), 1),
            (P(eyes="down", head=(0.0, 1.0), lean=8.0, pitch=2.0, pivot="tail", ff=(FRONT + 0.6, 45.6, -2.0),
               bx=BOARD_X + 0.6, spin=1), 1),
            (P(bx=BOARD_X, spin=0), 2), (br, 2), (n, 1), (P(eyes="closed"), 1), (n, 2), (br, 2),
            (n, 0)]
    frames = tween(keys)[:-1]
    for i, p in enumerate(frames):                      # vánek: vlasy se pomalu pohupují
        p["hair_extra"] = 0.14 * math.sin(i * 2 * math.pi * 4 / len(frames))
    return frames


def _push(fx=True, glide=2):
    """Bash: odrážení. Zadní noha se odrazí od země a natáhne dozadu (póza odrazu: přední
    pokrčená na prknu, trup nakloněný dopředu, ruce před sebou), klouže, pak se noha vrátí."""
    keys = [
        (P(wind=1.0), 1),
        (P(fb=(8.4, GROUND, 8.0), hip=(21.4, 35.0), lean=13.0, hn=(4.0, 6.0), hf=(5.0, 5.6)), 1),
        (P(fb=(5.4, 51.4, 28.0), hip=(22.2, 35.8), lean=19.0, hn=(6.4, 3.0), hf=(7.8, 2.4)), 1),
        (P(fb=(4.6, 47.4, 36.0), hip=(22.6, 36.0), lean=22.0, hn=(7.0, 1.8), hf=(8.6, 1.2)), glide),
        (P(fb=(5.4, 47.0, 30.0), hip=(22.4, 35.6), lean=21.0, hn=(6.8, 2.4), hf=(8.4, 1.8)), 1),
        (P(fb=(9.6, 49.4, 8.0), hip=(21.0, 34.8), lean=12.0, hn=(4.0, 6.2), hf=(5.2, 6.0)), 1),
        (P(), 0),
    ]
    frames = _roll(tween(keys)[:-1], fx)
    if fx:
        frames[1]["fx"].append(("puff", 8, GY - 1, 0))
        frames[2]["fx"].append(("puff", 6, GY - 1, 1))
        frames[3]["fx"].append(("puff", 4, GY - 1, 2))
    return frames


def _carve():
    """Edit, Write: odrazí se, naskočí zadní nohou na tail a jede v podřepu; v zatáčkách se
    houpe, prkno se pruží a naklání."""
    def cr(hip, lean, hn, hf, **kw):
        return P(RIDE, hip=hip, lean=lean, hn=hn, hf=hf, tl=10.4, **kw)
    keys = [
        (P(wind=1.0), 1),
        (P(fb=(8.4, GROUND, 8.0), hip=(21.4, 35.0), lean=13.0, hn=(4.0, 6.0), hf=(5.0, 5.6)), 1),
        (P(fb=(14.0, 49.0, -8.0), hip=(22.8, 33.0), lean=12.0, hn=(5.0, 4.0), hf=(3.0, 5.0)), 1),
        (cr((24.6, 30.6), 14.0, (5.6, 4.0), (-4.4, 5.0)), 1),
        (cr((24.8, 32.0), 19.0, (6.6, 2.4), (-5.4, 3.2), flex=0.6), 2),
        (cr((25.6, 31.4), 22.0, (6.8, 1.0), (-5.8, 2.0), pitch=-2.5, pivot="nose"), 2),
        (cr((24.6, 32.2), 17.0, (6.0, 3.0), (-5.0, 3.6), flex=0.6), 2),
        (cr((24.4, 31.2), 15.0, (6.4, 1.8), (-5.8, 2.6), pitch=2.5, pivot="tail"), 2),
        (cr((24.6, 30.6), 14.0, (5.4, 4.2), (-4.4, 5.0)), 1),
        (P(fb=(14.0, 49.4, 6.0), hip=(22.4, 33.4), lean=12.0, hn=(4.4, 5.2), hf=(3.0, 5.6)), 1),
        (P(), 0),
    ]
    return _roll(tween(keys)[:-1])


def _manual():
    """Read, Grep…: odrazí se, šlápne na tail a jede manuál po zadních kolečkách, balancuje
    rukama a kouká dopředu."""
    def m(t, hip, lean, hn, hf, **kw):
        a = math.radians(t)
        nose = (FRONT + 0.4 - (1 - math.cos(a)) * 11.0, ON - math.sin(a) * (FRONT - TAIL + 1.0))
        return P(RIDE, pitch=t, pivot="tail", hip=hip, lean=lean, hn=hn, hf=hf, ff=(nose[0], nose[1], -t),
                 fb=(TAIL - 1.0, ON - math.sin(a) * 0.4, -t), en=(0.2, 1.0), ef=(-0.6, 1.0), **kw)
    keys = [
        (P(wind=1.0), 1),
        (P(fb=(8.4, GROUND, 8.0), hip=(21.4, 35.0), lean=13.0, hn=(4.0, 6.0), hf=(5.0, 5.6)), 1),
        (P(fb=(14.0, 49.0, -8.0), hip=(22.8, 33.0), lean=12.0, hn=(5.0, 4.0), hf=(3.0, 5.0)), 1),
        (m(6.0, (23.6, 30.8), 4.0, (6.0, 2.0), (-5.0, 3.0)), 1),
        (m(13.0, (22.8, 30.6), -2.0, (7.0, -2.4), (-5.8, 0.4)), 2),
        (m(16.0, (22.4, 30.4), -4.0, (7.6, -3.6), (-6.0, 1.4), eyes="up"), 2),
        (m(11.0, (23.2, 30.8), 1.0, (6.6, -0.6), (-5.4, -2.0)), 2),
        (m(15.0, (22.6, 30.4), -3.0, (7.4, -3.0), (-6.2, 0.6), eyes="up"), 2),
        (m(5.0, (23.8, 31.0), 6.0, (6.0, 2.4), (-4.8, 3.2)), 1),
        (P(fb=(14.0, 49.4, 6.0), hip=(22.4, 33.4), lean=12.0, hn=(4.4, 5.2), hf=(3.0, 5.6)), 1),
        (P(), 0),
    ]
    return _roll(tween(keys)[:-1])


def _wave():
    """Čeká na povolení: narovná se, mává rukou nad hlavou, oko dokořán, blikající „!“."""
    up = dict(eyes="wide", mouth="o", en=(1.0, 0.0), lean=2.0, hip=(19.8, 34.2))
    keys = [(P(), 1), (P(up, hn=(5.4, -3.4)), 1), (P(up, hn=(6.4, -9.6)), 1), (P(up, hn=(2.4, -10.8), tl=10.8), 1),
            (P(up, hn=(6.6, -9.4)), 1), (P(up, hn=(2.4, -10.8), tl=10.8), 1), (P(up, hn=(6.4, -9.6)), 1),
            (P(up, hn=(4.6, -2.6)), 1), (P(), 0)]
    frames = tween(keys)[:-1]
    for i, p in enumerate(frames):
        p["fx"] = [("bang", 1 <= i <= 6 and i % 2 == 1)]
    return frames


def _think():
    """Zastaví se, ruka na bradě, oko nahoru, „…“ přibývá; jednou si poklepe na bradu."""
    chin = dict(hn=(3.8, -2.6), en=(0.4, 1.0), eyes="up", lean=3.0, hf=(1.6, 9.6))
    tap = dict(chin, hn=(3.8, -1.6))
    keys = [(P(), 1), (P(hn=(3.6, 3.0), en=(0.4, 1.0), lean=4.0), 1),
            (P(chin), 3), (P(tap), 1), (P(chin), 1), (P(tap), 1), (P(chin), 3),
            (P(chin, eyes="open", head=(0.0, 0.0)), 2), (P(chin), 3), (P(hn=(3.6, 3.0), en=(0.4, 1.0), lean=4.0), 1),
            (P(), 0)]
    frames = tween(keys)[:-1]
    for i, p in enumerate(frames):
        if 2 <= i < len(frames) - 1:
            p["fx"] = [("dots", min(3, 1 + (i - 2) // 3))]
    return frames


def _listen():
    """Zbystří: přikrčí se, narovná, hlava nahoru, oko dokořán, a zase se uvolní."""
    keys = [(P(), 1), (P(hip=(20.0, 35.0), tl=10.3, lean=8.0, eyes="wide", mouth="o"), 1),
            (P(hip=(19.6, 34.0), tl=11.0, lean=0.0, head=(0.0, -1.0), eyes="wide", mouth="o", hn=(1.0, 9.6),
               hf=(1.8, 9.4)), 2),
            (P(hip=(19.6, 34.1), tl=10.9, lean=1.0, head=(0.0, -1.0), eyes="wide", mouth="o", hn=(1.0, 9.6),
               hf=(1.8, 9.4)), 1), (P(eyes="wide"), 1), (P(), 0)]
    return tween(keys)


def _kickflip():
    """Kickflip: naskočí na tail, přikrčí se, pop, prkno se pod ním otočí kolem podélné osy,
    chytí ho nohama, dopadne do podřepu (squash, prkno se prohne, prach), vystřelí nahoru
    s rukama nad hlavou, jiskry, a zase sleze zadní nohou na zem."""
    tuck = dict(kf=(0.5, -1.0), kn=(0.7, -1.0), en=(-0.4, 1.0), ef=(-0.4, 1.0), eyes="wide", mouth="o")
    sp = [("sparkle", 9, 14), ("sparkle", 41, 12), ("sparkle", 38, 4, WHITE, False), ("sparkle", 13, 5, WHITE, False)]

    def air(lift, flip, hip, ff=0.0, **kw):
        return P(tuck, by=-lift, flip=flip, ff=(FRONT + ff, ON - lift - 2.6, 8.0), fb=(TAIL + 0.6, ON - lift - 2.4, -4.0),
                 hip=hip, lean=10.0, **kw)
    return [
        P(),
        P(fb=(14.4, 49.0, -8.0), hip=(22.6, 33.2), lean=10.0, hn=(2.6, 8.0)),
        P(RIDE, _feet_on(tail=TAIL - 1.0), hip=(24.8, 32.2), lean=20.0, tl=10.0, hn=(-1.4, 7.2), hf=(-2.6, 6.8),
          wind=0.0),
        P(tuck, pitch=22.0, pivot="tail", ff=(FRONT - 2.6, 40.6, -14.0), fb=(TAIL - 3.0, 49.0, 22.0),
          hip=(24.2, 27.0), lean=4.0, hn=(7.6, -1.6), hf=(-6.4, -1.0), en=(0.0, 1.0)),
        air(8.0, 75.0, (25.0, 22.4), ff=1.4, hn=(8.4, -1.6), hf=(-7.4, -2.0)),
        air(9.0, 160.0, (25.0, 21.4), hn=(8.6, -1.0), hf=(-7.6, -1.4)),
        air(9.0, 245.0, (25.0, 21.4), hn=(8.6, -0.4), hf=(-7.6, -0.8)),
        air(8.0, 320.0, (25.0, 22.2), hn=(8.0, 0.6), hf=(-7.0, 0.4), eyes="open"),
        P(RIDE, _feet_on(5.0), by=-5.0, hip=(25.4, 25.6), lean=10.0, hn=(6.0, 1.0), hf=(-4.6, 1.6), wind=0.0),
        P(RIDE, hip=(25.0, 33.4), lean=22.0, tl=9.6, flex=1.0, hn=(6.0, 3.0), hf=(-4.4, 3.6), wind=0.0,
          eyes="squeeze", mouth="flat", fx=[("dust", 14, GY, 0), ("dust", 38, GY, 0)]),
        P(RIDE, hip=(25.0, 28.4), lean=2.0, tl=11.2, hn=(5.6, -9.4), hf=(6.8, -8.8), en=(1.0, 0.0), ef=(1.0, 0.0),
          wind=0.0, eyes="happy", mouth="grin", fx=[("dust", 14, GY, 1), ("dust", 38, GY, 1), *sp[:2]]),
        P(RIDE, hip=(25.0, 29.0), lean=3.0, tl=11.0, hn=(6.2, -9.6), hf=(7.4, -8.8), en=(1.0, 0.0), ef=(1.0, 0.0),
          wind=0.0, eyes="happy", mouth="grin", fx=[("dust", 14, GY, 2), ("dust", 38, GY, 2), *sp[2:]]),
        P(RIDE, hip=(25.2, 29.6), lean=8.0, hn=(2.6, 8.4), hf=(3.4, 8.0), wind=0.0, eyes="happy", mouth="smile",
          fx=[("sparkle", 10, 12, YELLOW, False), ("sparkle", 40, 7, WHITE, False)]),
        P(fb=(14.4, 49.0, -8.0), hip=(22.6, 33.2), lean=8.0, hn=(2.4, 9.0), eyes="happy", mouth="smile"),
        P(),
    ]


def _bail():
    """Prkno mu ujede, padá dozadu na zadek, kolem hlavy krouží hvězdičky, pot; prkno se
    odrazí a přijede zpátky, vstane a postaví se na něj."""
    sit = dict(hip=(15.6, 50.4), lean=-16.0, tl=10.4, ff=(27.0, GROUND - 1.0, -10.0), fb=(24.6, GROUND, 0.0),
               kf=(0.2, -1.0), kn=(0.2, -1.0), hn=(-4.4, 6.6), hf=(-3.0, 7.0), en=(1.0, 0.0), ef=(1.0, 0.0),
               legs_front=True, eyes="x", mouth="o")

    def st(i):
        return [("stars", i, 20, 33)]
    return [
        P(),
        P(RIDE, hip=(25.2, 30.2), spin=2, wind=1.0, fx=[("speed", 0)]),
        P(RIDE, bx=BOARD_X + 7, spin=5, hip=(23.0, 30.0), lean=-16.0, ff=(29.4, 43.0, -24.0), fb=(21.0, 45.0, -14.0),
          kf=(0.4, -1.0), kn=(0.4, -1.0), hn=(8.6, -4.6), hf=(9.0, -1.4), en=(0.0, 1.0), ef=(0.0, 1.0),
          eyes="wide", mouth="o", fx=[("sweat", 33, 10)]),
        P(RIDE, bx=BOARD_X + 15, spin=0, hip=(19.0, 39.4), lean=-38.0, tl=10.4, ff=(30.4, 37.0, -44.0),
          fb=(26.6, 40.6, -34.0), kf=(0.2, -1.0), kn=(0.2, -1.0), hn=(8.4, -1.0), hf=(7.0, 2.6), en=(0.0, 1.0),
          ef=(0.0, 1.0), legs_front=True, eyes="x", mouth="o", wind=0.0),
        P(sit, hip=(15.6, 51.4), tl=9.8, bx=BOARD_X + 19, spin=3, fx=[("dust", 14, GY, 0), ("dust", 28, GY, 0), *st(0)]),
        P(sit, bx=BOARD_X + 21, spin=5, fx=[("dust", 14, GY, 1), *st(1)]),
        P(sit, head=(0.0, 1.0), bx=BOARD_X + 21, fx=[("dust", 14, GY, 2), *st(2), ("sweat", 30, 30)]),
        P(sit, eyes="squeeze", bx=BOARD_X + 21, fx=[*st(3), ("sweat", 30, 32)]),
        P(sit, eyes="squeeze", head=(0.0, 1.0), bx=BOARD_X + 18, spin=7, fx=[*st(4), ("clack", 45, 46)]),
        P(sit, eyes="open", mouth="flat", hn=(5.0, 2.4), bx=BOARD_X + 12, spin=4, fx=[*st(5)]),
        P(hip=(18.8, 43.0), lean=32.0, tl=10.2, ff=(28.0, GROUND, 0.0), fb=(15.4, GROUND, 24.0), kf=(1.0, -0.4),
          kn=(1.0, -0.4), hn=(5.4, 6.0), hf=(6.2, 6.2), bx=BOARD_X + 6, spin=1, eyes="squeeze", mouth="flat"),
        P(hip=(19.6, 36.4), lean=12.0, ff=(FRONT - 0.6, 50.0, -12.0), fb=(12.6, GROUND, 0.0), bx=BOARD_X + 2, spin=6,
          hn=(2.4, 9.0), eyes="open", mouth="flat"),
        P(mouth="flat"),
        P(),
    ]


def _sleep():
    """Sedí na prknu, kolena nahoře, ruce na kolenou, hlava skloněná na kolena, oddechuje, Zzz."""
    out = []
    for i in range(4):
        b = (0.0, 0.5, 1.0, 0.5)[i]
        out.append(P(hip=(21.6, 45.2), lean=22.0 + b * 2, tl=9.8 - b * 0.4, ff=(31.0, GROUND, 0.0),
                     fb=(29.4, GROUND, 0.0), kf=(0.6, -1.0), kn=(0.6, -1.0), legs_front=True,
                     hn=(6.8, 5.2 + b * 0.4), hf=(7.4, 4.8 + b * 0.4), en=(0.0, 1.0), ef=(0.0, 1.0),
                     head=(1.0, 1.0 + round(b * 0.6)), eyes="closed", mouth="o" if i >= 2 else "line",
                     hair_extra=-0.25, fx=[("zzz", i)]))
    return out


ANIMS = {   # tag → (fps, pózy, jednorázová, smyčka pro sekundární pohyb)
    "idle": (4, _idle(), False),
    "listen": (8, _listen(), True),
    "think": (6, _think(), False),
    "work_edit": (8, _carve(), False),
    "work_bash": (8, _push(), False),
    "work_search": (8, _manual(), False),
    "ride": (8, _push(fx=False, glide=1), False),
    "wave": (6, _wave(), False),
    "kickflip": (7, _kickflip(), True),
    "bail": (7, _bail(), True),
    "sleep": (2, _sleep(), False),
}

ACTIVITY = {"idle": "idle", "listening": "listen", "thinking": "think", "waiting": "wave",
            "success": "kickflip", "error": "bail", "sleeping": "sleep", "gone": "sleep", "walking": "ride"}
WORKING = {"Bash": "work_bash", "Edit": "work_edit", "Write": "work_edit", "NotebookEdit": "work_edit",
           "Read": "work_search", "Grep": "work_search", "Glob": "work_search", "WebSearch": "work_search",
           "WebFetch": "work_search", "ToolSearch": "work_search", "default": "work_edit"}


# --- vrstvy a zápis -------------------------------------------------------------------------

def _drone(k, phase):
    """Ujeté kolečko z prkna: žluté s nábojem, značka se otáčí a za ním je čárka pohybu."""
    g = Canvas()
    cx, cy = 5 + (k % 2) * 3, 22 + k * 7 + (phase + k) % 2
    g.part(_cells(lambda x, y: (x - cx - 0.5) ** 2 + (y - cy - 0.5) ** 2 <= 5.2, (cx - 3, cy - 3, cx + 3, cy + 3)),
           lambda *_: YELLOW)
    g.put(cx, cy, SILVER)
    dx, dy = ((-1, -1), (1, 1), (1, -1), (-1, 1))[(phase + k) % 2 + (k % 2) * 2]
    g.put(cx + dx, cy + dy, HAIR_D)
    for x in range(cx - 6 + phase, cx - 3):
        g.put(x, cy + 1 - (k % 2), SILVER)
    return g.px


def layers():
    body, fx, tags, keys = [], [], [], {"eyes": [], "mouth": [], "head": []}
    keep = {"eyes": {}, "mouth": {}}
    for anim, (fps, poses, oneshot) in ANIMS.items():
        tags.append((anim, len(poses), fps, oneshot))
        for i, (p, hair, flut) in enumerate(secondary(poses, not oneshot)):
            f = len(body)
            b, e, (ix, iy) = draw(p, hair, flut)
            body.append(b)
            fx.append(e)
            for s, key in (("eyes", (ix + EYES_OFF[0], iy + EYES_OFF[1], *EYES_SIZE)),
                           ("mouth", (ix + MOUTH_OFF[0], iy + MOUTH_OFF[1], *MOUTH_SIZE)),
                           ("head", (ix - 10, iy - 7, 13, 11))):
                if not keys[s] or keys[s][-1][1:] != key:
                    keys[s].append((f, *key))
            if p["eyes"] in LOCKED_EYES or anim == "sleep":
                keep["eyes"].setdefault(anim, []).append(i)
            if p["mouth"] != "line" or anim == "sleep":
                keep["mouth"].setdefault(anim, []).append(i)

    ref = draw(NEUTRAL)[2]
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
            g.px = bytearray([NONE]) * (32 * 32)
            sprites._pop(g, name, phase)
            out = Canvas()
            for n, v in enumerate(g.px):
                if v != NONE:
                    out.put(n % 32 + POP_AT[0], n // 32 + POP_AT[1], POP_COLORS[v])
            emote.append(out.px)
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
    lines = ["# Vygenerováno: python3 -I tools/skejtak2.py (kresba kódem). Formát popisuje docs/skiny.md.",
             "# Vlastní dílo projektu Pixel Familiars, CC BY 4.0 (viz CREDITS.txt).", "",
             "[skin]", 'name = "Skejťák v0.2"', f"size = [{W}, {H}]", f"anchor = [{W // 2}, {GY}]",
             'facing = "right"', 'author = "Pixel Familiars"', 'license = "CC-BY-4.0"', "",
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


CREDITS = """Skejťák v0.2 – skin pro Pixel Familiars

Grafika: vlastní dílo projektu Pixel Familiars, kreslené kódem (tools/skejtak2.py).
Licence: Creative Commons Uveďte původ 4.0 Mezinárodní (CC BY 4.0)
         https://creativecommons.org/licenses/by/4.0/ (plné znění v LICENSES/CC-BY-4.0.txt)
Uveďte: Pixel Familiars (Pavel Švec), https://github.com/pauliquib/familiar

Reakce nad hlavou jsou Robo-kunovy (familiar/sprites.py) přebarvené do palety skinu,
drony subagentů jsou malá skate prkýnka. Skin znovu vygeneruje: python3 -I tools/skejtak2.py
"""


def export(dest):
    os.makedirs(os.path.join(dest, "pal"), exist_ok=True)
    out, keep = layers()
    for layer, (frames, tags, overlay, slices) in out.items():
        skin_export.write_sheet(dest, layer, frames, tags, PALETTES["base"], overlay, slices, size=(W, H))
    for k, colors in PALETTES.items():
        skin_export.write_gpl(os.path.join(dest, "pal", f"{k}.gpl"), k, colors)
    with open(os.path.join(dest, "skin.toml"), "w", encoding="utf-8") as f:
        f.write(skin_toml(keep))
    with open(os.path.join(dest, "CREDITS.txt"), "w", encoding="utf-8") as f:
        f.write(CREDITS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="skin Skejťák v0.2 kreslený kódem")
    ap.add_argument("dest", nargs="?", default=os.path.join(REPO, "familiar", "skins", "skejtak2"))
    args = ap.parse_args(argv)
    export(args.dest)
    print(f"skin skejtak2 zapsán do {args.dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
