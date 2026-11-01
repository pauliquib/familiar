# familiar install / uninstall: hooky Claude Code (a Gemini CLI, Codexu), pravidlo KWinu (jen na
# KDE), rozšíření GNOME Shellu (volba --gnome-rozsireni, familiar/gnome.py), .desktop, autostart.
#
# Idempotentní: co už je hotové, přeskočí. Každý měněný soubor se nejdřív zálohuje
# do ~/.local/share/familiar/backup/<čas>/ (cesta relativně k HOME) a zapisuje se
# atomicky (dočasný soubor + rename). Cesty jsou z HOME/XDG_* (familiar/paths.py).
#
# Pořadí kroků: emitter v PATH dřív než hooky, při odinstalaci hooky jako první,
# takže hook nikdy nevolá chybějící familiar-emit.
import datetime, json, os, shutil, subprocess, sys, uuid

from familiar import __version__, paths

CMD = "familiar-emit claude-code"
CMD_POVOLENI = "familiar-emit claude-code --povoleni"    # volitelný hook: povolení z bubliny (docs/povoleni.md)
POVOLENI_EVENT = "PermissionRequest"
CMD_STATUSLINE = "familiar-emit claude-code --statusline"     # měřič kontextu (transcript na disku být nemusí)
POVOLENI_TIMEOUT = 600      # = výchozí timeout Claude Code; klient čeká nejvýš 595 s, bublinu dřív zruší daemon
EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
          "PostToolUseFailure", "PermissionRequest", "PermissionDenied", "Stop", "StopFailure",
          "SubagentStart", "SubagentStop", "PreCompact")
MATCHER = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"}
# Další agenti (docs/agenti.md): stejný tvar hooks → událost → [{matcher, hooks: [...]}].
# Gemini má timeout v ms, Codex v s. "auto" = jen agenti, jejichž adresář nastavení existuje.
AGENTS = {
    "gemini": {"name": "Gemini CLI", "dir": paths.gemini_dir, "file": "settings.json",
               "events": ("SessionStart", "SessionEnd", "BeforeAgent", "AfterAgent", "BeforeTool",
                          "AfterTool", "Notification", "PreCompress"),
               "matcher": {"BeforeTool", "AfterTool"},
               "hook": {"name": "familiar", "type": "command", "command": "familiar-emit gemini", "timeout": 2000}},
    "codex": {"name": "Codex", "dir": paths.codex_dir, "file": "hooks.json",
              "events": ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                         "PermissionRequest", "Stop", "Interrupt", "SubagentStart", "SubagentStop", "PreCompact"),
              "matcher": {"PreToolUse", "PostToolUse", "PermissionRequest"},
              "hook": {"type": "command", "command": "familiar-emit codex", "timeout": 2}},
}
RULE_DESC = "familiar: vždy navrchu"
RULE = [f"Description={RULE_DESC}", "above=true", "aboverule=2", "skippager=true", "skippagerrule=2",
        "skipswitcher=true", "skipswitcherrule=2", "skiptaskbar=true", "skiptaskbarrule=2",
        "wmclass=familiar", "wmclassmatch=1"]
DESKTOP = """[Desktop Entry]
Type=Application
Name=Familiar
Comment=Pixelová postavička, která ukazuje, co dělá Claude Code
Exec={exe} run
Icon=applications-games
Terminal=false
Categories=Utility;
StartupWMClass=familiar
"""


def dbus(dest, path, method, *args):
    """Volání D-Bus přes gdbus; vrací výstup, nebo None (bez sběrnice, chyba)."""
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", dest, "--object-path", path,
                            "--method", method, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def _atomic_write(path, text):
    path = os.path.realpath(path)     # settings.json může být odkaz do dotfiles
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o644
    tmp = f"{path}.familiar-tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


class Run:
    """Jeden běh install/uninstall: nanečisto, nebo naostro se společným adresářem záloh."""

    def __init__(self, dry):
        self.dry, self.backup_dir, self.changes = dry, None, 0

    def say(self, msg):
        print(("nanečisto: " if self.dry else "") + msg)

    def backup(self, path, follow=False):
        """Záloha před změnou; follow=False u odkazu zálohuje odkaz samotný (ten se mění)."""
        if not os.path.lexists(path):
            return
        if self.backup_dir is None:
            base = os.path.join(paths.data_dir(), "backup", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            self.backup_dir, n = base, 1
            while os.path.exists(self.backup_dir):
                n += 1
                self.backup_dir = f"{base}-{n}"
        rel = os.path.relpath(path, paths.home())
        dst = os.path.join(self.backup_dir, os.path.basename(path) if rel.startswith("..") else rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.islink(path) and not follow:
            os.symlink(os.readlink(path), dst)
        else:
            shutil.copy2(path, dst)     # u odkazu (settings.json do dotfiles) obsah cíle

    def write(self, path, text, what, backup=True):
        if _read(path) == text:
            return False
        self.say(f"{what}: {path}")
        self.changes += 1
        if not self.dry:
            if backup:
                self.backup(path, follow=True)     # zapisuje se do cíle odkazu
            _atomic_write(path, text)
        return True

    def remove(self, path, what, backup=True):
        if not os.path.lexists(path):
            return False
        self.say(f"{what}: {path}")
        self.changes += 1
        if not self.dry:
            if backup:
                self.backup(path)
            os.unlink(path)
        return True


# --- hooky v ~/.claude/settings.json ---

def _ours_any(hook):
    """Jakýkoli hook familiara (pro odinstalaci)."""
    cmd = hook.get("command") if isinstance(hook, dict) else None
    return isinstance(cmd, str) and bool(cmd.split()) and os.path.basename(cmd.split()[0]) == "familiar-emit"


def _ours_povoleni(hook):
    return _ours_any(hook) and "--povoleni" in hook["command"].split()[1:]


def _ours(hook):
    """Hook emitteru (bez povolovacího)."""
    return _ours_any(hook) and not _ours_povoleni(hook)


def _entries(settings, event):
    hooks = settings.get("hooks")
    entries = hooks.get(event) if isinstance(hooks, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def missing_hooks(settings, events=EVENTS):
    """Události, u kterých chybí hook familiara."""
    return [ev for ev in events
            if not any(_ours(h) for e in _entries(settings, ev) for h in e.get("hooks") or ())]


def add_hooks(settings, events=EVENTS, matcher=MATCHER, hook=None):
    """Doplní chybějící hooky (stejný tvar jako ruční instalace); events, matcher a hook
    jiného agenta (AGENTS), výchozí jsou Claude Code.

    Vrací (doplněné události, přeskočené události s cizí hodnotou, která není seznam,
    cizí prázdné hodnoty – události nebo "hooks" –, které má uninstall nechat)."""
    missing = missing_hooks(settings, events)
    added, skipped, empty = [], [], ["hooks"] if missing and settings.get("hooks") == {} else []
    if missing and "hooks" not in settings:
        settings["hooks"] = {}
    hooks = settings["hooks"] if missing else {}
    if not isinstance(hooks, dict):
        raise ValueError("klíč hooks není objekt")
    for ev in missing:
        if ev in hooks and not isinstance(hooks[ev], list):
            skipped.append(ev)      # cizí tvar nepřepisovat
            continue
        if hooks.get(ev) == []:
            empty.append(ev)
        entry = {"matcher": "*"} if ev in matcher else {}
        entry["hooks"] = [dict(hook or {"type": "command", "command": CMD, "timeout": 2})]
        hooks.setdefault(ev, []).append(entry)
        added.append(ev)
    return added, skipped, empty


def remove_hooks(settings, keep_empty=(), which=None):
    """Odebere jen hooky familiara (which: test hooku, výchozí všechny familiara). Zmizí jen
    položky, události a klíč hooks, které tím zůstaly prázdné, a ne ty, které byly prázdné
    už před instalací (keep_empty, viz add_hooks). Cizí položky zůstanou. Vrací počet odebraných."""
    which = which or _ours_any
    hooks, n = settings.get("hooks"), 0
    if not isinstance(hooks, dict):
        return 0
    for ev in list(hooks):
        if not isinstance(hooks[ev], list):
            continue
        kept_entries, removed = [], 0
        for e in hooks[ev]:
            if isinstance(e, dict) and isinstance(e.get("hooks"), list):
                kept = [h for h in e["hooks"] if not which(h)]
                if len(kept) < len(e["hooks"]):
                    removed += len(e["hooks"]) - len(kept)
                    if not kept:
                        continue
                    e = dict(e, hooks=kept)
            kept_entries.append(e)
        if removed:
            n += removed
            if kept_entries or ev in keep_empty:
                hooks[ev] = kept_entries
            else:
                del hooks[ev]
    if n and not hooks and "hooks" not in keep_empty:
        del settings["hooks"]
    return n


def has_povoleni(settings):
    return any(_ours_povoleni(h) for e in _entries(settings, POVOLENI_EVENT) for h in e.get("hooks") or ())


def add_povoleni(settings):
    """Přidá povolovací hook (vlastní položka s matcherem *). True = přidán, False = už byl.
    ValueError, když hooks nebo událost nemají tvar, do kterého jde přidat."""
    if has_povoleni(settings):
        return False
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict) or not isinstance(hooks.setdefault(POVOLENI_EVENT, []), list):
        raise ValueError(f"hooks.{POVOLENI_EVENT} nemá tvar seznamu")
    hooks[POVOLENI_EVENT].append({"matcher": "*", "hooks": [
        {"type": "command", "command": CMD_POVOLENI, "timeout": POVOLENI_TIMEOUT}]})
    return True


def remove_povoleni(settings, keep_empty=()):
    return remove_hooks(settings, keep_empty, which=_ours_povoleni)


# --- status line: obsazení kontextu pro měřič ---

def _ours_statusline(settings):
    sl = settings.get("statusLine")
    return isinstance(sl, dict) and _ours_any(sl)


def statusline_status(settings):
    """"nase" (familiar), "cizi" (jiná status line, nechává se) nebo "chybi"."""
    if _ours_statusline(settings):
        return "nase"
    return "cizi" if settings.get("statusLine") else "chybi"


def add_statusline(settings):
    """Status line familiara, když žádná není. True = přidána; cizí se nepřepisuje."""
    if statusline_status(settings) != "chybi":
        return False
    settings["statusLine"] = {"type": "command", "command": CMD_STATUSLINE, "padding": 0}
    return True


def remove_statusline(settings):
    if not _ours_statusline(settings):
        return False
    del settings["statusLine"]
    return True


def _load_settings(path=None):
    path = path or paths.claude_settings()
    text = _read(path)
    if text is None:
        return {}
    data = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant,
                      parse_float=_finite)  # vadný nebo nejednoznačný JSON (i s komentáři): raději skončit
    if not isinstance(data, dict):
        raise ValueError(f"{os.path.basename(path)} není objekt")
    return data


def _no_duplicates(pairs):
    d = dict(pairs)
    if len(d) != len(pairs):
        dup = sorted({k for k, _ in pairs if sum(1 for k2, _ in pairs if k2 == k) > 1})
        raise ValueError(f"duplicitní klíč {', '.join(dup)} (zápis by jeden z nich ztratil)")
    return d


def _no_constant(name):
    raise ValueError(f"{name} není platný JSON")


def _finite(text):
    value = float(text)
    if value in (float("inf"), float("-inf")):
        raise ValueError(f"číslo {text} je mimo rozsah (zápis by vytvořil neplatný JSON)")
    return value


def _dump(settings):
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


# --- hooky dalších agentů ---

def agent_file(agent):
    a = AGENTS[agent]
    return os.path.join(a["dir"](), a["file"])


def detected(agent):
    """Používá uživatel agenta? Jeho adresář nastavení existuje (agent už aspoň jednou běžel)."""
    return os.path.isdir(AGENTS[agent]["dir"]())


def parse_agents(value, default):
    """--agents: "auto" (zjištění), "none" (žádný), "all" (všichni), nebo "gemini,codex"."""
    value = (default if value is None else value).strip()
    if value == "auto":
        return [a for a in AGENTS if detected(a)]
    if value in ("none", ""):
        return []
    if value == "all":
        return list(AGENTS)
    chosen = [a.strip() for a in value.split(",") if a.strip()]
    bad = [a for a in chosen if a not in AGENTS]
    if bad:
        raise ValueError(f"neznámý agent {', '.join(bad)} (známí: {', '.join(AGENTS)})")
    return chosen


def agent_status(agent):
    """(chybějící události, kolik hooků familiara tam je) – pro doctor; ValueError u vadného souboru."""
    settings = _load_settings(agent_file(agent))
    missing = missing_hooks(settings, AGENTS[agent]["events"])
    return missing, len(AGENTS[agent]["events"]) - len(missing)


def _install_agent(run, agent, record):
    """Doplní hooky agenta. Vadný soubor agenta instalaci nezastaví, jen se přeskočí."""
    a, path = AGENTS[agent], agent_file(agent)
    try:
        settings = _load_settings(path)
        existed = os.path.lexists(path)
        added, skipped, empty = add_hooks(settings, a["events"], a["matcher"], a["hook"])
    except ValueError as e:
        print(f"POZOR: {path} nejde přečíst ({e}), hooky {a['name']} nechávám být")
        return
    if added and run.write(path, _dump(settings), f"hooky {a['name']} ({len(added)} událostí)"):
        if not existed:
            record[f"created_{agent}"] = True
        if agent == "codex":
            print("Codex: nové hooky je potřeba jednou povolit v Codexu příkazem /hooks")
    if skipped:
        print(f"POZOR: hooky {a['name']} {', '.join(skipped)} nemají tvar seznamu, doplň familiar ručně")
    key = f"keep_empty_{agent}"
    if empty or record.get(key):
        record[key] = sorted(set(record.get(key, [])) | set(empty))


def _uninstall_agent(run, agent, record):
    a, path = AGENTS[agent], agent_file(agent)
    if not os.path.lexists(path):
        return
    try:
        settings = _load_settings(path)
    except ValueError as e:
        print(f"POZOR: {path} nejde přečíst ({e}), hooky {a['name']} odeber ručně")
        return
    if not remove_hooks(settings, record.get(f"keep_empty_{agent}", ())):
        return
    if not settings and record.get(f"created_{agent}"):
        run.remove(path, f"odebírám hooky {a['name']} (soubor založil familiar)")
        record.pop(f"created_{agent}", None)
    else:
        run.write(path, _dump(settings), f"odebírám hooky {a['name']}")


# --- pravidlo KWinu v kwinrulesrc (INI, KConfig) ---

def _ini(text):
    """[(skupina nebo None pro začátek souboru, [řádky bez prázdných na konci])]."""
    groups = [[None, []]]
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            groups.append([s[1:-1], []])
        else:
            groups[-1][1].append(line)
    for g in groups:
        while g[1] and not g[1][-1].strip():
            g[1].pop()
    return [g for g in groups if g[0] is not None or g[1]]


def _ini_text(groups):
    parts = ["\n".join(([f"[{name}]"] if name is not None else []) + lines) for name, lines in groups]
    return "\n\n".join(parts) + "\n" if parts else ""


def _value(lines, key):
    for line in lines:
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            return v.strip()
    return None


def _set(lines, key, value):
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == key:
            lines[i] = f"{key}={value}"
            return
    lines.append(f"{key}={value}")


def _set_rules(groups, ids):
    general = next((g for g in groups if g[0] == "General"), None)
    if general is None:
        general = ["General", []]
        groups.append(general)
    _set(general[1], "count", len(ids))
    _set(general[1], "rules", ",".join(ids))


def _rule_ids(groups):
    general = next((g for g in groups if g[0] == "General"), None)
    value = _value(general[1], "rules") if general else None
    return [r for r in (value or "").split(",") if r]


def has_rule(text):
    return any(name not in (None, "General") and _value(lines, "wmclass") == "familiar"
               for name, lines in _ini(text))


def add_rule(text, rule_id=None):
    """kwinrulesrc s pravidlem familiara; existující pravidlo s wmclass=familiar nezdvojí."""
    if has_rule(text):
        return text
    groups = _ini(text)
    rule_id = rule_id or str(uuid.uuid4())
    at = next((i for i, g in enumerate(groups) if g[0] == "General"), len(groups))
    groups.insert(at, [rule_id, list(RULE)])
    _set_rules(groups, _rule_ids(groups) + [rule_id])
    return _ini_text(groups)


def remove_rule(text):
    """Odebere jen pravidla familiara (wmclass=familiar a náš popis)."""
    groups = _ini(text)
    ours = {name for name, lines in groups if name not in (None, "General")
            and _value(lines, "wmclass") == "familiar" and _value(lines, "Description") == RULE_DESC}
    if not ours:
        return text
    groups = [g for g in groups if g[0] not in ours]
    _set_rules(groups, [r for r in _rule_ids(groups) if r not in ours])
    return _ini_text(groups)


def _desktop():
    return os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")


def _kwin_reconfigure(run):
    if run.dry:
        run.say("KWin: reconfigure přes D-Bus")
    elif dbus("org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure") is None:
        print("KWin: reconfigure se nepovedlo (neběží KWin?), pravidlo začne platit po přihlášení")


# --- rozšíření GNOME Shellu ---

def _gnome_extensions(*args):
    """gnome-extensions …; True = uspělo (False i když příkaz chybí)."""
    if not shutil.which("gnome-extensions"):
        return False
    try:
        return subprocess.run(["gnome-extensions", *args], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _gnome_rozsireni(run):
    """Zapíše rozšíření do ~/.local/share/gnome-shell/extensions/<uuid>/ a zapne ho, jde-li to."""
    from familiar import gnome
    files = gnome.soubory()
    if files is None:
        print("CHYBA: zdroj rozšíření GNOME Shellu v balíčku chybí, rozšíření neinstaluji")
        return
    zmena = False
    for name, text in files.items():
        zmena |= run.write(os.path.join(gnome.cil(), name), text, f"rozšíření GNOME Shellu ({name})")
    zapni = f"gnome-extensions enable {gnome.UUID}"
    if run.dry:
        run.say(f"rozšíření GNOME Shellu: {zapni}")
    elif _gnome_extensions("enable", gnome.UUID):
        print(f"rozšíření GNOME Shellu {gnome.UUID} zapnuto"
              + (" (novou verzi GNOME na Waylandu načte po odhlášení a přihlášení)" if zmena else ""))
    else:
        how = zapni if shutil.which("gnome-extensions") else f"aplikace Rozšíření, nebo {zapni}"
        print(f"rozšíření GNOME Shellu zapni po odhlášení a přihlášení (Wayland ho do té doby nevidí): {how}")


def _gnome_odeber(run):
    from familiar import gnome
    meta = os.path.join(gnome.cil(), "metadata.json")
    if gnome.UUID not in (_read(meta) or ""):
        return
    if not run.dry:
        _gnome_extensions("disable", gnome.UUID)
    for name in (*gnome.SOUBORY, "perch.js"):
        run.remove(os.path.join(gnome.cil(), name), "odebírám rozšíření GNOME Shellu")
    if not run.dry:
        try:
            os.rmdir(gnome.cil())
        except OSError:
            pass


# --- emitter, starý wrapper, .desktop ---

def _from_repo(path):
    """Vede příkaz do repozitáře (starý odkaz na familiar/emit.py)?"""
    real = os.path.realpath(path)
    return real.endswith(os.path.join("familiar", "emit.py")) and "site-packages" not in real


def installed(name):
    """Příkaz z prostředí (venv uv/pipx), ve kterém běží tento familiar, nebo None."""
    if sys.prefix == sys.base_prefix:
        return None
    path = os.path.join(sys.prefix, "bin", name)
    return path if os.path.exists(path) else None


def _replaceable(link, name):
    """Smí install odkaz přesměrovat? Chybí, vede do repa, nebo je to odkaz do jiného prostředí."""
    if not os.path.lexists(link):
        return True
    return _from_repo(link) or (os.path.islink(link) and os.readlink(link).endswith(f"/bin/{name}"))


def _links(run):
    """~/.local/bin/familiar a familiar-emit → nainstalované prostředí (atomicky, bez okna)."""
    for name in ("familiar-emit", "familiar"):
        link = os.path.join(paths.bin_dir(), name)
        target = installed(name)
        if target is None:
            if _from_repo(link) or not os.path.lexists(link):
                print(f"{name}: přeskočeno, familiar neběží z nainstalovaného prostředí (spusť install.sh)")
            continue
        if os.path.realpath(link) == os.path.realpath(target) or not _replaceable(link, name):
            continue
        run.say(f"{name} → {target}: {link}")
        run.changes += 1
        if not run.dry:
            run.backup(link)
            os.makedirs(os.path.dirname(link), exist_ok=True)
            tmp = f"{link}.familiar-tmp{os.getpid()}"
            os.symlink(target, tmp)
            os.replace(tmp, link)       # atomicky: hook vždy najde nějaký familiar-emit


def _old_wrapper(run):
    path = os.path.join(paths.bin_dir(), "familiar-dock")
    if os.path.isfile(path) and not os.path.islink(path) and "familiar.dock" in (_read(path) or ""):
        run.remove(path, "odstraňuji starý spouštěč (nahrazuje ho `familiar run`)")


def desktop_text():
    exe = os.path.join(paths.bin_dir(), "familiar")
    return DESKTOP.format(exe=exe if os.path.exists(exe) else "familiar")


def _is_our_desktop(path):
    text = _read(path) or ""
    return "Name=Familiar" in text and "StartupWMClass=familiar" in text


def _source_dir():
    """Kořen repozitáře, když familiar běží přímo z něj (ne z nainstalovaného balíčku)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return root if os.path.exists(os.path.join(root, "pyproject.toml")) else None


def read_record():
    try:
        return json.loads(_read(paths.install_record()) or "{}")
    except ValueError:
        return {}


# --- příkazy ---

def install(dry=False, autostart=False, source=None, via=None, povoleni=None, agents=None, gnome_rozsireni=False):
    """povoleni: True přidá hook povolení z bubliny, False ho odebere, None nechá, jak je.
    gnome_rozsireni: nainstalovat rozšíření GNOME Shellu (perch a aktivní okno na GNOME Waylandu)."""
    run, auto = Run(dry), agents is None or agents.strip() == "auto"
    agents = _agents_or_exit(agents, "auto")
    try:
        settings = _load_settings()
    except ValueError as e:
        sys.exit(f"CHYBA: {paths.claude_settings()} nejde přečíst ({e}), nic neměním")

    _links(run)       # nejdřív emitter, pak hooky, které ho volají
    try:
        added, skipped, empty = add_hooks(settings)
    except ValueError as e:
        sys.exit(f"CHYBA: {paths.claude_settings()}: {e}, nic neměním")
    what = [f"hooky Claude Code ({len(added)} událostí)"] if added else []
    if add_statusline(settings):
        what.append("status line pro měřič kontextu")
    try:
        if povoleni and add_povoleni(settings):
            what.append("povolení z bubliny zapnuto")
    except ValueError as e:
        sys.exit(f"CHYBA: {paths.claude_settings()}: {e}, nic neměním")
    if povoleni is False and remove_povoleni(settings, read_record().get("keep_empty", ())):
        what.append("povolení z bubliny vypnuto")
    if what:
        run.write(paths.claude_settings(), _dump(settings), ", ".join(what))
    if skipped:
        print(f"POZOR: hooky {', '.join(skipped)} nemají tvar seznamu, nechávám je, doplň familiar ručně")
    if statusline_status(settings) == "cizi":
        print(f"POZOR: statusLine v settings.json je cizí, nechávám ji; měřič kontextu pak čte jen "
              f"transcript (ten Claude Code ukládat nemusí). Zavolej z ní `{CMD_STATUSLINE}` "
              f"se stejným vstupem.")
    record = read_record()
    off = set(record.get("agents_off", ()))     # odebraní přes `uninstall --agents`
    for agent in agents:
        if not (auto and agent in off):
            _install_agent(run, agent, record)
    if not auto and off & set(agents):
        record["agents_off"] = sorted(off - set(agents))
    _old_wrapper(run)

    if "KDE" in _desktop():     # jinde „vždy navrchu“ zařídí Qt (X11) nebo rozšíření (GNOME)
        rules = _read(paths.kwinrules())
        if run.write(paths.kwinrules(), add_rule(rules), "pravidlo KWinu „vždy navrchu“"):
            _kwin_reconfigure(run)
    if gnome_rozsireni:
        _gnome_rozsireni(run)
    elif "GNOME" in _desktop():
        from familiar import gnome
        if not gnome.nainstalovano():
            print("GNOME: postavičky na okně terminálu a přepínání do terminálu potřebují rozšíření "
                  "GNOME Shellu: familiar install --gnome-rozsireni (bez něj běží dock)")
    run.write(paths.desktop_file(), desktop_text(), "spouštěč v nabídce")
    from familiar import config
    config.migrate_file(run)        # starší config.toml převede (původní do zálohy)
    if autostart:
        run.write(paths.autostart_file(), desktop_text(), "autostart")

    record.update(version=__version__, autostart=autostart or bool(record.get("autostart")))
    if povoleni is not None:
        record["povoleni"] = bool(povoleni)
    if empty or record.get("keep_empty"):
        record["keep_empty"] = sorted(set(record.get("keep_empty", [])) | set(empty))
    source = source or _source_dir()
    if source:
        record["source"] = os.path.abspath(source)
    if via:
        record["via"] = via
    run.write(paths.install_record(), json.dumps(record, indent=2, ensure_ascii=False) + "\n",
              "zdroj instalace", backup=False)

    _summary(run)


def _agents_or_exit(value, default):
    try:
        return parse_agents(value, default)
    except ValueError as e:
        sys.exit(f"CHYBA: --agents: {e}")


def uninstall(dry=False, agents=None):
    """Odinstalace; s agents jen hooky těchto agentů (zbytek instalace zůstane)."""
    run = Run(dry)
    if agents is not None:
        record, agents = read_record(), _agents_or_exit(agents, "all")
        for agent in agents:
            _uninstall_agent(run, agent, record)
        if record and not set(agents) <= set(record.get("agents_off", ())):
            record["agents_off"] = sorted(set(record.get("agents_off", ())) | set(agents))
            run.write(paths.install_record(), json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                      "záznam: tyto agenty už automaticky neinstalovat", backup=False)
        _summary(run)
        return
    try:
        settings = _load_settings()
    except ValueError as e:
        sys.exit(f"CHYBA: {paths.claude_settings()} nejde přečíst ({e}), nic neměním")
    record = read_record()
    for agent in AGENTS:        # hooky jako první: nikdy nevolají chybějící familiar-emit
        _uninstall_agent(run, agent, record)
    hooks_off = remove_hooks(settings, record.get("keep_empty", ()))
    if remove_statusline(settings) or hooks_off:
        run.write(paths.claude_settings(), _dump(settings), "odebírám hooky familiara")

    rules = _read(paths.kwinrules())
    if rules is not None and run.write(paths.kwinrules(), remove_rule(rules), "odebírám pravidlo KWinu"):
        _kwin_reconfigure(run)
    _gnome_odeber(run)
    for path, what in ((paths.desktop_file(), "odebírám spouštěč"), (paths.autostart_file(), "odebírám autostart")):
        if _is_our_desktop(path):
            run.remove(path, what)
    via = read_record().get("via") or "uv"
    run.remove(paths.install_record(), "odebírám záznam o instalaci", backup=False)

    _summary(run)
    print("balíček odstraníš: " + {"pipx": "pipx uninstall familiar",
                                    "venv": f"rm ~/.local/bin/familiar ~/.local/bin/familiar-emit; rm -r {paths.data_dir()}/venv-*"
                                    }.get(via, "uv tool uninstall familiar"))


def _summary(run):
    if not run.changes:
        print("vše už je v pořádku, nic neměním")
    elif run.backup_dir:
        print(f"zálohy: {run.backup_dir}")
