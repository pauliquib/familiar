# Import vlastního skinu z Aseprite (formát skinu v docs/skiny.md, oddíl „Import z Aseprite“).
#
#   familiar skin-import postava.aseprite [--id muj] [--mapa mapa.toml] [--nahled nahled.png] [--prepsat]
#
# Vstup: export „Export Sprite Sheet“ (PNG + JSON, hash i array) nebo přímo .aseprite/.ase,
# který čte čistý Python podle docs/ase-file-specs.md z repozitáře Aseprite (RGBA, šedá
# i indexované snímky, viditelné vrstvy sloučené režimem Normal, tagy, cely raw/zlib/linked).
# Tagy se podle jmen přiřadí stavům familiara (ALIASES, česky i anglicky) nebo podle mapy;
# chybějící stavy se odvodí z idle.
# Postava se ořízne na obsah, celočíselně zvětší/zmenší do plátna 32×32 a posadí na spodní
# hranu. Z barev (nejvýš 15) vznikne paleta base a z ní palety nálad warm/cold/faded;
# reakce a drony jsou Robo-kunovy přebarvené do palety. Bez Qt.
import colorsys, json, os, re, shutil, struct, tempfile, tomllib, unicodedata, zlib
from collections import namedtuple

from familiar import paths, skin, skin_export, sprites

W, H = skin.W, skin.H
SkinError = skin.SkinError
Source = namedtuple("Source", "w h frames durations tags")      # frames: bytearray RGBA w×h
SrcTag = namedtuple("SrcTag", "name a b direction repeat")
Out = namedtuple("Out", "name frames fps oneshot fx")           # frames: obrázky 32×32, fx: fn(i) nebo None

STATES = ("idle", "listening", "thinking", "working", "waiting", "success", "error", "sleeping", "gone")
ALIASES = {     # první slovo jména tagu (malá písmena, bez diakritiky) → stav
    "idle": "idle stand standing neutral default base breath breathe klid stoji stani necinnost nic",
    "listening": "listen listening hear alert notice posloucha poslouchani poslech slysi",
    "thinking": "think thinking ponder hmm mysli premysli premysleni",
    "working": "work working tool tools run running walk walking type typing attack prace pracuje "
               "nastroj nastroje beh bezi chuze",
    "waiting": "wave waving wait waiting ask attention mava mavani ceka cekani povoleni otazka",
    "success": "success hop jump happy win victory celebrate done hotovo uspech radost skok vyskok hura",
    "error": "error trip stumble hit hurt damage fail chyba zakopnuti zakopne au bolest zasah pad",
    "sleeping": "sleep sleeping rest zzz spi spanek spat odpocinek",
    "gone": "gone leave exit bye odchod odesel pryc",
}
ALIASES = {st: set(v.split()) for st, v in ALIASES.items()}
TOOL_KINDS = {  # druh nástroje (jako work_bash/work_edit/work_search Robo-kuna) → slova v tagu
    "work_bash": {"bash", "shell", "terminal", "prikaz"},
    "work_edit": {"edit", "write", "psani", "pise", "uprava", "zapis"},
    "work_search": {"search", "read", "grep", "find", "hledani", "hleda", "cteni", "cte"},
}
ONESHOT_STATES = ("listening", "success", "error")      # jednorázové, pokud mapa neřekne jinak
WHITE, YELLOW = sprites.PALETTE[8], sprites.PALETTE[9]   # barvy efektů „…“, „!“, Zzz
TINTS = {"warm": ((255, 160, 64), 0.18), "cold": ((58, 95, 176), 0.28)}   # paleta → (odstín, podíl)


# --- čtení zdroje --------------------------------------------------------------

def load_source(path):
    """(Source, varování) podle přípony souboru."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".aseprite", ".ase"):
        return read_aseprite(path)
    if ext == ".json":
        return read_sheet(path), []
    if ext == ".png":
        js = os.path.splitext(path)[0] + ".json"
        if not os.path.isfile(js):
            raise SkinError(f"{path}: chybí {os.path.basename(js)}; v Aseprite exportuj sheet i s daty "
                            f"(Export Sprite Sheet → Output → JSON Data, s Tags)")
        return read_sheet(js, path), []
    raise SkinError(f"{path}: čekám .json, .png, .aseprite nebo .ase")


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise SkinError(f"{path}: nelze přečíst ({e.strerror})")


def read_sheet(js, png=None):
    """Export Sprite Sheet z Aseprite: JSON (hash i array) + PNG → Source."""
    try:
        doc = json.loads(_read(js).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise SkinError(f"{js}: neplatný JSON ({e})")
    if not isinstance(doc, dict):
        raise SkinError(f"{js}: čekám objekt s 'frames' a 'meta'")
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    if png is None:
        img = meta.get("image")
        cands = [os.path.join(os.path.dirname(js), os.path.basename(img))] if isinstance(img, str) and img else []
        cands.append(os.path.splitext(js)[0] + ".png")
        png = next((p for p in cands if os.path.isfile(p)), None)
        if png is None:
            raise SkinError(f"{js}: nenašel jsem obrázek sheetu ({', '.join(cands)})")
    frames = doc.get("frames")
    if isinstance(frames, dict):        # json-hash: pořadí klíčů = pořadí snímků
        frames = list(frames.values())
    if not isinstance(frames, list) or not frames or not all(isinstance(f, dict) for f in frames):
        raise SkinError(f"{js}: chybí seznam 'frames'")
    layers = [str(l.get("name")) for l in meta.get("layers") or [] if isinstance(l, dict)]
    if len(layers) > 1 and any(f"({n})" in str(fr.get("filename", "")) for fr in frames for n in layers):
        raise SkinError(f"{js}: export s --split-layers (snímek za každou vrstvu) neumím; exportuj vrstvy sloučené")
    sw, sh, rgba = skin.read_png(png)
    rects = []
    for n, fr in enumerate(frames):
        try:
            r, src = fr["frame"], fr.get("spriteSourceSize") or {"x": 0, "y": 0}
            size = fr.get("sourceSize") or {"w": r["w"], "h": r["h"]}
            rects.append(([int(r[k]) for k in "xywh"], int(src["x"]), int(src["y"]),
                          int(size["w"]), int(size["h"]), int(fr.get("duration", 100))))
        except (KeyError, TypeError, ValueError):
            raise SkinError(f"{js}: snímek {n} nemá platné 'frame'/'sourceSize'")
        if fr.get("rotated"):
            raise SkinError(f"{js}: snímek {n} je otočený; exportuj bez rotace")
    cw, ch = max(r[3] for r in rects), max(r[4] for r in rects)
    out, durations = [], []
    for n, ((rx, ry, rw, rh), ox, oy, _, _, dur) in enumerate(rects):
        if rx < 0 or ry < 0 or rx + rw > sw or ry + rh > sh:
            raise SkinError(f"{js}: snímek {n} leží mimo {os.path.basename(png)} ({sw}×{sh})")
        canvas = bytearray(cw * ch * 4)
        for yy in range(rh):
            ty = oy + yy
            x0, x1 = max(0, ox), min(cw, ox + rw)
            if 0 <= ty < ch and x0 < x1:
                s = ((ry + yy) * sw + rx + x0 - ox) * 4
                canvas[(ty * cw + x0) * 4:(ty * cw + x1) * 4] = rgba[s:s + (x1 - x0) * 4]
        out.append(canvas)
        durations.append(dur)
    tags = []
    for t in meta.get("frameTags") or []:
        try:
            tags.append(SrcTag(str(t["name"]), int(t["from"]), int(t["to"]), str(t.get("direction", "forward")),
                               int(t.get("repeat") or 0)))
        except (KeyError, TypeError, ValueError):
            raise SkinError(f"{js}: tag bez 'name'/'from'/'to'")
    return Source(cw, ch, out, durations, tags)


DIRECTIONS = ("forward", "reverse", "pingpong", "pingpong_reverse")


def read_aseprite(path):
    """Soubor .aseprite/.ase → Source; snímky = sloučené viditelné vrstvy (režim Normal)."""
    data = _read(path)
    if len(data) < 128 or struct.unpack_from("<H", data, 4)[0] != 0xA5E0:
        raise SkinError(f"{path}: není soubor Aseprite")
    nframes, w, h, depth = struct.unpack_from("<HHHH", data, 6)
    flags = struct.unpack_from("<I", data, 14)[0]
    trans = data[28]
    if depth not in (8, 16, 32) or not w or not h:
        raise SkinError(f"{path}: nepodporovaná barevná hloubka {depth} nebo prázdné plátno")
    bpp = depth // 8
    layers, cels, durations, tags, warnings = [], [], [], [], set()
    palette, new_palette = [(0, 0, 0, 255)] * 256, False

    def string(b, p):
        n = struct.unpack_from("<H", b, p)[0]
        return b[p + 2:p + 2 + n].decode("utf-8", "replace"), p + 2 + n

    pos = 128
    try:
        for f in range(nframes):
            size, magic, old_n, dur, new_n = struct.unpack_from("<IHHH2xI", data, pos)
            if magic != 0xF1FA:
                raise SkinError(f"{path}: snímek {f} má vadnou hlavičku")
            durations.append(dur)
            frame_cels, cp = {}, pos + 16
            for _ in range(new_n or old_n):
                csize, ctype = struct.unpack_from("<IH", data, cp)
                if csize < 6:
                    raise SkinError(f"{path}: vadný blok ve snímku {f}")
                b = data[cp + 6:cp + csize]
                cp += csize
                if ctype == 0x2004:        # vrstva
                    lflags, ltype, level, _, _, blend, opacity = struct.unpack_from("<HHHHHHB", b, 0)
                    layers.append((lflags, ltype, level, blend, opacity, string(b, 16)[0]))
                elif ctype == 0x2005:      # cel
                    li, x, y, op, kind, z = struct.unpack_from("<HhhBHh", b, 0)
                    if kind == 1:
                        frame_cels[li] = ("link", struct.unpack_from("<H", b, 16)[0], z)
                    elif kind in (0, 2):
                        cw, ch = struct.unpack_from("<HH", b, 16)
                        px = b[20:] if kind == 0 else zlib.decompress(b[20:])
                        if len(px) < cw * ch * bpp:
                            raise SkinError(f"{path}: cel ve snímku {f} má krátká data")
                        frame_cels[li] = (x, y, op, cw, ch, px, z)
                    else:
                        warnings.add("tilemapové vrstvy neumím, vynechány")
                elif ctype == 0x2018:      # tagy
                    p = 10
                    for _ in range(struct.unpack_from("<H", b, 0)[0]):
                        a, z2, d, rep = struct.unpack_from("<HHBH", b, p)
                        name, p = string(b, p + 17)
                        tags.append(SrcTag(name, a, z2, DIRECTIONS[d] if d < 4 else "forward", rep))
                elif ctype == 0x2019:      # nová paleta
                    n, first, last = struct.unpack_from("<III", b, 0)
                    palette, new_palette, p = palette + [(0, 0, 0, 255)] * max(0, n - 256), True, 20
                    for k in range(first, last + 1):
                        fl = struct.unpack_from("<H", b, p)[0]
                        if k < len(palette):
                            palette[k] = tuple(b[p + 2:p + 6])
                        p += 6
                        if fl & 1:
                            p = string(b, p)[1]
                elif ctype in (0x0004, 0x0011) and not new_palette:     # staré palety
                    mul = 1 if ctype == 0x0004 else 255 / 63
                    p, k = 2, 0
                    for _ in range(struct.unpack_from("<H", b, 0)[0]):
                        k += b[p]
                        n = b[p + 1] or 256
                        p += 2
                        for _ in range(n):
                            if k < 256:
                                palette[k] = tuple(min(255, round(v * mul)) for v in b[p:p + 3]) + (255,)
                            k, p = k + 1, p + 3
            cels.append(frame_cels)
            pos += size
    except (struct.error, IndexError, zlib.error) as e:
        raise SkinError(f"{path}: poškozený soubor Aseprite ({e})")

    # viditelnost včetně skupin: vrstva je vidět, jen když jsou vidět i všichni rodiče
    visible, parents = [], []
    for lflags, ltype, level, blend, opacity, name in layers:
        del parents[level:]
        vis = bool(lflags & 1) and not lflags & 64 and all(parents)    # 64 = referenční vrstva
        parents.append(vis)
        visible.append(vis and ltype == 0)
        if vis and ltype == 0 and blend:
            warnings.add(f"vrstva {name!r} má režim prolnutí {blend}, slučuji ji jako Normal")

    frames = []
    for f, frame_cels in enumerate(cels):
        canvas = bytearray(w * h * 4)
        order = []
        for li, c in frame_cels.items():
            z = c[-1]
            if c[0] == "link":
                c = cels[c[1]].get(li) if c[1] < len(cels) else None
                if not c or c[0] == "link":
                    continue
            if li < len(layers) and visible[li]:
                order.append((li + z, z, li, c))
        for _, _, li, (x, y, op, cw, ch, px, _) in sorted(order):
            lflags, _, _, _, lop, _ = layers[li]
            op = op * (lop if flags & 1 else 255) / 255
            bg = lflags & 8
            for yy in range(ch):
                ty = y + yy
                if not 0 <= ty < h:
                    continue
                for xx in range(cw):
                    tx = x + xx
                    if not 0 <= tx < w:
                        continue
                    k = (yy * cw + xx) * bpp
                    if bpp == 4:
                        r, g, bl, a = px[k:k + 4]
                    elif bpp == 2:
                        r = g = bl = px[k]
                        a = px[k + 1]
                    else:
                        i = px[k]
                        if i == trans and not bg:
                            continue
                        r, g, bl, a = palette[i] if i < len(palette) else (0, 0, 0, 0)
                    a = a * op / 255
                    if a <= 0:
                        continue
                    o = (ty * w + tx) * 4
                    da = canvas[o + 3] * (1 - a / 255)
                    oa = a + da
                    canvas[o:o + 4] = bytes((round((r * a + canvas[o] * da) / oa), round((g * a + canvas[o + 1] * da) / oa),
                                             round((bl * a + canvas[o + 2] * da) / oa), round(oa)))
        frames.append(canvas)
    if not frames:
        raise SkinError(f"{path}: soubor nemá žádný snímek")
    return Source(w, h, frames, durations, tags), sorted(warnings)


# --- úprava na plátno 32×32 ------------------------------------------------------

def normalize(src, scale=None):
    """Snímky jako seznamy W×H barev (r, g, b) nebo None; ořez na obsah, měřítko, spodní hrana.
    Vrací (snímky, varování)."""
    warn = []
    opaque = [[k for k in range(src.w * src.h) if fr[k * 4 + 3] >= 128] for fr in src.frames]
    pts = [k for ks in opaque for k in ks]
    if not pts:
        raise SkinError("všechny snímky jsou prázdné (průhledné)")
    xs, ys = {k % src.w for k in pts}, {k // src.w for k in pts}
    x0, y0, bw, bh = min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    if scale is None:
        if bw <= W and bh <= H:
            up, down = min(W // bw, H // bh), 1
        else:
            up, down = 1, max(-(-bw // W), -(-bh // H))
    elif scale >= 1:
        up, down = int(scale), 1
    else:
        up, down = 1, max(1, round(1 / scale))
    if down > 1:
        warn.append(f"postava má {bw}×{bh} px, zmenšuji {down}× (ztrátově; nejlepší je kreslit do {W}×{H})")
    elif up > 1:
        warn.append(f"postava má {bw}×{bh} px, zvětšuji {up}×")
    nw, nh = -(-bw * up // down), -(-bh * up // down)
    ox, oy = (W - nw) // 2, H - nh
    if nw > W or nh > H:
        warn.append(f"po změně měřítka má postava {nw}×{nh} px, ořezávám na {W}×{H} (horní okraj a boky)")
    out = []
    for fr in src.frames:
        img = [None] * (W * H)
        for Y in range(H):
            sy = Y - oy
            if not 0 <= sy < nh:
                continue
            for X in range(W):
                sx = X - ox
                if not 0 <= sx < nw:
                    continue
                if down == 1:
                    k = ((y0 + sy // up) * src.w + x0 + sx // up) * 4
                    if fr[k + 3] >= 128:
                        img[Y * W + X] = tuple(fr[k:k + 3])
                    continue
                count, total = {}, 0     # zmenšení: nejčastější barva bloku, je-li aspoň půl neprůhledné
                for by in range(y0 + sy * down, min(y0 + bh, y0 + (sy + 1) * down)):
                    for bx in range(x0 + sx * down, min(x0 + bw, x0 + (sx + 1) * down)):
                        k = (by * src.w + bx) * 4
                        total += 1
                        if fr[k + 3] >= 128:
                            c = tuple(fr[k:k + 3])
                            count[c] = count.get(c, 0) + 1
                if count and 2 * sum(count.values()) >= total:
                    img[Y * W + X] = max(count, key=count.get)
        out.append(img)
    return out, warn


# --- tagy a stavy ----------------------------------------------------------------

def norm_words(name):
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [re.sub(r"\d+$", "", w) for w in re.split(r"[^a-z0-9]+", s) if re.sub(r"\d+$", "", w)]


def guess_state(name):
    """(stav, druh nástroje nebo None) podle jména tagu, nebo (None, None)."""
    words = norm_words(name)
    kind = next((k for w in words for k, ws in TOOL_KINDS.items() if w in ws), None)
    for w in words:
        for st in STATES:
            if w in ALIASES[st]:
                return st, kind if st == "working" else None
    return ("working", kind) if kind else (None, None)


def state_key(key):
    """Klíč v [stavy] mapy: jméno stavu nebo kterékoli slovo z ALIASES (např. chyba)."""
    if key in STATES:
        return key
    st, _ = guess_state(key)
    if st is None:
        raise SkinError(f"mapa: neznámý stav {key!r} (stavy: {', '.join(STATES)})")
    return st


def read_mapa(path):
    if not path:
        return {}
    m = skin.read_toml(path)
    for k, t in (("stavy", dict), ("oneshot", list), ("name", str), ("nalady", bool)):
        if k in m and not isinstance(m[k], t):
            raise SkinError(f"{path}: {k} má špatný typ")
    if "meritko" in m and (not isinstance(m["meritko"], (int, float)) or m["meritko"] <= 0):
        raise SkinError(f"{path}: meritko musí být kladné číslo (2 = zvětšit 2×, 0.5 = zmenšit 2×)")
    return m


def build_tags(src, frames):
    """[(jméno ve zdroji, Out)] snímků v pořadí přehrávání; bez tagů jeden tag idle se vším."""
    raw = src.tags or [SrcTag("idle", 0, len(frames) - 1, "forward", 0)]
    out, used = [], set()
    for n, t in enumerate(raw):
        if not 0 <= t.a <= t.b < len(frames):
            raise SkinError(f"tag {t.name!r} odkazuje na snímky {t.a}–{t.b}, zdroj jich má {len(frames)}")
        seq = list(range(t.a, t.b + 1))
        if t.direction in ("reverse", "pingpong_reverse"):
            seq.reverse()
        if t.direction.startswith("pingpong"):
            seq += seq[-2:0:-1]
        ms = sum(src.durations[k] for k in seq) / len(seq)
        name = t.name.strip() or f"tag{n}"
        base, k = name, 2
        while name in used:
            name, k = f"{base}_{k}", k + 1
        used.add(name)
        out.append((t.name, Out(name, [frames[k] for k in seq], max(1, round(1000 / ms)) if ms > 0 else 8,
                                t.repeat == 1, None)))
    return out


def assign(tags, mapa):
    """{stav: jméno tagu} a {druh nástroje: jméno tagu} podle mapy a konvence jmen."""
    by_src = {}
    for src_name, o in tags:
        by_src.setdefault(src_name, o.name)
    names = {o.name for _, o in tags}

    def tag(v):
        if v in by_src:
            return by_src[v]
        if v in names:
            return v
        raise SkinError(f"mapa: tag {v!r} ve zdroji není (tagy: {', '.join(by_src)})")

    states, kinds, explicit = {}, {}, set()
    for key, v in (mapa.get("stavy") or {}).items():
        st = state_key(key)
        explicit.add(st)
        if isinstance(v, dict) and st == "working":
            for tool, t in v.items():
                states.setdefault("working", None)
                kinds["default" if tool == "default" else tool] = tag(t)
        elif isinstance(v, str):
            states[st] = tag(v)
        else:
            raise SkinError(f"mapa: [stavy] {key} musí být jméno tagu (working i tabulka nástroj → tag)")
    for src_name, o in tags:
        st, kind = guess_state(src_name)
        if st is None or st in explicit:
            continue
        if st == "working" and kind:
            kinds.setdefault(kind, o.name)
        else:
            states.setdefault(st, o.name)
    if "working" in states and states["working"] is None:
        states["working"] = kinds.get("default") or next(iter(kinds.values()))
    elif kinds and "working" not in states:
        states["working"] = kinds.get("work_bash") or next(iter(kinds.values()))
    return states, kinds


# --- odvozené animace ---------------------------------------------------------------

def shift(img, dx=0, dy=0):
    out = [None] * (W * H)
    for k, c in enumerate(img):
        x, y = k % W + dx, k // W + dy
        if c is not None and 0 <= x < W and 0 <= y < H:
            out[y * W + x] = c
    return out


def top(img):
    return next((k // W for k, c in enumerate(img) if c is not None), 0)


def up(img, dy):
    return shift(img, 0, -min(dy, top(img)))


def flip(img):
    return [img[(k // W) * W + W - 1 - k % W] for k in range(W * H)]


def dots(n):
    return [(22 + 3 * k + dx, 1 + dy, WHITE) for k in range(n) for dx in (0, 1) for dy in (0, 1)]


def glyph(rows, x0, y0, c=WHITE):
    return [(x0 + x, y0 + y, c) for y, r in enumerate(rows) for x, ch in enumerate(r) if ch != " "]


def zzz(i):
    pts = glyph(["xxx", "  x", " x ", "xxx"], 23, 2 - i % 2)
    return pts + (glyph(["xxxx", "   x", "  x ", " x  ", "xxxx"], 27, 0) if i % 2 == 0 else [])


def bang(i):
    return [] if i % 2 else glyph(["xx"] * 5 + ["  ", "xx"], 29, 0, YELLOW)


def derive(state, idle, used):
    """Out pro chybějící stav, odvozený z idle (+ efekt „…“, „!“ nebo Zzz)."""
    names = {"listening": "listen", "thinking": "think", "working": "work", "waiting": "wave",
             "success": "hop", "error": "stumble", "sleeping": "sleep"}
    name = names[state] if names[state] not in used else names[state] + "_auto"
    i0, fr = idle.frames[0], idle.frames
    loop = [fr[i % len(fr)] for i in range(max(4, len(fr)))]
    side = min(2, min((k % W for k, c in enumerate(i0) if c), default=0),
               min((W - 1 - k % W for k, c in enumerate(i0) if c), default=0))
    if state == "listening":
        return Out(name, [up(i0, 2), up(i0, 4), up(i0, 3), up(i0, 1), i0], 10, True, None)
    if state == "thinking":
        n = len(loop)
        return Out(name, loop, max(2, idle.fps // 2), False, lambda i: dots(i * 4 // n))
    if state == "working":
        return Out(name, [up(f, i % 2) for i, f in enumerate(loop)], max(8, idle.fps), False, None)
    if state == "waiting":
        return Out(name, [i0, i0, up(i0, 2), up(i0, 3), up(i0, 2), i0], 8, False, bang)
    if state == "success":
        return Out(name, [up(i0, 2), up(flip(i0), 4), up(i0, 4), up(flip(i0), 2), i0], 10, True, None)
    if state == "error":
        return Out(name, [shift(i0, d) for d in (side, -side, side, -side, min(1, side), 0)], 12, True, None)
    return Out(name, loop, 2, False, zzz)


# --- paleta --------------------------------------------------------------------------

def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def reduce_colors(count, n):
    """Median cut: {barva: počet} → {barva: náhradní barva}; náhrada je nejčastější skutečná barva krabice."""
    boxes = [list(count)]
    while len(boxes) < n:
        box = max((b for b in boxes if len(b) > 1), default=None,
                  key=lambda b: max(max(c[i] for c in b) - min(c[i] for c in b) for i in range(3)))
        if box is None:
            break
        ch = max(range(3), key=lambda i: max(c[i] for c in box) - min(c[i] for c in box))
        box.sort(key=lambda c: c[ch])
        total, acc, cut = sum(count[c] for c in box), 0, 1
        for k, c in enumerate(box[:-1]):      # řez v mediánu počtu pixelů
            acc += count[c]
            cut = k + 1
            if 2 * acc >= total:
                break
        boxes.remove(box)
        boxes += [box[:cut], box[cut:]]
    out = {}
    for b in boxes:
        rep = max(b, key=count.get)
        out.update((c, rep) for c in b)
    return out


def build_palette(images, extras):
    """(paleta "#rrggbb" s indexem 0, počet barev postavy, převod barvy → index, převod doplňků → index, varování)."""
    count = {}
    for img in images:
        for c in img:
            if c is not None:
                count[c] = count.get(c, 0) + 1
    warn, slots = [], skin.MAX_COLORS - 1
    remap = {c: c for c in count}
    if len(count) > slots:
        warn.append(f"postava má {len(count)} barev, sloučeny na {slots} (formát skinu jich víc nedovolí)")
        remap = reduce_colors(count, slots)
    body = sorted(set(remap.values()), key=lum)
    hexes = ["#%02x%02x%02x" % (c if c != (255, 0, 255) else (254, 0, 254)) for c in body]   # magenta = index 0
    pal = ["#ff00ff"] + hexes
    index = {c: body.index(remap[c]) + 1 for c in count}
    extra_ix = {}
    for c in extras:        # barvy efektů, reakcí a dronů: blízká barva postavy, jinak nová
        rgb = bytes.fromhex(c[1:])
        best = min(range(1, len(pal)), key=lambda k: dist(bytes.fromhex(pal[k][1:]), rgb)) if len(pal) > 1 else 0
        if (not best or dist(bytes.fromhex(pal[best][1:]), rgb) > 48) and len(pal) < skin.MAX_COLORS:
            pal.append(c)
            best = len(pal) - 1
        extra_ix[c] = best
    return pal, len(body), index, extra_ix, warn


def mood_palette(pal, n_body, kind):
    """Nálada mění jen barvy postavy: warm/cold přimíchá odstín, faded vybledne."""
    out = list(pal)
    for k in range(1, n_body + 1):
        rgb = bytes.fromhex(pal[k][1:])
        if kind == "faded":
            h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
            rgb = [round(v * 255) for v in colorsys.hls_to_rgb(h, l * 0.88, s * 0.35)]
        else:
            tint, part = TINTS[kind]
            rgb = [round(v * (1 - part) + t * part) for v, t in zip(rgb, tint)]
        out[k] = "#%02x%02x%02x" % tuple(rgb)
    return out


# --- zápis skinu -----------------------------------------------------------------------

def _toml(v):
    if isinstance(v, dict):
        key = lambda k: k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)
        return "{ " + ", ".join(f"{key(k)} = {_toml(x)}" for k, x in v.items()) + " }"
    return json.dumps(v, ensure_ascii=False)


def default_id(path):
    s = unicodedata.normalize("NFKD", os.path.splitext(os.path.basename(path))[0])
    s = re.sub(r"[^a-z0-9_.-]+", "-", "".join(c for c in s if not unicodedata.combining(c)).lower())
    return s.strip("-_.") or "muj-skin"


def importuj(path, skin_id=None, mapa_path=None, prepsat=False):
    """Vytvoří skin v uživatelském adresáři; vrátí (cesta, {stav: (tag, odvozený)}, varování).
    Existující skin (uživatelský i z balíčku) přepíše jen s prepsat=True."""
    sid = skin_id or default_id(path)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", sid):
        raise SkinError(f"id {sid!r}: jen písmena, číslice, -, _ a . (na začátku písmeno nebo číslice)")
    base = os.path.join(paths.data_dir(), "skins")
    dest = os.path.join(base, sid)
    found = skin.find(sid)
    if (found or os.path.exists(dest)) and not prepsat:
        where = found[0] if found else dest
        raise SkinError(f"skin {sid!r} už existuje ({where}); přepiš ho volbou --prepsat nebo zvol jiné --id")
    mapa = read_mapa(mapa_path)
    src, warn = load_source(path)
    frames, w2 = normalize(src, mapa.get("meritko"))
    warn += w2
    tags = build_tags(src, frames)
    states, kinds = assign(tags, mapa)
    outs = [o for _, o in tags]
    by_name = {o.name: o for o in outs}
    if "idle" not in states:
        states["idle"] = outs[0].name
        warn.append(f"žádný tag pro idle, beru první tag {outs[0].name!r}")
    report = {}
    oneshot = set(mapa.get("oneshot", ())) if "oneshot" in mapa else None
    for st in STATES:
        if st in states:
            report[st] = (states[st], False)
            if oneshot is None and st in ONESHOT_STATES:
                o = by_name[states[st]]
                by_name[o.name] = o._replace(oneshot=True)
        elif st == "gone":
            continue
        else:
            o = derive(st, by_name[states["idle"]], by_name)
            by_name[o.name] = o
            states[st] = o.name
            report[st] = (o.name, True)
    if "gone" not in states:
        states["gone"] = states["sleeping"]
        report["gone"] = (states["gone"], report["sleeping"][1])
    if oneshot is not None:
        src_names = {src_name: o.name for src_name, o in tags}
        for t in oneshot:
            n = src_names.get(t, t)
            if n in by_name:
                by_name[n] = by_name[n]._replace(oneshot=True)
    outs = list(by_name.values())

    robo = skin.PackageSkin(os.path.join(skin.PACKAGE_DIR, "robokun"))
    robo_pal = robo.palettes["base"]
    emote_cols = {robo_pal[v] for f in robo.emote.frames for _, _, v in f if v}
    drone_cols = {robo_pal[v] for f in robo.drone_sheet.frames for _, _, v in f if v}
    extras = [WHITE, YELLOW] + sorted(emote_cols - {WHITE, YELLOW}) + sorted(drone_cols - emote_cols - {WHITE, YELLOW})
    pal, n_body, index, extra_ix, w3 = build_palette([img for o in outs for img in o.frames], extras)
    warn += w3

    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f".{sid}.", dir=base)
    try:
        os.chmod(tmp, 0o755)
        os.makedirs(os.path.join(tmp, "pal"))
        body, body_tags, fx, fx_tags = [], [], [], []
        for o in outs:
            body += [bytearray(0 if c is None else index[c] for c in img) for img in o.frames]
            body_tags.append((o.name, len(o.frames), o.fps, o.oneshot))
            if o.fx:
                for i in range(len(o.frames)):
                    px = bytearray([skin.NONE]) * (W * H)
                    for x, y, c in o.fx(i):
                        px[y * W + x] = extra_ix[c]
                    fx.append(px)
                fx_tags.append((o.name, len(o.frames), o.fps, o.oneshot))
        skin_export.write_sheet(tmp, "body", body, body_tags, pal, False)
        if fx:
            skin_export.write_sheet(tmp, "fx", fx, fx_tags, pal, True)
        for layer, sheet in (("emote", robo.emote), ("drone", robo.drone_sheet)):
            frs = []
            for f in sheet.frames:
                px = bytearray([skin.NONE]) * (W * H)
                for x, y, v in f:
                    px[y * W + x] = extra_ix[robo_pal[v]] if v else 0
                frs.append(px)
            tg = [(n, len(t.frames), t.fps, t.oneshot) for n, t in sheet.tags.items()]
            skin_export.write_sheet(tmp, layer, frs, tg, pal, True)
        pals = ["base"] + (["warm", "cold", "faded"] if mapa.get("nalady", True) else [])
        for k in pals:
            cols = pal if k == "base" else mood_palette(pal, n_body, k)
            skin_export.write_gpl(os.path.join(tmp, "pal", f"{k}.gpl"), k, [None, *cols[1:]])

        working = {tool: kinds[k] for tool, k in sprites.TOOL_ANIM.items() if k in kinds}
        working.update({t: v for t, v in kinds.items() if t not in TOOL_KINDS})     # nástroje z mapy
        working.setdefault("default", states["working"])
        moods = []
        for mood, (_, _, p, emote, tempo) in sprites.MOOD.items():
            m = {"palette": p if p in pals else "base"}
            if emote:
                m["emote"] = emote
            line = f"{mood} = {_toml(m)}"
            moods.append(line[:-2] + f", tempo = {tempo} }}" if tempo != 1.0 else line)
        name = mapa.get("name") or os.path.splitext(os.path.basename(path))[0]
        layers = ["body"] + (["fx"] if fx else []) + ["emote", "drone"]
        toml = "\n".join([
            f"# Importováno z {_toml(os.path.basename(path))} příkazem familiar skin-import. Formát popisuje docs/skiny.md.",
            "# Obličej (face) ani klobouky (acc) skin nemá; reakce a drony jsou Robo-kunovy v paletě skinu.", "",
            "[skin]", f"name = {_toml(name)}", f"size = [{W}, {H}]", "anchor = [16, 31]", "",
            "[layers]", *[f'{k} = "{k}.png"' for k in layers], "",
            "[palettes]", *[f'{k} = "pal/{k}.gpl"' for k in pals], "",
            "[activity]", *[f"{st} = {_toml(states[st])}" for st in STATES if st != "working"],
            f"working = {_toml(working)}", "",
            "[mood]", *moods, ""])
        with open(os.path.join(tmp, "skin.toml"), "w", encoding="utf-8") as f:
            f.write(toml)
        s = skin.PackageSkin(tmp, skin.USER)     # ověření: musí se načíst bez chyby
        if s.missing:
            raise SkinError(f"interní chyba importu: chybí animace {s.missing}")
        if os.path.exists(dest):
            old = tempfile.mkdtemp(prefix=f".{sid}.old.", dir=base)
            os.rename(dest, os.path.join(old, sid))
            os.rename(tmp, dest)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.rename(tmp, dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dest, report, warn
