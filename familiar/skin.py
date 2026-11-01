# Skiny: rozhraní, přes které renderer a hub kreslí postavičku, a loader balíčků.
#
# Vestavěný skin (BuiltinSkin) obaluje Robo-kuna kresleného kódem v sprites.py.
# Balíček (PackageSkin) je adresář se skin.toml, PNG sheety, JSON z Aseprite
# (json-array s tagy a řezy) a paletami .gpl; formát a rozhodnutí v docs/skiny.md.
# Snímek = W×H indexů do palety (0 = průhledná) + barvy palety podle nálady.
# Skládá se ve stejném pořadí jako sprites.draw(): body → face → acc → fx → drone → emote.
# Bez Qt (PNG čte čistý Python), takže skin smí používat i hub.
import json, logging, os, re, struct, tomllib, zlib
from collections import namedtuple

from familiar import paths, sprites

W, H = sprites.W, sprites.H
DEFAULT = "robokun"
BUILTIN = "vestaveny"
PACKAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skins")
USER, PACKAGE, CODE = "uživatel", "balíček", "vestavěný"     # zdroje skinů
NONE = 255          # překryvné vrstvy: pixel nic nemění (index 0 = vyříznout do průhledna)
MAX_COLORS = 16
MAX_SIZE = 64       # největší plátno skinu (šířka i výška); nejmenší je W×H
SLOTS = ("eyes", "mouth")      # místa obličeje, která přepisuje nálada (vrstva face)
LAYERS = ("body", "face", "acc", "fx", "emote", "drone")   # vrstvy skinu v pořadí [layers]
NO_LOOK = ("klid", None, None, 0, 0, 0)

Anim = namedtuple("Anim", "fps frames oneshot")
Tag = namedtuple("Tag", "frames fps oneshot")       # frames = indexy snímků sheetu v pořadí přehrávání
log = logging.getLogger(__name__)


class SkinError(Exception):
    """Vadný balíček skinu; zpráva říká soubor a co je špatně."""


class Skin:
    """Rozhraní pro renderer a hub; vestavěný i balíčkový skin ho plní stejně.

    look = (nálada, klobouk, emote, fáze emote, počet dronů, fáze dronů), jak ho skládá hub.
    """
    id = name = source = ""
    size = (W, H)
    anchor = (16, 31)       # bod, kterým postavička sedí na hraně okna
    anims = {}              # animace → Anim(fps, počet snímků, jednorázová)
    error = None            # proč se nepoužil požadovaný skin (jen u náhradního)
    facing = None           # kam postavička kouká: "right" / "left" / None (zepředu, nezrcadlí se)

    def anim_for(self, state, tool=None):
        """Animace pro stav činnosti (a nástroj při working)."""
        raise NotImplementedError

    def frame_at(self, anim, t, speed=1.0):
        """Index snímku v čase t od začátku animace; jednorázové zůstanou na posledním."""
        a = self.anims[anim]
        i = int(t * a.fps * speed)
        return min(i, a.frames - 1) if a.oneshot else i % a.frames

    def walk_anim(self):
        """Animace chůze pro procházku (pohyb.py), nebo None: pak se kreslí klidová animace
        s poskakováním. Chůze vestavěného skinu se jinému skinu nepůjčuje (byl by to Robo-kun)."""
        return None

    def mood_emote(self, mood):
        """Emote, který se ukáže při změně na tuto náladu, nebo None."""
        raise NotImplementedError

    def mood_tempo(self, mood):
        """Zpomalení animací v této náladě (1.0 = beze změny)."""
        raise NotImplementedError

    def render(self, anim, i, look=None):
        """(bytes W×H indexů, seznam barev "#rrggbb" s None na indexu 0)."""
        raise NotImplementedError


class BuiltinSkin(Skin):
    """Robo-kun kreslený kódem (sprites.py)."""

    def __init__(self, error=None):
        self.id, self.name, self.source, self.error = BUILTIN, "Robo-kun (kreslený kódem)", CODE, error
        self.anims = {n: Anim(fps, len(poses), n in sprites.ONESHOT)
                      for n, (fps, poses) in sprites.ANIMS.items()}

    facing = sprites.FACING

    def anim_for(self, state, tool=None):
        return sprites.anim_for(state, tool)

    def walk_anim(self):
        return sprites.STATE_ANIM["walking"]

    def mood_emote(self, mood):
        return sprites.MOOD.get(mood, sprites.MOOD["klid"])[3]

    def mood_tempo(self, mood):
        return sprites.MOOD.get(mood, sprites.MOOD["klid"])[4]

    def render(self, anim, i, look=None):
        return sprites.frame(anim, i, look), sprites.palette(look[0] if look else "klid")


# --- čtení souborů -------------------------------------------------------------

def read_png(path):
    """(šířka, výška, bytearray RGBA); 8bitové PNG všech barevných typů, indexované i 1–4 bity."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise SkinError(f"{path}: nelze přečíst ({e.strerror})")
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SkinError(f"{path}: není PNG")
    pos, ihdr, idat, plte, trns = 8, None, [], b"", b""
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            plte = chunk
        elif kind == b"tRNS":
            trns = chunk
        elif kind == b"IDAT":
            idat.append(chunk)
        elif kind == b"IEND":
            break
    if not ihdr:
        raise SkinError(f"{path}: PNG bez hlavičky IHDR")
    w, h, depth, ctype, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None or interlace or not (depth == 8 or (ctype in (0, 3) and depth in (1, 2, 4))):
        raise SkinError(f"{path}: nepodporované PNG (barevný typ {ctype}, {depth} bitů, prokládání "
                        f"{interlace}); ulož 8bitové RGBA nebo indexované bez prokládání")
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error:
        raise SkinError(f"{path}: poškozená obrazová data")
    bpp = max(1, channels * depth // 8)
    stride = (w * channels * depth + 7) // 8
    if len(raw) < h * (stride + 1):
        raise SkinError(f"{path}: obrazová data jsou krátká")
    lines, prev = [], bytearray(stride)
    for y in range(h):
        start = y * (stride + 1)
        ft, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if ft == 1:
            for k in range(bpp, stride):
                line[k] = (line[k] + line[k - bpp]) & 255
        elif ft == 2:
            for k in range(stride):
                line[k] = (line[k] + prev[k]) & 255
        elif ft == 3:
            for k in range(stride):
                left = line[k - bpp] if k >= bpp else 0
                line[k] = (line[k] + ((left + prev[k]) >> 1)) & 255
        elif ft == 4:
            for k in range(stride):
                a = line[k - bpp] if k >= bpp else 0
                b, c = prev[k], prev[k - bpp] if k >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[k] = (line[k] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif ft:
            raise SkinError(f"{path}: neznámý filtr řádku {ft}")
        lines.append(line)
        prev = line
    out = bytearray(w * h * 4)
    for y, line in enumerate(lines):
        if depth < 8:       # indexované/šedé po 1–4 bitech
            per = 8 // depth
            vals = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(w)]
        else:
            vals = line
        o = y * w * 4
        if ctype == 6:
            out[o:o + w * 4] = vals
        elif ctype == 2:
            for x in range(w):
                out[o + x * 4:o + x * 4 + 4] = bytes((vals[x * 3], vals[x * 3 + 1], vals[x * 3 + 2], 255))
        elif ctype == 3:
            for x in range(w):
                k = vals[x]
                if 3 * k + 3 > len(plte):
                    raise SkinError(f"{path}: index {k} mimo paletu PNG")
                a = trns[k] if k < len(trns) else 255
                out[o + x * 4:o + x * 4 + 4] = plte[3 * k:3 * k + 3] + bytes((a,))
        else:               # šedá (0) a šedá s alfou (4)
            scale = 255 // ((1 << depth) - 1)
            for x in range(w):
                v = vals[x * channels] * scale
                a = vals[x * 2 + 1] if ctype == 4 else 255
                out[o + x * 4:o + x * 4 + 4] = bytes((v, v, v, a))
    return w, h, out


def read_gpl(path):
    """Paleta GIMP (.gpl) → seznam "#rrggbb"; Aseprite ji umí uložit i načíst."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise SkinError(f"{path}: nelze přečíst ({e.strerror})")
    except UnicodeDecodeError:
        raise SkinError(f"{path}: není v kódování UTF-8")
    if not lines or lines[0].strip() != "GIMP Palette":
        raise SkinError(f"{path}: první řádek musí být 'GIMP Palette'")
    colors = []
    for n, line in enumerate(lines[1:], 2):
        s = line.strip()
        if not s or s.startswith("#") or re.match(r"^[A-Za-z]+:", s):
            continue
        parts = s.split()
        try:
            rgb = [int(v) for v in parts[:3]]
        except ValueError:
            rgb = []
        if len(rgb) != 3 or not all(0 <= v <= 255 for v in rgb):
            raise SkinError(f"{path}:{n}: čekám 'R G B název', je tam {s!r}")
        colors.append("#%02x%02x%02x" % tuple(rgb))
    if not 2 <= len(colors) <= MAX_COLORS:
        raise SkinError(f"{path}: paleta má {len(colors)} barev, čekám 2–{MAX_COLORS} (index 0 = průhledná)")
    return colors


def play_order(a, b, direction="forward"):
    """Snímky a..b v pořadí přehrávání podle směru tagu Aseprite."""
    seq = list(range(a, b + 1))
    if direction in ("reverse", "pingpong_reverse"):
        seq.reverse()
    if str(direction).startswith("pingpong"):
        seq += seq[-2:0:-1]
    return seq


def read_toml(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise SkinError(f"{path}: nelze přečíst ({e.strerror})")
    except tomllib.TOMLDecodeError as e:
        raise SkinError(f"{path}: chyba TOML: {e}")
    except UnicodeDecodeError:      # tomllib dekóduje UTF-8 sám, chyba není TOMLDecodeError
        raise SkinError(f"{path}: není v kódování UTF-8")


class Sheet:
    """Jeden PNG sheet s JSON z Aseprite: snímky (indexy palety), tagy a řezy (kotvy)."""

    @classmethod
    def memory(cls, name, frames, tags, slices=None, overlay=False, size=(W, H)):
        """Sheet z dat v paměti (editor skinů), bez souborů. frames: w×h indexů (NONE = nic);
        tags: {jméno: Tag}; slices: {řez: [(snímek, x, y)]}."""
        self = cls.__new__(cls)
        self.png, self.json = name + ".png", name + ".json"
        self.durations = [100] * len(frames)
        if overlay:
            w = size[0]
            self.frames = [[(k % w, k // w, v) for k, v in enumerate(px) if v != NONE] for px in frames]
        else:
            self.frames = [bytes(bytes(px).replace(b"\xff", b"\x00")) for px in frames]
        self.tags = dict(tags)
        self.slices = {k: sorted(v) for k, v in (slices or {}).items()}
        return self

    def __init__(self, png, lookup, overlay, size=(W, H)):
        self.png, self.json = png, os.path.splitext(png)[0] + ".json"
        w, h = size
        doc = self._doc()
        sw, sh, rgba = read_png(png)
        frames = doc.get("frames")
        if isinstance(frames, dict):        # json-hash: pořadí klíčů = pořadí snímků
            frames = list(frames.values())
        if not isinstance(frames, list) or not frames:
            raise SkinError(f"{self.json}: chybí seznam 'frames' (exportuj --format json-array)")
        self.frames, self.durations = [], []
        for n, fr in enumerate(frames):
            try:
                r, src = fr["frame"], fr.get("spriteSourceSize", {"x": 0, "y": 0})
                size = fr.get("sourceSize", {"w": r["w"], "h": r["h"]})
                rx, ry, rw, rh = (int(r[k]) for k in "xywh")
                ox, oy = int(src["x"]), int(src["y"])
                self.durations.append(int(fr.get("duration", 100)))
                fsize = (int(size["w"]), int(size["h"]))
            except (KeyError, TypeError, ValueError):
                raise SkinError(f"{self.json}: snímek {n} nemá platné 'frame'/'sourceSize'")
            if fr.get("rotated"):
                raise SkinError(f"{self.json}: snímek {n} je otočený; exportuj bez --sheet-type packed/rotace")
            if fsize != (w, h):
                raise SkinError(f"{self.json}: snímek {n} má {fsize[0]}×{fsize[1]} px, plátno skinu musí "
                                f"být {w}×{h}")
            if rx < 0 or ry < 0 or rx + rw > sw or ry + rh > sh:
                raise SkinError(f"{self.json}: snímek {n} leží mimo {os.path.basename(png)} ({sw}×{sh})")
            px = bytearray([NONE]) * (w * h)
            for yy in range(rh):
                for xx in range(rw):
                    k = ((ry + yy) * sw + rx + xx) * 4
                    if rgba[k + 3] < 128:
                        continue
                    v = lookup.get(bytes(rgba[k:k + 3]))
                    if v is None:
                        raise SkinError(f"{png}: barva #{rgba[k:k + 3].hex()} na ({rx + xx}, {ry + yy}) "
                                        f"(snímek {n}) není v paletě base")
                    tx, ty = ox + xx, oy + yy
                    if 0 <= tx < w and 0 <= ty < h:
                        px[ty * w + tx] = v
            if overlay:     # řídce: jen pixely, které něco mění
                self.frames.append([(k % w, k // w, v) for k, v in enumerate(px) if v != NONE])
            else:
                self.frames.append(bytes(px.replace(b"\xff", b"\x00")))
        meta = doc.get("meta") or {}
        self.tags = self._tags(meta.get("frameTags") or [])
        self.slices = self._slices(meta.get("slices") or [])

    def _doc(self):
        try:
            with open(self.json, encoding="utf-8") as f:
                doc = json.load(f)
        except OSError as e:
            raise SkinError(f"{self.json}: nelze přečíst ({e.strerror}); patří k {os.path.basename(self.png)}")
        except ValueError as e:
            raise SkinError(f"{self.json}: neplatný JSON ({e})")
        if not isinstance(doc, dict):
            raise SkinError(f"{self.json}: čekám objekt s 'frames' a 'meta'")
        return doc

    def _tags(self, raw):
        tags = {}
        for t in raw:
            try:
                name, a, b = str(t["name"]), int(t["from"]), int(t["to"])
            except (KeyError, TypeError, ValueError):
                raise SkinError(f"{self.json}: tag bez 'name'/'from'/'to'")
            if not 0 <= a <= b < len(self.frames):
                raise SkinError(f"{self.json}: tag '{name}' odkazuje na snímky {a}–{b}, sheet jich má "
                                f"{len(self.frames)}")
            if name in tags:
                raise SkinError(f"{self.json}: tag '{name}' je dvakrát")
            seq = play_order(a, b, t.get("direction", "forward"))
            ms = sum(self.durations[k] for k in seq) / len(seq)
            tags[name] = Tag(seq, max(1, round(1000 / ms)) if ms > 0 else 8, str(t.get("repeat", "")) == "1")
        return tags

    def _slices(self, raw):
        out = {}
        for s in raw:
            try:
                out[str(s["name"])] = sorted((int(k["frame"]), int(k["bounds"]["x"]), int(k["bounds"]["y"]))
                                             for k in s["keys"])
            except (KeyError, TypeError, ValueError):
                raise SkinError(f"{self.json}: řez (slice) bez platných 'keys'")
        return out

    def anchor(self, name, frame):
        """Levý horní roh řezu na snímku (poslední klíč ≤ frame, jako v Aseprite), nebo None."""
        hit = None
        for f, x, y in self.slices.get(name, ()):
            if f > frame:
                break
            hit = (x, y)
        return hit


# --- balíček -------------------------------------------------------------------

class PackageSkin(Skin):
    """Skin z adresáře se skin.toml. Při chybě vyhodí SkinError s čitelnou zprávou.

    Animace, které balíček nemá, kreslí `fallback` (vestavěný skin) celé i s jeho paletou."""

    def __init__(self, path, source=PACKAGE, fallback=None):
        self.path, self.source, self.fallback = path, source, fallback
        self.id = os.path.basename(os.path.normpath(path))
        toml = os.path.join(path, "skin.toml")
        cfg = read_toml(toml)
        self._meta(cfg, toml)

        pals = self._table(cfg, "palettes", toml)
        if "base" not in pals:
            raise SkinError(f"{toml}: [palettes] musí mít paletu base")
        raw = {k: read_gpl(self._file(v, toml, f"palettes.{k}")) for k, v in pals.items()}
        self._palettes(raw, toml)
        lookup = {}
        for k, c in reversed(list(enumerate(raw["base"]))):    # při shodě vyhraje nižší index
            lookup[bytes.fromhex(c[1:])] = k

        layers = self._table(cfg, "layers", toml)
        if "body" not in layers:
            raise SkinError(f"{toml}: [layers] musí mít body")
        sheets = {}
        for k in LAYERS:
            if k in layers:
                sheets[k] = Sheet(self._file(layers[k], toml, f"layers.{k}"), lookup, k != "body", self.size)
        self._setup(cfg, sheets, toml)

    @classmethod
    def from_parts(cls, skin_id, cfg, palettes, sheets, source=USER, fallback=None, where="(editor)"):
        """Skin z dat v paměti (editor skinů): cfg jako skin.toml bez [layers] a [palettes],
        palettes = {jméno: barvy "#rrggbb" včetně indexu 0}, sheets = {vrstva: Sheet.memory(...)}.
        Kontroluje stejně jako načtení ze souborů; chyby začínají `where`."""
        self = cls.__new__(cls)
        self.path, self.source, self.fallback, self.id = None, source, fallback, skin_id
        self._meta(cfg, where)
        self._palettes(palettes, where)
        if "body" not in sheets:
            raise SkinError(f"{where}: chybí vrstva body")
        self._setup(cfg, sheets, where)
        return self

    def _meta(self, cfg, toml):
        self.missing = []       # stavy, které kreslí fallback
        self._cache = {}
        meta = self._table(cfg, "skin", toml)
        self.name = str(meta.get("name", self.id))
        size = meta.get("size", [W, H])
        if (not isinstance(size, list) or len(size) != 2 or not all(type(v) is int for v in size)
                or not all(lo <= v <= MAX_SIZE for v, lo in zip(size, (W, H)))):
            raise SkinError(f"{toml}: size musí být [šířka, výška] v rozsahu {W}–{MAX_SIZE} px "
                            f"(menší postavičku nakresli na plátno {W}×{H})")
        self.size = tuple(size)
        self.anchor = tuple(meta.get("anchor", (size[0] // 2, size[1] - 1)))
        self.facing = meta.get("facing")
        if self.facing not in (None, "right", "left"):
            raise SkinError(f"{toml}: facing musí být \"right\" nebo \"left\" (zepředu = klíč vynech)")

    def _palettes(self, raw, toml):
        for k, cols in raw.items():
            if len(cols) != len(raw["base"]):
                raise SkinError(f"{toml}: paleta {k} má {len(cols)} barev, base {len(raw['base'])}")
        self.palettes = {k: [None] + cols[1:] for k, cols in raw.items()}

    def _setup(self, cfg, sheets, toml):
        """Vrstvy, animace a tabulky [activity], [mood], [face] (společné pro soubory i paměť)."""
        meta = self._table(cfg, "skin", toml)
        self.body = sheets["body"]
        self.face, self.acc, self.fx = sheets.get("face"), sheets.get("acc"), sheets.get("fx")
        self.emote = sheets.get("emote")
        drone = sheets.get("drone")
        self.drones = [drone.tags[t] for t in sorted((t for t in drone.tags if re.fullmatch(r"drone\d+", t)),
                                                     key=lambda t: int(t[5:]))] if drone else []
        self.drone_sheet = drone
        if not self.body.tags:
            raise SkinError(f"{self.body.json}: žádné tagy; animace jsou tagy (exportuj s --list-tags)")
        oneshot = set(meta.get("oneshot", ()))
        self.anims = {n: Anim(t.fps, len(t.frames), t.oneshot or n in oneshot) for n, t in self.body.tags.items()}
        if self.fx:
            for n, t in self.fx.tags.items():
                if n not in self.body.tags or len(t.frames) != len(self.body.tags[n].frames):
                    raise SkinError(f"{self.fx.json}: tag '{n}' musí mít v body.json stejný počet snímků")

        self.activity = self._table(cfg, "activity", toml)
        for state, v in self.activity.items():
            names = v.values() if isinstance(v, dict) else [v]
            if not all(isinstance(a, str) for a in names):
                raise SkinError(f"{toml}: [activity] {state} musí být jméno tagu nebo tabulka nástroj → tag")
            self.missing += [f"{state}: {a}" for a in names if a not in self.anims]

        self.moods = self._table(cfg, "mood", toml)
        for mood, m in self.moods.items():
            if not isinstance(m, dict):
                raise SkinError(f"{toml}: [mood] {mood} musí být tabulka")
            if m.get("palette", "base") not in self.palettes:
                raise SkinError(f"{toml}: nálada {mood} chce paletu {m['palette']}, ta není v [palettes]")
            for slot in SLOTS:
                if m.get(slot) and (not self.face or f"{slot}_{m[slot]}" not in self.face.tags):
                    raise SkinError(f"{toml}: nálada {mood} chce {slot} = {m[slot]!r}, ve face.json chybí "
                                    f"tag {slot}_{m[slot]}")
            if not isinstance(m.get("tempo", 1.0), (int, float)) or m.get("tempo", 1.0) <= 0:
                raise SkinError(f"{toml}: nálada {mood}: tempo musí být kladné číslo")

        face = self._table(cfg, "face", toml)
        self.keep = {}
        for slot in SLOTS:
            keep = face.get(f"keep_{slot}", {})
            if not isinstance(keep, dict) or not all(v is True or isinstance(v, list) for v in keep.values()):
                raise SkinError(f"{toml}: [face] keep_{slot} = {{ tag = [snímky] nebo true }}")
            self.keep[slot] = {a: v if v is True else set(v) for a, v in keep.items()}

    @staticmethod
    def _table(cfg, key, toml):
        v = cfg.get(key, {})
        if not isinstance(v, dict):
            raise SkinError(f"{toml}: [{key}] musí být tabulka")
        return v

    def _file(self, name, toml, key):
        if not isinstance(name, str) or os.path.isabs(name) or ".." in name.split("/"):
            raise SkinError(f"{toml}: {key} musí být relativní cesta uvnitř skinu")
        path = os.path.join(self.path, name)
        if not os.path.isfile(path):
            raise SkinError(f"{toml}: {key} = {name!r}, soubor neexistuje")
        return path

    def _mood(self, mood):
        return self.moods.get(mood) or self.moods.get("klid") or {}

    def anim_for(self, state, tool=None):
        a = self.activity.get(state)
        if isinstance(a, dict):
            a = a.get(tool) or a.get("default")
        if a in self.anims:
            return a
        return self.fallback.anim_for(state, tool) if self.fallback else next(iter(self.anims))

    def walk_anim(self):
        a = self.activity.get("walking")
        return a if isinstance(a, str) and a in self.anims else None

    def frame_at(self, anim, t, speed=1.0):
        if anim not in self.anims and self.fallback:
            return self.fallback.frame_at(anim, t, speed)
        return Skin.frame_at(self, anim, t, speed)

    def mood_emote(self, mood):
        return self._mood(mood).get("emote")

    def mood_tempo(self, mood):
        return float(self._mood(mood).get("tempo", 1.0))

    def render(self, anim, i, look=None):
        if anim not in self.anims:
            if self.fallback:
                return self._fit(*self.fallback.render(anim, i, look))
            raise KeyError(anim)
        key = (anim, i, look)
        hit = self._cache.get(key)
        if hit is None:
            if len(self._cache) > 4000:
                self._cache.clear()
            hit = self._cache[key] = self._compose(anim, i, look or NO_LOOK)
        return hit

    def _compose(self, anim, i, look):
        mood, hat, pop, pop_phase, drones, drone_phase = look
        m = self._mood(mood)
        seq = self.body.tags[anim].frames
        i %= len(seq)
        f = seq[i]
        px = bytearray(self.body.frames[f])
        for slot in SLOTS:
            keep = self.keep[slot].get(anim, ())
            if m.get(slot) and not (keep is True or i in keep):
                self._paste(px, self.face, f"{slot}_{m[slot]}", 0, slot, f)
        if hat and self.acc:
            tag = f"{hat}@{anim}" if f"{hat}@{anim}" in self.acc.tags else hat
            self._paste(px, self.acc, tag, i, "head", f)
        self._paste(px, self.fx, anim, i)
        for tag in self.drones[:drones]:
            self._paste_frame(px, self.drone_sheet, tag.frames[drone_phase % len(tag.frames)])
        if pop:
            self._paste(px, self.emote, pop, pop_phase)
        return bytes(px), self.palettes.get(m.get("palette", "base"), self.palettes["base"])

    def _paste(self, px, sheet, tag, i, slot=None, f=0):
        """Snímek i tagu z překryvné vrstvy; se slotem posunutý tak, aby řez vrstvy padl na řez těla."""
        if not sheet or tag not in sheet.tags:
            return
        seq = sheet.tags[tag].frames
        k = seq[i % len(seq)]
        dx = dy = 0
        if slot:
            at, ref = self.body.anchor(slot, f), sheet.anchor(slot, k)
            if at and ref:
                dx, dy = at[0] - ref[0], at[1] - ref[1]
        self._paste_frame(px, sheet, k, dx, dy)

    def _paste_frame(self, px, sheet, k, dx=0, dy=0):
        w, h = self.size
        for x, y, v in sheet.frames[k]:
            x, y = x + dx, y + dy
            if 0 <= x < w and 0 <= y < h:
                px[y * w + x] = v

    def _fit(self, px, colors):
        """Snímek vestavěného skinu (W×H) na větší plátno: kotva na kotvu, aby postavička neposkočila."""
        w, h = self.size
        if (w, h) == (W, H):
            return px, colors
        ox = min(max(self.anchor[0] - Skin.anchor[0], 0), w - W)
        oy = min(max(self.anchor[1] - Skin.anchor[1], 0), h - H)
        out = bytearray(w * h)
        for y in range(H):
            out[(oy + y) * w + ox:(oy + y) * w + ox + W] = px[y * W:(y + 1) * W]
        return bytes(out), colors


# --- hledání a načtení -----------------------------------------------------------

_builtin = None


def builtin():
    global _builtin
    if _builtin is None:
        _builtin = BuiltinSkin()
    return _builtin


def search_path():
    """[(adresář, zdroj)]: uživatelské skiny mají přednost před skiny z balíčku."""
    return [(os.path.join(paths.data_dir(), "skins"), USER), (PACKAGE_DIR, PACKAGE)]


def find(skin_id):
    """(cesta, zdroj) adresáře skinu, nebo None."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", skin_id or ""):
        return None
    for base, source in search_path():
        path = os.path.join(base, skin_id)
        if os.path.isfile(os.path.join(path, "skin.toml")):
            return path, source
    return None


def load(skin_id=None):
    """Skin podle id. Nikdy nevyhodí: při chybě vrátí vestavěný skin s důvodem v .error (a v logu)."""
    skin_id = skin_id or DEFAULT
    if skin_id == BUILTIN:
        return builtin()
    found = find(skin_id)
    if found is None:
        error = f"skin {skin_id!r} nenalezen v " + " ani ".join(base for base, _ in search_path())
    else:
        try:
            return PackageSkin(*found, fallback=builtin())
        except SkinError as e:
            error = str(e)
        except Exception as e:      # poškozený soubor nesmí shodit daemon
            error = f"{found[0]}: {type(e).__name__}: {e}"
    log.warning("%s; kreslím vestavěného Robo-kuna", error)
    return BuiltinSkin(error)


def available():
    """[(id, název, zdroj)] všech skinů, které load() najde; vestavěný je poslední."""
    out, seen = [], {BUILTIN}
    for base, source in search_path():
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for sid in names:
            toml = os.path.join(base, sid, "skin.toml")
            if sid in seen or not os.path.isfile(toml) or not find(sid):
                continue
            try:
                name = str(read_toml(toml).get("skin", {}).get("name", sid))
            except (SkinError, AttributeError):
                name = f"{sid} (vadný skin.toml)"
            seen.add(sid)
            out.append((sid, name, source))
    out.append((BUILTIN, builtin().name, CODE))
    return out


def save_preview(s, path):
    """Náhled skinu do PNG: řádky = nálady, sloupce = stavy (s reakcí a jedním dronem)."""
    from familiar.skin_export import write_png
    moods = [m for m in sprites.MOOD]
    cols = [s.anim_for(st, "Bash") for st in ("idle", "listening", "thinking", "working", "waiting",
                                               "success", "error", "sleeping")]
    z, (sw, sh) = 4, s.size
    w, h = len(cols) * sw * z, len(moods) * sh * z
    rgba = bytearray(b"\x30\x30\x3a\xff") * (w * h)
    for r, mood in enumerate(moods):
        for c, anim in enumerate(cols):
            i = s.anims[anim].frames // 2 if anim in s.anims else 0
            px, colors = s.render(anim, i, (mood, None, s.mood_emote(mood), 0, 1, 0))
            for k, v in enumerate(px):
                if colors[v] is None:
                    continue
                rgb = bytes.fromhex(colors[v][1:]) + b"\xff"
                x0, y0 = (c * sw + k % sw) * z, (r * sh + k // sw) * z
                for y in range(y0, y0 + z):
                    rgba[(y * w + x0) * 4:(y * w + x0 + z) * 4] = rgb * z
    write_png(path, w, h, rgba)


def main(argv=None):
    """python3 -m familiar.skin [id] [--nahled soubor.png]: ověří skin a vykreslí náhled."""
    import argparse
    ap = argparse.ArgumentParser(description="ověření skinu familiara")
    ap.add_argument("id", nargs="?", help="id skinu; bez něj vypíše dostupné skiny")
    ap.add_argument("--nahled", metavar="PNG", help="uloží náhled: řádky = nálady, sloupce = animace")
    args = ap.parse_args(argv)
    if not args.id:
        for sid, name, source in available():
            print(f"{sid:16} {name:28} {source}")
        return
    s = load(args.id)
    print(f"{s.id}: {s.name} ({s.source})")
    if s.error:
        print(f"CHYBA: {s.error}")
    for m in getattr(s, "missing", []):
        print(f"chybí animace (kreslí vestavěný): {m}")
    if args.nahled:
        save_preview(s, args.nahled)
        print(f"náhled: {args.nahled}")


if __name__ == "__main__":
    main()
