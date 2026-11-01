# Překlad hooku Gemini CLI → události familiara (docs/agenti.md).
#
# Vstupem jsou pole z emitteru (familiar-emit gemini): hook_event_name, session_id, cwd,
# source, reason, prompt (jen BeforeAgent), tool_name, command, trigger, notification_type
# a z tool_response jen odvozené error, error_type, exit_code, cancelled.
# Gemini nedává id volání nástroje: otevřené nástroje se párují bez id (None).
from familiar.adapters.claude_code import KILLED

SOURCE = "gemini"


def translate(raw, ts, pid=None):
    hook = raw.get("hook_event_name")
    data = {}
    if raw.get("tool_name"):
        data["tool"] = raw["tool_name"]
    if isinstance(raw.get("command"), str):
        data["cmd"] = raw["command"][:200]

    def ev(kind, **extra):
        return {"v": 1, "source": SOURCE, "session": raw.get("session_id"), "pid": pid,
                "ts": ts, "kind": kind, "data": {**data, **extra}}

    if hook == "SessionStart":
        return [ev("session.start", how=raw.get("source"), cwd=raw.get("cwd"))]
    if hook == "SessionEnd":
        return [ev("session.end", reason=raw.get("reason"))]
    if hook == "BeforeAgent":
        return [ev("user.prompt", text=raw.get("prompt") or "")]
    if hook == "BeforeTool":
        # Gemini spouští nástroje až po schválení všech v dávce: start = už se nečeká
        return [ev("tool.start", schvaleno=True)]
    if hook == "AfterTool":
        if raw.get("cancelled"):
            return [ev("tool.end", killed=True), ev("agent.interrupted")]
        code = raw.get("exit_code")
        code = code if isinstance(code, int) and not isinstance(code, bool) else None
        if code in KILLED:
            return [ev("tool.end", killed=True)]
        if raw.get("error") or code:
            err = raw.get("error")
            err = err if isinstance(err, str) else f"Exit code {code}"
            return [ev("tool.error", code=code, error=err[:200])]
        return [ev("tool.end")]
    if hook == "Notification":
        if raw.get("notification_type") == "ToolPermission":
            return [ev("agent.waiting", why="permission")]
        return []
    if hook == "AfterAgent":
        return [ev("agent.done", background=0)]
    if hook == "PreCompress":
        # "auto" chodí před každým kolem (0.62 volá hook ještě před kontrolou prahu): jen /compress
        if raw.get("trigger") == "manual":
            return [ev("context.compact", trigger="manual")]
        return []
    return []   # BeforeModel, AfterModel, BeforeToolSelection a neznámé hooky
