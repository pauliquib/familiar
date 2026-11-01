# Úrovně, XP, úspěchy a odemykatelné doplňky (druhá etapa, M10a). Bez UI a bez Qt.
#
# zapocti(ev) bere události ve společném schématu (familiar/adapters/claude_code.py)
# a vrací nově odemčené úspěchy. Čas je jen ts události (a tz z konstruktoru),
# takže stejné události dají vždy stejný výsledek.
# Do $XDG_STATE_HOME/familiar/postup.json (0600) jdou jen čísla, data dnů, id
# úspěchů a názvy nástrojů. Příkaz (data.cmd) se čte jen kvůli poznání testů
# a nikam se neukládá; text promptu se nečte vůbec.
import logging, math, re, time
from datetime import date, datetime, timedelta

from familiar import uloziste

lg = logging.getLogger("familiar.progress")

JMENO = "postup.json"
INTERVAL_S = 60.0
MAX_UROVEN = 99

# XP za události
XP_SESSION = 5
XP_KOLO = 10            # kolo dokončené bez chyby
XP_NASTROJ = 1
XP_NASTROJE_DEN = 300   # strop XP za nástroje za den (proti spamu)
XP_SUBAGENT = 3
XP_TESTY = 20           # zelené testy
XP_OPRAVA_TESTU = 30    # zelené testy po červených
XP_OPRAVA = 15          # nástroj uspěl po chybě stejného nástroje (jednou za kolo)
XP_COMPACT = 25         # kolo dokončené po compactu
XP_DLOUHA = 50          # session delší než DLOUHA_S bez přestávky (jednou za session)
XP_DEN = 20             # první aktivita dne
DLOUHA_S = 3 * 3600
PRESTAVKA_S = 30 * 60   # delší ticho v session = přestávka, maraton začíná znovu

# Spouštěče testů na začátku příkazu (před nimi smí být proměnné prostředí a „cd … &&“).
TEST_RE = re.compile(
    r"(?:(?:uv|poetry|pdm|hatch|pipenv)\s+run\s+)?(?:(?:python3?(?:\.\d+)?|py)\s+-m\s+)?"
    r"(?:pytest|py\.test|tox|nox|unittest)\b"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|npx\s+(?:jest|vitest|mocha)\b|(?:jest|vitest|mocha)\b"
    r"|cargo\s+(?:test|nextest)\b|go\s+test\b|make\s+(?:test|check)\b|ctest\b|deno\s+test\b"
    r"|(?:mvn|\./mvnw)\s+(?:\S+\s+)*test\b|(?:gradle|\./gradlew)\s+test\b|dotnet\s+test\b"
    r"|(?:bundle\s+exec\s+)?rspec\b|(?:vendor/bin/)?phpunit\b|mix\s+test\b")
_PREFIX_RE = re.compile(r"\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+|cd\s+[^;&|]+?\s*&&\s*|timeout\s+\d+[smh]?\s+)")


def je_test(cmd):
    """Spouští příkaz testy? (podle začátku, po odříznutí proměnných, cd … && a timeout)."""
    if not isinstance(cmd, str):
        return False
    pos = 0
    while True:
        m = _PREFIX_RE.match(cmd, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
    return bool(TEST_RE.match(cmd, pos))


def xp_na_uroven(n):
    """Celkové XP potřebné k dosažení úrovně n (úroveň 1 = 0 XP, každá další o 50 dražší)."""
    n = max(1, n)
    return 100 * (n - 1) + 25 * (n - 1) * (n - 2)


def uroven_z_xp(xp):
    n = 1
    while n < MAX_UROVEN and xp >= xp_na_uroven(n + 1):
        n += 1
    return n


# Úspěchy: id → (název, popis, podmínka nad stavem). Podmínka dostane slovník čítačů.
def _c(klic, n):
    return lambda c: c.get(klic, 0) >= n


USPECHY = {
    "prvni_session": ("První krůček", "Spusť první session s familiarem.", _c("session", 1)),
    "prvni_kolo": ("Hotovo!", "Dokonči první kolo bez jediné chyby.", _c("kola_cista", 1)),
    "kola_100": ("Čistá práce", "Dokonči 100 kol bez chyby.", _c("kola_cista", 100)),
    "prompty_100": ("Povídálek", "Pošli 100 promptů.", _c("prompty", 100)),
    "prompty_1000": ("Stálý hlas", "Pošli 1000 promptů.", _c("prompty", 1000)),
    "nastroje_100": ("Šikovné ruce", "Agent zavolal 100 nástrojů.", _c("nastroje", 100)),
    "nastroje_1000": ("Mistr nářadí", "Agent zavolal 1000 nástrojů.", _c("nastroje", 1000)),
    "nastroje_10000": ("Dílna snů", "Agent zavolal 10 000 nástrojů.", _c("nastroje", 10000)),
    "sberatel": ("Sběratel nástrojů", "Použij 10 různých nástrojů.", _c("ruznych_nastroju", 10)),
    "nocni_sova": ("Noční sova", "Pošli prompt mezi půlnocí a čtvrtou ráno.", _c("nocni", 1)),
    "ranni_ptace": ("Ranní ptáče", "Pošli prompt mezi pátou a sedmou ráno.", _c("ranni", 1)),
    "vikend": ("Víkendový kutil", "Pracuj o víkendu.", _c("vikendovych_dni", 1)),
    "serie_3": ("Tři v řadě", "Pracuj tři dny po sobě.", _c("max_serie", 3)),
    "serie_7": ("Týden v kuse", "Pracuj sedm dní po sobě.", _c("max_serie", 7)),
    "serie_30": ("Měsíc věrnosti", "Pracuj třicet dní po sobě.", _c("max_serie", 30)),
    "dni_100": ("Stálice", "Pracuj celkem sto dní.", _c("aktivnich_dni", 100)),
    "prvni_subagent": ("Pomocník", "Agent poprvé vyslal subagenta.", _c("subagenti", 1)),
    "subagenti_50": ("Velitel roje", "Agent vyslal 50 subagentů.", _c("subagenti", 50)),
    "zelene_testy": ("Zelená!", "Testy poprvé prošly.", _c("testy_zelene", 1)),
    "testy_10": ("Deset zelených", "Deset zelených běhů testů po sobě.", _c("max_serie_testu", 10)),
    "oprava_testu": ("Z červené do zelené", "Testy prošly po neúspěšném běhu.", _c("opravy_testu", 1)),
    "prvni_oprava": ("Oprava za pochodu", "Nástroj uspěl hned po vlastní chybě.", _c("opravy", 1)),
    "compact": ("Přežil jsem compact", "Dokonči kolo po zhuštění kontextu.", _c("compacty_prezite", 1)),
    "maraton": ("Maratonec", "Pracuj v jedné session tři hodiny bez přestávky.", _c("dlouhe_session", 1)),
    "zarazit": ("Stop!", "Poprvé přeruš agenta klávesou Esc.", _c("preruseni", 1)),
    "uroven_5": ("Učeň", "Dosáhni úrovně 5.", _c("uroven", 5)),
    "uroven_10": ("Tovaryš", "Dosáhni úrovně 10.", _c("uroven", 10)),
    "uroven_20": ("Mistr", "Dosáhni úrovně 20.", _c("uroven", 20)),
}

# Odemykatelné doplňky (jen data, kreslí je skin): id → (druh, název, podmínka)
# podmínka {"uroven": n} nebo {"uspech": id}
DOPLNKY = {
    "emote_srdicko": ("emote", "Srdíčko", {"uroven": 2}),
    "klobouk_cepice": ("klobouk", "Kšiltovka", {"uroven": 3}),
    "emote_hvezda": ("emote", "Hvězdička", {"uroven": 5}),
    "klobouk_slamak": ("klobouk", "Slamák", {"uroven": 8}),
    "klobouk_cylindr": ("klobouk", "Cylindr", {"uroven": 12}),
    "klobouk_koruna": ("klobouk", "Koruna", {"uroven": 20}),
    "klobouk_cepicka": ("klobouk", "Noční čepička", {"uspech": "nocni_sova"}),
    "emote_zelena": ("emote", "Zelená fajfka", {"uspech": "testy_10"}),
    "emote_roj": ("emote", "Roj", {"uspech": "subagenti_50"}),
    "klobouk_vavrin": ("klobouk", "Vavřínový věnec", {"uspech": "serie_30"}),
}
# doplněk → klobouk (sprites.HATS) nebo emote (sprites.POPS), jak se jmenuje ve skinech;
# skin, který ho nemá (třeba kvetina bez klobouků), ho prostě nekreslí
SPRITY = {"emote_srdicko": "heart", "klobouk_cepice": "cap", "emote_hvezda": "star", "klobouk_slamak": "straw",
          "klobouk_cylindr": "tophat", "klobouk_koruna": "crown", "klobouk_cepicka": "nightcap",
          "emote_zelena": "badge", "emote_roj": "swarm", "klobouk_vavrin": "laurel"}

# čítače ve stavu (všechny celá čísla)
CITACE = ("session", "prompty", "nastroje", "ruznych_nastroju", "kola_cista", "nocni", "ranni",
          "vikendovych_dni", "serie", "max_serie", "aktivnich_dni", "subagenti", "testy_zelene",
          "serie_testu", "max_serie_testu", "opravy_testu", "opravy", "compacty_prezite",
          "dlouhe_session", "preruseni")
NASTROJ_RE = re.compile(r"[A-Za-z0-9_.:\-]{1,64}")
MAX_NAZVU = 500


def soubor():
    return uloziste.soubor(JMENO)


class _Kolo:
    __slots__ = ("chyba", "chybne", "oprava", "compact", "preruseno")

    def __init__(self, compact=False):
        self.chyba, self.chybne, self.oprava = False, set(), False
        self.compact, self.preruseno = compact, False


class Postup:
    def __init__(self, cesta=None, interval_s=INTERVAL_S, tz=None, zalohovat=True):
        self.cesta = cesta or soubor()
        self.interval_s, self.tz = interval_s, tz
        self.xp = 0
        self.c = {k: 0 for k in CITACE}
        self.odemceno = {}          # id úspěchu → ts odemčení
        self.nazvy = set()          # názvy použitých nástrojů (pro „Sběratele“)
        self.posledni_den = None    # 'YYYY-MM-DD' poslední aktivity
        self.xp_den = (None, 0)     # (den, XP za nástroje v tom dni)
        self.zmeneno = False
        self.posledni_ulozeni = float("-inf")
        self._kola = {}             # klíč (pid/session) → _Kolo
        self._session = {}          # session id → [začátek bez přestávky, poslední událost, maraton započten]
        self._testy_cervene = False
        try:
            self._nacti(uloziste.nacti(self.cesta, zalohovat))
        except Exception:
            lg.exception("postup nejde načíst, začínám znovu")

    def _nacti(self, raw):
        self.xp = uloziste.cele(raw.get("xp"))
        c = raw.get("citace") if isinstance(raw.get("citace"), dict) else {}
        self.c = {k: uloziste.cele(c.get(k)) for k in CITACE}
        u = raw.get("uspechy") if isinstance(raw.get("uspechy"), dict) else {}
        self.odemceno = {k: uloziste.cislo(v, 0.0, 1e11) for k, v in u.items() if k in USPECHY}
        n = raw.get("nastroje") if isinstance(raw.get("nastroje"), list) else []
        self.nazvy = {x for x in n if isinstance(x, str) and NASTROJ_RE.fullmatch(x)}
        d = raw.get("posledni_den")
        try:
            self.posledni_den = date.fromisoformat(d).isoformat() if isinstance(d, str) else None
        except ValueError:
            self.posledni_den = None
        self._testy_cervene = raw.get("testy_cervene") is True
        self.c["ruznych_nastroju"] = max(self.c["ruznych_nastroju"], len(self.nazvy))
        x = raw.get("xp_den")
        if isinstance(x, list) and len(x) == 2 and x[0] == self.posledni_den:
            self.xp_den = (x[0], uloziste.cele(x[1], 0, XP_NASTROJE_DEN))

    # --- odvozené hodnoty -----------------------------------------------------------

    @property
    def uroven(self):
        return uroven_z_xp(self.xp)

    @property
    def do_dalsi(self):
        """XP chybějící do další úrovně (0 na maximu)."""
        n = self.uroven
        return 0 if n >= MAX_UROVEN else xp_na_uroven(n + 1) - self.xp

    def uspechy(self):
        """[{"id", "nazev", "popis", "odemceno", "cas"}] v pevném pořadí."""
        return [{"id": k, "nazev": v[0], "popis": v[1], "odemceno": k in self.odemceno,
                 "cas": self.odemceno.get(k)} for k, v in USPECHY.items()]

    def odemcene_doplnky(self):
        """[{"id", "druh", "nazev", "sprite"}] doplňků, jejichž podmínka platí."""
        return [{k: d[k] for k in ("id", "druh", "nazev", "sprite")} for d in self.doplnky() if d["odemceno"]]

    def doplnky(self):
        """Všechny doplňky: [{"id", "druh", "nazev", "sprite", "odemceno", "podminka"}] (podmínka česky)."""
        n, out = self.uroven, []
        for k, (druh, nazev, p) in DOPLNKY.items():
            if "uroven" in p:
                ok, podm = n >= p["uroven"], f"úroveň {p['uroven']}"
            else:
                ok, podm = p["uspech"] in self.odemceno, f"úspěch „{USPECHY[p['uspech']][0]}“"
            out.append({"id": k, "druh": druh, "nazev": nazev, "sprite": SPRITY.get(k), "odemceno": ok,
                        "podminka": podm})
        return out

    # --- vstup ----------------------------------------------------------------------

    def zapocti(self, ev):
        """Započte událost; vrací nově odemčené úspěchy [{"id", "nazev", "popis", "cas"}]."""
        try:
            return self._zapocti(ev)
        except Exception:
            lg.exception("postup: událost nejde započíst")
            return []

    def _pridej(self, xp):
        self.xp += xp

    def _den(self, ts):
        """První aktivita dne: bonus, série dnů, víkend."""
        dt = datetime.fromtimestamp(ts, self.tz)
        dnes = dt.date()
        if self.posledni_den == dnes.isoformat():
            return dt
        vcera = (dnes - timedelta(days=1)).isoformat()
        if self.posledni_den is not None and self.posledni_den > dnes.isoformat():
            return dt           # událost ze starého dne (posun hodin): nic
        self.c["serie"] = self.c["serie"] + 1 if self.posledni_den == vcera else 1
        self.c["max_serie"] = max(self.c["max_serie"], self.c["serie"])
        self.c["aktivnich_dni"] += 1
        if dnes.weekday() >= 5:
            self.c["vikendovych_dni"] += 1
        self.posledni_den = dnes.isoformat()
        self._pridej(XP_DEN)
        return dt

    def _zapocti(self, ev):
        kind, ts = ev.get("kind"), ev.get("ts")
        if not isinstance(kind, str) or isinstance(ts, bool) or not isinstance(ts, (int, float)) \
                or not math.isfinite(ts):
            return []
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        key = ev.get("pid") or ev.get("session")
        sid = ev.get("session")
        dt = self._den(ts)
        c = self.c
        kolo = self._kola.get(key)

        if kind == "session.start":
            if data.get("how") != "compact":
                c["session"] += 1
                self._pridej(XP_SESSION)
        elif kind == "session.end":
            self._kola.pop(key, None)
            self._session.pop(sid, None)
        elif kind == "user.prompt":
            c["prompty"] += 1
            if dt.hour < 4:
                c["nocni"] += 1
            elif 5 <= dt.hour < 7:
                c["ranni"] += 1
            # compact uprostřed kola platí i pro další kolo, dokud nějaké neskončí
            self._kola[key] = _Kolo(compact=bool(kolo and kolo.compact))
        elif kind == "tool.start":
            c["nastroje"] += 1
            den, xp = self.xp_den
            if den != self.posledni_den:
                den, xp = self.posledni_den, 0
            if xp < XP_NASTROJE_DEN:
                self._pridej(XP_NASTROJ)
                xp += XP_NASTROJ
            self.xp_den = (den, xp)
            tool = data.get("tool")
            if isinstance(tool, str) and NASTROJ_RE.fullmatch(tool) and len(self.nazvy) < MAX_NAZVU:
                self.nazvy.add(tool)
                c["ruznych_nastroju"] = len(self.nazvy)
        elif kind == "tool.end" and not data.get("killed"):
            if je_test(data.get("cmd")):
                c["testy_zelene"] += 1
                c["serie_testu"] += 1
                c["max_serie_testu"] = max(c["max_serie_testu"], c["serie_testu"])
                self._pridej(XP_TESTY)
                if self._testy_cervene:
                    c["opravy_testu"] += 1
                    self._pridej(XP_OPRAVA_TESTU)
                self._testy_cervene = False
            if kolo and not kolo.oprava and data.get("tool") in kolo.chybne:
                kolo.oprava = True
                c["opravy"] += 1
                self._pridej(XP_OPRAVA)
        elif kind == "tool.error":
            if kolo:
                kolo.chyba = True
                if isinstance(data.get("tool"), str):
                    kolo.chybne.add(data["tool"])
            if je_test(data.get("cmd")):
                c["serie_testu"] = 0
                self._testy_cervene = True
        elif kind == "subagent.start":
            c["subagenti"] += 1
            self._pridej(XP_SUBAGENT)
        elif kind == "context.compact":
            if kolo is None:
                kolo = self._kola[key] = _Kolo()
            kolo.compact = True
        elif kind == "agent.interrupted":
            if kolo is None or not kolo.preruseno:     # hook i transcript: v kole jen jednou
                c["preruseni"] += 1
                if kolo:
                    kolo.preruseno = True
        elif kind == "agent.done":
            if kolo is not None:
                if not kolo.chyba and not kolo.preruseno:
                    c["kola_cista"] += 1
                    self._pridej(XP_KOLO)
                if kolo.compact:
                    c["compacty_prezite"] += 1
                    self._pridej(XP_COMPACT)
                del self._kola[key]
        elif kind == "agent.failed":
            self._kola.pop(key, None)

        # maraton: v session se něco děje DLOUHA_S bez přestávky delší než PRESTAVKA_S
        if sid and kind != "session.end":
            st = self._session.get(sid)
            if st is None:
                st = self._session[sid] = [ts, ts, False]
                if len(self._session) > 200:       # session.end se ztratil: nejstarší pryč
                    del self._session[next(iter(self._session))]
            if ts - st[1] > PRESTAVKA_S:
                st[0] = ts
            st[1] = max(st[1], ts)
            if not st[2] and ts - st[0] >= DLOUHA_S:
                st[2] = True
                c["dlouhe_session"] += 1
                self._pridej(XP_DLOUHA)

        self.zmeneno = True
        return self._odemkni(ts)

    def _odemkni(self, ts):
        stav, nove = {**self.c, "uroven": self.uroven}, []     # úspěchy XP nepřidávají
        for k, (nazev, popis, podm) in USPECHY.items():
            if k not in self.odemceno and podm(stav):
                self.odemceno[k] = ts
                nove.append({"id": k, "nazev": nazev, "popis": popis, "cas": ts})
        return nove

    # --- ukládání -------------------------------------------------------------------

    def uloz(self, now=None, vynutit=False):
        """Zapíše změny nejvýš jednou za interval_s (vynutit=True hned). True = zapsáno."""
        try:
            now = time.time() if now is None else now
            if not self.zmeneno and not vynutit:
                return False
            if not vynutit and now - self.posledni_ulozeni < self.interval_s:
                return False
            uloziste.zapis(self.cesta, {
                "v": 1, "xp": self.xp, "citace": self.c, "uspechy": self.odemceno,
                "nastroje": sorted(self.nazvy), "posledni_den": self.posledni_den,
                "testy_cervene": self._testy_cervene, "xp_den": list(self.xp_den)})
            self.zmeneno, self.posledni_ulozeni = False, now
            return True
        except Exception:
            lg.exception("postup nejde uložit")
            return False
