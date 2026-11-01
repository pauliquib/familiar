from familiar.hub import LEAVE_S, REAP_S, SETTLE_S, Hub


def msg(ts, hook, pid=7, **raw):
    return {"v": 1, "source": "claude-code", "pid": pid, "ts": ts,
            "raw": {"hook_event_name": hook, "session_id": "s", **raw}}


def test_one_familiar_per_process_across_clear():
    hub = Hub(reap=False)
    hub.receive(msg(0, "SessionStart", cwd="/home/x/projekt"))
    hub.receive(msg(5, "SessionEnd", reason="clear"))
    hub.receive(msg(5.1, "SessionStart", session_id="s2", source="clear"))
    fams = hub.tick(10)
    assert len(fams) == 1 and fams[0].name == "projekt" and fams[0].fsm.state == "idle"


def test_shown_state_settles_but_oneshots_are_immediate():
    hub = Hub(reap=False)
    hub.receive(msg(0, "UserPromptSubmit", prompt="ahoj"))
    (fam,) = hub.tick(0)
    assert fam.update(0)[0] == "listen"
    hub.receive(msg(1, "PreToolUse", tool_name="Read", tool_use_id="a"))
    assert fam.update(1)[0] == "listen"
    assert fam.update(1 + SETTLE_S)[0] == "work_search"


def test_brief_working_before_permission_is_not_shown():
    hub = Hub(reap=False)
    hub.receive(msg(0, "UserPromptSubmit"))
    (fam,) = hub.tick(0)
    fam.update(5)
    hub.receive(msg(10, "PreToolUse", tool_name="Bash", tool_use_id="a"))
    fam.update(10.05)
    hub.receive(msg(10.1, "PermissionRequest", tool_name="Bash"))
    seen = {fam.update(10.1 + k * 0.05)[0] for k in range(20)}
    assert "work_bash" not in seen and "wave" in seen


def test_subagent_tool_does_not_change_animation():
    hub = Hub(reap=False)
    hub.receive(msg(0, "PreToolUse", tool_name="Edit", tool_use_id="a"))
    hub.receive(msg(0.1, "PreToolUse", tool_name="Read", tool_use_id="b", agent_id="x"))
    (fam,) = hub.tick(1)
    assert fam.tool == "Edit"


def test_dead_process_leaves():
    hub = Hub()
    hub.receive(msg(0, "SessionStart", pid=999999999))
    assert hub.tick(REAP_S)[0].fsm.state == "gone"
    assert hub.tick(REAP_S + LEAVE_S) == []


def test_message_without_identity_is_ignored():
    hub = Hub(reap=False)
    hub.receive({"ts": 0, "raw": {"hook_event_name": "Stop"}})
    assert hub.tick(0) == []


def test_find_terminal_walks_parents(monkeypatch):
    from familiar import hub
    tree = {50: ("claude", 40), 40: ("fish", 30), 30: ("kitty", 1), 60: ("claude", 1)}
    monkeypatch.setattr(hub, "_stat", lambda pid: tree.get(pid))
    assert hub.find_terminal(50) == 30
    assert hub.find_terminal(60) is None


def test_adopt_live_claude_with_terminal(monkeypatch):
    from familiar import hub
    tree = {50: ("claude", 40), 40: ("fish", 30), 30: ("kitty", 1), 60: ("claude", 1)}
    monkeypatch.setattr(hub, "_stat", lambda pid: tree.get(pid))
    monkeypatch.setattr(hub, "pid_alive", lambda pid, source=None: pid in (50, 60))
    monkeypatch.setattr(hub.os, "listdir", lambda path: ["50", "60", "70", "abc"])
    h = Hub(reap=False)
    assert h.adopt_live(0) == 1                 # 60 nemá terminál, 70 není claude
    fam = h.fams[50]
    assert fam.term == 30 and fam.source == "claude-code"
    assert h.adopt_live(1) == 0                 # podruhé nic nepřidá


def test_one_familiar_per_terminal(monkeypatch):
    from familiar import hub
    ttys = {7: 34817, 8: 34817, 9: 34818}              # 7 a 8 sdílí terminál, 9 je jiný
    monkeypatch.setattr(hub, "tty_of", lambda pid: ttys.get(pid, 0))
    h = Hub(reap=False)
    h.receive(msg(0, "SessionStart", pid=7, cwd="/a/projekt"))
    h.receive(msg(1, "SessionStart", pid=8, cwd="/a/projekt"))
    h.receive(msg(2, "SessionStart", pid=9, cwd="/a/jiny"))
    fams = h.tick(3)
    assert len(fams) == 2
    assert sorted(f.pid for f in fams) == [8, 9]        # vede ten, co naposledy poslal událost
