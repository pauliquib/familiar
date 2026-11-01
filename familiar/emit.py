#!/usr/bin/env -S python3 -I
# familiar-emit: hook → familiard. Nikdy nic nevypisuje, vždy exit 0.
#
# Pošle daemonu jeden datagram s poli hooku, která potřebuje adaptér zdroje z argumentu
# (claude-code, gemini, codex; familiar/adapters/). Když daemon neběží nebo nestíhá číst,
# událost se zahodí (odeslání nikdy neblokuje).
# Nic neukládá na disk; nahrávání z fáze 0 je ukončené.
# S volbou --statusline běží jako status line Claude Code (statusLine v settings.json): pošle
# jen obsazení kontextu pro měřič a nic nevypíše (transcript na disku být nemusí).
# Výjimka z „nic nevypisuje“: s volbou --povoleni běží klient familiar/povoleni_klient.py
# (samostatný, výslovně zapínaný hook PermissionRequest), viz docs/povoleni.md.
# Spouští se jako příkaz `familiar-emit` (spouštěč z _build/familiar_build.py, python -I -S)
# i přímo jako skript. Bez site se nenačte ani `os`: proto `posix` (o ~3 ms méně).
import posix, sys, time

try:    # jen C části: `import json` (kvůli re) a `import socket` (kvůli enum) stojí ~12 ms na hook
    from _json import encode_basestring_ascii as _quote, make_scanner as _make_scanner, scanstring
    import _socket as socket
except ImportError:
    _make_scanner = None
    import socket

# tool_input a tool_response se neposílají, jen začátek příkazu Bash (testy, téma)
# a pro bublinu s činností jméno souboru bez cesty ("file") a začátek vzoru Grep/Glob ("pattern")
KEEP = ("hook_event_name", "session_id", "transcript_path", "cwd", "source", "reason",
        "prompt", "tool_name", "tool_use_id", "duration_ms", "error", "is_interrupt",
        "agent_id", "agent_type", "background_tasks", "trigger", "notification_type")
# Gemini CLI a Codex (docs/agenti.md): transcript (jiný formát) ani texty odpovědí se neposílají,
# prompt jen z hooku odeslání promptu, z tool_response jen odvozené kódy (_gemini_tool)
KEEP_BY_SOURCE = {
    "gemini": ("hook_event_name", "session_id", "cwd", "source", "reason", "prompt", "tool_name",
               "trigger", "notification_type"),
    "codex": ("hook_event_name", "session_id", "cwd", "source", "reason", "prompt", "tool_name",
              "tool_use_id", "agent_id", "agent_type", "trigger"),
}
PROMPT_HOOKS = ("UserPromptSubmit", "BeforeAgent")     # Gemini AfterAgent má prompt také
SHELLS = (b"sh", b"bash", b"dash", b"zsh", b"fish", b"ksh", b"mksh")
GEMINI_TAIL = ("Signal:", "Background PIDs:", "Process Group PGID:")   # řádky za Exit Code
LIMIT = 1 << 18     # větší vstup (velký tool_response) se celý neparsuje: jen začátek a konec
TAIL = 1 << 16      # kolik bajtů z konce velkého vstupu hledat pole za tool_response
WS = " \t\n\r"
PIPE_SIZE = 1 << 20     # roura stdin u velkého vstupu (výchozí 64 kB = víc probouzení zapisujícího)
F_SETPIPE_SZ, FIONREAD = 1031, 0x541B   # Linux; fcntl/termios je nemají všude jako konstanty
FALLBACK = "/tmp/familiar-{uid}"   # bez XDG_RUNTIME_DIR (stejně v paths.py)


def sock_path():
    """Socket daemonu; bez XDG_RUNTIME_DIR soukromý /tmp/familiar-<uid> (stejně jako paths.py).
    None, když ten adresář není náš a jen pro nás (jinak by zprávy mohl číst někdo cizí)."""
    d = _env("XDG_RUNTIME_DIR")
    if not d or not d.startswith("/"):
        d = FALLBACK.format(uid=posix.getuid())
        st = posix.lstat(d)
        if st.st_mode & 0o170000 != 0o040000 or st.st_uid != posix.getuid() or st.st_mode & 0o077:
            return None
    return d.rstrip("/") + "/familiar.sock"


def _env(name):
    """Proměnná prostředí; os.environ, je-li načtené (v testech ho mění monkeypatch)."""
    os = sys.modules.get("os")
    if os is not None:
        return os.environ.get(name)
    v = posix.environ.get(name.encode())
    return None if v is None else v.decode(sys.getfilesystemencoding(), "surrogateescape")


class _NoJsonImport:
    """_json při chybě v datech importuje json.decoder kvůli JSONDecodeError, a s ním json a re
    (~10 ms). Uříznutý tool_response v začátku velkého vstupu chybu vyvolá vždy. Po dobu
    parsování mu podstrčí náhradu: chyba je pak obyčejný ValueError (ten se chytá stejně).
    Jen od Pythonu 3.12: 3.11 si třídu výjimky v _json natrvalo ukládá (static), náhrada by
    v procesu zůstala i pro pozdější skutečný json. Na 3.11 tedy chyba json jen načte."""

    def __enter__(self):
        self.stub = (_make_scanner is not None and sys.version_info >= (3, 12)
                     and "json" not in sys.modules and "json.decoder" not in sys.modules)
        if self.stub:
            pkg, dec = type(sys)("json"), type(sys)("json.decoder")
            dec.JSONDecodeError, pkg.decoder = ValueError, dec
            sys.modules["json"], sys.modules["json.decoder"] = pkg, dec

    def __exit__(self, *exc):
        if self.stub:
            sys.modules.pop("json", None)
            sys.modules.pop("json.decoder", None)


class _Ctx:
    """Nastavení dekodéru, jak ho čte _json.make_scanner (jako json.JSONDecoder)."""
    strict = True
    object_hook = object_pairs_hook = None
    parse_float, parse_int, parse_constant = float, int, float


def loads(text):
    if _make_scanner is None:
        import json
        return json.loads(text)
    return _make_scanner(_Ctx())(text, len(text) - len(text.lstrip()))[0]


def dumps(o):
    if _make_scanner is None:
        import json
        return json.dumps(o)
    if isinstance(o, str):
        return _quote(o)
    if o is None or isinstance(o, bool):
        return "null" if o is None else "true" if o else "false"
    if isinstance(o, (int, float)):
        return repr(o)
    if isinstance(o, dict):
        return "{" + ",".join(_quote(str(k)) + ":" + dumps(v) for k, v in o.items()) + "}"
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(map(dumps, o)) + "]"
    raise TypeError(type(o).__name__)


def _ws(text, i):
    while i < len(text) and text[i] in WS:
        i += 1
    return i


def pairs(text, i, to_end):
    """Páry "klíč": hodnota objektu od indexu i (za '{' nebo ','); vrací (páry, kde skončil).

    to_end=False: začátek vstupu – páry, které se do textu celé vešly.
    to_end=True: konec vstupu – páry musí doběhnout až k '}' na konci textu, jinak
    páry None (tak se pozná, že i leží v nejvyšší úrovni, ne ve vnořeném objektu)."""
    scan, out = _make_scanner(_Ctx()), {}
    while True:
        i = _ws(text, i)
        if i >= len(text) or text[i] != '"':
            return (None if to_end else out), i
        try:
            key, i = scanstring(text, i + 1)
            i = _ws(text, i)
            if text[i] != ":":
                raise ValueError
            value, i = scan(text, _ws(text, i + 1))
        except (StopIteration, ValueError, IndexError):
            return (None if to_end else out), i
        i = _ws(text, i)
        if i >= len(text) or text[i] not in ",}":
            return (None if to_end else out), i     # hodnota mohla být uříznutá
        out[key] = value
        if text[i] == "}":
            return (out if not to_end or _ws(text, i + 1) == len(text) else None), i
        i += 1


def read_hook(fd=0):
    """Data hooku ze stdin. Velký vstup se přečte celý (aby zapisující Claude nedostal
    EPIPE), ale parsuje se jen začátek a konec: tool_response se nepotřebuje."""
    buf, head = bytearray(LIMIT), bytearray()
    while len(head) < LIMIT:
        got = posix.readv(fd, [buf])
        if not got:
            break
        head += memoryview(buf)[:got]
    rest, joined = _drain(fd, buf) if len(head) >= LIMIT else (b"", True)
    with _NoJsonImport():
        if not rest:
            return loads(head.decode())
        if _make_scanner is None:
            return {}
        text = head.decode(errors="ignore")
        start = _ws(text, 0)
        out = pairs(text, start + 1, False)[0] if text[start:start + 1] == "{" else {}
        last = head[-TAIL:] + rest if joined else rest      # navazuje přímo na head?
        out.update(_tail_pairs(bytes(last[-TAIL:]).decode(errors="ignore")))
        return out


def _drain(fd, buf):
    """Dočte zbytek vstupu co nejlevněji. Vrací (konec vstupu: poslední dvě čtení, navazuje
    na head?). Čte se střídavě do dvou bufferů, nic se nekopíruje. Je-li stdin roura, zvětší
    se a střed jde rovnou do /dev/null (splice); Claude Code ale dává hookům socket: jen čtení."""
    bufs, lens, k, reads, joined = (buf, bytearray(len(buf))), [0, 0], 0, 0, True
    null = fcntl = None
    try:
        if posix.fstat(fd).st_mode & 0o170000 == 0o010000:     # S_IFIFO
            import fcntl
            try:
                fcntl.fcntl(fd, F_SETPIPE_SZ, PIPE_SIZE)
            except OSError:
                pass
            null = posix.open("/dev/null", posix.O_WRONLY)
    except (ImportError, OSError):
        pass
    avail = bytearray(4)
    try:
        while True:
            if null is not None:
                try:    # v rouře necháme TAIL bajtů, ty se přečtou: konec tak zůstane souvislý
                    fcntl.ioctl(fd, FIONREAD, avail)
                    n = int.from_bytes(avail, sys.byteorder) - TAIL
                    if n > 0 and posix.splice(fd, null, n):
                        lens, reads, joined = [0, 0], 0, False
                        continue
                except (AttributeError, OSError):
                    posix.close(null)       # splice nejde: jen čtení
                    null = None
            got = posix.readv(fd, [bufs[k]])
            if not got:
                break
            lens[k], k, reads = got, k ^ 1, reads + 1
    finally:
        if null is not None:
            posix.close(null)
    return bufs[k][:lens[k]] + bufs[k ^ 1][:lens[k ^ 1]], joined and reads <= 2   # starší, novější


def _tail_pairs(tail):
    """Páry nejvyšší úrovně na konci vstupu (za tool_response). Hledá první čárku, od které
    páry doběhnou až na konec; nejdřív jen ',"' (kompaktní JSON od Claude Code, rychle
    v C), pak jakoukoli čárku (JSON s mezerami). Uvnitř řetězce '"' nestojí bez zpětného lomítka."""
    for sep in (',"', ","):
        i = tail.find(sep)
        while i != -1:
            nxt = i + 1
            if tail[_ws(tail, i + 1):_ws(tail, i + 1) + 1] == '"':
                found, end = pairs(tail, i + 1, True)
                if found is not None:
                    return found
                if end < len(tail) and tail[end] == "}":
                    nxt = end   # vnořený objekt se zavřel v end: čárky před ním jsou také vnořené
            i = tail.find(sep, nxt)
    return {}


def _emit(ppid=None):
    source = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    if source == "codex" and len(sys.argv) > 2:     # starý notify: JSON v posledním argumentu
        full = _codex_notify(loads(sys.argv[-1]))
    else:
        full = read_hook()
    keep = KEEP_BY_SOURCE.get(source)
    raw = {k: full[k] for k in keep or KEEP if k in full}
    if keep and full.get("hook_event_name") not in PROMPT_HOOKS:
        raw.pop("prompt", None)
    ti = full.get("tool_input")
    cmd = ti.get("command") if isinstance(ti, dict) else None
    if isinstance(cmd, str) and full.get("tool_name") != "apply_patch":    # Codex: text patche
        raw["command"] = cmd[:200]
    if not keep and isinstance(ti, dict):   # bublina s činností: jméno souboru bez cesty, začátek vzoru hledání
        f = ti.get("file_path") or ti.get("notebook_path")
        if isinstance(f, str) and f:
            raw["file"] = f.rstrip("/").rpartition("/")[2][:80]
        pat = ti.get("pattern")
        if isinstance(pat, str) and pat:
            raw["pattern"] = " ".join(pat.split())[:40]
    if source == "gemini":
        _gemini_tool(full.get("tool_response"), full.get("tool_name"), raw)
    if isinstance(raw.get("prompt"), str):
        raw["prompt"] = raw["prompt"][:2000]
    if isinstance(raw.get("error"), str):
        raw["error"] = raw["error"][:500]
    if isinstance(raw.get("background_tasks"), list):
        raw["background_tasks"] = [{}] * len(raw["background_tasks"])   # stačí počet
    pid = _pid(ppid)    # proces agenta, hook ho spouští přímo (u spouštěče rodič sh)
    if keep:
        pid = _skip_shell(pid)
    msg = {
        "v": 1,
        "source": source,
        "pid": pid,
        "ts": time.time(),
        "raw": raw,
    }
    _send(msg)


def _send(msg):
    """Jeden datagram daemonu; nikdy neblokuje (daemon neběží nebo nestíhá → zahodí se)."""
    path = sock_path()
    if path is None:
        return
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.setblocking(False)    # plná fronta (daemon visí) → EAGAIN, zpráva se zahodí
    try:
        s.sendto(dumps(msg).encode(), path)
    except OSError:
        pass  # daemon neběží nebo nestíhá
    finally:
        s.close()


def _codex_notify(n):
    """notify Codexu ({"type": "agent-turn-complete", "thread-id", "turn-id", "cwd",
    "input-messages", "last-assistant-message"}) → pole jako z hooku, bez textů."""
    if not isinstance(n, dict):
        return {}
    return {"hook_event_name": n.get("type"), "session_id": n.get("thread-id"), "cwd": n.get("cwd")}


def _gemini_tool(tr, tool, raw):
    """Z tool_response Gemini (AfterTool) jen chyba nástroje, exit kód a zrušení příkazu.
    Velký vstup (> LIMIT) tool_response nemá: chyba se pak nepozná."""
    if not isinstance(tr, dict):
        return
    err = tr.get("error")
    if isinstance(err, dict):
        raw["error"] = str(err.get("message") or err.get("type") or "error")[:500]
    llm = tr.get("llmContent")
    if tool != "run_shell_command" or not isinstance(llm, str):
        return
    if llm.startswith("Command was cancelled by user"):
        raw["cancelled"] = True
    i = llm.rfind("\nExit Code: ")
    if i == -1:
        return
    head, _, tail = llm[i + 12:].partition("\n")
    if (head.lstrip("-").isdigit() and len(head) < 12
            and all(line.startswith(GEMINI_TAIL) for line in tail.split("\n") if line)):
        raw["exit_code"] = int(head)


def _skip_shell(pid):
    """Codex spouští hook přes `$SHELL -lc` a fish neudělá exec: rodič je krátce žijící shell,
    ne agent (postavička by vznikala pro každý hook). Je-li rodič shell, vrátí jeho rodiče."""
    try:
        fd = posix.open(f"/proc/{pid}/stat", posix.O_RDONLY)
        try:
            data = posix.read(fd, 1024)
        finally:
            posix.close(fd)
        head, _, rest = data.rpartition(b")")
        if head.partition(b"(")[2] in SHELLS:
            return int(rest.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return pid


def discard(fd=0):
    """Dočte zbytek stdin naprázdno: Claude Code zapisující do hooku nesmí dostat EPIPE."""
    try:
        buf = bytearray(1 << 18)
        while posix.readv(fd, [buf]):
            pass
    except Exception:
        pass


def _pid(ppid):
    try:
        return int(ppid) if ppid else posix.getppid()
    except ValueError:
        return posix.getppid()


def statusline_context(full):
    """Vstup status line Claude Code → {"used", "window", "model"}, nebo None (zatím žádná
    odpověď). Obsazeno = input + cache_creation + cache_read posledního volání API (jako
    z transcriptu), okno = context_window.context_window_size."""
    cw = full.get("context_window") if isinstance(full, dict) else None
    if not isinstance(cw, dict):
        return None
    window = cw.get("context_window_size")
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        return None
    cu = cw.get("current_usage")
    if isinstance(cu, dict):
        used = sum(v for v in (cu.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                                   "cache_read_input_tokens"))
                   if isinstance(v, int) and not isinstance(v, bool) and v > 0)
    else:
        pct = cw.get("used_percentage")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            return None
        used = int(round(max(0, min(100, pct)) * window / 100))
    m = full.get("model")
    model = m.get("id") if isinstance(m, dict) else None
    return {"used": used, "window": window, "model": model[:100] if isinstance(model, str) else None}


def _statusline(ppid=None):
    """Status line Claude Code (statusLine v settings.json): obsazení kontextu pro měřič.
    Na rozdíl od transcriptu ho Claude Code předává vždy (transcript na disku být nemusí).
    Nic nevypisuje: status line zůstane prázdná."""
    full = read_hook()
    ctx = statusline_context(full)
    if ctx is None:
        return
    raw = {"hook_event_name": "StatusLine", "context": ctx}
    if isinstance(full.get("session_id"), str):
        raw["session_id"] = full["session_id"]
    _send({"v": 1, "source": "claude-code", "pid": _pid(ppid), "ts": time.time(), "raw": raw})


def main(ppid=None):
    if "--statusline" in sys.argv[2:]:
        try:
            _statusline(ppid)
        except Exception:
            discard()
        sys.exit(0)
    if "--povoleni" in sys.argv[2:]:    # samostatný hook PermissionRequest (docs/povoleni.md), jediný smí vypsat rozhodnutí
        try:
            from familiar import povoleni_klient
        except BaseException:
            discard()
            sys.exit(0)
        povoleni_klient.main(ppid)
    try:
        _emit(ppid)
    except Exception:
        discard()   # familiar nesmí nikdy ovlivnit agenta; po chybě při čtení dočíst vstup
    sys.exit(0)


if __name__ == "__main__":
    main()
