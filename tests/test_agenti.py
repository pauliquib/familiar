# Další agenti: adaptéry Gemini CLI a Codexu, emitter, instalace hooků, doctor.
# Vzorové vstupy podle dokumentace (docs/agenti.md); vše s dočasným HOME a socketem.
import json, os, socket, subprocess, sys, tempfile

import pytest

from familiar import adapters, doctor, install, paths
from familiar.adapters import codex, gemini
from familiar.fsm import ActivityFSM
from familiar.hub import Hub

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMIT = os.path.join(ROOT, "familiar", "emit.py")
BASE = {"session_id": "g1", "transcript_path": "/home/x/.gemini/tmp/chats/session.json",
        "cwd": "/home/x/projekt", "timestamp": "2026-10-23T10:00:00.000Z"}


def kinds(mod, raw):
    return [(e["kind"], e["data"]) for e in mod.translate(raw, 1.0, pid=42)]


# --- adaptér Gemini ---

def test_gemini_lifecycle():
    assert kinds(gemini, {"hook_event_name": "SessionStart", "source": "startup", **BASE}) == [
        ("session.start", {"how": "startup", "cwd": "/home/x/projekt"})]
    assert kinds(gemini, {"hook_event_name": "SessionEnd", "reason": "exit"}) == [("session.end", {"reason": "exit"})]
    assert kinds(gemini, {"hook_event_name": "BeforeAgent", "prompt": "oprav testy"}) == [
        ("user.prompt", {"text": "oprav testy"})]
    assert kinds(gemini, {"hook_event_name": "AfterAgent"}) == [("agent.done", {"background": 0})]
    assert kinds(gemini, {"hook_event_name": "PreCompress", "trigger": "manual"}) == [
        ("context.compact", {"trigger": "manual"})]
    assert kinds(gemini, {"hook_event_name": "PreCompress", "trigger": "auto"}) == []     # před každým kolem
    assert kinds(gemini, {"hook_event_name": "Notification", "notification_type": "ToolPermission"}) == [
        ("agent.waiting", {"why": "permission"})]
    for hook in ("BeforeModel", "AfterModel", "BeforeToolSelection", "Neznamy"):
        assert kinds(gemini, {"hook_event_name": hook}) == []


def test_gemini_schema():
    (e,) = gemini.translate({"hook_event_name": "BeforeTool", "session_id": "g1", "tool_name": "run_shell_command",
                             "command": "pytest -q"}, 5.0, pid=42)
    assert e == {"v": 1, "source": "gemini", "session": "g1", "pid": 42, "ts": 5.0, "kind": "tool.start",
                 "data": {"tool": "run_shell_command", "cmd": "pytest -q", "schvaleno": True}}


def test_gemini_tool_results():
    t = {"hook_event_name": "AfterTool", "tool_name": "run_shell_command"}
    assert kinds(gemini, t) == [("tool.end", {"tool": "run_shell_command"})]
    assert kinds(gemini, {**t, "exit_code": 2})[0][0] == "tool.error"
    assert kinds(gemini, {**t, "exit_code": 2})[0][1]["code"] == 2
    assert kinds(gemini, {**t, "exit_code": 143}) == [("tool.end", {"tool": "run_shell_command", "killed": True})]
    assert [k for k, _ in kinds(gemini, {**t, "cancelled": True})] == ["tool.end", "agent.interrupted"]
    out = kinds(gemini, {"hook_event_name": "AfterTool", "tool_name": "read_file", "error": "File not found"})
    assert out == [("tool.error", {"tool": "read_file", "code": None, "error": "File not found"})]


def test_gemini_waiting_ends_when_approved_tool_starts():
    fsm = ActivityFSM(0)
    for i, raw in enumerate(({"hook_event_name": "BeforeAgent", "prompt": "x"},
                             {"hook_event_name": "Notification", "notification_type": "ToolPermission"})):
        for ev in gemini.translate(raw, float(i), 1):
            fsm.feed(ev)
    assert fsm.state == "waiting"
    for ev in gemini.translate({"hook_event_name": "BeforeTool", "tool_name": "write_file"}, 5.0, 1):
        fsm.feed(ev)
    assert fsm.state == "working" and fsm.waiting is None
    # Claude Code: souběžný nástroj při čekání na povolení čekání neukončí
    fsm2 = ActivityFSM(0)
    fsm2.feed({"ts": 0, "kind": "agent.waiting", "data": {"why": "permission"}})
    fsm2.feed({"ts": 1, "kind": "tool.start", "data": {"tool": "Read", "id": "a"}})
    assert fsm2.state == "waiting"


# --- adaptér Codexu ---

def test_codex_events():
    c = {"session_id": "c1", "turn_id": "t", "cwd": "/p", "model": "gpt-5", "permission_mode": "default"}
    assert kinds(codex, {**c, "hook_event_name": "SessionStart", "source": "startup"})[0][0] == "session.start"
    assert kinds(codex, {**c, "hook_event_name": "UserPromptSubmit", "prompt": "ahoj"}) == [
        ("user.prompt", {"text": "ahoj"})]
    assert kinds(codex, {**c, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "u1",
                         "command": "cargo test"}) == [("tool.start", {"tool": "Bash", "id": "u1", "cmd": "cargo test"})]
    assert kinds(codex, {**c, "hook_event_name": "PostToolUse", "tool_name": "apply_patch", "tool_use_id": "u2"}) == [
        ("tool.end", {"tool": "apply_patch", "id": "u2"})]
    assert kinds(codex, {**c, "hook_event_name": "PermissionRequest", "tool_name": "Bash"})[0] == (
        "agent.waiting", {"tool": "Bash", "why": "permission"})
    assert kinds(codex, {**c, "hook_event_name": "Stop"}) == [("agent.done", {"background": 0})]
    assert kinds(codex, {**c, "hook_event_name": "Interrupt"}) == [("agent.interrupted", {})]
    assert kinds(codex, {**c, "hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "explorer"}) == [
        ("subagent.start", {"agent": "a1", "type": "explorer"})]
    assert kinds(codex, {**c, "hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "explorer"}) == [
        ("subagent.done", {"agent": "a1", "type": "explorer"})]
    assert kinds(codex, {**c, "hook_event_name": "PreCompact", "trigger": "manual"})[0][0] == "context.compact"
    assert kinds(codex, {"hook_event_name": "agent-turn-complete", "session_id": "th"}) == [
        ("agent.done", {"background": 0})]
    assert kinds(codex, {**c, "hook_event_name": "PostCompact"}) == []


def test_registry_dispatch_and_fallback():
    raw = {"hook_event_name": "Stop", "session_id": "s"}
    assert adapters.translate("codex", raw, 1.0)[0]["source"] == "codex"
    assert adapters.translate("gemini", {"hook_event_name": "AfterAgent"}, 1.0)[0]["source"] == "gemini"
    assert adapters.translate("unknown", raw, 1.0)[0]["source"] == "claude-code"
    assert adapters.translate(None, raw, 1.0)[0]["source"] == "claude-code"


def test_hub_uses_adapter_by_source():
    hub = Hub(reap=False)
    hub.receive({"v": 1, "source": "gemini", "pid": 9, "ts": 0,
                 "raw": {"hook_event_name": "SessionStart", "session_id": "g", "cwd": "/home/x/gproj", "source": "startup"}})
    hub.receive({"v": 1, "source": "gemini", "pid": 9, "ts": 1, "raw": {"hook_event_name": "BeforeAgent", "session_id": "g"}})
    (fam,) = hub.tick(1)
    assert fam.name == "gproj" and fam.fsm.state == "listening"


# --- emitter ---

@pytest.fixture
def sock(monkeypatch):
    d = tempfile.mkdtemp(prefix="fam", dir="/tmp")      # krátká cesta kvůli Unix socketu
    monkeypatch.setenv("XDG_RUNTIME_DIR", d)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(os.path.join(d, "familiar.sock"))
    s.settimeout(2)
    yield s
    s.close()
    for name in os.listdir(d):
        os.unlink(os.path.join(d, name))
    os.rmdir(d)


def emit_run(args, stdin=b"", shell=False):
    cmd = [sys.executable, "-I", EMIT, *args]
    if shell:   # jako Codex: hook přes shell, který neudělá exec
        cmd = ["sh", "-c", " ".join(f"'{a}'" for a in cmd) + "; true"]
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=5)


def test_emit_gemini_after_tool_sends_only_codes(sock):
    hook = {**BASE, "hook_event_name": "AfterTool", "tool_name": "run_shell_command",
            "tool_input": {"command": "pytest -q", "description": "tajný popis"},
            "tool_response": {"llmContent": "Output: tajné\nExit Code: 1\nProcess Group PGID: 77",
                              "returnDisplay": "tajné", "error": None}}
    r = emit_run(["gemini"], json.dumps(hook).encode())
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    msg = json.loads(sock.recv(65536))
    assert msg["source"] == "gemini" and msg["pid"] == os.getpid()
    assert msg["raw"] == {"hook_event_name": "AfterTool", "session_id": "g1", "cwd": "/home/x/projekt",
                          "tool_name": "run_shell_command", "command": "pytest -q", "exit_code": 1}
    assert b"tajn" not in json.dumps(msg).encode("ascii") and "transcript_path" not in msg["raw"]


def test_emit_gemini_error_cancel_and_prompt_rules(sock):
    err = {**BASE, "hook_event_name": "AfterTool", "tool_name": "read_file", "tool_input": {},
           "tool_response": {"llmContent": "x", "returnDisplay": "x", "error": {"type": "file_not_found", "message": "nenalezeno"}}}
    emit_run(["gemini"], json.dumps(err).encode())
    assert json.loads(sock.recv(65536))["raw"]["error"] == "nenalezeno"
    cancel = {**BASE, "hook_event_name": "AfterTool", "tool_name": "run_shell_command", "tool_input": {"command": "sleep 9"},
              "tool_response": {"llmContent": "Command was cancelled by user before it could complete. Exit Code: 9"}}
    emit_run(["gemini"], json.dumps(cancel).encode())
    raw = json.loads(sock.recv(65536))["raw"]
    assert raw["cancelled"] is True and "exit_code" not in raw
    fake = {**BASE, "hook_event_name": "AfterTool", "tool_name": "run_shell_command", "tool_input": {"command": "cat log"},
            "tool_response": {"llmContent": "Output: a\nExit Code: 3\nnějaký další výstup"}}
    emit_run(["gemini"], json.dumps(fake).encode())
    assert "exit_code" not in json.loads(sock.recv(65536))["raw"]      # Exit Code uvnitř výstupu
    emit_run(["gemini"], json.dumps({**BASE, "hook_event_name": "BeforeAgent", "prompt": "ahoj"}).encode())
    assert json.loads(sock.recv(65536))["raw"]["prompt"] == "ahoj"
    after = {**BASE, "hook_event_name": "AfterAgent", "prompt": "ahoj", "prompt_response": "odpověď", "stop_hook_active": False}
    emit_run(["gemini"], json.dumps(after).encode())
    raw = json.loads(sock.recv(65536))["raw"]
    assert raw == {"hook_event_name": "AfterAgent", "session_id": "g1", "cwd": "/home/x/projekt"}


def test_emit_codex_hook_skips_shell_parent(sock):
    hook = {"session_id": "c1", "transcript_path": None, "cwd": "/p", "hook_event_name": "PreToolUse",
            "model": "m", "turn_id": "t", "tool_name": "apply_patch", "tool_use_id": "u",
            "tool_input": {"command": "*** Begin Patch tajné"}, "permission_mode": "default"}
    r = emit_run(["codex"], json.dumps(hook).encode(), shell=True)
    assert (r.returncode, r.stdout) == (0, b"")
    msg = json.loads(sock.recv(65536))
    assert msg["pid"] == os.getpid()        # rodič sh přeskočen
    assert msg["raw"] == {"hook_event_name": "PreToolUse", "session_id": "c1", "cwd": "/p",
                          "tool_name": "apply_patch", "tool_use_id": "u"}


def test_emit_codex_notify_from_argv(sock):
    note = {"type": "agent-turn-complete", "thread-id": "th1", "turn-id": "7", "cwd": "/p",
            "input-messages": ["tajný prompt"], "last-assistant-message": "tajná odpověď"}
    r = subprocess.run([sys.executable, "-I", EMIT, "codex", json.dumps(note)], stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=5)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    msg = json.loads(sock.recv(65536))
    assert msg["raw"] == {"hook_event_name": "agent-turn-complete", "session_id": "th1", "cwd": "/p"}


def test_emit_claude_pid_unchanged_under_shell(sock):
    """Claude Code zdroj se chová jako dřív: rodič (i shell) je pid."""
    emit_run(["claude-code"], b'{"hook_event_name": "Stop", "session_id": "s"}', shell=True)
    assert json.loads(sock.recv(65536))["pid"] != os.getpid()


def test_emit_bad_input_silent(sock):
    for args, stdin in ((["gemini"], b"{ rozbite"), (["codex", "{rozbite"], b""), (["gemini"], b"")):
        r = emit_run(args, stdin)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


# --- instalace ---

@pytest.fixture
def home(tmp_path, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_BIN_HOME", "GEMINI_CLI_HOME", "CODEX_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(install, "dbus", lambda *a: "()")
    monkeypatch.setattr(install, "installed", lambda name: None)
    return tmp_path


GEMINI_FOREIGN = {"security": {"auth": {"selectedType": "oauth-personal"}},
                  "hooks": {"BeforeTool": [{"matcher": "write_file", "hooks": [{"type": "command", "command": "kontrola.sh"}]}]}}


def gemini_settings(home, data=GEMINI_FOREIGN):
    p = home / ".gemini" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")
    return p


def test_auto_installs_only_used_agents(home):
    p = gemini_settings(home)
    install.install()
    s = json.loads(p.read_text())
    assert s["security"] == GEMINI_FOREIGN["security"]
    assert not install.missing_hooks(s, install.AGENTS["gemini"]["events"])
    bt = s["hooks"]["BeforeTool"]
    assert bt[0] == GEMINI_FOREIGN["hooks"]["BeforeTool"][0]
    assert bt[1] == {"matcher": "*", "hooks": [{"name": "familiar", "type": "command",
                                                "command": "familiar-emit gemini", "timeout": 2000}]}
    assert "matcher" not in s["hooks"]["SessionStart"][0]
    assert not (home / ".codex").exists()       # Codex nepoužívá: nic


def test_agent_install_idempotent_backup_and_uninstall(home, capsys):
    p = gemini_settings(home)
    original = p.read_text()
    install.install()
    backups = list((home / ".local/share/familiar/backup").glob("*/.gemini/settings.json"))
    assert len(backups) == 1 and backups[0].read_text() == original
    capsys.readouterr()
    install.install()
    assert "vše už je v pořádku" in capsys.readouterr().out
    install.uninstall()
    assert json.loads(p.read_text()) == GEMINI_FOREIGN


def test_dry_run_touches_no_agent(home, capsys):
    p = gemini_settings(home)
    before = p.read_text()
    install.install(dry=True, agents="all")
    out = capsys.readouterr().out
    assert "nanečisto: hooky Gemini CLI (8 událostí)" in out and "hooky Codex" in out
    assert p.read_text() == before and not (home / ".codex").exists()


def test_codex_created_file_removed_on_uninstall(home, capsys):
    install.install(agents="codex")
    h = home / ".codex" / "hooks.json"
    s = json.loads(h.read_text())
    assert s["hooks"]["PreToolUse"] == [{"matcher": "*", "hooks": [
        {"type": "command", "command": "familiar-emit codex", "timeout": 2}]}]
    assert "/hooks" in capsys.readouterr().out
    install.uninstall()
    assert not h.exists()


def test_partial_uninstall_and_auto_respects_it(home):
    p = gemini_settings(home)
    install.install()
    install.uninstall(agents="gemini")
    assert json.loads(p.read_text()) == GEMINI_FOREIGN
    assert install.read_record()["agents_off"] == ["gemini"]
    assert install.missing_hooks(install._load_settings()) == []    # Claude zůstal
    install.install()       # auto: odebraný agent se nevrací
    assert json.loads(p.read_text()) == GEMINI_FOREIGN
    install.install(agents="gemini")    # výslovně: vrátí se
    assert not install.missing_hooks(json.loads(p.read_text()), install.AGENTS["gemini"]["events"])
    assert "agents_off" not in install.read_record() or install.read_record()["agents_off"] == []


def test_broken_agent_settings_do_not_block_install(home, capsys):
    p = home / ".gemini" / "settings.json"
    p.parent.mkdir()
    p.write_text('{\n  // komentář\n  "a": 1\n}\n')
    install.install()
    assert "POZOR" in capsys.readouterr().out
    assert p.read_text() == '{\n  // komentář\n  "a": 1\n}\n'
    assert install.missing_hooks(install._load_settings()) == []


def test_unknown_agent_refused(home):
    with pytest.raises(SystemExit):
        install.install(agents="cursor")


def test_gemini_cli_home(home, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "jinde"))
    assert install.agent_file("gemini") == str(tmp_path / "jinde" / ".gemini" / "settings.json")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "cx"))
    assert install.agent_file("codex") == str(tmp_path / "cx" / "hooks.json")


def test_doctor_agent_rows(home, monkeypatch):
    monkeypatch.setattr(doctor, "emit_check", lambda exe: (True, ""))
    monkeypatch.setattr(doctor, "tray", lambda pid: (True, ""))
    rows = {name: (ok, detail) for ok, name, detail in doctor.checks()}
    assert "hooky Gemini CLI" not in rows and "hooky Codex" not in rows     # nepoužívané agenty vynechá
    p = gemini_settings(home)
    rows = {name: (ok, detail) for ok, name, detail in doctor.checks()}
    assert rows["hooky Gemini CLI"][0] and "nenainstalovány" in rows["hooky Gemini CLI"][1]
    install.install()
    s = json.loads(p.read_text())
    del s["hooks"]["AfterAgent"]
    p.write_text(json.dumps(s))
    rows = {name: (ok, detail) for ok, name, detail in doctor.checks()}
    assert rows["hooky Gemini CLI"] == (False, "chybí: AfterAgent")


def test_cli_agents_option():
    from familiar import cli
    args = cli.parser().parse_args(["install", "--agents", "gemini,codex"])
    assert args.agents == "gemini,codex"
    assert cli.parser().parse_args(["install"]).agents is None
    assert cli.parser().parse_args(["uninstall", "--agents", "all"]).agents == "all"
