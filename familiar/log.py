# Log daemonu: $XDG_STATE_HOME/familiar/familiar.log s rotací.
#
# Do logu nesmí obsah promptů (omezeni.md): data hooku se logují jen přes
# safe() (filtr to udělá i se slovníky v argumentech), výjimky bez svého textu,
# každá zpráva se zkrátí na jeden řádek a MAX_MSG znaků.
import logging, os, traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

NAME = "familiar"
MAX_BYTES = 512 * 1024
BACKUPS = 3
MAX_MSG = 300       # znaků na zprávu
MAX_EXC = 2000      # znaků na traceback
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# pole hooku, která se smí logovat celá (krátké identifikátory a čísla)
SAFE_KEYS = ("hook_event_name", "tool_name", "tool_use_id", "agent_id", "agent_type", "source",
             "reason", "trigger", "notification_type", "duration_ms", "is_interrupt")
# u těchto se loguje jen délka
LEN_KEYS = ("prompt", "command", "error")


def log_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "familiar" / "familiar.log"


def _short(s, n):
    s = str(s).replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def _arg(a):
    """Argument zprávy: slovník (data hooku) jen přes safe(), kolekce jen délkou."""
    if isinstance(a, dict):
        return safe(a)
    if isinstance(a, (list, tuple, set)):
        return f"<{type(a).__name__} {len(a)}>"
    return a


def _exc_text(exc_info):
    """Traceback bez textů výjimek: ty mohou nést data hooku (např. ValueError s promptem)."""
    te, parts = traceback.TracebackException(*exc_info), []
    while te is not None:
        name = getattr(te, "exc_type_str", None) or te.exc_type.__name__
        parts.append("Traceback (most recent call last):\n" + "".join(te.stack.format())
                     + f"{name} (text výjimky se neloguje)")
        te = te.__cause__ or te.__context__
    return "\n".join(reversed(parts))


class SafeFilter(logging.Filter):
    """Data hooku v argumentech projdou přes safe(), výjimky bez textu, vše zkrácené."""

    def filter(self, record):
        if isinstance(record.msg, dict):
            record.msg = safe(record.msg)
        if isinstance(record.args, dict):       # logger.info("%(x)s", {...})
            record.args = safe(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_arg(a) for a in record.args)
        try:
            msg = record.getMessage()
        except Exception:   # rozbité argumenty – zalogovat aspoň šablonu
            msg = str(record.msg)
        record.msg, record.args = _short(msg, MAX_MSG), None
        if record.exc_info:
            lines = _exc_text(record.exc_info).splitlines()
            record.exc_text = "\n".join(_short(l, 200) for l in lines)[-MAX_EXC:]
            record.exc_info = None
        if record.stack_info:
            record.stack_info = record.stack_info[-MAX_EXC:]
        return True


def setup(level=logging.INFO):
    """Nastaví logger "familiar" (i pro potomky familiar.*) a vrátí ho; opakované volání jen změní úroveň."""
    log = logging.getLogger(NAME)
    log.setLevel(level)
    log.propagate = False
    path = log_path()
    for h in log.handlers:
        if isinstance(h, RotatingFileHandler) and h.baseFilename == str(path):
            return log
    path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    h.setFormatter(logging.Formatter(FORMAT))
    h.addFilter(SafeFilter())   # na handleru, aby platil i pro záznamy potomků
    log.addHandler(h)
    return log


def safe(raw):
    """Data hooku (raw, nebo celá zpráva emitteru s "raw") → jen bezpečná pole."""
    out = {}
    if not isinstance(raw, dict):
        return out
    inner = raw.get("raw")
    if isinstance(inner, dict):   # obálka emitteru: pid, ts, source
        for k in ("source", "pid", "ts"):
            if isinstance(raw.get(k), (str, int, float)):
                out[k] = _short(raw[k], 40) if isinstance(raw[k], str) else raw[k]
        raw = inner
    for k in SAFE_KEYS:
        v = raw.get(k)
        if isinstance(v, (bool, int, float)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = _short(v, 80)
    sid = raw.get("session_id")
    if isinstance(sid, str):
        out["session_id"] = sid[:8]
    for k in LEN_KEYS:
        if isinstance(raw.get(k), str):
            out[k + "_len"] = len(raw[k])
    if isinstance(raw.get("background_tasks"), list):
        out["background_tasks"] = len(raw["background_tasks"])
    tp = raw.get("transcript_path")
    if isinstance(tp, str):
        out["transcript"] = _short(os.path.basename(tp), 80)
    return out
