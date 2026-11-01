# Překlad hooku OpenAI Codex CLI → události familiara (docs/agenti.md).
#
# Hooky Codexu (hooks.json) mají skoro stejný tvar jako Claude Code. Rozdíly: chyba nástroje
# nemá vlastní hook (neúspěšný nástroj PostToolUse nespustí, nenulový exit Bash ano, ale
# výstup kód neobsahuje), přerušení má hook Interrupt. Starý `notify` (jen konec kola)
# emitter převede na hook_event_name "agent-turn-complete".
SOURCE = "codex"


def translate(raw, ts, pid=None):
    hook = raw.get("hook_event_name")
    data = {}
    if raw.get("agent_id"):
        data["agent"] = raw["agent_id"]
    if raw.get("tool_name"):
        data["tool"] = raw["tool_name"]
    if raw.get("tool_use_id"):
        data["id"] = raw["tool_use_id"]
    if isinstance(raw.get("command"), str):
        data["cmd"] = raw["command"][:200]

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
        return [ev("tool.end")]
    if hook == "PermissionRequest":
        return [ev("agent.waiting", why="permission")]
    if hook in ("Stop", "agent-turn-complete"):
        return [ev("agent.done", background=0)]
    if hook == "Interrupt":
        return [ev("agent.interrupted")]
    if hook == "SubagentStart":
        return [ev("subagent.start", type=raw.get("agent_type"))]
    if hook == "SubagentStop":
        return [ev("subagent.done", type=raw.get("agent_type"))]
    if hook == "PreCompact":
        return [ev("context.compact", trigger=raw.get("trigger"))]
    return []   # PostCompact a neznámé hooky
