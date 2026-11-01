# Robo-kun kreslený kódem: dočasný skin, než vzniknou sprity v Aseprite.
#
# Snímek je mřížka 32×32 indexů do palety (0 = průhledná), viz kapitola 5.
# Každá animace je seznam parametrů póz; draw() z nich složí snímek.
W = H = 32

PALETTE = [
    None,        # 0 průhledná
    "#1b1b2f",   # 1 obrys
    "#5fa8d3",   # 2 tělo
    "#3d7ea6",   # 3 stín
    "#a9d6f0",   # 4 světlo
    "#14213d",   # 5 obrazovka
    "#7cf5ff",   # 6 oči
    "#3a8f99",   # 7 tlumené oči
    "#f1f1f1",   # 8 bílá
    "#ffd166",   # 9 žlutá
    "#ef476f",   # 10 červená
    "#06d6a0",   # 11 zelená
    "#f8961e",   # 12 oranžová
    "#8d99ae",   # 13 šedá
    "#a0663c",   # 14 hnědá
    "#c77dff",   # 15 fialová
]

# nálada přes výměnu palety (kapitola 5): mění se jen barvy těla 2, 3, 4
PALETTES = {
    "base": PALETTE,
    "warm": PALETTE[:2] + ["#5cc8a8", "#38917a", "#b8f0dc"] + PALETTE[5:],
    "cold": PALETTE[:2] + ["#4a6fa5", "#2f4a73", "#8aa6cf"] + PALETTE[5:],
    "faded": PALETTE[:2] + ["#8fa3b3", "#6b7d8c", "#c4d0da"] + PALETTE[5:],
}


class Grid:
    def __init__(self):
        self.px = bytearray(W * H)

    def put(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.px[y * W + x] = c

    def rect(self, x, y, w, h, c):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, c)

    def box(self, x, y, w, h, fill, edge=1, round_=True):
        """Obdélník s obrysem a volitelně zakulacenými rohy."""
        self.rect(x, y, w, h, edge)
        self.rect(x + 1, y + 1, w - 2, h - 2, fill)
        if round_:
            for cx, cy in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
                self.put(cx, cy, 0)

    def blit(self, rows, x, y, colors):
        """Malý obrázek z textu: znak → barva podle colors, mezera = nic."""
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch in colors:
                    self.put(x + dx, y + dy, colors[ch])


# --- části těla -----------------------------------------------------------

def _legs(g, dy, sit, step=0):
    if sit:      # sedí: nohy natažené dopředu
        g.rect(10, 29, 5, 2, 1)
        g.rect(17, 29, 5, 2, 1)
        return
    # chůze: step 1 zvedne levou nohu (a posune ji dopředu, doprava), -1 pravou
    ly, ry = dy - (step == 1), dy - (step == -1)
    lx, rx = (step == 1), (step == -1)
    g.rect(12 + lx, 27 + ly, 2, 3, 13)
    g.rect(18 + rx, 27 + ry, 2, 3, 13)
    g.rect(11 + lx, 30 + ly, 4, 2, 1)
    g.rect(17 + rx, 30 + ry, 4, 2, 1)


def _body(g, dy):
    g.box(10, 18 + dy, 12, 10, 2)
    g.rect(20, 19 + dy, 1, 8, 3)                 # stín vpravo
    g.box(13, 20 + dy, 6, 4, 4, round_=False)    # panel na hrudi
    g.put(15, 21 + dy, 11)


ARM = {   # póza → (body ruky relativně k rameni, poloha dlaně)
    "down":  ([(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)], (0, 6)),
    "up":    ([(0, 0), (1, -1), (2, -2), (2, -3), (2, -4), (2, -5), (2, -6)], (2, -8)),
    "up2":   ([(0, 0), (1, -1), (2, -2), (3, -3), (3, -4), (4, -5), (4, -6)], (4, -8)),
    "chin":  ([(0, 0), (0, -1), (-1, -2)], (-2, -3)),
    "front": ([(0, 0), (0, 1), (0, 2), (-1, 3), (-2, 4)], (-3, 5)),
    "front2": ([(0, 0), (0, 1), (0, 2), (-1, 3), (-2, 3)], (-3, 4)),
    "side":  ([(0, 0), (1, 0), (2, -1), (3, -2)], (4, -3)),
    "flail": ([(0, 0), (1, -1), (2, -2), (3, -2)], (4, -3)),
}


def _arm(g, side, pose, dy):
    pts, hand = ARM[pose]
    sx = 8 if side == "L" else 22
    mirror = -1 if side == "L" else 1
    for px, py in pts:
        g.rect(sx + px * mirror, 19 + dy + py, 2, 1, 2)
        g.put(sx + px * mirror + (1 if side == "R" else 0), 19 + dy + py, 3)
    hx, hy = hand
    g.rect(sx + hx * mirror, 19 + dy + hy, 2, 2, 13)


EYES = {   # tvar očí (nebo dvojice levé, pravé) a svislý posun; pravé oko je o 6 px vpravo
    "open":   (["xx", "xx", "xx"], 0),
    "wide":   (["xxx", "xxx", "xxx"], -1),
    "closed": (["  ", "  ", "xx"], 0),
    "up":     (["xx", "xx", "  "], -1),
    "happy":  ([" x ", "x x"], 0),
    "x":      (["x x", " x ", "x x"], 0),
    "side":   (["xx", "xx", "xx"], 0),
    "angry":  ((["x ", "xx", "xx"], [" x", "xx", "xx"]), 0),
    "droopy": (["  ", "xx", "xx"], 0),
    "dazed":  (["xxx", "x x", "xxx"], 0),
}


def _head(g, dx, dy, eyes, mouth, antenna, look=0):
    x, y = 8 + dx, 6 + dy
    if antenna is not None:                          # pod kloboukem schovaná
        g.rect(x + 8, y - 3, 1, 3, 13)
        g.box(x + 7, y - 5, 3, 3, antenna, round_=False)
    g.box(x, y, 16, 12, 2)
    g.rect(x + 2, y + 1, 12, 1, 4)                   # odlesk
    g.box(x + 2, y + 2, 12, 8, 5, edge=5)
    shape, oy = EYES[eyes]
    shapes = shape if isinstance(shape, tuple) else (shape, shape)
    col = 7 if eyes in ("closed", "droopy") else 6
    for ex, sh in zip((x + 4, x + 10), shapes):
        g.blit(sh, ex + look, y + 4 + oy, {"x": col})
    my = y + 8
    if mouth == "smile":
        g.blit(["x  x", " xx "], x + 6, my - 1, {"x": 6})
    elif mouth == "o":
        g.blit(["xx", "xx"], x + 7, my - 1, {"x": 7})
    elif mouth == "frown":
        g.blit([" xx ", "x  x"], x + 6, my - 1, {"x": 7})
    elif mouth == "wave":
        g.blit([" x x", "x x "], x + 6, my - 1, {"x": 7})
    else:
        g.rect(x + 7, my, 2, 1, 7)


# --- doplňky a emoty ------------------------------------------------------

def _keyboard(g, phase):
    g.box(7, 25, 18, 4, 13, round_=False)
    for kx in range(9, 23, 2):
        g.put(kx, 26, 1)
    g.put(9 + (phase * 4) % 14, 27, 11)              # svítící klávesa


def _paper(g, phase):
    g.box(23, 21, 8, 10, 8, edge=13, round_=False)
    for line in range(min(phase, 4)):
        g.rect(25, 23 + line * 2, 4 if line % 2 else 5, 1, 13)
    tip_x, tip_y = 25 + (phase % 3) * 2, 23 + min(phase, 3) * 2
    g.rect(tip_x + 1, tip_y - 4, 1, 4, 9)            # tužka
    g.put(tip_x, tip_y, 10)


def _magnifier(g, dx):
    x = 24 + dx
    g.blit([" xxx ", "x...x", "x...x", "x...x", " xxx "], x, 4, {"x": 1, ".": 4})
    g.rect(x + 2, 9, 1, 2, 12)       # rukojeť do dlaně


def _dots(g, n):
    for i in range(n):
        g.rect(23 + i * 3, 2, 2, 2, 8)


def _bang(g, col):
    g.rect(27, 0, 2, 5, col)
    g.rect(27, 6, 2, 2, col)


def _sweat(g, dy):
    g.blit([" x ", "xxx", "xxx", " x "], 24, 4 + dy, {"x": 6})


Z_SMALL = ["xxxx", "  x ", " x  ", "xxxx"]
Z_BIG = ["xxxxx", "   x ", "  x  ", " x   ", "xxxxx"]


def _zzz(g, n):
    g.blit(Z_SMALL, 22, 8, {"x": 8})
    if n > 1:
        g.blit(Z_BIG, 26, 1, {"x": 8})


def _sparkle(g, x, y, c):
    g.put(x, y - 1, c); g.put(x - 1, y, c); g.put(x, y, 8); g.put(x + 1, y, c); g.put(x, y + 1, c)


# --- téma: pokrývka hlavy (x, y = levý horní roh hlavy) ---------------------

def _hardhat(g, x, y, lamp):
    g.blit(["     oooooo     ",
            "   ooyyLLyyoo   ",
            "  oyywyyyyyyyo  ",
            "  oyyyyyyyyyyo  ",
            "obbbbbbbbbbbbbbo"], x, y - 5, {"o": 1, "y": 9, "w": 8, "b": 12, "L": lamp})


def _headphones(g, x, y, _):
    g.rect(x + 2, y - 3, 12, 1, 13)
    for px, py in ((1, -2), (0, -1), (-1, 0), (-1, 1), (-1, 2)):
        g.put(x + px, y + py, 13)
        g.put(x + 15 - px, y + py, 13)
    g.box(x - 2, y + 3, 4, 6, 10)
    g.box(x + 14, y + 3, 4, 6, 10)


def _beret(g, x, y, _):
    g.blit(["          o    ",
            "     oooooooo  ",
            "   oopppppppppo",
            "  oppppwpppppppo",
            "  opppppppppppo "], x, y - 4, {"o": 1, "p": 15, "w": 8})


def _mortarboard(g, x, y, _):
    g.rect(x + 4, y - 5, 8, 1, 1)
    g.rect(x + 1, y - 4, 14, 1, 1)
    g.box(x + 4, y - 3, 8, 4, 5, round_=False)
    g.rect(x + 13, y - 4, 1, 6, 9)                   # střapec
    g.rect(x + 12, y + 2, 3, 2, 9)


def _explorer(g, x, y, _):
    g.blit(["       oooooo       ",
            "      obbbbbbo      ",
            "      obbwbbbo      ",
            "      oddddddo      ",
            "obbbbbbbbbbbbbbbbbbo"], x - 2, y - 5, {"o": 1, "b": 14, "w": 12, "d": 1})


def _cap(g, x, y, _):
    g.blit(["    oooooooo      ",
            "   occccwccco     ",
            "  occcccccccccooooo"], x, y - 3, {"o": 1, "c": 12, "w": 8})


# odemykatelné doplňky (progress.DOPLNKY): jen barvy mimo tělo (1, 8–15), ať sedí i Rubínovi

def _straw(g, x, y, _):
    g.blit(["      oooooooo      ",
            "     oyywydyyyo     ",
            "     oydyyyydyo     ",
            "     orrrrrrrro     ",
            "  oooyyydyyyyyyooo  ",
            " oyyyydyyyydyyyyyyo ",
            "  oooooooooooooooo  "], x - 2, y - 6, {"o": 1, "y": 9, "w": 8, "d": 12, "r": 10})


def _tophat(g, x, y, _):
    g.blit(["   oooooooooo   ",
            "   okhkkkkkko   ",
            "   okhkkkkkko   ",
            "   orrrrrrrro   ",
            " oooooooooooooo ",
            " okkkkkkkkkkkko "], x, y - 6, {"o": 1, "k": 5, "h": 13, "r": 10})


def _crown(g, x, y, _):
    g.blit(["  o    oo    o  ",
            " oyo  oyyo  oyo ",
            " oyyooywyyooyyo ",
            " oyyryyppyyryyo ",
            " oddddddddddddo "], x, y - 5, {"o": 1, "y": 9, "w": 8, "r": 10, "p": 15, "d": 12})


def _nightcap(g, x, y, _):
    g.blit(["     oooooo         ",
            "   oopppppoooo      ",
            "  opppwwwpppppoo    ",
            " opwwpppppwwwppppo  ",
            "owwwwwwwwwwwwwwoppo ",
            "owwwwwwwwwwwwwwo  w ",
            "                 www",
            "                  w "], x, y - 6, {"o": 1, "p": 15, "w": 8})


def _laurel(g, x, y, _):
    g.blit(["  o  o    o  o  ",
            " ogoogo  ogoogo ",
            "oggggggooggggggo",
            "og            go",
            "og            go",
            " o            o "], x, y - 3, {"o": 1, "g": 11})


HATS = {"hardhat": _hardhat, "headphones": _headphones, "beret": _beret,
        "mortarboard": _mortarboard, "explorer": _explorer, "cap": _cap,
        "straw": _straw, "tophat": _tophat, "crown": _crown, "nightcap": _nightcap, "laurel": _laurel}
HIDES_ANTENNA = {"hardhat", "beret", "mortarboard", "explorer", "straw", "tophat", "crown", "nightcap"}


# --- emoty vlevo nahoře: reakce na chat a změny nálady -------------------------

POPS = {
    "heart": ([" xx xx ", "xxxxxxx", "xxxxxxx", " xxxxx ", "  xxx  ", "   x   "], {"x": 10}),
    "check": (["      x", "     xx", "x   xx ", "xx xx  ", " xxx   ", "  x    "], {"x": 11}),
    "grawlix": ([" x x  r", "xxxxx r", " x x  r", "xxxxx r", " x x   ", "      r"], {"x": 10, "r": 9}),
    "coffee": ([" s  s  ", "  s  s ", "wwwww  ", "wcccwww", "wwwww w", "wwwwww ", " www   "],
               {"s": 13, "w": 8, "c": 14}),
    "camera": (["  oo   ", "ooooooo", "oo...yo", "o.o.o.o", "oo...oo", "ooooooo"],
               {"o": 13, ".": 1, "y": 9}),
    "question": ([" xxx ", "x   x", "   x ", "  x  ", "     ", "  x  "], {"x": 9}),
    "storm": ([" ooo   ", "ooooo  ", "ooooooo", "  y    ", " yy    ", "  y    ", " y     "],
              {"o": 13, "y": 9}),
    "spiral": (["xxxxxxx", "      x", " xxxx x", " x  x x", " x xx x", " x    x", " xxxxxx"], {"x": 15}),
    "flower": (["  ppp  ", " ppppp ", "pppyppp", " ppppp ", "  ppp  ", " g g g ", "  ggg  "],
               {"p": 10, "y": 9, "g": 11}),
    # odemykatelné (progress.DOPLNKY), jen barvy 1, 8–11, 13–15 (ty mají i převedené skiny)
    "star": (["   y   ", "  yyy  ", "yyywyyy", " yyyyy ", "  yyy  ", " yy yy ", " y   y "], {"y": 9, "w": 8}),
    "badge": (["  ggg  ", " ggggw ", "ggggwgg", "gwgwggg", "ggwgggg", " ggggg ", "  ggg  "], {"g": 11, "w": 8}),
    "swarm": (["    w   ", "w  yky  ", "yky     ", "      w ", "  w  yky", " yky    "], {"y": 9, "k": 1, "w": 8}),
}


def _pop(g, name, phase):
    rows, colors = POPS[name]
    g.blit(rows, 1, 2 - phase, colors)


def _drones(g, n, phase):
    """Subagenti: malí drony vlevo dole."""
    for k in range(min(n, 3)):
        y = 17 + k * 5 + (phase + k) % 2
        prop = " ppp " if (phase + k) % 2 else "p   p"
        g.blit([prop, "ooooo", "oeoeo", " ooo "], 1, y, {"p": 13, "o": 3, "e": 6})


# --- nálada: obličej, paleta, emote, tempo -----------------------------------

MOOD = {   # nálada → (oči, pusa, paleta, emote při změně, zpomalení)
    "klid":      (None, None, "base", None, 1.0),
    "radost":    (None, "smile", "warm", "heart", 1.0),
    "zvedavost": ("wide", "o", "base", "question", 1.0),
    "frustrace": ("angry", "frown", "cold", "storm", 1.0),
    "zmatek":    ("dazed", "wave", "base", "spiral", 1.0),
    "unava":     ("droopy", None, "faded", None, 0.6),
}
KEEP_EYES = {"closed", "x", "happy", "wide"}      # oči, které určuje činnost


def draw(p, look=None):
    """Složí snímek z parametrů póz a vzhledu (nálada, téma, emote, drony)."""
    mood, hat, pop, pop_phase, drones, drone_phase = look or ("klid", None, None, 0, 0, 0)
    eyes, mouth, *_ = MOOD.get(mood, MOOD["klid"])
    p = dict(p)
    if eyes and p.get("eyes", "open") not in KEEP_EYES:
        p["eyes"] = eyes
    if mouth and p.get("mouth", "line") == "line":
        p["mouth"] = mouth
    g = Grid()
    dy = p.get("dy", 0)
    sit = p.get("sit", False)
    bdy = dy + (2 if sit else 0)
    _legs(g, dy, sit, p.get("step", 0))
    _body(g, bdy)
    _arm(g, "L", p.get("left", "down"), bdy)
    _arm(g, "R", p.get("right", "down"), bdy)
    antenna = p.get("antenna", 10)
    hx, hy = p.get("hdx", 0), bdy + p.get("hdy", 0)
    _head(g, hx, hy, p.get("eyes", "open"), p.get("mouth", "line"),
          None if hat in HIDES_ANTENNA else antenna, p.get("look", 0))
    if hat:
        HATS[hat](g, 8 + hx, 6 + hy, antenna)
    for name, *args in p.get("fx", []):
        FX[name](g, *args)
    if drones:
        _drones(g, drones, drone_phase)
    if pop:
        _pop(g, pop, pop_phase)
    return g.px


FX = {"keyboard": _keyboard, "paper": _paper, "magnifier": _magnifier, "dots": _dots,
      "bang": _bang, "sweat": _sweat, "zzz": _zzz, "sparkle": _sparkle}


# --- animace (kapitola 5: snímky, fps, smyčka/jednorázová) -----------------

def _idle():
    frames = []
    for i in range(20):                  # 5 s: dýchání, jednou mrkne
        frames.append({"hdy": 1 if i % 4 in (2, 3) else 0,
                       "eyes": "closed" if i == 13 else "open"})
    return frames


ANIMS = {
    "idle": (4, _idle()),
    "listen": (8, [{"eyes": "wide", "antenna": 9, "hdy": h, "mouth": "o"} for h in (0, 1, 1, 0)]),
    "think": (6, [{"right": "chin", "eyes": "up", "look": 1, "antenna": 9 if i % 2 else 12,
                   "fx": [("dots", i // 2 + 1)]} for i in range(6)]),
    "work_bash": (8, [{"left": "front" if i % 2 else "front2", "right": "front2" if i % 2 else "front",
                       "eyes": "open", "look": 0, "hdy": 1, "fx": [("keyboard", i)]} for i in range(6)]),
    "work_edit": (8, [{"right": "side", "look": 1, "mouth": "line", "fx": [("paper", i % 5)]}
                      for i in range(6)]),
    "work_search": (8, [{"right": "up2", "look": 1 + (i % 3 == 1), "eyes": "side",
                         "fx": [("magnifier", (0, 1, 2, 1, 0, -1)[i])]} for i in range(6)]),
    "wave": (6, [{"right": "up" if i % 2 else "up2", "eyes": "wide", "mouth": "o",
                  "fx": [("bang", 9 if i % 2 else 10)]} for i in range(4)]),
    "hop": (8, [{"dy": d, "left": "up" if d else "down", "right": "up" if d else "down",
                 "eyes": "happy", "mouth": "smile",
                 "fx": [("sparkle", 25, 6, 9), ("sparkle", 5, 9, 11)] if d <= -3 else []}
                for d in (0, -2, -4, -4, -2, 0)]),
    "stumble": (8, [{"hdx": x, "left": "flail" if i % 2 else "down", "right": "down" if i % 2 else "flail",
                     "eyes": "x", "mouth": "wave", "fx": [("sweat", i // 2)]}
                    for i, x in enumerate((0, 1, 2, 2, 1, 0))]),
    # procházka (pohyb.py): kráčí doprava, zrcadlí se podle směru (skin.facing)
    "walk": (8, [{"step": st, "hdy": h, "eyes": "side", "look": 1,
                  "left": "front2" if st == 1 else "down", "right": "front2" if st == -1 else "down"}
                 for st, h in ((1, 0), (0, 1), (-1, 0), (0, 1))]),
    "sleep": (2, [{"sit": True, "eyes": "closed", "antenna": 13, "hdy": i % 2,
                   "fx": [("zzz", 1 + i // 2)]} for i in range(4)]),
}

ONESHOT = {"listen", "hop", "stumble"}

TOOL_ANIM = {
    "Bash": "work_bash",
    "Edit": "work_edit", "Write": "work_edit", "NotebookEdit": "work_edit",
    "Read": "work_search", "Grep": "work_search", "Glob": "work_search",
    "WebSearch": "work_search", "WebFetch": "work_search", "ToolSearch": "work_search",
}

STATE_ANIM = {"idle": "idle", "listening": "listen", "thinking": "think", "waiting": "wave",
              "success": "hop", "error": "stumble", "sleeping": "sleep", "gone": "sleep",
              "walking": "walk"}    # walking není stav automatu, jen procházka (pohyb.py)
FACING = "right"    # kam kouká animace walk (skin.facing)


def anim_for(state, tool=None):
    if state == "working":
        return TOOL_ANIM.get(tool, "work_bash")
    return STATE_ANIM[state]


_cache = {}


def frame(anim, i, look=None):
    key = (anim, i, look)
    if key not in _cache:
        if len(_cache) > 4000:
            _cache.clear()
        _cache[key] = draw(ANIMS[anim][1][i], look)
    return _cache[key]


def palette(mood):
    return PALETTES[MOOD.get(mood, MOOD["klid"])[2]]


def frame_at(anim, t, speed=1.0):
    """Index snímku v čase t od začátku animace; jednorázové zůstanou na posledním."""
    fps, poses = ANIMS[anim]
    i = int(t * fps * speed)
    return min(i, len(poses) - 1) if anim in ONESHOT else i % len(poses)
