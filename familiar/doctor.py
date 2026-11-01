# familiar doctor: kontrola instalace, každý bod OK/CHYBA (POZOR = jen varování).
import json, logging, os, re, shutil, socket, statistics, subprocess, sys, tempfile, time

import familiar
from familiar import config, install, log, okna, paths, skin

EMIT_RUNS = 40
EMIT_WARMUP = 3     # první běhy po pauze (studená cache, úsporný stav CPU, kompilace .pyc) se nepočítají
EMIT_LIMIT_MS = 30  # platí pro p90: maximum z pár desítek běhů měří hlavně zátěž systému, ne emitter
HOOK_JSON = json.dumps({"hook_event_name": "PreToolUse", "session_id": "doctor", "cwd": "/tmp",
                        "tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "ls"}})


def measure_emit(exe, runs=EMIT_RUNS, warmup=EMIT_WARMUP):
    """Doby běhu emitteru v ms se socketem v dočasném adresáři; (časy, chyba nebo None).
    Emitter při poruše mlčí a končí 0, proto se po každém běhu ověří i doručený datagram."""
    return _measure([exe, "claude-code"], runs, warmup, HOOK_JSON.encode(), check=_datagram_error)


def _datagram_error(data):
    """Popis chyby doručeného datagramu (None = v pořádku), nebo že nedorazil (data None)."""
    if data is None:
        return "datagram nedorazil (emitter tiše selhal: prostředí, balíček nebo emit.py)"
    try:
        msg = json.loads(data)
        raw = msg["raw"]
        ok = (msg["v"] == 1 and msg["source"] == "claude-code" and msg["pid"] == os.getpid()
              and raw["tool_use_id"] == "t1" and raw["command"] == "ls" and raw["hook_event_name"] == "PreToolUse")
    except (ValueError, KeyError, TypeError):
        ok = False
    return None if ok else f"datagram s nečekaným obsahem: {data[:200]!r}"


def _measure(cmd, runs, warmup, stdin=b"", check=None):
    with tempfile.TemporaryDirectory(prefix="fam", dir="/tmp") as d:   # krátká cesta socketu
        env = dict(os.environ, XDG_RUNTIME_DIR=d)
        times = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.bind(os.path.join(d, "familiar.sock"))
            s.settimeout(2)     # datagram je ve frontě dřív, než emitter skončí; čeká se jen při chybě
            for i in range(warmup + runs):
                t = time.perf_counter()
                r = subprocess.run(cmd, input=stdin, env=env, capture_output=True, timeout=5)
                if i >= warmup:
                    times.append((time.perf_counter() - t) * 1000)
                if r.returncode != 0 or r.stdout:
                    return times, f"návratový kód {r.returncode}, stdout {len(r.stdout)} B"
                if check is not None:
                    try:
                        data = s.recv(65536)
                    except TimeoutError:
                        data = None
                    err = check(data)
                    if err:
                        return times, err
    return times, None


def _p90(times):
    s = sorted(times)
    return s[min(len(s) - 1, int(len(s) * 0.9))]


def emit_check(exe):
    """(ok, podrobnost) pro dobu emitteru. Hodnotí se p90, ne maximum: pomalé běhy chodí
    v dávkách se zátěží systému a stejně zpomalí i holý Python (ověřeno na 300+ bězích)."""
    times, err = measure_emit(exe)
    if err or not times:
        return False, err or "žádné měření"
    med, p90 = statistics.median(times), _p90(times)
    detail = (f"medián {med:.1f} ms, p90 {p90:.1f} ms (limit {EMIT_LIMIT_MS} ms), "
              f"max {max(times):.1f} ms jen informativně ({len(times)} běhů)")
    if p90 < EMIT_LIMIT_MS:
        return True, detail
    base, _ = _measure([sys.executable, "-I", "-S", "-c", "pass"], 10, 1)
    if base:    # pro srovnání: je pomalý emitter, nebo celý systém?
        detail += f"; holý python3 -I -S medián {statistics.median(base):.1f} ms"
    return False, detail


def checks():
    """[(ok, název, podrobnost)]"""
    out = []

    def add(ok, name, detail=""):
        out.append((ok, name, detail))

    pkg = os.path.dirname(os.path.abspath(familiar.__file__))
    add("site-packages" in pkg, f"verze {familiar.__version__}",
        pkg if "site-packages" in pkg else f"běží z repozitáře, ne z instalace: {pkg}")

    try:
        missing = install.missing_hooks(install._load_settings())
        add(not missing, "hooky v settings.json",
            f"chybí: {', '.join(missing)}" if missing else f"{len(install.EVENTS)} událostí")
    except (ValueError, OSError) as e:
        add(False, "hooky v settings.json", str(e))
    try:
        sl = install.statusline_status(install._load_settings())
        add(True if sl == "nase" else None, "status line (měřič kontextu)",
            {"nase": "nainstalována", "cizi": f"cizí status line; volej z ní `{install.CMD_STATUSLINE}`",
             }.get(sl, "chybí (familiar install), měřič pak čte jen transcript"))
    except (ValueError, OSError):
        pass    # vadný settings.json už ohlásila kontrola hooků

    for agent, a in install.AGENTS.items():     # jen agenti, které uživatel používá
        if not install.detected(agent):
            continue
        name = f"hooky {a['name']}"
        try:
            missing, present = install.agent_status(agent)
        except (ValueError, OSError) as e:
            add(False, name, str(e))
            continue
        if not present:
            add(True, name, f"nenainstalovány (familiar install --agents {agent})")
        else:
            add(not missing, name, f"chybí: {', '.join(missing)}" if missing
                else f"{present} událostí" + (", povol je v Codexu příkazem /hooks" if agent == "codex" else ""))

    emit = shutil.which("familiar-emit")
    if emit is None:
        add(False, "familiar-emit v PATH", "nenalezen")
    else:
        real = os.path.realpath(emit)
        add(not install._from_repo(emit), "familiar-emit v PATH",
            emit if real == emit else f"{emit} → {real}")

    pid = paths.daemon_pid()
    sock = os.path.exists(paths.sock())
    if pid is None:
        add(False, "daemon běží", "neběží (spusť `familiar run`)")
    else:
        add(sock, "daemon běží", (f"pid {pid}" if pid else "pid neznámé (starší verze)")
            + ("" if sock else f", chybí socket {paths.sock()}"))

    cfg = config.load()
    rows = okna.kontroly(cfg["okno"]["backend"])     # backend oken a jeho kontroly
    out.extend(rows)
    if okna.zvol(cfg["okno"]["backend"])[0] == "kwin":
        mode = paths.daemon_mode() if pid else None
        if not pid:
            add(True, "KWin skript familiar-perch", "nekontroluji, daemon neběží" if pid is None
                else "nekontroluji, daemon nezapsal režim (starší verze)")
        elif mode == "dock":
            add(True, "KWin skript familiar-perch", "nepoužívá se, daemon je v režimu dock")
        else:
            reply = install.dbus("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.isScriptLoaded",
                                 "familiar-perch")
            add(reply == "(true,)", "KWin skript familiar-perch",
                "nahrán (režim perch)" if reply == "(true,)" else f"nenahrán, ač je daemon v režimu {mode or 'perch'}")
        add(install.has_rule(install._read(paths.kwinrules())), "pravidlo KWinu", paths.kwinrules())

    add(os.path.exists(paths.desktop_file()), "spouštěč v nabídce", paths.desktop_file())

    if cfg.errors:
        add(False, "konfigurace", f"{len(cfg.errors)} chyb (familiar config --check): {cfg.errors[0]}")
    else:
        add(True, "konfigurace", (cfg.path if cfg.exists else "výchozí (soubor neexistuje)")
            + (f", {len(cfg.warnings)} varování" if cfg.warnings else ""))

    add(*povoleni_check(cfg))

    skin_log = logging.getLogger(skin.__name__)
    skin_log.disabled = True        # chybu skinu ukáže řádek níže, ne varování na stderr
    try:
        s = skin.load(cfg["skin"])
    finally:
        skin_log.disabled = False
    add(s.error is None, f"skin {cfg['skin']}", s.error or f"{s.name} ({s.source})")

    if cfg["upozorneni"]["zvuky"]:
        ok, detail = zvuky()
        add(ok, "přehrávání zvuků", detail)

    lp = str(log.log_path())
    old = [os.path.getsize(f) for f in (f"{lp}.{i}" for i in range(1, log.BACKUPS + 1)) if os.path.exists(f)]
    add(True, "log", f"{config._short(lp)}, "
        + (f"{os.path.getsize(lp) / 1024:.0f} kB" if os.path.exists(lp) else "zatím neexistuje")
        + (f" + {len(old)} starší ({sum(old) / 1024:.0f} kB)" if old else ""))

    ok, detail = tray(pid)
    add(ok, "ikona v liště", detail)

    if emit is not None:
        ok, detail = emit_check(emit)
        add(ok, "doba emitteru", detail)
    return out


def zvuky():
    """(ok, podrobnost): čím se přehrají zvuky upozornění (QSoundEffect, pw-play, paplay)."""
    from familiar import upozorneni
    zpusob = upozorneni.zpusob_prehravani()
    if zpusob is None:
        return False, "chybí QtMultimedia (QSoundEffect) i pw-play/paplay; vypni zvuky nebo doinstaluj pipewire-utils"
    return True, "QSoundEffect (QtMultimedia)" if zpusob == "qt" else zpusob


def povoleni_check(cfg):
    """(ok, název, podrobnost) pro povolení z bubliny; ok None = jen varování (exit 0):
    zapnuto v configu, ale hook PermissionRequest v settings.json chybí."""
    name = "povolení z bubliny"
    try:
        hook = install.has_povoleni(install._load_settings())
    except (ValueError, OSError) as e:
        return False, name, f"settings.json nejde přečíst: {e}"
    if cfg["povoleni"]["zapnuto"]:
        if not hook:
            return None, name, "zapnuto v configu, ale chybí hook (familiar install --povoleni)"
        return True, name, "zapnuto, hook nainstalován"
    if hook:
        return True, name, "hook nainstalován, v configu vypnuto (klient hned skončí; [povoleni] zapnuto = true)"
    return True, name, "vypnuto"


SNW = ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.freedesktop.DBus.Properties.Get",
       "org.kde.StatusNotifierWatcher")


def tray(pid):
    """(ok, podrobnost): je systémový tray (StatusNotifierWatcher) a registroval do něj běžící daemon ikonu?
    Bez traye mimo KDE to není chyba, nabídka je i na postavičce (pravé tlačítko)."""
    host = install.dbus(*SNW, "IsStatusNotifierHostRegistered")
    if host != "(<true>,)":
        kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")
        return not kde, "systémový tray nedostupný (nabídka jen pravým tlačítkem na postavičce)"
    if pid is None:
        return True, "tray dostupný, daemon neběží"
    if pid == 0:
        return False, "tray dostupný, daemon nezapsal pid (starší verze), ikonu nejde ověřit; restartuj ho"
    items = install.dbus(*SNW, "RegisteredStatusNotifierItems") or ""
    for service in re.findall(r"'([^'/]+)[^']*'", items):
        owner = install.dbus("org.freedesktop.DBus", "/org/freedesktop/DBus",
                             "org.freedesktop.DBus.GetConnectionUnixProcessID", service)
        if owner and re.search(rf"\b{pid}\b", owner):
            return True, f"tray dostupný, ikona daemonu registrovaná ({service})"
    return False, "tray dostupný, ale ikona daemonu v něm není (restart: familiar stop && familiar run)"


def main():
    results = checks()
    for ok, name, detail in results:
        print(f"{'POZOR' if ok is None else 'OK   ' if ok else 'CHYBA'}  {name}" + (f": {detail}" if detail else ""))
    return 0 if all(ok is not False for ok, _, _ in results) else 1     # None = varování
