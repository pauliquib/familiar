# Téma rozhovoru → doplněk na hlavě postavičky (vrstva acc z kapitoly 5).
#
# Body za klíčová slova v promptech, nástroje a příkazy; s časem vyprchávají
# (poločas ~15 min), takže téma se samo přepne, když se rozhovor stočí jinam.
# Konstanty jsou výchozí hodnoty sekce [temata] configu (familiar/config.py).
import functools, math, re

from familiar.mood import norm

TAU = 1300.0          # s, poločas ~15 min
SHOW = 1.5            # od kolika bodů se téma ukáže
LEAD = 1.3            # o kolik musí vést před druhým
WORD_PTS = 0.8        # body za každé různé klíčové slovo v promptu
WORD_MAX = 3          # nejvýš tolik slov z jednoho promptu
CWD_PTS = 0.8         # klíčové slovo v adresáři projektu

ELEKTRONIKA, KOD, WEB, STUDIUM, RESERSE, SYSTEM = (
    "elektronika", "kod", "web", "studium", "reserse", "system")

HAT = {ELEKTRONIKA: "hardhat", KOD: "headphones", WEB: "beret", STUDIUM: "mortarboard",
       RESERSE: "explorer", SYSTEM: "cap"}


def _rx(words):
    return re.compile(r"\b(" + "|".join(words) + r")")


WORD_LISTS = {   # začátky slov bez diakritiky; \b jen na začátku, takže chytí i tvary
    ELEKTRONIKA: ["pcb", "kicad", "desk[auy]", "desce", "soucastk", "rezistor", "kondenzator", "esp32",
                  "stm32", "mcu", "jlcpcb", "footprint", "gerber", "pajen", "napet", "osciloskop",
                  "senzor", "radar", "anten", "ghz", "mhz", "obvod", "cip", "arduino", "uart", "i2c",
                  "firmware", "schemat", "spoj", "konektor", "routing", "via\\b", "silkscreen"],
    KOD: ["funkc", "bug", "refaktor", "refactor", "python", "rust", "javascript", "typescript", "kompil",
          "compil", "build", "commit", "merge", "api\\b", "tridu", "trida", "kod", "skript", "script",
          "program", "implement", "test", "debug", "promenn", "variable", "repo", "fsm", "modul"],
    WEB: ["web", "strank", "landing", "css", "html", "design", "ui\\b", "ux\\b", "barv", "font", "logo",
          "layout", "responsiv", "eshop", "e-shop", "wordpress", "figma", "animac", "ikon", "pixel"],
    STUDIUM: ["clan", "esej", "seminar", "studi", "skol", "prednask", "zkousk", "referat", "prezentac",
              "docx", "pdf", "preklad", "citac", "literatur", "kapitol", "odstav", "text", "dopis",
              "email", "mail", "napis", "formulac", "gramatik"],
    RESERSE: ["vyhledej", "najdi", "zjisti", "porovne", "porovnej", "research", "reserse", "zdroj",
              "recenz", "cen[auy]\\b", "kolik stoji", "srovnani", "trh", "konkurenc"],
    SYSTEM: ["linux", "fedora", "kde", "wayland", "nastaven", "config", "settings", "server", "docker",
             "ssh", "systemd", "instal", "ovladac", "driver", "hook", "terminal", "kitty", "fish",
             "bash", "disk", "oddil", "balic", "dnf", "flatpak", "plasma", "kwin"],
}

WORDS = {topic: _rx(words) for topic, words in WORD_LISTS.items()}

TOOLS = {"WebSearch": (RESERSE, 0.3), "WebFetch": (RESERSE, 0.3), "Edit": (KOD, 0.1),
         "Write": (KOD, 0.05), "NotebookEdit": (KOD, 0.1)}

COMMAND_LIST = [   # (regex hledaný v příkazu Bash, téma, body)
    (r"kicad-cli|kicad\b|\.kicad_", ELEKTRONIKA, 0.5),
    (r"\b(pytest|cargo|npm|npx|node|python3?|go|git|make|gcc|rustc|uv|pip)\b", KOD, 0.2),
    (r"\b(systemctl|dnf|flatpak|kwriteconfig6|qdbus|journalctl|sudo|mount|lsblk)\b", SYSTEM, 0.3),
    (r"\b(pandoc|libreoffice|soffice|pdftotext|docx)\b", STUDIUM, 0.3),
]
COMMANDS = [(re.compile(rx), topic, pts) for rx, topic, pts in COMMAND_LIST]


def defaults():
    """Sekce [temata] configu z konstant modulu."""
    return {"tau_s": TAU, "ukazat": SHOW, "naskok": LEAD, "za_slovo": WORD_PTS, "max_slov": WORD_MAX,
            "za_adresar": CWD_PTS, "klobouky": dict(HAT),
            "slova": {t: list(w) for t, w in WORD_LISTS.items()},
            "nastroje": {tool: {"tema": t, "body": pts} for tool, (t, pts) in TOOLS.items()},
            "prikazy": [{"regex": rx, "tema": t, "body": pts} for rx, t, pts in COMMAND_LIST]}


@functools.lru_cache(maxsize=64)
def _words_rx(words):
    return _rx(words)


@functools.lru_cache(maxsize=64)
def _cmd_rx(rx):
    return re.compile(rx)


class TopicTracker:
    def __init__(self, now=0.0, cfg=None):
        self.configure(cfg)
        self.score = {}
        self.t = now
        self.topic = None

    def configure(self, cfg=None):
        """Nastaví sekci [temata] (validovanou, viz familiar/config.py); body zůstanou."""
        self.c = c = cfg or defaults()
        self.words = {t: _words_rx(tuple(w)) for t, w in c["slova"].items() if w}
        self.tools = {tool: (v["tema"], v["body"]) for tool, v in c["nastroje"].items()}
        self.commands = [(_cmd_rx(p["regex"]), p["tema"], p["body"]) for p in c["prikazy"]]

    def _decay(self, now):
        k = math.exp(-max(0.0, now - self.t) / self.c["tau_s"])
        self.score = {t: s * k for t, s in self.score.items() if s * k > 0.05}
        self.t = now

    def _add(self, topic, pts):
        self.score[topic] = self.score.get(topic, 0.0) + pts

    def feed(self, ev):
        ts, kind, data = ev["ts"], ev["kind"], ev["data"]
        self._decay(ts)
        if kind == "user.prompt":
            text = norm(data.get("text") or "")
            for topic, rx in self.words.items():
                hits = len(set(m.group(0) for m in rx.finditer(text)))
                if hits:
                    self._add(topic, min(hits, self.c["max_slov"]) * self.c["za_slovo"])
        elif kind == "session.start" and data.get("cwd"):
            cwd = norm(data["cwd"])
            for topic, rx in self.words.items():
                if rx.search(cwd):
                    self._add(topic, self.c["za_adresar"])
        elif kind == "tool.start":
            if data.get("tool") in self.tools:
                self._add(*self.tools[data["tool"]])
            cmd = data.get("cmd") or ""
            for rx, topic, pts in self.commands:
                if rx.search(cmd):
                    self._add(topic, pts)
        self._pick()

    def _pick(self):
        ranked = sorted(self.score.items(), key=lambda kv: -kv[1])
        if not ranked or ranked[0][1] < self.c["ukazat"]:
            self.topic = None
        elif len(ranked) == 1 or ranked[0][1] >= self.c["naskok"] * ranked[1][1]:
            self.topic = ranked[0][0]
        elif self.topic not in (ranked[0][0], ranked[1][0]):
            self.topic = ranked[0][0]
        # jinak drží dosavadní téma z prvních dvou, aby neblikalo

    def advance(self, now):
        self._decay(now)
        self._pick()
        return self.topic
