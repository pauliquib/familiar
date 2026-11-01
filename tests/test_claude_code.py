from familiar.adapters.claude_code import translate


def kinds(raw):
    return [(e["kind"], e["data"]) for e in translate(raw, 1.0, pid=42)]


def test_schema():
    (e,) = translate({"hook_event_name": "PreToolUse", "session_id": "s1",
                      "tool_name": "Read", "tool_use_id": "t1"}, 5.0, pid=42)
    assert e == {"v": 1, "source": "claude-code", "session": "s1", "pid": 42, "ts": 5.0,
                 "kind": "tool.start", "data": {"tool": "Read", "id": "t1"}}


def test_bash_failure_is_error_with_exit_code():
    out = kinds({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_use_id": "t1",
                 "error": "Exit code 2\nls: nelze přistoupit", "is_interrupt": False, "duration_ms": 9})
    assert out[0][0] == "tool.error" and out[0][1]["code"] == 2 and len(out) == 1


def test_killed_process_is_not_error():
    out = kinds({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_use_id": "t1",
                 "error": "Exit code 143\n", "duration_ms": 9})
    assert out == [("tool.end", {"tool": "Bash", "id": "t1", "ms": 9, "killed": True})]


def test_non_bash_failure_has_no_code():
    out = kinds({"hook_event_name": "PostToolUseFailure", "tool_name": "Read", "tool_use_id": "t1",
                 "error": "File does not exist."})
    assert out[0][0] == "tool.error" and out[0][1]["code"] is None


def test_interrupt_flag():
    out = kinds({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": "x",
                 "is_interrupt": True})
    assert [k for k, _ in out] == ["tool.error", "agent.interrupted"]


def test_waiting_kinds():
    assert kinds({"hook_event_name": "PermissionRequest", "tool_name": "AskUserQuestion"})[0][1]["why"] == "question"
    assert kinds({"hook_event_name": "PermissionRequest", "tool_name": "Bash"})[0][1]["why"] == "permission"


def test_ignored_hooks():
    assert kinds({"hook_event_name": "Notification", "notification_type": "idle_prompt"}) == []
    assert kinds({"hook_event_name": "PostCompact"}) == []
    assert kinds({"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": ""}) == []


def test_subagent_events_carry_agent():
    out = kinds({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "t1",
                 "agent_id": "a1", "agent_type": "general-purpose"})
    assert out[0][1]["agent"] == "a1"
    assert kinds({"hook_event_name": "SubagentStop", "agent_id": "a1",
                  "agent_type": "Explore"})[0][0] == "subagent.done"


def test_stop_reports_background_tasks():
    out = kinds({"hook_event_name": "Stop", "background_tasks": [{"id": "b1"}, {"id": "b2"}]})
    assert out == [("agent.done", {"background": 2})]
