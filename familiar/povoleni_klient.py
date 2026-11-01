# Klient hooku PermissionRequest: `familiar-emit claude-code --povoleni` (docs/povoleni.md).
#
# Zeptá se daemonu (familiar/povoleni.py) přes stream socket a čeká, až uživatel klikne
# v bublině u postavičky. Rozhodnutí (JSON na stdout) vypíše jen po odpovědi daemonu;
# sám nikdy nic nerozhodne. Daemon neběží, odmítne, zavře spojení, timeout nebo jakákoli
# chyba → exit 0 bez výstupu = Claude Code ukáže (nebo už ukazuje) dialog v terminálu.
# Do daemonu jde jen shrnutí (nástroj, příkaz, cesta, URL), nikdy text promptu ani obsah
# souboru. Co se do bubliny nevejde celé, smí bublina jen zamítnout.
# Běží ze spouštěče jako emit.py (python -I -S): jen posix a C moduly.
import posix, sys

from familiar import emit

SOCK = "familiar-povoleni.sock"
CEKAT_S = 595.0         # nejdéle; Claude Code hook zabije po 600 s (timeout v settings.json)
CEKAT_AGENT_S = 20.0    # subagent na pozadí / session bez terminálu: Claude čeká na hook (i když daemon visí)
MAX_VSTUP = 8 << 20     # větší vstup (Write s obřím obsahem) se neparsuje: dialog v terminálu
MAX_ODPOVED = 4096
NEPODPOROVANE = {"AskUserQuestion", "ExitPlanMode"}     # allow z hooku nic neodpoví / plán patří do terminálu
DUVOD = "Uživatel to zamítl v bublině familiara."
ROZHODNUTI = ("allow", "deny", "allow_always")
CO_ZNAKU = 500          # delší příkaz/cesta/URL = zkrácené → bublina nabídne jen Zamítnout
VZDY_ZNAKU = 300        # delší popis „vždy povolit“ = tlačítko Vždy se neukáže
CILE_PRAVIDEL = ("session", "localSettings", "projectSettings")     # userSettings ne (platí všude)
KAM = {"session": "session", "localSettings": "projekt", "projectSettings": "projekt, sdílené"}
REZIMY = ("acceptEdits",)   # setMode jen tyto, jen pro session
KLICE_TEXT = ("query", "skill")     # WebSearch, Skill: krátký text bez obsahu souboru


def sock_path():
    """Stream socket daemonu vedle datagramového (stejná kontrola soukromého adresáře)."""
    p = emit.sock_path()
    return None if p is None else p[:p.rfind("/") + 1] + SOCK


def _home():
    v = posix.environ.get(b"HOME")
    return v.decode(errors="replace").rstrip("/") if v else None


def _kratce(text, n=CO_ZNAKU):
    text = " ".join(str(text).split())      # jeden řádek
    return text if len(text) <= n else text[:n - 1] + "…"


def _radky(text, n=CO_ZNAKU):
    """(text, zkráceno): řádky bez prázdných, mezery v řádku sloučené, nejvýš n znaků."""
    text = "\n".join(r for r in (" ".join(r.split()) for r in str(text).split("\n")) if r)
    return (text, False) if len(text) <= n else (text[:n - 1] + "…", True)


def _cesta(p, n=CO_ZNAKU):
    home = _home()
    if home and (p == home or p.startswith(home + "/")):
        p = "~" + p[len(home):]
    return p if len(p) <= n else "…" + p[-(n - 1):]   # konec cesty je důležitější


def shrnuti_vstupu(tool, ti):
    """(co, zkráceno, dotaz): příkaz Bash (řádky), cesta, celá URL, nebo krátký text.
    zkráceno = uživatel by v bublině neviděl celý vstup (dlouhý, nebo nástroj, který
    neumíme shrnout); dotaz = URL s query. Obojí → bublina nabídne jen Zamítnout."""
    if not isinstance(ti, dict):
        return "", False, False
    cmd = ti.get("command")
    if isinstance(cmd, str):
        return _radky(cmd) + (False,)
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(ti.get(key), str):
            return _cesta(ti[key]), len(ti[key]) > CO_ZNAKU or "\n" in ti[key], False
    url = ti.get("url")
    if isinstance(url, str):
        text, zkraceno = _radky(url)
        return text, zkraceno or "\n" in text, "?" in url
    for key in KLICE_TEXT:
        if isinstance(ti.get(key), str):
            text, zkraceno = _radky(ti[key])
            return text, zkraceno, False
    return "", any(k != "description" for k in ti), False


def co(tool, ti):
    """Bezpečné shrnutí vstupu nástroje (jen text, viz shrnuti_vstupu)."""
    return shrnuti_vstupu(tool, ti)[0]


def vzdy_popis(suggestions):
    """Popis voleb „vždy povolit“ z povolených návrhů, nebo None (tlačítko Vždy se neukáže):
    žádný návrh, nebo by se popis nevešel celý."""
    parts = []
    for s in _navrhy(suggestions):
        kam = KAM.get(s.get("destination"), "?")
        if s["type"] == "addRules":
            pravidla = []
            for r in s["rules"]:
                rc = r.get("ruleContent")
                pravidla.append(r["toolName"] + (f"({rc})" if isinstance(rc, str) and rc else ""))
            parts.append(", ".join(pravidla) + f" [{kam}]")
        elif s["type"] == "addDirectories":
            parts.append("složky " + ", ".join(_cesta(d) for d in s["directories"]) + f" [{kam}]")
        else:
            parts.append(f"režim {s['mode']} [{kam}]")
    if not parts:
        return None
    text = " ".join("; ".join(parts).split())
    return text if len(text) <= VZDY_ZNAKU else None


def _navrh_ok(s):
    """Allowlist návrhů pro „Vždy“ (zdůvodnění v docs/povoleni.md)."""
    t, kam = s.get("type"), s.get("destination")
    if t == "addRules":
        rules = s.get("rules")
        return (s.get("behavior") == "allow" and kam in CILE_PRAVIDEL and isinstance(rules, list) and rules
                and all(isinstance(r, dict) and isinstance(r.get("toolName"), str) and r["toolName"]
                        and isinstance(r.get("ruleContent", ""), str) for r in rules))
    if t == "addDirectories":
        d = s.get("directories")
        return kam == "session" and isinstance(d, list) and d and all(isinstance(x, str) and x for x in d)
    if t == "setMode":
        return kam == "session" and s.get("mode") in REZIMY
    return False


def _navrhy(suggestions):
    """Návrhy, které smí bublina použít (_navrh_ok); ostatní se zahodí."""
    if not isinstance(suggestions, list):
        return []
    return [s for s in suggestions if isinstance(s, dict) and _navrh_ok(s)]


def bez_terminalu(pid):
    """Claude bez interaktivního terminálu (`claude -p`, SDK): stdin není terminál, nebo je
    v příkazu -p/--print. Pak dialog není a bublina by žádost jen zdržela → krátký timeout.
    Neznámé (proces nejde přečíst) = interaktivní."""
    try:
        cil = posix.readlink(f"/proc/{pid}/fd/0")
    except (OSError, ValueError):
        return False
    if not cil.startswith(("/dev/pts/", "/dev/tty")):
        return True
    try:
        fd = posix.open(f"/proc/{pid}/cmdline", posix.O_RDONLY)
        try:
            args = posix.read(fd, 1 << 16).split(b"\0")
        finally:
            posix.close(fd)
    except OSError:
        return False
    return b"-p" in args or b"--print" in args


def pozadavek(hook, pid, headless=False):
    tool = hook.get("tool_name") if isinstance(hook.get("tool_name"), str) else "?"
    text, zkraceno, dotaz = shrnuti_vstupu(tool, hook.get("tool_input"))
    return {"v": 1, "session": hook.get("session_id") if isinstance(hook.get("session_id"), str) else "",
            "pid": pid, "agent": bool(hook.get("agent_id")), "bez_terminalu": bool(headless),
            "shrnuti": {"nastroj": _kratce(tool, 60), "co": text, "zkraceno": zkraceno, "dotaz": dotaz,
                        "vzdy": vzdy_popis(hook.get("permission_suggestions"))}}


def jen_zamitnout(hook):
    """Bublina smí jen zamítnout (vstup se do ní celý nevejde nebo URL má query)."""
    _, zkraceno, dotaz = shrnuti_vstupu(hook.get("tool_name"), hook.get("tool_input"))
    return zkraceno or dotaz


def vystup(rozhodnuti, hook):
    """JSON rozhodnutí pro Claude Code, nebo None (žádné rozhodnutí). Povolit jen to, co šlo
    v bublině vidět celé; „Vždy“ jen s návrhy, jejichž popis bublina ukázala."""
    if rozhodnuti == "deny":
        decision = {"behavior": "deny", "message": DUVOD}
    elif rozhodnuti in ("allow", "allow_always"):
        if jen_zamitnout(hook):
            return None
        decision = {"behavior": "allow"}
        sugg = hook.get("permission_suggestions")
        if rozhodnuti == "allow_always" and vzdy_popis(sugg) is not None:
            decision["updatedPermissions"] = _navrhy(sugg)
    else:
        return None
    return emit.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}})


def _connect():
    path = sock_path()
    if path is None:
        return None
    s = emit.socket.socket(emit.socket.AF_UNIX, emit.socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)      # lokální socket: connect je hned, nebo vůbec
        s.connect(path)
    except OSError:
        s.close()
        return None
    return s


def _read_all(fd=0):
    """Celý vstup hooku; None, když je větší než MAX_VSTUP (zbytek se dočte naprázdno)."""
    buf, data = bytearray(1 << 18), bytearray()
    while True:
        got = posix.readv(fd, [buf])
        if not got:
            return bytes(data)
        data += memoryview(buf)[:got]
        if len(data) > MAX_VSTUP:
            emit.discard(fd)
            return None


def _cekat(argv):
    for a in argv:
        if a.startswith("--cekat="):
            try:
                v = float(a[8:])
                if 0 < v < 3600:
                    return v
            except ValueError:
                pass
    return CEKAT_S


def _odpoved(s, cekat):
    """Rozhodnutí z jednoho řádku odpovědi daemonu, nebo None (zavřel, timeout, nesmysl)."""
    s.settimeout(cekat)
    data = b""
    while b"\n" not in data and len(data) < MAX_ODPOVED:
        got = s.recv(MAX_ODPOVED)
        if not got:
            return None
        data += got
    if b"\n" not in data:
        return None
    msg = emit.loads(data.split(b"\n", 1)[0].decode())
    r = msg.get("rozhodnuti") if isinstance(msg, dict) else None
    return r if r in ROZHODNUTI else None


def run(ppid=None, argv=None):
    """Vrací text pro stdout, nebo None. Vstup hooku vždy dočte."""
    argv = sys.argv[1:] if argv is None else argv
    s = _connect()
    if s is None:
        emit.discard()      # daemon neběží: jen dočíst vstup, rychle pryč
        return None
    try:
        raw = _read_all()
        if not raw:
            return None
        with emit._NoJsonImport():
            hook = emit.loads(raw.decode())
        if not isinstance(hook, dict) or hook.get("tool_name") in NEPODPOROVANE:
            return None
        pid = emit._pid(ppid)
        headless = bez_terminalu(pid)
        s.sendall((emit.dumps(pozadavek(hook, pid, headless)) + "\n").encode())
        cekat = _cekat(argv)
        if hook.get("agent_id") or headless:
            cekat = min(cekat, CEKAT_AGENT_S)
        return vystup(_odpoved(s, cekat), hook)
    finally:
        s.close()


def main(ppid=None):
    out = None
    try:
        out = run(ppid)
    except BaseException:
        emit.discard()
        out = None
    if out:
        try:
            posix.write(1, (out + "\n").encode())
        except OSError:
            pass
    sys.exit(0)
