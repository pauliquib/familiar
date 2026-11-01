# Jádro daemonu bez UI: datagramy z emitteru → automat pro každý proces claude.
#
# Familiar patří procesu claude (pid), ne session: /clear a resume ve stejném
# okně založí novou session, ale postavička zůstává. Čas se předává zvenku,
# takže stejný kód obslouží živý provoz i přehrávání nahrávek.
#
# Konstanty jsou výchozí hodnoty configu (familiar/config.py); Hub i Familiar
# dostanou celý efektivní config a configure() ho umí vyměnit za běhu.
# Vzhled (animace, emoty a tempo nálad) dává skin (familiar/skin.py) podle volby
# `skin`; hub ho drží a renderer kreslí přes hub.skin.
# Přerušení (Esc) nemá hook: hub sleduje transcript_path každého familiara
# (familiar/transcript.py) a poll_transcripts() z něj dělá událost agent.interrupted.
# Pro panel nálady drží každý familiar hodinu vzorků (čas, valence, aktivace) a druhy
# posledních událostí (jen identifikátory, nikdy text promptu); stav_panelu() je složí.
# Uspání (z nabídky) je jen za běhu: postavička spí, dokud ji uživatel nevzbudí.
# Posluchači (Hub.posluchaci, např. familiar/sluzby.py) dostanou (familiar, událost) po každé
# události, kterou familiar přijal; chyba posluchače se zaloguje a nic nezastaví.
# Události agentů vypnutých v [agenti] (gemini, codex) hub zahodí.
# Vrstvy u postavičky (logika ve familiar/vrstvy.py, renderer je jen kreslí): bublina()
# – žádost o povolení, krátká zpráva (oznam, varování kontextu) nebo činnost; meric()
# z transcriptu (poll_kontext); pomocnici_ted() za subagenty. Požadavky na povolení
# předává server (familiar/povoleni.py) přes pozadavek(); které zrušit, hlásí hub přes on_zrus.
# Odemčené doplňky (progress.DOPLNKY) dodá sluzby.py přes nastav_doplnky(): oblíbený klobouk
# (když téma nemá vlastní, s [postup] klobouk_vzdy vždy) a emoty, které se střídají v klidu.
# oslav() = krátká animace success (nová úroveň).
# Procházky a reakce na myš (logika ve familiar/pohyb.py): renderer před update() nastaví
# meze (kam nejdál smí na procházce) a po něm čte chuze; události myši posílá přes reaguj().
import json, logging, os, time
from collections import deque

from familiar import adapters, log, pohyb, skin as skins, vrstvy
from familiar.adapters.claude_code import SOURCE
from familiar.fsm import IDLE, ActivityFSM, ERROR, GONE, LISTENING, SLEEPING, SUCCESS, THINKING, WAITING, WORKING
from familiar.mood import KLID, MoodEngine
from familiar.topic import TopicTracker
from familiar.transcript import INTERRUPTED_TOOL, TranscriptWatchers

SETTLE_S = 0.35     # trvalý stav se ukáže, až vydrží; vyhladí záblesky z kapitoly 3.1
LEAVE_S = 3.0       # po session.end zmizí, pokud nepřijde nová session
REAP_S = 5.0        # jak často kontrolovat, že proces claude žije
URGENT = {LISTENING, ERROR, SUCCESS}   # jednorázové stavy se ukážou hned
KONEC_KOLA = ("agent.done", "agent.failed", "agent.interrupted", "session.end")
POP_S = 2.5         # jak dlouho visí emote nad hlavou
POP_GAP_S = 2.5     # pravidlo klidu: nejvýš jedna výrazná reakce za 5 s
POP_QUEUE = 2
FADE_STEP_S = 0.08  # přechod palety při změně nálady: 3 kroky po 80 ms (kapitola 5)
FADE_STEPS = 3
HIST_S = 15.0       # panel nálady: vzorek valence/aktivace každých 15 s …
HIST_N = 240        # … za poslední hodinu
UDALOSTI_N = 8      # druhy posledních událostí v panelu
OSLAVA_S = 1.5      # oslava nové úrovně: tak dlouho animace success

lg = logging.getLogger("familiar.hub")


TERMINALS = {"kitty", "konsole", "alacritty", "foot", "wezterm-gui", "ghostty", "xterm",
             "gnome-terminal-", "yakuake", "terminator", "tilix", "kgx", "ptyxis"}


def _stat(pid):
    """(jméno procesu, pid rodiče), nebo None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            head, _, rest = f.read().rpartition(")")
    except OSError:
        return None
    return head.partition("(")[2], int(rest.split()[1])


def find_terminal(pid, depth=10, terminals=TERMINALS):
    """PID emulátoru terminálu nad procesem (claude → shell → kitty), nebo None."""
    while pid and pid > 1 and depth:
        st = _stat(pid)
        if st is None:
            return None
        if st[0] in terminals:
            return pid
        pid, depth = st[1], depth - 1
    return None


def tty_of(pid):
    """Číslo terminálu (tty) procesu, nebo 0. Stejné tty = stejné okno terminálu."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            rest = f.read().rpartition(")")[2].split()
        return int(rest[4])
    except (OSError, ValueError, IndexError):
        return 0


def pid_alive(pid, source=None):
    """Žije proces agenta? Claude Code podle jména procesu, Gemini/Codex (node, codex) jen podle pid."""
    try:
        with open(f"/proc/{pid}/comm") as f:
            return source not in (None, SOURCE) or f.read().strip() == "claude"
    except OSError:
        return False


def _defaults():
    from familiar import config     # config importuje tento modul
    return config.defaults()


class Familiar:
    def __init__(self, key, pid, now, bind=True, cfg=None, skin=None):
        cfg = cfg or _defaults()
        self.skin = skin or skins.builtin()
        self.key, self.pid = key, pid
        self.term = find_terminal(pid, terminals=set(cfg["okno"]["terminaly"])) if pid and bind else None
        self.tty = tty_of(pid) if pid and bind else 0
        self.fsm = ActivityFSM(now)
        self.mood = MoodEngine(now, cfg["nalada"])
        self.topic = TopicTracker(now, cfg["temata"])
        self.pops = []              # čekající emoty
        self.pop, self.pop_since = None, float("-inf")
        self.cwd = None
        self.tool = None            # poslední nástroj hlavního agenta
        self.last_prompt = float("-inf")
        self.last_interrupt = float("-inf")
        self.kolo_od = float("-inf")    # začátek kola: prompt, nebo první událost po konci kola
        self.kolo_konec = True          # (úlohy na pozadí probudí agenta bez promptu)
        self.shown, self.shown_since = self.fsm.state, now
        self.anim, self.anim_since = self.skin.anim_for(self.shown), now
        self.mood_shown, self.fade_from, self.fade_since = KLID, None, now
        self.fade = None            # (nálada, ze které paleta přechází, krok 1..FADE_STEPS-1) nebo None
        self.spi = False            # uspaný z nabídky (nepersistuje)
        self.historie = deque(maxlen=HIST_N)        # (čas, valence, aktivace)
        self.hist_last = float("-inf")
        self.udalosti = deque(maxlen=UDALOSTI_N)    # (čas, druh události); žádné texty
        self.session = None
        self.cinnost = None         # (text bubliny s činností, od kdy)
        self.zprava = None          # (text, do kdy): oznam() a varování kontextu
        self.kontext, self.kontext_varovan = None, False
        self.pomocnici = vrstvy.Pomocnici()
        self.zadosti = vrstvy.Zadosti()
        self.k_zruseni = []         # id požadavků na povolení, které hub předá on_zrus
        self.doplnky = (None, ())   # (klobouk, emoty v klidu) z odemčených doplňků (Hub.nastav_doplnky)
        self.klid_emote_t, self.klid_i = now, 0
        self.oslava_do = float("-inf")
        self.prochazka = pohyb.Prochazka()
        self.meze = 0.0             # nejdál px na procházce (nastaví renderer; 0 = nechodí)
        self.chuze = (0.0, False, 0, 0)     # (posun px dovnitř, jde, natočení ±1/0, poskok) pro renderer
        self.reakce, self.reakce_nova = None, False     # (druh, od kdy) reakce na myš
        self.configure(cfg)

    def configure(self, cfg):
        """Použije (nový) config; stav nálady, témat i činnosti zůstane."""
        quiet = cfg["tichy"] or cfg["soustredeni"]
        z, k, p = cfg["zobrazit"], cfg["klid"], cfg["postavicka"]
        self.moods, self.topics = z["nalada"], z["temata"]
        self.emotes, self.drones = z["emoty"] and not quiet, z["drony"] and not quiet
        self.focus = cfg["soustredeni"]
        self.hats = cfg["temata"]["klobouky"]
        self.pop_s, self.pop_gap_s, self.pop_queue = k["emote_s"], k["rozestup_s"], k["fronta"]
        self.settle_s = p["ustaleni_s"]
        self.fsm.sleep_s = p["usnuti_s"]
        self.mood.configure(cfg["nalada"])
        self.topic.configure(cfg["temata"])
        if not self.emotes:
            self.pops, self.pop = [], None
        del self.pops[self.pop_queue:]
        b, kt, pm = cfg["bublina"], cfg["kontext"], cfg["pomocnici"]
        self.quiet = quiet
        self.bublina_rezim, self.bublina_s = b["cinnost"], b["doba_s"]
        self.kontext_rezim, self.kontext_prah, self.kontext_varovat = kt["zobrazit"], kt["prah"], kt["varovat"]
        self.pomocnici_on, self.pomocnici_limit = pm["zapnuto"] and not quiet, pm["limit"]
        if pm["zapnuto"]:
            self.drones = False     # pomocníci nahrazují drony
        self.klobouk_vzdy, self.klid_emote_s = cfg["postup"]["klobouk_vzdy"], cfg["postup"]["klid_emote_s"]
        self.prochazka.configure(cfg["prochazky"])
        m = cfg["mys"]
        self.mys_on, self.hlazeni_on, self.najeti_on = m["zapnuto"], m["hlazeni"], m["najeti"]

    @property
    def name(self):
        return os.path.basename(self.cwd.rstrip("/")) if self.cwd else f"pid {self.pid}"

    def feed(self, ev):
        if ev["kind"] == "agent.interrupted":
            # přerušení hlásí hook (is_interrupt) i transcript: v jednom kole platí jen první
            if self.last_interrupt > self.last_prompt:
                return False
            self.last_interrupt = ev["ts"]
        self.udalosti.append((ev["ts"], ev["kind"]))
        if ev["kind"] == "tool.start" and not ev["data"].get("agent"):
            self.tool = ev["data"].get("tool")
        elif ev["kind"] == "user.prompt":
            self.last_prompt = ev["ts"]
        self._kolo(ev)
        self.fsm.feed(ev)
        self.topic.feed(ev)
        for pop in self.mood.feed(ev):
            self._queue(pop)
        self._vrstvy(ev)
        return True

    def _kolo(self, ev):
        kind = ev["kind"]
        if kind in KONEC_KOLA:
            if kind == "session.end" or not ev["data"].get("agent"):
                self.kolo_konec = True
        elif kind == "user.prompt" or self.kolo_konec:
            self.kolo_od, self.kolo_konec = ev["ts"], False

    def _vrstvy(self, ev):
        """Činnost do bubliny, pomocníci a rušení požadavků na povolení."""
        kind = ev["kind"]
        text = vrstvy.cinnost_text(ev)
        if text is not None:
            if not self.cinnost or self.cinnost[0] != text:
                self.cinnost = (text, ev["ts"])
        elif kind in ("agent.done", "agent.interrupted", "agent.failed", "session.end") \
                and not ev["data"].get("agent"):
            self.cinnost = None
        self.pomocnici.feed(ev)
        self.k_zruseni.extend(self.zadosti.udalost(ev))

    def oznam(self, text, sekund, now):
        self.zprava = (" ".join(str(text).split()), now + sekund)

    def oslav(self, now, sekund=OSLAVA_S):
        """Krátká animace success (nová úroveň); ne ve spánku a soustředění."""
        self.oslava_do = now + sekund

    def _klidovy_emote(self, now):
        """Bdělý v klidu: klid_emote_s od začátku klidu (nebo od minulého) další odemčený emote."""
        emoty = self.doplnky[1]
        if not emoty or self.spi or self.shown != IDLE or self.pop or self.pops:
            return
        if now - max(self.klid_emote_t, self.shown_since) >= self.klid_emote_s:
            self._queue(emoty[self.klid_i % len(emoty)])
            self.klid_i += 1
            self.klid_emote_t = now

    def nastav_kontext(self, ctx, now):
        """Nový stav kontextu (transcript nebo status line); nad prahem jednou krátké varování."""
        self.kontext = ctx
        pct = vrstvy.kontext_procento(ctx)
        if pct is None:
            return
        if pct >= self.kontext_prah:
            if not self.kontext_varovan and self.kontext_varovat:
                self.oznam(f"kontext {pct} %, brzy compact", vrstvy.ZPRAVA_S, now)
            self.kontext_varovan = True
        elif pct < self.kontext_prah - vrstvy.KONTEXT_HYST:
            self.kontext_varovan = False

    def bublina(self, now):
        """Co ukázat v bublině: ("povoleni", id, shrnuti) | ("text", text) | None.
        Žádost o povolení vždy; texty ne v tichém režimu, soustředění a ve spánku."""
        z = self.zadosti.prvni()
        if z:
            return ("povoleni",) + z
        st = self.fsm.advance(now)
        if self.quiet or self.spi or st == GONE:
            return None
        if self.zprava and now < self.zprava[1]:
            return ("text", self.zprava[0])
        self.zprava = None
        if not self.cinnost or self.bublina_rezim == "nikdy":
            return None
        if self.bublina_rezim == "vzdy":
            if st == THINKING:
                return ("text", "přemýšlí…")
            return ("text", self.cinnost[0]) if st in (WORKING, WAITING, LISTENING) else None
        return ("text", self.cinnost[0]) if now - self.cinnost[1] < self.bublina_s else None

    def meric(self):
        """(procento, úroveň "ok" | "pozor" | "plno") pro měřič kontextu, nebo None."""
        pct = vrstvy.kontext_procento(self.kontext)
        if self.fsm.state == GONE or not vrstvy.ukazat_meric(self.kontext_rezim, pct, self.kontext_prah):
            return None
        return pct, vrstvy.kontext_uroven(pct, self.kontext_prah)

    def pomocnici_ted(self, now):
        """→ ((typ, animace, snímek, fáze, postup), …), počet dalších, jejich typy) pro renderer."""
        if not self.pomocnici_on or self.spi:
            return (), 0, ()
        seznam, dalsi, typy = self.pomocnici.ted(now, self.pomocnici_limit)
        anim = self.skin.anim_for(WORKING)
        out = tuple((p["typ"], anim, self.skin.frame_at(anim, now - p["od"]), faze, round(k, 2))
                    for p, faze, k in seznam)
        return out, dalsi, typy

    def reaguj(self, druh, now):
        """Reakce na myš (pohyb.Gesta). False = neukáže se: vypnuto, soustředění, uspaná,
        odchází, nebo se po zamotání zlobí; zbystření (najetí) jinou reakci nepřeruší."""
        if not self.mys_on or self.focus or self.spi or self.fsm.state == GONE or druh not in pohyb.REAKCE:
            return False
        if (druh == pohyb.HLAZENI and not self.hlazeni_on) or (druh == pohyb.POHLED and not self.najeti_on):
            return False
        r = self._reakce_ted(now)
        if r and (druh == pohyb.POHLED or (r[0] == pohyb.ZAMOTANI and druh in pohyb.ZLOST)):
            return False
        self.reakce, self.reakce_nova = (druh, now), True
        return True

    def _reakce_ted(self, now):
        if self.reakce and now - self.reakce[1] < pohyb.REAKCE[self.reakce[0]]["celkem_s"]:
            return self.reakce
        self.reakce = None
        return None

    def _queue(self, pop):
        if self.emotes and not self.spi and pop not in self.pops and len(self.pops) < self.pop_queue:
            self.pops.append(pop)

    def _next_pop(self, now):
        if self.pop and now - self.pop_since >= self.pop_s:
            self.pop = None
        if not self.pop and self.pops and now - self.pop_since >= self.pop_s + self.pop_gap_s \
                and not self.prochazka.probiha:     # na procházce počká (zrcadlený snímek by obrátil i emote)
            self.pop, self.pop_since = self.pops.pop(0), now
        return self.pop

    def _fade(self, mood, now):
        """Paleta při změně nálady přechází ve FADE_STEPS krocích po FADE_STEP_S."""
        if mood != self.mood_shown:
            self.fade_from, self.fade_since, self.mood_shown = self.mood_shown, now, mood
        step = 1 + int((now - self.fade_since) / FADE_STEP_S)
        if self.fade_from is None or step >= FADE_STEPS:
            self.fade_from = None
            return None
        return self.fade_from, step

    def update(self, now):
        """Posune zobrazený stav; vrací (animace, snímek, vzhled pro skin.render).
        Probíhající přechod palety nechá v self.fade."""
        mood, changed = self.mood.advance(now)
        if now - self.hist_last >= HIST_S:
            self.hist_last = now
            self.historie.append((now, self.mood.v, self.mood.a))
        if not self.moods:
            mood = KLID         # engine počítá dál, aby po zapnutí neukázal starý stav
        elif changed and self.skin.mood_emote(mood):
            self._queue(self.skin.mood_emote(mood))
        self.fade = self._fade(mood, now)
        topic = self.topic.advance(now)
        if self.spi:
            self.pops, self.pop = [], None
        st = self.fsm.advance(now)
        if st != self.shown and (st in URGENT or now - self.fsm.since >= self.settle_s):
            self.shown, self.shown_since = st, now
        self._klidovy_emote(now)
        pop = self._next_pop(now)
        still = self.focus and (self.spi or self.shown != WAITING)
        r = None if self.spi or self.focus else self._reakce_ted(now)
        rr = pohyb.REAKCE[r[0]] if r else None
        po = r is not None and now - r[1] >= rr["anim_s"]       # reakce dohrála, trvá jen výraz
        klid = (self.shown == IDLE and not self.spi and not self.focus and r is None and not self.zadosti
                and (pop is None or self.prochazka.probiha))
        x, jde, smer = self.prochazka.krok(now, klid, self.meze)
        if self.spi:
            anim = self.skin.anim_for(SLEEPING)
        elif self.focus and self.shown != WAITING:
            anim = "idle"       # soustředění: stojí bez pohybu, hýbe se jen při čekání na uživatele
        elif now < self.oslava_do:
            anim = self.skin.anim_for(SUCCESS)
        elif r and not po and rr["stav"]:
            anim = self.skin.anim_for(rr["stav"])
        elif jde:
            anim = self.skin.walk_anim() or self.skin.anim_for(IDLE)
        else:
            anim = self.skin.anim_for(self.shown, self.tool)
        if anim != self.anim or self.reakce_nova:
            self.anim, self.anim_since, self.reakce_nova = anim, now, False
        poskok = int(jde and not self.skin.walk_anim() and int((now - self.anim_since) * 4) % 2)
        self.chuze = (x, jde, smer, poskok)
        if still:
            i = 0
        else:
            i = self.skin.frame_at(self.anim, now - self.anim_since, self.skin.mood_tempo(mood))
        phase = int(now * 3) % 2
        drones = len(self.fsm.subagents) if self.drones else 0
        hat = (self.hats.get(topic) or None) if self.topics else None
        if self.doplnky[0] and (hat is None or self.klobouk_vzdy):
            hat = self.doplnky[0]
        if r:       # reakce na myš: výraz a emote hned, mimo frontu emotů
            m, e = rr.get("nalada_po" if po else "nalada"), rr.get("emote_po" if po else "emote")
            if m and self.moods:
                mood, self.fade = m, None
            if e and self.emotes:
                pop = e
        look = (mood, hat, pop, phase if pop else 0, drones, phase if drones else 0)
        return self.anim, i, look

    @property
    def title_state(self):
        """Stav pro titulek okna perch: uspaný se netlačí do rohu ani při čekání."""
        return SLEEPING if self.spi else self.shown

    def stav_panelu(self, now):
        """Data pro panel.PanelNalady.nastav(): čísla, štítky a druhy událostí, žádné texty.
        Poslední bod historie je aktuální stav enginu (oprava z panelu ho uloží)."""
        m = self.mood
        hist = list(self.historie)
        if not hist or m.t > hist[-1][0]:
            hist.append((m.t, m.v, m.a))
        q = m.questions[-m.c["otazky_n"]:]
        return {"historie": hist, "nalada": m.label, "tema": self.topic.topic,
                "cinnost": self.shown, "udalosti": list(self.udalosti), "ted": now,
                "signaly": {"zmatek": len(m.corrections), "unava": round(m.fatigue, 4),
                            "otazek": len(q), "podil_otazek": round(sum(q) / len(q), 4) if q else 0.0}}


def skin_signature(skin_id):
    """Kde skin leží a mtime/velikost jeho souborů; None u vestavěného a nenalezeného."""
    found = skins.find(skin_id) if skin_id != skins.BUILTIN else None
    if not found:
        return None
    sig = [found]
    for root, dirs, files in os.walk(found[0]):
        dirs.sort()
        for name in sorted(files):
            try:
                st = os.stat(os.path.join(root, name))
            except OSError:
                continue
            sig.append((root, name, st.st_mtime_ns, st.st_size))
    return tuple(sig)


class Hub:
    def __init__(self, reap=True, bind=True, cfg=None, transcripts=True):
        self.fams = {}
        self.reap, self.bind = reap, bind    # v demu jsou pidy z nahrávek cizí procesy
        self.last_reap = 0.0
        self.cfg = cfg or _defaults()
        self.skin_id, self.skin = None, skins.builtin()
        self.skin_sig = self._pending_sig = None
        self._use_skin(self.cfg["skin"])
        self.watchers = TranscriptWatchers() if transcripts else None
        self.last_poll = float("-inf")
        self.spi = False        # uspané všechny (i nově příchozí), z lišty
        self.posluchaci = []    # f(familiar, událost) po přijaté události
        self.on_zrus = None     # f(id): požadavek na povolení už neplatí (dock.Povolovani)
        self.doplnky = (None, ())   # (klobouk, emoty v klidu) pro všechny familiary
        self.sluzby = None      # sluzby.Sluzby, když běží (okno statistik z ní bere data)

    def _ohlas(self, fam, ev):
        for f in self.posluchaci:
            try:
                f(fam, ev)
            except Exception:
                lg.exception("posluchač %s selhal u %s", getattr(f, "__qualname__", f), ev["kind"])

    def agent_zapnut(self, source):
        """Zdroj emitteru vypnutý v [agenti] (gemini, codex) = jeho události se zahazují."""
        return (self.cfg.get("agenti") or {}).get(source, True) is not False

    def adopt_live(self, now):
        """Postavičky pro Claude Code běžící už před startem daemonu. Jeho SessionStart přišel
        dřív, než daemon existoval, takže jinak by se u takového okna objevila až s první
        událostí. Bere jen procesy claude s terminálem (jako Familiar.term). Vrací počet."""
        if not self.bind or not self.agent_zapnut(SOURCE):
            return 0
        terminaly = set(self.cfg["okno"]["terminaly"])
        claimed = {f.tty for f in self.fams.values() if f.tty}
        added = 0
        for pid in sorted((int(n) for n in os.listdir("/proc") if n.isdigit()), reverse=True):
            if pid in self.fams or not pid_alive(pid, SOURCE):
                continue
            if find_terminal(pid, terminals=terminaly) is None:
                continue
            tty = tty_of(pid)
            if tty in claimed:      # jedno okno, jedna postavička: vezme se nejnovější claude
                continue
            claimed.add(tty)
            fam = self.fams[pid] = Familiar(pid, pid, now, self.bind, self.cfg, self.skin)
            fam.spi, fam.doplnky, fam.source = self.spi, self.doplnky, SOURCE
            added += 1
        return added

    def _na_terminalu(self, pid):
        """Postavička, která už sedí v tom samém terminálu (tty) jako proces pid, přepojená na pid.
        Víc procesů claude ve stejném okně = jedna postavička; vede ten, co naposledy poslal událost."""
        tty = tty_of(pid) if self.bind else 0
        for fam in self.fams.values():
            if tty and fam.tty == tty:
                del self.fams[fam.key]
                fam.key = fam.pid = pid
                self.fams[pid] = fam
                return fam
        return None

    # --- vrstvy u postavičky: zprávy, kontext, povolení ---

    def _fam_pid(self, pid):
        fam = self.fams.get(pid)
        if fam is None:
            fam = next((f for f in self.fams.values() if pid and f.pid == pid), None)
        return fam

    def oznam(self, pid, text, sekund=vrstvy.ZPRAVA_S, now=None):
        """Krátká textová bublina u postavičky procesu pid (úspěchy, upozornění) na `sekund` s.
        False, když taková postavička není. Tichý režim a soustředění ji neukážou."""
        fam = self._fam_pid(pid)
        if fam is None:
            return False
        fam.oznam(text, sekund, time.time() if now is None else now)
        return True

    def oslav(self, pid, now=None):
        """Krátká oslava (animace success) u postavičky procesu pid; False, když není."""
        fam = self._fam_pid(pid)
        if fam is None:
            return False
        fam.oslav(time.time() if now is None else now)
        return True

    def nastav_doplnky(self, klobouk, emoty):
        """Odemčené doplňky pro všechny postavičky: klobouk (jméno ze sprites.HATS) nebo None
        a emoty v klidu (jména ze sprites.POPS). Skin, který je nemá, je nekreslí."""
        self.doplnky = (klobouk or None, tuple(emoty))
        for fam in self.fams.values():
            fam.doplnky = self.doplnky

    def poll_kontext(self, now):
        """Po poll_transcripts: změny obsazení kontextu do měřičů (a varování nad prahem)."""
        if self.watchers is None:
            return
        for key, _, ctx in self.watchers.poll_context():
            fam = self.fams.get(key)
            if fam is not None:
                fam.nastav_kontext(ctx, now)

    def _kontext_statusline(self, pid, raw, now):
        """Obsazení kontextu ze status line (familiar-emit --statusline) do měřiče postavičky
        procesu pid, jinak podle session. Postavičku nezakládá: status line běží i bez událostí."""
        ctx = raw.get("context")
        if not isinstance(ctx, dict):
            return
        used, window, model = ctx.get("used"), ctx.get("window"), ctx.get("model")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (used, window)) \
                or used < 0 or window <= 0:
            return
        fam = self._fam_pid(pid) if pid else None
        session = raw.get("session_id")
        if fam is None and isinstance(session, str):
            fam = next((f for f in self.fams.values() if f.session == session), None)
        if fam is None or fam.fsm.state == GONE:
            return
        ctx = {"used": used, "window": window, "model": model if isinstance(model, str) else None}
        if ctx != fam.kontext:
            fam.nastav_kontext(ctx, now)

    def pozadavek(self, id_, session, pid, shrnuti, now):
        """Požadavek na povolení ze serveru → bublina u postavičky podle pid, jinak podle session.
        Vrací klíč postavičky, nebo None (nikomu nepatří: volající ho zruší)."""
        fam = self._fam_pid(pid) if pid else None
        if fam is None and session:
            fam = next((f for f in self.fams.values() if f.session == session), None)
        if fam is None or fam.fsm.state == GONE:
            return None
        fam.zadosti.pridej(id_, shrnuti, now)
        return fam.key

    def vyrizeno(self, id_):
        """Požadavek zodpovězený nebo zrušený serverem: bublinu schovat. Vrací klíč postavičky,
        nebo None (požadavek už nikdo nemá)."""
        for key, fam in self.fams.items():
            if fam.zadosti.odeber(id_):
                return key
        return None

    def _zrus(self, fam, ids=None):
        ids = list(fam.zadosti.cekajici) if ids is None else ids
        for i in ids:
            fam.zadosti.odeber(i)
            if self.on_zrus is not None:
                self.on_zrus(i)

    def _po_udalosti(self, fam):
        if fam.k_zruseni:
            ids, fam.k_zruseni = fam.k_zruseni, []
            self._zrus(fam, ids)

    def uspat(self, spi=True, key=None):
        """Uspí (spi=False vzbudí) jednoho familiara podle klíče, nebo bez klíče všechny."""
        if key is None:
            self.spi = spi
        elif not spi:
            self.spi = False        # probuzení kohokoli ruší „spí všichni“
        if key is None:
            fams = self.fams.values()
        else:
            fams = [self.fams[key]] if key in self.fams else []
        for fam in fams:
            fam.spi = spi
        lg.info("%s %s", "uspán" if spi else "vzbuzen", "všichni" if key is None else f"familiar {key}")

    def reaguj(self, key, druh, now=None):
        """Reakce postavičky `key` na myš (druh z pohyb.Gesta, None = nic); True = ukáže se."""
        fam = self.fams.get(key)
        return bool(fam is not None and druh and fam.reaguj(druh, time.time() if now is None else now))

    def stav_panelu(self, key, now):
        fam = self.fams.get(key)
        return fam.stav_panelu(now) if fam else None

    def _use_skin(self, skin_id, sig=None):
        """Načte skin podle configu; vadný → vestavěný (skin.load to zapíše do logu)."""
        sig = sig or skin_signature(skin_id)
        if skin_id != self.skin_id or sig != self.skin_sig:
            self.skin_id, self.skin_sig, self.skin = skin_id, sig, skins.load(skin_id)
            self._pending_sig = None
            for fam in self.fams.values():
                fam.skin = self.skin
            lg.info("skin %s (%s)", self.skin.id, self.skin.source)

    def refresh_skin(self):
        """Volá daemon z časovače: změněné soubory skinu (nebo nově přidaný uživatelský
        skin se stejným id) → načíst znovu. Čeká, až se podpis dvakrát po sobě nezmění,
        aby nečetl napůl zapsaný export."""
        sig = skin_signature(self.skin_id)
        if sig == self.skin_sig:
            self._pending_sig = None
        elif sig != self._pending_sig:
            self._pending_sig = sig
        else:
            lg.info("soubory skinu %s se změnily, načítám znovu", self.skin_id)
            self._use_skin(self.skin_id, sig)

    def drop_skin(self, reason):
        """Skin selhal při kreslení: dál kreslí vestavěný (do příští změny volby skin)."""
        if self.skin.id != skins.BUILTIN:
            lg.error("skin %s selhal při kreslení (%s), kreslím vestavěného Robo-kuna", self.skin.id, reason)
            self.skin = skins.BuiltinSkin(f"chyba při kreslení: {reason}")
            for fam in self.fams.values():
                fam.skin = self.skin

    def configure(self, cfg):
        """Nový config pro hub i všechny běžící familiary (přenačtení bez restartu).
        Atomicky: když config nejde použít (vyhodí výjimku), nezmění se nic."""
        Familiar(None, None, 0.0, bind=False, cfg=cfg)     # zkouška nanečisto
        self.cfg = cfg
        for fam in self.fams.values():
            fam.configure(cfg)
            if not self.agent_zapnut(getattr(fam, "source", None)) and fam.fsm.state != GONE:
                fam.fsm.feed({"ts": fam.fsm.since, "kind": "session.end", "data": {"reason": "agent vypnut"}})
        self._use_skin(cfg["skin"])

    def handle(self, data):
        """Datagram z emitteru (bytes). Vadná zpráva ani chyba v obsluze nesmí shodit daemon;
        do logu jde jen log.safe() zprávy (bez textu promptu)."""
        try:
            msg = json.loads(data)
        except ValueError:
            lg.warning("zpráva hooku není JSON (%d B)", len(data))
            return
        try:
            self.receive(msg)
        except Exception:
            # jako text: SafeFilter by slovník prohnal přes safe() podruhé
            lg.exception("chyba při zpracování zprávy hooku %s", str(log.safe(msg)))

    def receive(self, msg):
        """Zpracuje zprávu emitteru: {"v", "source", "pid", "ts", "raw"}."""
        raw, ts, pid = msg.get("raw") or {}, msg["ts"], msg.get("pid")
        key = pid or raw.get("session_id")
        if key is None or not self.agent_zapnut(msg.get("source")):
            return
        if raw.get("hook_event_name") == "StatusLine":
            self._kontext_statusline(pid, raw, ts)
            return
        fam = self.fams.get(key)
        if fam is None and pid and msg.get("source") == SOURCE:
            fam = self._na_terminalu(pid)
        if fam is None:
            fam = self.fams[key] = Familiar(key, pid, ts, self.bind, self.cfg, self.skin)
            fam.spi = self.spi
            fam.doplnky = self.doplnky
            fam.source = msg.get("source")
        if raw.get("cwd"):
            fam.cwd = raw["cwd"]
        if isinstance(raw.get("session_id"), str):
            fam.session = raw["session_id"]
        if self.watchers is not None and raw.get("transcript_path"):
            self.watchers.watch(key, raw["transcript_path"])
        for ev in adapters.translate(msg.get("source"), raw, ts, pid):     # podle zdroje emitteru
            if fam.feed(ev):
                self._ohlas(fam, ev)
            self._po_udalosti(fam)
            if ev["kind"] == "session.end" and self.watchers is not None:
                self.watchers.unwatch(key)      # po /clear ho nová session zase napojí

    def poll_transcripts(self, now):
        """Přečte přírůstky transcriptů; přerušení → agent.interrupted {tool_use}.
        Přerušení zapsané dřív než poslední prompt se zahodí: nové kolo už začalo
        (otevřené nástroje automat odloží sám). Rozhoduje čas záznamu v transcriptu;
        záznam bez času se zahodí, jen když prompt přišel od minulého čtení."""
        if self.watchers is None:
            return []
        hits, since = self.watchers.poll_all(), self.last_poll
        self.last_poll = now
        out = []
        for key, kind, ts in hits:
            fam = self.fams.get(key)
            if fam is None or fam.fsm.state == GONE:
                continue
            if fam.last_prompt > (since if ts is None else ts):
                continue
            ev = {"v": 1, "source": SOURCE, "session": None, "pid": fam.pid, "ts": now,
                  "kind": "agent.interrupted", "data": {"tool_use": kind == INTERRUPTED_TOOL}}
            if fam.feed(ev):
                out.append(key)     # False: hook (is_interrupt) ho už nahlásil
                self._ohlas(fam, ev)
                self._po_udalosti(fam)
        return out

    def tick(self, now):
        if self.reap and now - self.last_reap >= REAP_S:
            self.last_reap = now
            for fam in self.fams.values():
                if fam.pid and fam.fsm.state != GONE and not pid_alive(fam.pid, getattr(fam, "source", None)):
                    ev = {"ts": now, "kind": "session.end", "pid": fam.pid, "data": {"reason": "dead"}}
                    fam.fsm.feed(ev)
                    self._ohlas(fam, ev)
        for key in [k for k, f in self.fams.items()
                    if f.fsm.state == GONE and now - f.fsm.since >= self.cfg["postavicka"]["odchod_s"]]:
            self._zrus(self.fams[key])      # mrtvý proces: jeho požadavky už nikdo nezodpoví
            del self.fams[key]
            if self.watchers is not None:
                self.watchers.unwatch(key)
        return sorted(self.fams.values(), key=lambda f: (f.fsm.state == GONE, f.name))
