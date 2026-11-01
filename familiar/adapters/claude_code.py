# Překlad hooku Claude Code → události familiara (kapitola 6.1 konceptu).
#
# Vstupem je JSON hooku (celý z nahrávky, nebo jen pole KEEP z emitteru),
# výstupem seznam událostí ve společném schématu. Pravidla vycházejí z nahrávek
# z 17.–22. 10. 2026.
import re

SOURCE = "claude-code"
KILLED = {143, 144}   # SIGTERM / zastavená úloha na pozadí, ne chyba
EXIT_RE = re.compile(r"Exit code (\d+)")


def translate(raw, ts, pid=None):
    hook = raw.get("hook_event_name")
    data = {}
    if raw.get("agent_id"):
        data["agent"] = raw["agent_id"]
    if raw.get("tool_name"):
        data["tool"] = raw["tool_name"]
    if raw.get("tool_use_id"):
        data["id"] = raw["tool_use_id"]
    ti = raw.get("tool_input")
    cmd = raw.get("command") or (ti.get("command") if isinstance(ti, dict) else None)
    if isinstance(cmd, str):   # emitter posílá jen začátek, nahrávky celý tool_input
        data["cmd"] = cmd[:200]
    ti = ti if isinstance(ti, dict) else {}     # bublina s činností: soubor bez cesty, vzor hledání
    f = raw.get("file") or ti.get("file_path") or ti.get("notebook_path")
    if isinstance(f, str) and f:
        data["file"] = f.rstrip("/").rpartition("/")[2][:80]
    pat = raw.get("pattern") or ti.get("pattern")
    if isinstance(pat, str) and pat:
        data["pattern"] = " ".join(pat.split())[:40]

    def ev(kind, **extra):
        return {"v": 1, "source": SOURCE, "session": raw.get("session_id"), "pid": pid,
                "ts": ts, "kind": kind, "data": {**data, **extra}}

    if hook == "SessionStart":
        return [ev("session.start", how=raw.get("source"), cwd=raw.get("cwd"))]
    if hook == "SessionEnd":
        return [ev("session.end", reason=raw.get("reason"))]
    if hook == "UserPromptSubmit":
        return [ev("user.prompt", text=raw.get("prompt") or "")]
    if hook == "PreToolUse":
        return [ev("tool.start")]
    if hook == "PostToolUse":
        return [ev("tool.end", ms=raw.get("duration_ms"))]
    if hook == "PostToolUseFailure":
        err = raw.get("error")
        err = err if isinstance(err, str) else str(err)
        m = EXIT_RE.match(err)
        code = int(m.group(1)) if m else None
        if code in KILLED:
            return [ev("tool.end", ms=raw.get("duration_ms"), killed=True)]
        out = [ev("tool.error", ms=raw.get("duration_ms"), code=code, error=err[:200])]
        if raw.get("is_interrupt"):
            out.append(ev("agent.interrupted"))
        return out
    if hook == "PermissionRequest":
        why = "question" if raw.get("tool_name") == "AskUserQuestion" else "permission"
        return [ev("agent.waiting", why=why)]
    if hook == "PermissionDenied":
        return [ev("tool.denied")]
    if hook == "Stop":
        return [ev("agent.done", background=len(raw.get("background_tasks") or []))]
    if hook == "StopFailure":
        return [ev("agent.failed", error=raw.get("error"))]
    if hook == "SubagentStart":
        return [ev("subagent.start", type=raw.get("agent_type"))]
    if hook == "SubagentStop":
        # prázdný agent_type = vnitřní pomocné volání bez SubagentStart
        if not raw.get("agent_type"):
            return []
        return [ev("subagent.done", type=raw["agent_type"])]
    if hook == "PreCompact":
        return [ev("context.compact", trigger=raw.get("trigger"))]
    return []   # Notification (opožděné), PostCompact a neznámé hooky
