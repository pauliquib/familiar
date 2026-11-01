# Denní statistiky práce s agentem (druhá etapa, M10a). Bez UI a bez Qt.
#
# zapocti() bere události ve společném schématu (familiar/adapters/claude_code.py),
# vzorek_nalady() bod (valence, aktivace); obojí se sčítá do dne podle místního
# času (nebo podle tz z konstruktoru). Do $XDG_STATE_HOME/familiar/statistiky.json
# (0600) jdou jen čísla a názvy nástrojů: nikdy text promptu, příkaz, chyba ani cesta.
#   {"v": 1, "dny": {"2026-10-23": {"session": 2, "prompty": 14, "nastroje": {"Bash": 30},
#    "chyby": 3, "selhani": 0, "preruseni": 1, "zamitnuti": 0, "subagenti": 2, "compacty": 0,
#    "aktivni_s": 5400.0, "nalada": {"14": [součet valence, součet aktivace, počet]}}},
#    "stav": {"posledni": čas poslední události, "den": "2026-10-23", "session": [otisk…]}}
# Aktivní čas = mezery mezi libovolnými událostmi (i subagentů a úloh na pozadí, ze všech
# session dohromady) kratší než MEZERA_S; při běžícím nástroji (dlouhý build) i delší, nejvýš
# MAX_NASTROJ_S. Interval přes půlnoc se rozdělí. session = počet různých session_id za den;
# do souboru jde jen zkrácený SHA-256 otisk id za poslední den (počítání pokračuje po restartu),
# stejně jako čas poslední události (mezera přes restart daemonu se započte).
# uloz() volá daemon z časovače: zapíše nejvýš jednou za interval_s, atomicky.
# Žádná metoda nevyhodí výjimku do volajícího; rozbitý soubor = záloha a nový začátek.
import hashlib, logging, math, re, time
from datetime import date, datetime, timedelta

from familiar import uloziste

lg = logging.getLogger("familiar.stats")

JMENO = "statistiky.json"
RETENCE_DNI = 365
INTERVAL_S = 60.0       # throttling uloz()
MEZERA_S = 300.0        # jako mood.GAP_S: delší ticho se do aktivního času nepočítá
MAX_NASTROJ_S = 2 * 3600    # mezera při běžícím nástroji se započte nejvýš takhle dlouhá
OTISK_RE = re.compile(r"[0-9a-f]{16}")
MAX_OTISKU = 2000
CITACE = ("session", "prompty", "chyby", "selhani", "preruseni", "zamitnuti", "subagenti", "compacty")
NASTROJ_RE = re.compile(r"[A-Za-z0-9_.:\-]{1,64}")   # MCP nástroje: mcp__server__tool
JINY = "jiny"           # nástroj s podivným názvem se nezapíše jménem
MAX_NASTROJU = 200      # různých názvů za den, zbytek → JINY
KONEC_KOLA = {"agent.done", "agent.failed", "agent.interrupted", "session.end"}
KONEC_NASTROJE = {"tool.end", "tool.error", "tool.denied"}
_HODINY = {str(h) for h in range(24)}


def soubor():
    return uloziste.soubor(JMENO)


def _prazdny_den():
    d = {k: 0 for k in CITACE}
    d.update(nastroje={}, aktivni_s=0.0, nalada={})
    return d


def _cisty_den(raw):
    """Den z načteného souboru: neznámé klíče pryč, čísla zkontrolovaná."""
    d = _prazdny_den()
    if not isinstance(raw, dict):
        return d
    for k in CITACE:
        d[k] = uloziste.cele(raw.get(k))
    n = raw.get("nastroje")
    if isinstance(n, dict):
        d["nastroje"] = {k: uloziste.cele(v) for k, v in n.items()
                         if isinstance(k, str) and NASTROJ_RE.fullmatch(k)}
    d["aktivni_s"] = uloziste.cislo(raw.get("aktivni_s"), 0.0, 86400.0)
    m = raw.get("nalada")
    if isinstance(m, dict):
        for h, s in m.items():
            if h in _HODINY and isinstance(s, list) and len(s) == 3:
                cnt = uloziste.cele(s[2])
                if cnt:
                    d["nalada"][h] = [uloziste.cislo(s[0], -cnt, cnt), uloziste.cislo(s[1], 0.0, cnt), cnt]
    return d



def otisk(session):
    """Zkrácený SHA-256 otisk session_id (do souboru nejde samotné id)."""
    return hashlib.sha256(session.encode(errors="replace")).hexdigest()[:16]


def _datum(x):
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(x)


class Statistiky:
    def __init__(self, cesta=None, retence_dni=RETENCE_DNI, interval_s=INTERVAL_S, tz=None, zalohovat=True):
        self.cesta = cesta or soubor()
        self.retence_dni, self.interval_s, self.tz = retence_dni, interval_s, tz
        self.dny = {}
        self.zmeneno = False
        self.posledni_ulozeni = float("-inf")
        self._posledni = None   # čas poslední události (aktivní čas)
        self._bezi = {}         # (klíč, agent, tool_use_id) → začátek běžícího nástroje
        self._session = {}      # den → (otisky session_id, počet před prvním otiskem)
        self._preruseno = {}    # klíč → přerušení v tomto kole už započteno
        try:
            raw = uloziste.nacti(self.cesta, zalohovat)
            dny = raw.get("dny") if isinstance(raw.get("dny"), dict) else {}
            for k, v in dny.items():
                try:
                    self.dny[date.fromisoformat(k).isoformat()] = _cisty_den(v)
                except (TypeError, ValueError):
                    continue
            self._nacti_stav(raw.get("stav"))
        except Exception:
            lg.exception("statistiky nejde načíst, začínám znovu")
            self.dny = {}

    def _nacti_stav(self, st):
        """Stav po minulém běhu (soubor ze starší verze ho nemá: session se dopočítají od
        uloženého počtu, aktivní čas začne první událostí)."""
        if not isinstance(st, dict):
            return
        p = st.get("posledni")
        if isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and p > 0:
            self._posledni = float(p)
        den, otisky = st.get("den"), st.get("session")
        if isinstance(den, str) and den in self.dny and isinstance(otisky, list):
            ok = {o for o in otisky[:MAX_OTISKU] if isinstance(o, str) and OTISK_RE.fullmatch(o)}
            self._session[den] = (ok, self.dny[den]["session"])

    def _stav(self):
        den = max(self._session, default=None)
        return {"posledni": self._posledni, "den": den,
                "session": sorted(self._session[den][0]) if den else []}

    # --- čas ----------------------------------------------------------------------

    def _dt(self, ts):
        return datetime.fromtimestamp(ts, self.tz)

    def _den(self, ts):
        k = self._dt(ts).date().isoformat()
        d = self.dny.get(k)
        if d is None:
            d = self.dny[k] = _prazdny_den()
        return d

    def _pridej_cas(self, od, do):
        """Interval [od, do) do aktivního času, rozdělený na místních půlnocích."""
        do = min(do, od + MAX_NASTROJ_S)
        while do > od:
            dt = self._dt(od)
            pulnoc = datetime.combine(dt.date() + timedelta(days=1), datetime.min.time(), dt.tzinfo)
            hranice = min(do, pulnoc.timestamp())
            if hranice <= od:       # přechod času: aspoň posun o sekundu
                hranice = min(do, od + 1)
            d = self._den(od)
            d["aktivni_s"] = min(86400.0, d["aktivni_s"] + (hranice - od))
            od = hranice
        self.zmeneno = True

    # --- vstup --------------------------------------------------------------------

    def zapocti(self, ev):
        """Započte událost ve společném schématu; vadnou tiše přeskočí."""
        try:
            self._zapocti(ev)
        except Exception:
            lg.exception("statistiky: událost nejde započíst")

    def _zapocti(self, ev):
        kind, ts = ev.get("kind"), ev.get("ts")
        if not isinstance(kind, str) or isinstance(ts, bool) or not isinstance(ts, (int, float)) \
                or not math.isfinite(ts):
            return
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        key = ev.get("pid") or ev.get("session")
        d = self._den(ts)
        self._aktivita(ts, kind, key, data)
        sid = ev.get("session")
        if isinstance(sid, str) and sid:
            self._nova_session(ts, d, sid)
        if kind == "user.prompt":
            d["prompty"] += 1
            self._preruseno[key] = False
        elif kind == "tool.start":
            tool = data.get("tool")
            name = tool if isinstance(tool, str) and NASTROJ_RE.fullmatch(tool) else JINY
            if name not in d["nastroje"] and len(d["nastroje"]) >= MAX_NASTROJU:
                name = JINY
            d["nastroje"][name] = d["nastroje"].get(name, 0) + 1
        elif kind == "tool.error":
            d["chyby"] += 1
        elif kind == "tool.denied":
            d["zamitnuti"] += 1
        elif kind == "subagent.start":
            d["subagenti"] += 1
        elif kind == "context.compact":
            d["compacty"] += 1
        elif kind == "agent.failed":
            d["selhani"] += 1
        if kind == "agent.interrupted":
            # hook (is_interrupt) i transcript hlásí totéž přerušení: v kole platí jen jedno
            if self._preruseno.get(key):
                return
            self._preruseno[key] = True
            d["preruseni"] += 1
        if kind == "session.end":
            self._preruseno.pop(key, None)
        self.zmeneno = True

    def _aktivita(self, ts, kind, key, data):
        """Mezera od poslední události do aktivního času: kratší než MEZERA_S vždy, delší
        jen při běžícím nástroji (nejvýš MAX_NASTROJ_S, viz _pridej_cas)."""
        self._bezi = {k: t for k, t in self._bezi.items() if ts - t < MAX_NASTROJ_S}
        p = self._posledni
        if p is not None and ts > p and (ts - p <= MEZERA_S or self._bezi):
            self._pridej_cas(p, ts)
        if p is None or ts > p:
            self._posledni = ts
            self.zmeneno = True
        agent, tid = data.get("agent"), data.get("id")
        if kind == "tool.start" and tid:
            self._bezi[(key, agent, tid)] = ts
        elif kind in KONEC_NASTROJE:
            self._bezi.pop((key, agent, tid), None)
        elif kind == "session.end":
            self._bezi = {k: t for k, t in self._bezi.items() if k[0] != key}
        elif kind in KONEC_KOLA and not agent:      # hlavní agent skončil: jeho nástroje taky
            self._bezi = {k: t for k, t in self._bezi.items() if k[0] != key or k[1]}

    def _nova_session(self, ts, d, sid):
        den = self._dt(ts).date().isoformat()
        if den not in self._session:
            self._session[den] = (set(), d["session"])      # počet z dřívějška (starší verze)
            for k in sorted(self._session)[:-2]:            # starší dny už nepotřebujeme
                del self._session[k]
        otisky, zaklad = self._session.get(den, (set(), d["session"]))
        o = otisk(sid)
        if o not in otisky and len(otisky) < MAX_OTISKU:
            otisky.add(o)
            d["session"] = max(zaklad, len(otisky))

    def vzorek_nalady(self, ts, v, a):
        """Bod nálady do hodinového průměru (valence −1…1, aktivace 0…1, ořízne se)."""
        try:
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                       for x in (ts, v, a)):
                return
            h = str(self._dt(ts).hour)
            s = self._den(ts)["nalada"].setdefault(h, [0.0, 0.0, 0])
            s[0] += max(-1.0, min(1.0, float(v)))
            s[1] += max(0.0, min(1.0, float(a)))
            s[2] += 1
            self.zmeneno = True
        except Exception:
            lg.exception("statistiky: vzorek nálady nejde započíst")

    # --- výstup -------------------------------------------------------------------

    def den(self, datum):
        """Kopie dne (date, datetime nebo 'YYYY-MM-DD'); nálada jako {hodina: (valence, aktivace)}.
        Den bez dat má nuly."""
        try:
            dt = _datum(datum)
        except (TypeError, ValueError):
            dt = None
        d = self.dny.get(dt.isoformat()) if dt else None
        d = d or _prazdny_den()
        out = {k: d[k] for k in CITACE}
        out.update(datum=dt.isoformat() if dt else None, nastroje=dict(d["nastroje"]),
                   volani=sum(d["nastroje"].values()), aktivni_s=round(d["aktivni_s"], 1),
                   nalada={int(h): (round(s[0] / s[2], 4), round(s[1] / s[2], 4))
                           for h, s in sorted(d["nalada"].items(), key=lambda x: int(x[0]))})
        return out

    def tyden(self, datum):
        """Týden (pondělí–neděle) obsahující datum: {"od", "do", "dny": [den…], "soucet": {…}}.
        Součet má citače, nástroje, volání, aktivní čas a průměr nálady za týden."""
        try:
            dt = _datum(datum)
        except (TypeError, ValueError):
            dt = date.today()
        po = dt - timedelta(days=dt.weekday())
        dny = [self.den(po + timedelta(days=i)) for i in range(7)]
        soucet = {k: sum(d[k] for d in dny) for k in CITACE}
        nastroje = {}
        for d in dny:
            for k, v in d["nastroje"].items():
                nastroje[k] = nastroje.get(k, 0) + v
        sv = sa = n = 0
        for d in dny:
            for h, s in self.dny.get(d["datum"], {}).get("nalada", {}).items():
                sv, sa, n = sv + s[0], sa + s[1], n + s[2]
        soucet.update(nastroje=nastroje, volani=sum(nastroje.values()),
                      aktivni_s=round(sum(d["aktivni_s"] for d in dny), 1),
                      nalada=(round(sv / n, 4), round(sa / n, 4)) if n else None)
        return {"od": po.isoformat(), "do": (po + timedelta(days=6)).isoformat(), "dny": dny, "soucet": soucet}

    # --- ukládání -----------------------------------------------------------------

    def _orizni(self, now):
        hranice = (self._dt(now).date() - timedelta(days=self.retence_dni)).isoformat()
        for k in [k for k in self.dny if k < hranice]:
            del self.dny[k]

    def uloz(self, now=None, vynutit=False):
        """Zapíše změny, nejvýš jednou za interval_s (vynutit=True: hned, např. při ukončení).
        Starší dny než retence zahodí. Vrací True, když zapsal."""
        try:
            now = time.time() if now is None else now
            if not self.zmeneno and not vynutit:
                return False
            if not vynutit and now - self.posledni_ulozeni < self.interval_s:
                return False
            self._orizni(now)
            uloziste.zapis(self.cesta, {"v": 1, "dny": self.dny, "stav": self._stav()})
            self.zmeneno, self.posledni_ulozeni = False, now
            return True
        except Exception:
            lg.exception("statistiky nejde uložit")
            return False


# --- souhrn pro okno statistik a `familiar statistiky` ---------------------------------

DNY = ("Po", "Út", "St", "Čt", "Pá", "So", "Ne")


def cas(s):
    """Sekundy → „1 h 05 min“ / „12 min“."""
    m = int(round((s or 0) / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def prehled(statistiky=None, postup=None, cfg=None, now=None):
    """Jen čísla a názvy: {"ted", "datum", "dnes", "tyden", "postup", "volba"}; dnes/tyden/postup
    jsou None, když statistiky/postup nejsou (vypnuté). Daemon dává své instance (sluzby.Sluzby),
    CLI instance načtené ze souborů."""
    now = time.time() if now is None else now
    dnes = datetime.fromtimestamp(now, statistiky.tz if statistiky else None).date()
    out = {"ted": now, "datum": dnes.isoformat(), "dnes": None, "tyden": None, "postup": None, "volba": None}
    if statistiky is not None:
        out["dnes"], out["tyden"] = statistiky.den(dnes), statistiky.tyden(dnes)
    if postup is not None:
        from familiar import progress
        n = postup.uroven
        out["postup"] = {"uroven": n, "xp": postup.xp, "xp_od": progress.xp_na_uroven(n),
                         "xp_do": progress.xp_na_uroven(n + 1) if n < progress.MAX_UROVEN else postup.xp,
                         "do_dalsi": postup.do_dalsi, "uspechy": postup.uspechy(), "doplnky": postup.doplnky()}
    if cfg is not None:
        out["volba"] = {k: cfg["postup"][k] for k in ("doplnek_klobouk", "klobouk_vzdy", "emoty_v_klidu")}
    return out
