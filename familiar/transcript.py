# Sledování konce transcriptu Claude Code → přerušení (Esc), kapitola 6.1.
#
# Přerušení nemá hook. Claude Code ho zapíše do transcript_path (JSONL) jako
# záznam {"type": "user", "message": {"role": "user", "content": [{"type": "text",
# "text": "[Request interrupted by user]"}]}}; při přerušení běžícího nástroje
# s textem "[Request interrupted by user for tool use]" (po tool_result s chybou).
# Sledovač si pamatuje jen cestu, inode a offset, obsah nikam neukládá.
# Bez vláken a bez Qt: daemon volá poll_all() ze svého časovače.
# Ke každému přerušení vrací i čas záznamu (pole timestamp, ISO 8601 v UTC), aby
# daemon poznal, jestli bylo před promptem, nebo po něm.
#
# Obsazený kontext (měřič kontextu): každá odpověď hlavního agenta má v transcriptu
# message.usage a message.model; obsazeno = input_tokens + cache_read_input_tokens
# + cache_creation_input_tokens posledního volání API. Po compactu zapíše Claude Code
# {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"postTokens": n}},
# kontext se tím vynuluje na n. Okno transcript nezapisuje (model je holé ID bez [1m],
# 1M beta v požadavcích chybí), proto ho určí okno() podle ID modelu a přeteče-li
# obsazení 200k, platí 1M. Ze záznamů se čtou jen čísla a ID modelu.
import json, os
from datetime import datetime

MARKER = "[Request interrupted by user"
_MARKER_B = MARKER.encode()
MAX_READ = 1 << 20      # strop čtení na jeden poll; větší přírůstek → jen konec souboru
MAX_LINE = 256 << 10    # delší neúplný řádek se přeskočí (přerušení má ~600 B)

INTERRUPTED = "interrupted"
INTERRUPTED_TOOL = "interrupted.tool_use"
CONTEXT = "context"

OKNO = 200_000
OKNO_1M = 1_000_000
# modely s oknem 1M už ve výchozím stavu (holé ID); starší a neznámé mají 200k
MODELY_1M = ("claude-fable-", "claude-mythos-", "claude-opus-5", "claude-sonnet-5", "claude-haiku-5",
             "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-4-6")
_USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def okno(model, used=0):
    """Velikost okna kontextu podle ID modelu (i s prefixem poskytovatele nebo [1m])."""
    m = model.lower() if isinstance(model, str) else ""
    i = m.find("claude-")
    m = m[i:] if i > 0 else m
    w = OKNO_1M if "[1m]" in m or m.endswith("-1m") or m.startswith(MODELY_1M) else OKNO
    return OKNO_1M if used > w else w


def context_hit(line):
    """Řádek JSONL (bytes) → ("usage", obsazeno, model) | ("compact", obsazeno po compactu) | None.
    Jen hlavní agent: sidechain (subagent) a syntetické zprávy (chyby API) se nepočítají."""
    if b'"compact_boundary"' in line:
        try:
            o = json.loads(line)
        except ValueError:
            return None
        if not isinstance(o, dict) or o.get("type") != "system" or o.get("subtype") != "compact_boundary" \
                or o.get("isSidechain"):
            return None
        cm = o.get("compactMetadata")
        post = cm.get("postTokens") if isinstance(cm, dict) else None
        return "compact", post if isinstance(post, int) and not isinstance(post, bool) and post >= 0 else 0
    if b'"usage"' not in line or b'"assistant"' not in line:
        return None
    try:
        o = json.loads(line)
    except ValueError:
        return None
    if not isinstance(o, dict) or o.get("type") != "assistant" or o.get("isSidechain") \
            or o.get("isApiErrorMessage"):
        return None
    msg = o.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
        return None
    model = msg.get("model")
    if not isinstance(model, str) or model.startswith("<") or len(model) > 100:
        return None
    u = msg["usage"]
    used = sum(u[k] for k in _USAGE_KEYS if isinstance(u.get(k), int) and not isinstance(u.get(k), bool))
    return "usage", max(0, used), model


def _time(o):
    """Čas záznamu transcriptu v sekundách epochy, nebo None."""
    ts = o.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


def detect(line):
    """Řádek JSONL (bytes) → INTERRUPTED / INTERRUPTED_TOOL / None."""
    h = hit(line)
    return h[0] if h else None


def hit(line):
    """Řádek JSONL (bytes) → (INTERRUPTED | INTERRUPTED_TOOL, čas záznamu nebo None), nebo None."""
    if _MARKER_B not in line:   # levné síto, JSON se parsuje jen u kandidátů
        return None
    try:
        o = json.loads(line)
    except ValueError:
        return None
    if not isinstance(o, dict) or o.get("type") != "user" or o.get("isSidechain"):
        return None
    msg = o.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return None
    content = msg.get("content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):   # tool_result s markerem (výstup grepu apod.) se nepočítá
        texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    else:
        return None
    for t in texts:
        if isinstance(t, str) and t.startswith(MARKER) and len(t) < 80:
            return INTERRUPTED_TOOL if t.startswith(MARKER + " for tool use") else INTERRUPTED, _time(o)
    return None


class TranscriptWatcher:
    """Čte jen nově přidané řádky jednoho transcriptu, od konce v okamžiku napojení."""

    def __init__(self, path):
        self.path = path
        self.offset = 0
        self._ino = None
        self._skip = False   # zahodit bajty do nejbližšího konce řádku
        self.context = None  # {"used", "window", "model"} nebo None (zatím nevíme)
        self.context_changed = False
        self._model = None
        try:
            st = os.stat(path)
        except OSError:
            return   # soubor ještě nevznikl → až vznikne, čte se od začátku
        self._ino = st.st_ino
        self.offset = st.st_size
        self._skip = st.st_size > 0 and not self._ends_line(st.st_size)
        if st.st_size > 0:
            self._context_from_tail(st.st_size)

    def _apply_context(self, h):
        if h[0] == "usage":
            used, self._model = h[1], h[2]
        else:
            used = h[1]
        ctx = {"used": used, "window": okno(self._model, used), "model": self._model}
        if ctx != self.context:
            self.context, self.context_changed = ctx, True

    def _context_from_tail(self, size):
        """Při napojení: poslední stav kontextu z konce souboru (nejvýš MAX_READ bajtů)."""
        try:
            with open(self.path, "rb") as f:
                f.seek(max(0, size - MAX_READ))
                data = f.read(min(size, MAX_READ))
        except OSError:
            return
        lines = data.split(b"\n")
        if size > MAX_READ:
            lines = lines[1:]   # useknutý první řádek
        last = None
        for line in reversed(lines):
            h = context_hit(line)
            if h is None:
                continue
            if last is None:
                last = h
                if h[0] == "usage":
                    break
            elif h[0] == "usage":   # po compactu chybí model: vezme se z dřívější odpovědi
                self._model = h[2]
                break
        if last:
            self._apply_context(last)

    def _ends_line(self, pos):
        try:
            with open(self.path, "rb") as f:
                f.seek(pos - 1)
                return f.read(1) == b"\n"
        except OSError:
            return True

    def poll(self):
        """→ [(INTERRUPTED | INTERRUPTED_TOOL, čas záznamu nebo None), …] z nových řádků."""
        try:
            st = os.stat(self.path)
        except OSError:
            if self._ino is not None:   # smazaný → nový soubor se bude číst od začátku
                self._ino, self.offset, self._skip = None, 0, False
            return []
        if st.st_ino != self._ino or st.st_size < self.offset:
            # nový, vyměněný (rotace) nebo zkrácený soubor
            self._ino, self.offset, self._skip = st.st_ino, 0, False
        if st.st_size - self.offset > MAX_READ:
            # velký přírůstek: starší část se zahodí, přerušení bývá na konci
            self.offset = st.st_size - MAX_READ
            self._skip = not self._ends_line(self.offset)
        if st.st_size <= self.offset:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read(MAX_READ)
        except OSError:
            return []
        start = 0
        if self._skip:
            nl = data.find(b"\n")
            if nl < 0:
                self.offset += len(data)
                return []
            start, self._skip = nl + 1, False
        end = data.rfind(b"\n") + 1   # za posledním celým řádkem
        if end <= start:
            end = start
        out = []
        for line in data[start:end].splitlines():
            h = hit(line)
            if h:
                out.append(h)
            else:
                c = context_hit(line)
                if c:
                    self._apply_context(c)
        self.offset += end
        if len(data) - end >= MAX_LINE:   # obří neúplný řádek: dál ho nedržet
            self.offset += len(data) - end
            self._skip = True
        return out


class TranscriptWatchers:
    """Sledovače podle pid familiara; daemon volá poll_all() z časovače."""

    def __init__(self):
        self._by_pid = {}

    def watch(self, pid, path):
        """Napojí (nebo přepojí po /clear) sledovač; neplatná cesta se ignoruje."""
        if not isinstance(path, str) or not os.path.isabs(path) or not path.endswith(".jsonl"):
            return
        w = self._by_pid.get(pid)
        if w is None or w.path != path:
            self._by_pid[pid] = TranscriptWatcher(path)

    def unwatch(self, pid):
        self._by_pid.pop(pid, None)

    def __contains__(self, pid):
        return pid in self._by_pid

    def __len__(self):
        return len(self._by_pid)

    def poll_all(self):
        """→ [(pid, INTERRUPTED | INTERRUPTED_TOOL, čas záznamu nebo None), …] v pořadí výskytu.
        Zároveň aktualizuje stav kontextu (viz poll_context)."""
        out = []
        for pid, w in list(self._by_pid.items()):
            out.extend((pid, kind, ts) for kind, ts in w.poll())
        return out

    def context(self, pid):
        """Poslední známý kontext {"used", "window", "model"}, nebo None."""
        w = self._by_pid.get(pid)
        return dict(w.context) if w is not None and w.context else None

    def poll_context(self):
        """→ [(pid, CONTEXT, {"used", "window", "model"}), …] u sledovačů, jejichž kontext se
        změnil od minulého volání (volat po poll_all; po napojení hlásí stav z konce souboru)."""
        out = []
        for pid, w in self._by_pid.items():
            if w.context_changed and w.context:
                w.context_changed = False
                out.append((pid, CONTEXT, dict(w.context)))
        return out
