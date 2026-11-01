# Registr adaptérů: zdroj v datagramu emitteru (familiar-emit <zdroj>) → překlad na události.
# Neznámý zdroj (starší emitter, "unknown") se překládá jako Claude Code.
from familiar.adapters import claude_code, codex, gemini

ADAPTERS = {m.SOURCE: m for m in (claude_code, gemini, codex)}


def translate(source, raw, ts, pid=None):
    return ADAPTERS.get(source, claude_code).translate(raw, ts, pid)
