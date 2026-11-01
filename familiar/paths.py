# Cesty familiara odvozené z HOME a XDG_* (při každém volání, kvůli testům s dočasným HOME)
# a stav běžícího daemonu podle zámku. Bez Qt.
import fcntl, os, stat


def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def _xdg(var, default):
    return os.environ.get(var) or os.path.join(home(), default)


def config_home():
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_home():
    return _xdg("XDG_DATA_HOME", ".local/share")


FALLBACK = "/tmp/familiar-{uid}"   # bez XDG_RUNTIME_DIR (stejně v emit.py)


def runtime_dir():
    """$XDG_RUNTIME_DIR; bez něj (i prázdného) soukromý /tmp/familiar-<uid>, jako emit.sock_path()."""
    d = os.environ.get("XDG_RUNTIME_DIR")
    return d if d and os.path.isabs(d) else FALLBACK.format(uid=os.getuid())


def _private(d):
    st = os.lstat(d)
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077


def secure_runtime_dir():
    """Adresář pro socket a zámek daemonu; náhradní /tmp/familiar-<uid> založí s právy 0700.
    OSError, když patří někomu jinému nebo je přístupný ostatním."""
    d = runtime_dir()
    if d == FALLBACK.format(uid=os.getuid()):
        try:
            os.mkdir(d, 0o700)
        except FileExistsError:
            pass
        if not _private(d):
            raise PermissionError(f"{d} není soukromý adresář tohoto uživatele")
    return d


def sock():
    return os.path.join(runtime_dir(), "familiar.sock")


def lock():
    return os.path.join(runtime_dir(), "familiar.lock")


def mode_file():
    """Skutečný režim běžícího daemonu (perch/dock); zapisuje ho daemon, čte doctor."""
    return os.path.join(runtime_dir(), "familiar.rezim")


def daemon_mode():
    try:
        with open(mode_file()) as f:
            return f.read().strip() or None
    except OSError:
        return None


def bin_dir():
    return os.environ.get("XDG_BIN_HOME") or os.path.join(home(), ".local", "bin")


def data_dir():
    """~/.local/share/familiar: zdroj instalace, zálohy."""
    return os.path.join(data_home(), "familiar")


def config_file():
    return os.path.join(config_home(), "familiar", "config.toml")


def claude_settings():
    return os.path.join(home(), ".claude", "settings.json")


def gemini_dir():
    """~/.gemini; Gemini CLI bere místo HOME proměnnou GEMINI_CLI_HOME."""
    return os.path.join(os.environ.get("GEMINI_CLI_HOME") or home(), ".gemini")


def codex_dir():
    """~/.codex, nebo $CODEX_HOME."""
    return os.environ.get("CODEX_HOME") or os.path.join(home(), ".codex")


def kwinrules():
    return os.path.join(config_home(), "kwinrulesrc")


def desktop_file():
    return os.path.join(data_home(), "applications", "familiar.desktop")


def autostart_file():
    return os.path.join(config_home(), "autostart", "familiar.desktop")


def install_record():
    return os.path.join(data_dir(), "install.json")


def daemon_pid():
    """PID běžícího daemonu, 0 = běží bez zapsaného pid (starší verze), None = neběží.

    Daemon drží na zámku flock a má v něm své pid."""
    try:
        if runtime_dir() != os.environ.get("XDG_RUNTIME_DIR") and not _private(runtime_dir()):
            return None     # cizí náhradní adresář: pid v něm nevěřit
        f = open(lock())
    except OSError:
        return None
    with f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:     # zámek drží daemon
            try:
                return int(f.read().strip() or 0)
            except ValueError:
                return 0
        return None
