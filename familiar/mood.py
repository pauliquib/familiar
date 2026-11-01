# Mood engine (kapitola 3.2–3.4 konceptu): valence a aktivace, z nich štítek.
#
# Jako automat činnosti bere čas jen z událostí a z advance(now). Texty promptů
# zpracuje v paměti a zahodí. feed() vrací jednorázové reakce („pops“), které
# renderer přehraje nad hlavou postavičky.
#
# Konstanty níže jsou výchozí hodnoty sekce [nalada] configu (familiar/config.py);
# engine čte hodnoty ze sekce, kterou dostane (bez ní z defaults()).
import difflib, functools, math, re, unicodedata

TAU_V, TAU_A = 300.0, 90.0
BASE_V, BASE_A = 0.0, 0.2
HOLD_S = 4.0            # hystereze štítku
MANUAL_S = 600.0        # nálada zvolená v panelu platí tolik s
QUESTIONS_N = 6         # z kolika posledních promptů se počítá podíl otázek
REPEAT_S = 600.0        # opakovaná prosba: podobnost s prompty za posledních 10 min
CONFUSION_S = 300.0     # zmatek = korekce za posledních 5 min
GAP_S = 300.0           # delší pauza se do aktivního času nepočítá
REST_S = 1800.0         # po půl hodině klidu únava zmizí
REPEAT_RATIO = 0.8      # od jaké podobnosti je prompt opakovaná prosba
REPEAT_MIN = 15         # kratší prompty se na opakování nehodnotí
SHARP_LETTERS = 12      # ostrý tón verzálkami: aspoň tolik písmen
SHARP_UPPER = 0.6       # a takový podíl velkých
STREAK_N = 3            # od kolikáté chyby nástroje za sebou jde o sérii

IMPULSES = {   # signál → (Δ valence, Δ aktivace), tabulka 3.3
    "dekovani": (0.35, 0.05), "korekce": (-0.20, 0.10), "ostry_ton": (-0.30, 0.30),
    "opakovani": (-0.20, 0.20), "otazka": (0.05, 0.10), "chyba_nastroje": (-0.10, 0.15),
    "serie_chyb": (-0.25, 0.25), "testy": (0.20, 0.10), "preruseni": (-0.15, 0.20),
    "zamitnuti": (-0.05, 0.05), "kolo_bez_chyb": (0.06, 0.02)}
THRESHOLDS = {   # štítky, tabulka 3.4 (vyhodnocuje se shora)
    "zmatek_korekci": 2, "frustrace_valence": -0.3, "frustrace_aktivace": 0.5, "unava": 0.7,
    "radost_valence": 0.3, "zvedavost_aktivace": 0.3, "zvedavost_valence": 0.0,
    "zvedavost_otazek": 2, "zvedavost_podil": 0.5}
FATIGUE = {"kol": 60, "hodin": 6.0, "za_komprimaci": 0.15}   # kdy je únava plná (1,0)

KLID, RADOST, ZVEDAVOST, FRUSTRACE, ZMATEK, UNAVA = (
    "klid", "radost", "zvedavost", "frustrace", "zmatek", "unava")


def norm(text):
    """Malá písmena bez diakritiky."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _rx(words, end=r"\b"):
    return re.compile(r"\b(" + "|".join(words) + ")" + end)


THANKS_WORDS = [r"dik\w*", r"dekuj\w*", "super", r"parad\w*", r"vyborn\w*", r"skvel\w*", r"perfekt\w*",
                "bezva", "paradni", "funguje to", "uz to funguje", "dobra prace", "thanks?", "thank you",
                "great", "awesome", "perfect", "nice", "good job", "well done"]
CORRECTION_WORDS = [r"^ne", "to jsem nemyslel", "nemyslel jsem", "zase", r"spatn\w*", r"nefunguj\w*",
                    "porad", "stale", "furt", "nesedi", "to neni", "to nechci", "proc jsi", r"neudelal\w*",
                    "znovu", "jeste jednou", "wrong", "not what", "again", "still", "doesn'?t work", "broken"]
VULGAR_WORDS = [r"kurv\w*", r"pic[aeiou]\w*", "sakra", "do prdele", r"hovn\w*", r"zasran\w*", r"debil\w*",
                r"kokot\w*", r"fuck\w*", "shit", "damn", r"wtf"]
QUESTION_WORDS = ["jak", "proc", "co", "kde", "kdy", "kolik", "muzes", "umis", "neslo by", "what", "how",
                  "why", "can you"]     # začátky otázek; otazník se počítá vždy
TESTS_WORDS = ["pytest", "unittest", "cargo (test|build|check|clippy)", "npm (run )?(test|build)",
               "go (test|build)", r"make\b", "ctest", "jest", "vitest", r"tsc\b", "mvn", "gradle",
               r"kicad-cli \w+ (drc|erc)"]


def _question_rx(words):
    return re.compile(r"\?|^(" + "|".join(words) + r")\b")


@functools.lru_cache(maxsize=16)
def _compile(thanks, correction, vulgar, question, tests):
    """Regexy ze seznamů slov (n-tice kvůli cache: stejný config se nekompiluje znovu)."""
    return {"dekovani": _rx(thanks), "korekce": _rx(correction), "vulgarismy": _rx(vulgar),
            "otazky": _question_rx(question), "testy": _rx(tests, end="")}


def compile_words(words):
    """Sekce [nalada.slova] → slovník regexů; nevalidní regex vyhodí re.error."""
    return _compile(*(tuple(words[k]) for k in ("dekovani", "korekce", "vulgarismy", "otazky", "testy")))


_DEFAULT_RX = compile_words({"dekovani": THANKS_WORDS, "korekce": CORRECTION_WORDS, "vulgarismy": VULGAR_WORDS,
                             "otazky": QUESTION_WORDS, "testy": TESTS_WORDS})
THANKS, CORRECTION, VULGAR, QUESTION, TESTS = (
    _DEFAULT_RX[k] for k in ("dekovani", "korekce", "vulgarismy", "otazky", "testy"))


def defaults():
    """Sekce [nalada] configu z konstant modulu."""
    return {
        "tau_valence_s": TAU_V, "tau_aktivace_s": TAU_A, "zaklad_valence": BASE_V, "zaklad_aktivace": BASE_A,
        "hystereze_s": HOLD_S, "rucne_s": MANUAL_S, "otazky_n": QUESTIONS_N, "opakovani_s": REPEAT_S,
        "opakovani_podobnost": REPEAT_RATIO, "opakovani_min_znaku": REPEAT_MIN, "zmatek_s": CONFUSION_S,
        "pauza_s": GAP_S, "odpocinek_s": REST_S, "vlastni_znaky": OWN_N, "ostry_min_pismen": SHARP_LETTERS,
        "ostry_podil_verzalek": SHARP_UPPER, "serie_chyb_n": STREAK_N,
        "impulsy": {k: list(v) for k, v in IMPULSES.items()},
        "prahy": dict(THRESHOLDS),
        "unava": dict(FATIGUE),
        "slova": {"dekovani": list(THANKS_WORDS), "korekce": list(CORRECTION_WORDS),
                  "vulgarismy": list(VULGAR_WORDS), "otazky": list(QUESTION_WORDS), "testy": list(TESTS_WORDS)},
    }


OWN_N = 160            # vložené texty bývají až za vlastními slovy
NOISE = re.compile(r"\[image #\d+\]|\S*/\S*", re.I)


def own_words(text, n=OWN_N):
    """Začátek promptu, který napsal uživatel: bez zpráv agentů, obrázků a cest."""
    if text.lstrip().startswith("<"):
        return ""
    return NOISE.sub(" ", text)[:n].strip()


def sharp(text, min_letters=SHARP_LETTERS, upper_share=SHARP_UPPER):
    letters = [c for c in text if c.isalpha()]
    upper = sum(c.isupper() for c in letters)
    return (len(letters) >= min_letters and upper / len(letters) >= upper_share) or "!!" in text or "?!" in text


class MoodEngine:
    def __init__(self, now=0.0, cfg=None):
        self.configure(cfg)
        self.v, self.a, self.t = self.c["zaklad_valence"], self.c["zaklad_aktivace"], now
        self.corrections = []           # časy korekcí
        self.compacts = 0
        self.rounds = 0
        self.active = 0.0               # aktivní čas session, s
        self.last_event = now
        self.streak = 0                 # chyby nástrojů za sebou
        self.questions = []             # True/False u posledních promptů
        self.recent = []                # (čas, normalizovaný prompt)
        self.label = self.candidate = KLID
        self.since = now
        self.manual = None              # (štítek, do kdy) zvolený uživatelem v panelu
        self.manual_new = False

    def configure(self, cfg=None):
        """Nastaví sekci [nalada] (validovanou, viz familiar/config.py); stav zůstane."""
        self.c = cfg or defaults()
        self.rx = compile_words(self.c["slova"])

    def _imp(self, name):
        self._impulse(*self.c["impulsy"][name])

    # --- čísla ---------------------------------------------------------------

    def _decay(self, now):
        c, dt = self.c, max(0.0, now - self.t)
        bv, ba = c["zaklad_valence"], c["zaklad_aktivace"]
        self.v = bv + (self.v - bv) * math.exp(-dt / c["tau_valence_s"])
        self.a = ba + (self.a - ba) * math.exp(-dt / c["tau_aktivace_s"])
        self.corrections = [t for t in self.corrections if now - t <= c["zmatek_s"]]
        self.t = now

    def _impulse(self, dv=0.0, da=0.0):
        self.v = max(-1.0, min(1.0, self.v + dv))
        self.a = max(0.0, min(1.0, self.a + da))

    @property
    def fatigue(self):
        f = self.c["unava"]
        return min(1.0, self.rounds / f["kol"] + self.active / 3600 / f["hodin"] + f["za_komprimaci"] * self.compacts)

    def _classify(self):
        p = self.c["prahy"]
        if len(self.corrections) >= p["zmatek_korekci"]:
            return ZMATEK
        if self.v <= p["frustrace_valence"] and self.a >= p["frustrace_aktivace"]:
            return FRUSTRACE
        if self.fatigue >= p["unava"]:
            return UNAVA
        if self.v >= p["radost_valence"]:
            return RADOST
        q = self.questions[-self.c["otazky_n"]:]
        if (q and self.a >= p["zvedavost_aktivace"] and self.v >= p["zvedavost_valence"]
                and len(q) >= p["zvedavost_otazek"] and sum(q) / len(q) >= p["zvedavost_podil"]):
            return ZVEDAVOST
        return KLID

    def take(self, label, now):
        """Štítek zvolený uživatelem v panelu nálady: platí hned a drží rucne_s sekund,
        pak štítek zase určují čísla (s hysterezí)."""
        s = self.c.get("rucne_s", MANUAL_S)
        if s <= 0:
            return
        self.manual = (label, now + s)
        self.label = self.candidate = label
        self.since, self.manual_new = now, True

    def advance(self, now):
        """Posune čas; vrací (štítek, změnil se)."""
        self._decay(now)
        if self.manual:
            if now < self.manual[1]:
                changed, self.manual_new = self.manual_new, False
                return self.label, changed
            self.manual = None
        new = self._classify()
        if new != self.candidate:
            self.candidate, self.since = new, now
        elif new != self.label and now - self.since >= self.c["hystereze_s"]:
            self.label = new
            return self.label, True
        return self.label, False

    # --- signály (tabulka 3.3) -----------------------------------------------

    def _prompt(self, ts, text):
        c, rx = self.c, self.rx
        pops = ["camera"] if "[image #" in text.lower() else []
        text = own_words(text, c["vlastni_znaky"])
        if not text:
            return pops
        n = norm(text)
        if rx["dekovani"].search(n):
            self._imp("dekovani")
            pops.append("heart")
        if rx["korekce"].search(n):
            self._imp("korekce")
            self.corrections.append(ts)
        if sharp(text, c["ostry_min_pismen"], c["ostry_podil_verzalek"]) or rx["vulgarismy"].search(n):
            self._imp("ostry_ton")
            pops.append("grawlix")
        self.recent = [(t, p) for t, p in self.recent if ts - t <= c["opakovani_s"]]
        if len(n) >= c["opakovani_min_znaku"] and any(
                difflib.SequenceMatcher(None, n, p).ratio() > c["opakovani_podobnost"] for _, p in self.recent):
            self._imp("opakovani")
        self.recent.append((ts, n))
        is_q = bool(rx["otazky"].search(n.strip()))
        if is_q:
            self._imp("otazka")
        self.questions = (self.questions + [is_q])[-c["otazky_n"]:]
        return pops

    def feed(self, ev):
        ts, kind, data = ev["ts"], ev["kind"], ev["data"]
        self._decay(ts)
        gap = ts - self.last_event
        if gap >= self.c["odpocinek_s"]:
            self._rest()
        else:
            self.active += min(max(gap, 0.0), self.c["pauza_s"])
        self.last_event = ts
        if data.get("agent"):
            return []           # subagenti náladu hlavní postavičky neovlivňují
        if kind == "user.prompt":
            return self._prompt(ts, data.get("text") or "")
        if kind == "tool.error":
            self.streak += 1
            n = self.c["serie_chyb_n"]
            if self.streak == n:
                self._imp("serie_chyb")         # místo jednotlivých
            elif self.streak < n:
                self._imp("chyba_nastroje")
            return []
        if kind == "tool.end":
            self.streak = 0
            if self.rx["testy"].search(data.get("cmd") or "") and not data.get("killed"):
                self._imp("testy")
                return ["check"]
            return []
        if kind == "agent.interrupted":
            self._imp("preruseni")
        elif kind == "tool.denied":
            self._imp("zamitnuti")
        elif kind == "context.compact":
            self.compacts += 1
        elif kind == "agent.done":
            self.rounds += 1
            if not self.streak:
                self._imp("kolo_bez_chyb")      # kolo bez chyby na konci
                if self.label == RADOST:
                    return ["flower"]           # daří se: hotové kolo bez chyby v radosti
        elif kind == "agent.failed":
            return ["coffee"] if data.get("error") == "rate_limit" else []
        elif kind == "session.start" and data.get("how") in ("startup", "clear"):
            self._rest()
        return []

    def _rest(self):
        self.rounds = self.compacts = 0
        self.active = 0.0
