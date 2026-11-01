# Editor skinů – model bez Qt: balíček skinu jako upravitelná data.
#
# Načte adresář se skin.toml (formát v docs/skiny.md), drží vrstvy jako seznam animací
# se snímky (indexy palety), palety, metadata a tabulky [activity], [mood], [face] a zapíše
# je zpátky ve stejném formátu, jaký čte skin.py: PNG + JSON Aseprite (json-array s tagy
# a řezy), palety .gpl a skin.toml (tomlkit: komentáře a neznámé klíče zůstanou).
#
# Snímek nese vše, co k němu patří: pixely, efekty fx (jen postava), kotvy řezů
# (eyes / mouth / head) a zámky obličeje (které sloty nálada na snímku nemění). Přesun,
# smazání nebo kopie snímku je tak jedna operace a indexy v [face] se spočítají při zápisu.
#
# Ukládá se jen do uživatelského adresáře skinů: skin z balíčku se uloží jako uživatelská
# kopie se stejným id (přebije ho). Zápis jde do dočasného adresáře, ověří se načtením
# (skin.PackageSkin) a teprve pak nahradí původní adresář; vadný výsledek nic nezmění.
import copy, os, re, shutil, tempfile
from dataclasses import dataclass, field

from familiar import paths, skin, sprites
from familiar.skin import NONE, SkinError

CUT = "#ff00ff"         # barva indexu 0 v .gpl a v překryvných vrstvách (vyříznout)
LAYER_NAMES = {"body": "Postava", "face": "Obličej (výrazy nálad)", "acc": "Klobouky",
               "emote": "Reakce nad hlavou", "drone": "Drony subagentů"}
LAYER_ORDER = ("body", "face", "acc", "emote", "drone")      # fx patří ke snímkům postavy
LAYER_SLICES = {"body": ("eyes", "mouth", "head"), "face": ("eyes", "mouth"), "acc": ("head",)}
SLICE_SIZE = {"eyes": (9, 4), "mouth": (4, 2), "head": (16, 12)}
STATES = ("idle", "listening", "thinking", "waiting", "success", "error", "sleeping", "gone", "walking")
TOOLS = ("Bash", "Edit", "Read", "default")
MOODS = tuple(sprites.MOOD)
DIRECTIONS = ("forward", "reverse", "pingpong", "pingpong_reverse")
MAX_FPS = 30            # víc by zápis délky snímku v ms nezachoval (round(1000 / fps))
ID_RE = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
NAME_RE = r"[^\s\"'\\]+"         # jméno tagu (animace) nebo palety


@dataclass
class Frame:
    px: bytearray                               # w×h indexů; postava 0 = průhledná, překryvy NONE = nic
    fx: bytearray = None                        # jen postava: efekty animace (NONE = nic), None = žádné
    anchors: dict = field(default_factory=dict)     # řez → (x, y) levý horní roh
    keep: set = field(default_factory=set)          # jen postava: sloty, které na snímku nálada nemění


@dataclass
class Anim:
    name: str
    fps: int = 8
    oneshot: bool = False
    direction: str = "forward"
    frames: list = field(default_factory=list)


class Layer:
    """Jedna vrstva (sheet) skinu: animace (tagy) se snímky a velikosti řezů."""

    def __init__(self, name, size):
        self.name, self.size = name, tuple(size)
        self.overlay = name != "body"
        self.anims = []
        self.slices = {}        # řez → (w, h)

    def get(self, name):
        return next((a for a in self.anims if a.name == name), None)

    def names(self):
        return [a.name for a in self.anims]

    def blank(self):
        return bytearray([NONE if self.overlay else 0]) * (self.size[0] * self.size[1])

    def flatten(self):
        """(snímky, [(tag, počet, fps, jednorázová, směr)], {řez: [(snímek, x, y, w, h)]}) v pořadí zápisu."""
        frames, tags, slices, last = [], [], {}, {}
        for a in self.anims:
            tags.append((a.name, len(a.frames), a.fps, a.oneshot, a.direction))
            for fr in a.frames:
                for s, xy in fr.anchors.items():
                    if s in self.slices and last.get(s) != xy:
                        slices.setdefault(s, []).append((len(frames), *xy, *self.slices[s]))
                        last[s] = xy
                frames.append(fr.px)
        return frames, tags, slices


class SkinDoc:
    """Upravitelný skin. Vytváří ho load() / new(); zapisuje save()."""

    def __init__(self, skin_id, size=(sprites.W, sprites.H)):
        self.id = skin_id
        self.path = None            # odkud se načetl (None = nový)
        self.source = skin.USER
        self.size = tuple(size)
        self.anchor = (size[0] // 2, size[1] - 1)
        self.meta = {"name": skin_id}           # [skin] kromě size/anchor/oneshot (i neznámé klíče)
        self.palettes = {"base": [None]}        # jméno → barvy "#rrggbb", index 0 = None (průhledná)
        self.layers = {}
        self.activity, self.moods = {}, {}
        self.toml_text = ""         # původní skin.toml (zápis zachová komentáře a neznámé tabulky)
        self.files = set()          # soubory vrstev a palet původního balíčku (při zápisu se nahradí)
        self.warnings = []

    # --- základ ---

    def clone(self):
        return copy.deepcopy(self)

    @property
    def name(self):
        return str(self.meta.get("name") or self.id)

    @property
    def body(self):
        return self.layers["body"]

    def layer(self, name):
        """Vrstva; chybějící překryvnou založí (prázdnou, s výchozími řezy)."""
        if name not in self.layers:
            lay = self.layers[name] = Layer(name, self.size)
            for s in LAYER_SLICES.get(name, ()):
                lay.slices[s] = SLICE_SIZE[s]
        return self.layers[name]

    def colors(self, palette="base"):
        return self.palettes.get(palette) or self.palettes["base"]

    def editable(self):
        return self.source != skin.CODE

    # --- render přes skin.py (náhled kreslí stejný kód jako daemon) ---

    def cfg(self):
        """Tabulky jako ze skin.toml (bez [layers] a [palettes])."""
        meta = {k: v for k, v in self.meta.items() if v not in (None, "")}
        meta.update(size=list(self.size), anchor=list(self.anchor))
        face = {}
        if "body" in self.layers:
            for slot in skin.SLOTS:
                keep = {}
                for a in self.body.anims:
                    seq = skin.play_order(0, len(a.frames) - 1, a.direction) if a.frames else []
                    hit = [i for i, f in enumerate(seq) if slot in a.frames[f].keep]
                    if hit:
                        keep[a.name] = True if len(hit) == len(seq) else hit
                if keep:
                    face[f"keep_{slot}"] = keep
        return {"skin": meta, "activity": copy.deepcopy(self.activity), "mood": copy.deepcopy(self.moods),
                "face": face}

    def sheets(self):
        """{vrstva: (snímky, tagy, řezy, překryvná)} včetně fx; tagy jako flatten()."""
        out = {}
        for name in LAYER_ORDER:
            lay = self.layers.get(name)
            if lay is None or (lay.overlay and not lay.anims):
                continue
            frames, tags, slices = lay.flatten()
            out[name] = (frames, tags, slices, lay.overlay)
        if "body" in self.layers:
            fx, fx_tags = [], []
            for a in self.body.anims:
                if any(f.fx is not None for f in a.frames):
                    blank = bytearray([NONE]) * (self.size[0] * self.size[1])
                    fx += [f.fx if f.fx is not None else blank for f in a.frames]
                    fx_tags.append((a.name, len(a.frames), a.fps, a.oneshot, a.direction))
            if fx:
                out["fx"] = (fx, fx_tags, {}, True)
        return out

    def to_skin(self):
        """PackageSkin v paměti; SkinError, když by se skin nenačetl."""
        if "body" not in self.layers or not self.body.anims:
            raise SkinError("postava (body) nemá žádnou animaci")
        for lay in self.layers.values():
            for a in lay.anims:
                if not a.frames:
                    raise SkinError(f"{LAYER_NAMES.get(lay.name, lay.name)}: animace {a.name!r} nemá snímky")
        sheets = {}
        for name, (frames, tags, slices, overlay) in self.sheets().items():
            mem = {t: skin.Tag(_seq_offset(tags, t), fps, one) for t, _, fps, one, _ in tags}
            sheets[name] = skin.Sheet.memory(name, frames, mem,
                                             {s: [k[:3] for k in keys] for s, keys in slices.items()},
                                             overlay, self.size)
        pals = {k: [CUT] + list(v[1:]) for k, v in self.palettes.items()}
        return skin.PackageSkin.from_parts(self.id, self.cfg(), pals, sheets, fallback=skin.builtin(),
                                           where=f"skin {self.id}")

    def problems(self):
        """Chyby, kvůli kterým nejde uložit (prázdný seznam = jde)."""
        out = []
        base = self.palettes["base"][1:]
        seen = {}
        for k, c in enumerate(base, 1):
            if c.lower() == CUT:
                out.append(f"paleta base: barva {k} je {CUT}, ta patří indexu 0 (průhledná)")
            elif c.lower() in seen:
                out.append(f"paleta base: barvy {seen[c.lower()]} a {k} jsou stejné ({c}); v PNG by splynuly")
            seen.setdefault(c.lower(), k)
        try:
            self.to_skin()
        except SkinError as e:
            out.append(str(e))
        return out

    # --- animace ---

    def add_anim(self, layer, name, frames=1, fps=8, at=None):
        lay = self.layer(layer)
        self._check_name(lay, name)
        a = Anim(name, fps)
        ref = self._ref_anchors(lay)
        for _ in range(frames):
            a.frames.append(Frame(lay.blank(), anchors=dict(ref)))
        lay.anims.insert(len(lay.anims) if at is None else at, a)
        return a

    def duplicate_anim(self, layer, name, new):
        lay = self.layers[layer]
        self._check_name(lay, new)
        a = copy.deepcopy(lay.get(name))
        a.name = new
        lay.anims.insert(lay.anims.index(lay.get(name)) + 1, a)
        return a

    def rename_anim(self, layer, old, new):
        """Přejmenuje animaci a odkazy na ni ([activity], [mood], varianty klobouků)."""
        if old == new:
            return
        lay = self.layers[layer]
        self._check_name(lay, new)
        lay.get(old).name = new
        if layer == "body":
            self._map_activity(lambda a: new if a == old else a)
            if "acc" in self.layers:
                for a in self.layers["acc"].anims:
                    hat, at, anim = a.name.partition("@")
                    if at and anim == old:
                        a.name = f"{hat}@{new}"
        elif layer == "face":
            for slot in skin.SLOTS:
                if old.startswith(slot + "_"):
                    keep = new[len(slot) + 1:] if new.startswith(slot + "_") else None
                    for m in self.moods.values():
                        if m.get(slot) == old[len(slot) + 1:]:
                            _set(m, slot, keep)
        elif layer == "emote":
            for m in self.moods.values():
                if m.get("emote") == old:
                    m["emote"] = new

    def delete_anim(self, layer, name):
        lay = self.layers[layer]
        lay.anims.remove(lay.get(name))
        if layer == "body":
            self._map_activity(lambda a: None if a == name else a)
            if "acc" in self.layers:
                acc = self.layers["acc"]
                acc.anims = [a for a in acc.anims if a.name.partition("@")[2] != name]
        elif layer == "face":
            for slot in skin.SLOTS:
                if name.startswith(slot + "_"):
                    for m in self.moods.values():
                        if m.get(slot) == name[len(slot) + 1:]:
                            m.pop(slot)
        elif layer == "emote":
            for m in self.moods.values():
                if m.get("emote") == name:
                    m.pop("emote")

    def move_anim(self, layer, name, delta):
        anims = self.layers[layer].anims
        i = anims.index(self.layers[layer].get(name))
        j = max(0, min(len(anims) - 1, i + delta))
        anims.insert(j, anims.pop(i))
        return j

    def _check_name(self, lay, name):
        if not re.fullmatch(NAME_RE, name or ""):
            raise ValueError(f"jméno {name!r}: bez mezer a uvozovek")
        if lay.get(name):
            raise ValueError(f"animace {name!r} už ve vrstvě je")
        if lay.name == "face" and not name.startswith(("eyes_", "mouth_")):
            raise ValueError("výraz se musí jmenovat eyes_<jméno> nebo mouth_<jméno>")
        if lay.name == "drone" and not re.fullmatch(r"drone\d+", name):
            raise ValueError("dron se musí jmenovat drone1, drone2, …")

    def _ref_anchors(self, lay):
        """Kotvy pro nový snímek: z prvního snímku vrstvy, jinak výchozí podle Robo-kuna."""
        for a in lay.anims:
            if a.frames:
                return dict(a.frames[0].anchors)
        return {s: _default_anchor(s, self.size) for s in lay.slices}

    def _map_activity(self, fn):
        for st in list(self.activity):
            v = self.activity[st]
            if isinstance(v, dict):
                for tool in list(v):
                    _set(v, tool, fn(v[tool]))
                if not v:
                    del self.activity[st]
            else:
                _set(self.activity, st, fn(v))

    # --- snímky ---

    def add_frame(self, layer, anim, at=None, copy_from=None):
        lay = self.layers[layer]
        a = lay.get(anim)
        if copy_from is not None:
            fr = copy.deepcopy(a.frames[copy_from])
        else:
            ref = a.frames[-1].anchors if a.frames else self._ref_anchors(lay)
            fr = Frame(lay.blank(), anchors=dict(ref))
        at = len(a.frames) if at is None else at
        a.frames.insert(at, fr)
        return at

    def delete_frame(self, layer, anim, i):
        a = self.layers[layer].get(anim)
        if len(a.frames) <= 1:
            raise ValueError("animace musí mít aspoň jeden snímek (smaž celou animaci)")
        del a.frames[i]
        return min(i, len(a.frames) - 1)

    def move_frame(self, layer, anim, i, delta):
        a = self.layers[layer].get(anim)
        j = max(0, min(len(a.frames) - 1, i + delta))
        a.frames.insert(j, a.frames.pop(i))
        return j

    # --- plátno ---

    def resize(self, w, h):
        """Nová velikost plátna; obsah zůstane na kotvě (střed spodní hrany se posune s ní)."""
        if not (sprites.W <= w <= skin.MAX_SIZE and sprites.H <= h <= skin.MAX_SIZE):
            raise ValueError(f"plátno musí být {sprites.W}–{skin.MAX_SIZE} px")
        ow, oh = self.size
        dx, dy = (w - ow) // 2, h - oh
        for lay in self.layers.values():
            lay.size = (w, h)
            for a in lay.anims:
                for f in a.frames:
                    f.px = shift(f.px, (ow, oh), dx, dy, NONE if lay.overlay else 0, (w, h))
                    if f.fx is not None:
                        f.fx = shift(f.fx, (ow, oh), dx, dy, NONE, (w, h))
                    f.anchors = {s: (x + dx, y + dy) for s, (x, y) in f.anchors.items()}
        self.size = (w, h)
        self.anchor = (min(max(self.anchor[0] + dx, 0), w - 1), min(max(self.anchor[1] + dy, 0), h - 1))

    # --- palety ---

    def add_palette(self, name, copy_of="base"):
        if not re.fullmatch(NAME_RE, name or "") or name in self.palettes:
            raise ValueError(f"paleta {name!r}: jméno bez mezer, které ještě není")
        self.palettes[name] = list(self.palettes[copy_of])

    def rename_palette(self, old, new):
        if old == "base":
            raise ValueError("paleta base se přejmenovat nedá (je v ní nakreslené PNG)")
        if old == new:
            return
        if not re.fullmatch(NAME_RE, new or "") or new in self.palettes:
            raise ValueError(f"paleta {new!r}: jméno bez mezer, které ještě není")
        self.palettes = {new if k == old else k: v for k, v in self.palettes.items()}
        for m in self.moods.values():
            if m.get("palette") == old:
                m["palette"] = new

    def delete_palette(self, name):
        if name == "base":
            raise ValueError("paleta base je povinná")
        del self.palettes[name]
        for m in self.moods.values():
            if m.get("palette") == name:
                m["palette"] = "base"

    def set_color(self, palette, index, color):
        color = color.lower()
        if index == 0:
            raise ValueError("index 0 je průhledná barva")
        if palette == "base":
            if color == CUT:
                raise ValueError(f"{CUT} patří indexu 0 (průhledná / vyříznout)")
            other = [k for k, c in enumerate(self.palettes["base"]) if k and k != index and c == color]
            if other:
                raise ValueError(f"barva {color} už je v paletě base na indexu {other[0]}")
        self.palettes[palette][index] = color

    def add_color(self, color="#808080"):
        """Nový index ve všech paletách; vrátí ho."""
        base = self.palettes["base"]
        if len(base) >= skin.MAX_COLORS:
            raise ValueError(f"paleta má nejvýš {skin.MAX_COLORS} barev včetně průhledné")
        while color in base or color == CUT:
            color = "#%06x" % ((int(color[1:], 16) + 0x010101) & 0xffffff)
        for cols in self.palettes.values():
            cols.append(color)
        return len(base) - 1

    def used_colors(self):
        used = set()
        for lay in self.layers.values():
            for a in lay.anims:
                for f in a.frames:
                    used.update(f.px)
                    if f.fx is not None:
                        used.update(f.fx)
        used.discard(NONE)
        return used

    def remove_last_color(self):
        base = self.palettes["base"]
        k = len(base) - 1
        if k <= 1:
            raise ValueError("paleta musí mít aspoň jednu barvu")
        if k in self.used_colors():
            raise ValueError(f"barvu {k} používají snímky; nejdřív ji v nich přemaluj")
        for cols in self.palettes.values():
            cols.pop()

    def body_colors(self):
        """Indexy barev, které používá postava (bez efektů, reakcí a dronů)."""
        used = set()
        for a in self.body.anims:
            for f in a.frames:
                used.update(f.px)
        used.discard(0)
        return used

    def derive_palette(self, name, kind):
        """Paleta nálady odvozená z base: warm / cold přimíchá odstín, faded vybledne (jen barvy postavy)."""
        from familiar import skin_import
        if name == "base":
            raise ValueError("paletu base nejde odvodit sama ze sebe")
        if not re.fullmatch(NAME_RE, name or ""):
            raise ValueError(f"paleta {name!r}: jméno bez mezer")
        base = self.palettes["base"]
        tinted = skin_import.mood_palette(base, len(base) - 1, kind)
        body = self.body_colors()
        self.palettes[name] = [c if k in body else base[k] for k, c in enumerate(tinted)]

    def replace_color(self, old, new):
        """Přemaluje index old na new ve všech snímcích všech vrstev."""
        for lay in self.layers.values():
            for a in lay.anims:
                for f in a.frames:
                    for px in (f.px, f.fx):
                        if px is not None:
                            for k, v in enumerate(px):
                                if v == old:
                                    px[k] = new


# --- pixely ---------------------------------------------------------------------

def shift(px, size, dx, dy, fill, new_size=None):
    """Snímek posunutý o (dx, dy) (na plátno new_size); co vyjede, zmizí."""
    w, h = size
    nw, nh = new_size or size
    out = bytearray([fill]) * (nw * nh)
    for y in range(h):
        ty = y + dy
        if 0 <= ty < nh:
            for x in range(w):
                tx = x + dx
                if 0 <= tx < nw:
                    out[ty * nw + tx] = px[y * w + x]
    return out


def flip(px, size):
    w, h = size
    return bytearray(b for y in range(h) for b in reversed(px[y * w:(y + 1) * w]))


def fill(px, size, x, y, v):
    """Vyplní souvislou oblast stejné barvy (4-sousedství); vrátí počet změněných pixelů."""
    w, h = size
    old = px[y * w + x]
    if old == v:
        return 0
    stack, n = [(x, y)], 0
    while stack:
        x, y = stack.pop()
        if 0 <= x < w and 0 <= y < h and px[y * w + x] == old:
            px[y * w + x] = v
            n += 1
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return n


def line(x0, y0, x1, y1):
    """Body úsečky (Bresenham)."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, out = dx + dy, []
    while True:
        out.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return out
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def rect(x0, y0, x1, y1):
    """Body obrysu obdélníku."""
    xa, xb, ya, yb = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    pts = {(x, y) for x in range(xa, xb + 1) for y in (ya, yb)}
    pts |= {(x, y) for y in range(ya, yb + 1) for x in (xa, xb)}
    return sorted(pts)


# --- načtení, nový, zápis ------------------------------------------------------------

def _set(d, key, value):
    if value is None:
        d.pop(key, None)
    else:
        d[key] = value


def _seq_offset(tags, name):
    """Snímky tagu (globální indexy) v pořadí přehrávání."""
    start = 0
    for t, count, _, _, direction in tags:
        if t == name:
            return skin.play_order(start, start + count - 1, direction)
        start += count
    raise KeyError(name)


def _default_anchor(s, size):
    """Výchozí kotva řezu na plátně: místo, kde je má Robo-kun (posunuté s velikostí plátna)."""
    from familiar import skin_export as ex
    at = {"eyes": ex.EYES_AT, "mouth": ex.MOUTH_AT, "head": ex.HEAD}[s]
    return at[0] + (size[0] - sprites.W) // 2, at[1] + size[1] - sprites.H


def _dense(sheet, k, size):
    """Snímek k ze skin.Sheet jako bytearray w×h (překryvné vrstvy mají NONE = nic)."""
    f = sheet.frames[k]
    if isinstance(f, (bytes, bytearray)):
        return bytearray(f)
    w, h = size
    px = bytearray([NONE]) * (w * h)
    for x, y, v in f:
        px[y * w + x] = v
    return px


def load(path, source=None):
    """SkinDoc z adresáře skinu; SkinError, když se skin nenačte."""
    path = os.path.normpath(path)
    if source is None:
        source = skin.USER if path.startswith(os.path.join(paths.data_dir(), "skins")) else skin.PACKAGE
    s = skin.PackageSkin(path, source)
    toml = os.path.join(path, "skin.toml")
    cfg = skin.read_toml(toml)
    doc = SkinDoc(s.id, s.size)
    doc.path, doc.source = path, source
    with open(toml, encoding="utf-8") as f:
        doc.toml_text = f.read()
    doc.anchor = tuple(s.anchor)
    doc.meta = {k: v for k, v in cfg.get("skin", {}).items() if k not in ("size", "anchor", "oneshot")}
    doc.meta.setdefault("name", s.name)
    oneshot = set(cfg.get("skin", {}).get("oneshot", ()))
    doc.palettes = {k: list(v) for k, v in s.palettes.items()}
    doc.activity = copy.deepcopy(s.activity)
    doc.moods = copy.deepcopy(s.moods)
    for key in ("layers", "palettes"):
        for v in cfg.get(key, {}).values():
            doc.files.add(v)
            if key == "layers":
                doc.files.add(os.path.splitext(v)[0] + ".json")

    sheets = {"body": s.body, "face": s.face, "acc": s.acc, "emote": s.emote, "drone": s.drone_sheet}
    fx_raw = {t["name"]: t for t in _raw_meta(s.fx).get("frameTags", [])} if s.fx else {}
    for name in LAYER_ORDER:
        sheet = sheets[name]
        if sheet is None:
            continue
        lay = doc.layers[name] = Layer(name, s.size)
        meta = _raw_meta(sheet)
        for sl in meta.get("slices") or []:
            keys = sl.get("keys") or [{}]
            b = keys[0].get("bounds", {})
            lay.slices[str(sl["name"])] = (int(b.get("w", 1)), int(b.get("h", 1)))
        used = set()
        for t in meta.get("frameTags") or []:
            a0, b0 = int(t["from"]), int(t["to"])
            tag = sheet.tags[str(t["name"])]
            a = Anim(str(t["name"]), min(max(tag.fps, 1), MAX_FPS), tag.oneshot or t["name"] in oneshot,
                     t.get("direction", "forward") if t.get("direction") in DIRECTIONS else "forward")
            for k in range(a0, b0 + 1):
                used.add(k)
                fr = Frame(_dense(sheet, k, s.size))
                fr.anchors = {sl: xy for sl in lay.slices if (xy := sheet.anchor(sl, k)) is not None}
                a.frames.append(fr)
            if name == "body":
                ft = fx_raw.get(a.name)
                if ft:
                    for i, fr in enumerate(a.frames):
                        fr.fx = _dense(s.fx, int(ft["from"]) + i, s.size)
                seq = skin.play_order(0, len(a.frames) - 1, a.direction)
                for slot in skin.SLOTS:
                    keep = s.keep[slot].get(a.name, ())
                    for i, f in enumerate(seq):
                        if keep is True or i in keep:
                            a.frames[f].keep.add(slot)
            lay.anims.append(a)
        if len(used) < len(sheet.frames):
            doc.warnings.append(f"{LAYER_NAMES[name]}: {len(sheet.frames) - len(used)} snímků mimo tagy "
                                f"se při uložení vynechá")
    return doc


def _raw_meta(sheet):
    return sheet._doc().get("meta") or {}


def load_id(skin_id):
    """SkinDoc podle id (uživatelský skin má přednost, jako skin.find)."""
    found = skin.find(skin_id)
    if not found:
        raise SkinError(f"skin {skin_id!r} nenalezen")
    return load(*found)


def new(skin_id, name=None, size=(sprites.W, sprites.H)):
    """Prázdný skin: paleta Robo-kuna, jedna animace idle, reakce a drony Robo-kuna."""
    doc = SkinDoc(skin_id, size)
    doc.meta = {"name": name or skin_id}
    robo = skin.PackageSkin(os.path.join(skin.PACKAGE_DIR, "robokun"))
    doc.palettes = {"base": list(robo.palettes["base"])}
    doc.layers["body"] = Layer("body", size)
    for s in LAYER_SLICES["body"]:
        doc.body.slices[s] = SLICE_SIZE[s]
    doc.add_anim("body", "idle", frames=1, fps=4)
    doc.activity = {"idle": "idle"}
    doc.moods = {m: {"palette": "base"} for m in MOODS}
    for m, (_, _, _, emote, tempo) in sprites.MOOD.items():
        if emote:
            doc.moods[m]["emote"] = emote
        if tempo != 1.0:
            doc.moods[m]["tempo"] = tempo
    dx, dy = (size[0] - sprites.W) // 2, size[1] - sprites.H
    for name, sheet in (("emote", robo.emote), ("drone", robo.drone_sheet)):
        lay = doc.layers[name] = Layer(name, size)
        for t, tag in sheet.tags.items():
            a = Anim(t, tag.fps, tag.oneshot)
            a.frames = [Frame(shift(_dense(sheet, k, (sprites.W, sprites.H)), (sprites.W, sprites.H),
                                    dx, dy, NONE, size)) for k in tag.frames]
            lay.anims.append(a)
    return doc


def user_dir():
    return os.path.join(paths.data_dir(), "skins")


def valid_id(skin_id):
    return bool(re.fullmatch(ID_RE, skin_id or ""))


def toml_text(doc):
    """skin.toml: původní text upravený tomlkitem (komentáře a cizí klíče zůstanou)."""
    import tomlkit
    d = tomlkit.parse(doc.toml_text) if doc.toml_text else tomlkit.document()
    if not doc.toml_text:
        d.add(tomlkit.comment("Vytvořeno editorem skinů familiara (Nastavení → Editor). "
                              "Formát popisuje docs/skiny.md."))
    cfg = doc.cfg()

    def table(key):
        if key not in d or not isinstance(d[key], dict):
            d[key] = tomlkit.table()
        return d[key]

    def inline(v):
        if isinstance(v, dict):
            t = tomlkit.inline_table()
            for k, x in v.items():
                t[k] = inline(x)
            return t
        return v

    def replace(key, values):
        t = table(key)
        for k in [k for k in t if k not in values]:
            del t[k]
        for k, v in values.items():
            t[k] = inline(v)

    meta = table("skin")
    for k in [k for k in meta if k not in cfg["skin"]]:
        del meta[k]
    order = ["name", "size", "anchor", "facing"]
    for k in order + [k for k in cfg["skin"] if k not in order]:
        if k in cfg["skin"]:
            meta[k] = cfg["skin"][k]
    sheets = doc.sheets()
    replace("layers", {k: f"{k}.png" for k in skin.LAYERS if k in sheets})
    replace("palettes", {k: f"pal/{k}.gpl" for k in doc.palettes})
    replace("activity", cfg["activity"])
    replace("mood", cfg["mood"])
    if cfg["face"] or "face" in d:
        replace("face", cfg["face"])
    return tomlkit.dumps(d)


def save(doc, skin_id=None):
    """Zapíše skin do uživatelského adresáře (id = skin_id, jinak doc.id). Vrátí cestu.
    Skin z balíčku se uloží jako uživatelská kopie se stejným id. Při chybě nic nezmění."""
    from familiar import skin_export
    sid = skin_id or doc.id
    if not valid_id(sid) or sid == skin.BUILTIN:
        raise SkinError(f"id {sid!r}: jen písmena, číslice, -, _ a . (na začátku písmeno nebo číslice)")
    problems = doc.problems()
    if problems:
        raise SkinError("; ".join(problems))
    base = user_dir()
    os.makedirs(base, exist_ok=True)
    dest = os.path.join(base, sid)
    tmp = tempfile.mkdtemp(prefix=f".{sid}.", dir=base)
    try:
        os.chmod(tmp, 0o755)
        if doc.path and os.path.isdir(doc.path):        # CREDITS.txt, zdroje .aseprite …
            for root, dirs, files in os.walk(doc.path):
                rel = os.path.relpath(root, doc.path)
                for n in files:
                    r = os.path.normpath(os.path.join(rel, n))
                    if r in doc.files or r == "skin.toml" or n.startswith("."):
                        continue
                    os.makedirs(os.path.join(tmp, rel), exist_ok=True)
                    shutil.copy2(os.path.join(root, n), os.path.join(tmp, r))
        os.makedirs(os.path.join(tmp, "pal"), exist_ok=True)
        for name, (frames, tags, slices, overlay) in doc.sheets().items():
            skin_export.write_sheet(tmp, name, frames, tags, doc.palettes["base"], overlay, slices, doc.size)
        for k, cols in doc.palettes.items():
            skin_export.write_gpl(os.path.join(tmp, "pal", f"{k}.gpl"), k, cols)
        with open(os.path.join(tmp, "skin.toml"), "w", encoding="utf-8") as f:
            f.write(toml_text(doc))
        skin.PackageSkin(tmp, skin.USER)        # ověření: musí se načíst ze souborů
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
    doc.id, doc.path, doc.source = sid, dest, skin.USER
    with open(os.path.join(dest, "skin.toml"), encoding="utf-8") as f:
        doc.toml_text = f.read()
    doc.files = {f"{k}.png" for k in doc.sheets()} | {f"{k}.json" for k in doc.sheets()} | \
        {f"pal/{k}.gpl" for k in doc.palettes}
    return dest


def delete(skin_id):
    """Smaže uživatelský skin (skin z balíčku se stejným id se tím vrátí)."""
    if not valid_id(skin_id):
        raise SkinError(f"id {skin_id!r} není platné")
    path = os.path.join(user_dir(), skin_id)
    if not os.path.isfile(os.path.join(path, "skin.toml")):
        raise SkinError(f"{skin_id!r} není uživatelský skin")
    shutil.rmtree(path)
