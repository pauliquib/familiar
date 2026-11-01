import json, os, shutil, signal, socket, subprocess, sys, tempfile, threading, time, zipfile

import pytest

import familiar
from familiar import cli, doctor, emit, paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMIT = os.path.join(ROOT, "familiar", "emit.py")


@pytest.fixture
def runtime(monkeypatch):
    d = tempfile.mkdtemp(prefix="fam", dir="/tmp")      # krátká cesta kvůli Unix socketu
    monkeypatch.setenv("XDG_RUNTIME_DIR", d)
    yield d
    for name in os.listdir(d):
        os.unlink(os.path.join(d, name))
    os.rmdir(d)


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"familiar {familiar.__version__}"


def test_parser_daemon_options():
    args = cli.parser().parse_args(["run", "--mode", "dock"])
    assert args.func is cli.cmd_run and args.mode == "dock"
    args = cli.parser().parse_args(["demo", "0ac5", "--speed", "3"])
    assert args.demo == "0ac5" and args.speed == 3 and args.gap == 4.0
    args = cli.parser().parse_args(["install", "--autostart", "--dry-run"])
    assert args.autostart and args.dry_run and args.source is None


def test_config_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main(["config", "--path"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "familiar" / "config.toml")


def test_stop_when_not_running(runtime, capsys):
    assert paths.daemon_pid() is None
    assert cli.main(["stop"]) == 0
    assert "neběží" in capsys.readouterr().out


def test_stop_terminates_daemon_holding_lock(runtime, capsys):
    # náhradní daemon: drží zámek s pid jako familiar.dock.listen a skončí na SIGTERM
    code = ("import fcntl, os, signal, sys, time\n"
            f"f = open(os.open({paths.lock()!r}, os.O_RDWR | os.O_CREAT, 0o600), 'r+')\n"
            "fcntl.flock(f, fcntl.LOCK_EX)\n"
            "f.write(str(os.getpid())); f.flush()\n"
            "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
            "print('ok', flush=True)\n"
            "time.sleep(30)\n")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ok"
    assert paths.daemon_pid() == p.pid
    assert cli.main(["stop"]) == 0
    assert p.wait(5) == 0
    assert "ukončen" in capsys.readouterr().out
    assert paths.daemon_pid() is None


def run_emit(stdin, runtime):
    return subprocess.run([sys.executable, "-I", EMIT, "claude-code"], input=stdin, capture_output=True,
                          env=dict(os.environ, XDG_RUNTIME_DIR=runtime), timeout=5)


def test_emit_silent_without_daemon(runtime):
    for stdin in (b'{"hook_event_name": "Stop"}', "{ rozbité".encode(), b""):
        r = run_emit(stdin, runtime)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_emit_sends_trimmed_datagram(runtime):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(2)
    hook = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": "/home/x/žluťák",
            "prompt": "ř" * 3000, "tool_name": "Bash", "tool_input": {"command": "ls " + "x" * 300},
            "tool_response": {"stdout": "tajné"}, "background_tasks": [{"id": 1}, {"id": 2}],
            "duration_ms": 12.5, "is_interrupt": False, "error": None}
    r = run_emit(json.dumps(hook).encode(), os.environ["XDG_RUNTIME_DIR"])
    assert (r.returncode, r.stdout) == (0, b"")
    msg = json.loads(s.recv(65536))
    s.close()
    assert msg["v"] == 1 and msg["source"] == "claude-code" and msg["pid"] == os.getpid()
    raw = msg["raw"]
    assert "tool_input" not in raw and "tool_response" not in raw
    assert raw["command"] == ("ls " + "x" * 300)[:200] and raw["prompt"] == "ř" * 2000
    assert raw["background_tasks"] == [{}, {}] and raw["cwd"] == "/home/x/žluťák"
    assert raw["duration_ms"] == 12.5 and raw["is_interrupt"] is False and raw["error"] is None


def test_emit_json_matches_stdlib():
    for value in ({"a": "ž \"x\"\n\t\\ 🐍", "b": [1, 2.5, -3e10, True, None, {}], "n": 2 ** 70}, [], "x", 0.1):
        text = json.dumps(value, ensure_ascii=False)
        assert emit.loads(" \n" + text) == value
        assert json.loads(emit.dumps(value)) == value


def test_emit_stays_light():
    code = f"import sys; sys.path.insert(0, {ROOT!r}); import familiar.emit; print(sorted(m for m in ('json', 're', 'PySide6', 'enum') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT).stdout
    assert out.strip() == "[]"


def test_doctor_measures_emit():
    times, err = doctor.measure_emit(EMIT, runs=3)
    assert err is None and len(times) == 3


def test_daemon_entry_still_works():
    r = subprocess.run([sys.executable, "-m", "familiar.dock", "--help"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "--demo" in r.stdout


def test_emit_does_not_block_on_full_queue(runtime, monkeypatch):
    # daemon žije, ale nečte: fronta datagramů se zaplní
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    w = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    w.setblocking(False)
    with pytest.raises(BlockingIOError):
        for _ in range(100000):
            w.sendto(b"x" * 1000, paths.sock())
    monkeypatch.setattr(emit, "read_hook", lambda: {"hook_event_name": "Stop"})
    t = time.perf_counter()
    emit._emit()
    assert time.perf_counter() - t < 0.01
    w.close()
    s.close()


def big_hook(n_mb):
    """Kompaktní JSON jako od Claude Code: tool_use_id až za velkým tool_response,
    ve vnořených objektech návnady se stejnými klíči."""
    line = 'řádek s "uvozovkami", \\ lomítkem a\ttabem, {závorky} [a] ,"tool_use_id":"x"'
    out = "\n".join([line] * (n_mb * 1024 * 1024 // len(line.encode())))
    hook = {"session_id": "s1", "transcript_path": "/t.jsonl", "cwd": "/home/x/p", "permission_mode": "default",
            "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "cat big"},
            "tool_response": {"stdout": out, "nested": [{"tool_use_id": "návnada", "duration_ms": 1}] * 3000,
                              "last": {"tool_use_id": "návnada2"}},
            "tool_use_id": "toolu_ok", "duration_ms": 1234}
    return json.dumps(hook, ensure_ascii=False, separators=(",", ":")).encode()


def test_emit_big_input_reads_head_and_tail(tmp_path):
    data = big_hook(3)
    assert len(data) > emit.LIMIT
    path = tmp_path / "hook.json"
    path.write_bytes(data)
    fd = os.open(path, os.O_RDONLY)
    got = emit.read_hook(fd)
    os.close(fd)
    assert got["tool_use_id"] == "toolu_ok" and got["duration_ms"] == 1234
    assert got["hook_event_name"] == "PostToolUse" and got["tool_input"] == {"command": "cat big"}
    assert "tool_response" not in got


def test_emit_big_input_tail_last_nested_is_not_top_level(tmp_path):
    hook = json.loads(big_hook(1))
    del hook["tool_use_id"], hook["duration_ms"]      # konec patří vnořenému objektu
    path = tmp_path / "hook.json"
    path.write_text(json.dumps(hook))
    fd = os.open(path, os.O_RDONLY)
    got = emit.read_hook(fd)
    os.close(fd)
    assert "tool_use_id" not in got and got["tool_name"] == "Bash"


def test_emit_small_input_same_as_json(tmp_path):
    hook = {"hook_event_name": "PreToolUse", "tool_input": {"command": "ls"}, "x": [1, 2.5, None]}
    path = tmp_path / "hook.json"
    path.write_text("  " + json.dumps(hook, indent=2))
    fd = os.open(path, os.O_RDONLY)
    assert emit.read_hook(fd) == hook
    os.close(fd)


def test_emit_big_input_datagram(runtime):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(2)
    r = run_emit(big_hook(7), runtime)
    assert (r.returncode, r.stdout) == (0, b"")
    raw = json.loads(s.recv(65536))["raw"]
    s.close()
    assert raw["tool_use_id"] == "toolu_ok" and raw["command"] == "cat big"


def pipe_read_hook(data, kind="pipe"):
    """read_hook z roury (cesta přes splice) nebo socketu (jak ho dává Claude Code),
    do kterých souběžně zapisuje vlákno."""
    if kind == "socket":
        a, b = socket.socketpair()
        r, w = a.detach(), b.detach()
    else:
        r, w = os.pipe()

    def write():
        mv = memoryview(data)
        while mv:
            mv = mv[os.write(w, mv):]
        os.close(w)

    t = threading.Thread(target=write)
    t.start()
    try:
        return emit.read_hook(r)
    finally:
        t.join(10)
        os.close(r)


@pytest.mark.parametrize("kind", ["pipe", "socket"])
@pytest.mark.parametrize("n_mb", [1, 9])
def test_emit_big_input_from_pipe(n_mb, kind):
    got = pipe_read_hook(big_hook(n_mb), kind)
    assert got["tool_use_id"] == "toolu_ok" and got["duration_ms"] == 1234
    assert got["hook_event_name"] == "PostToolUse" and "tool_response" not in got


@pytest.mark.parametrize("kind", ["pipe", "socket"])
@pytest.mark.parametrize("extra", [0, 1, 100, emit.TAIL - 1, emit.TAIL + 7, 3 * emit.TAIL])
def test_emit_input_around_limit(extra, kind):
    """Konec vstupu těsně za začátkem (head): pole se najdou, ať už navazuje, nebo ne."""
    hook = {"hook_event_name": "PostToolUse", "tool_response": "x"}
    pad = emit.LIMIT + extra - len(json.dumps(hook)) - 40
    hook = {"hook_event_name": "PostToolUse", "tool_response": "x" * max(pad, 0), "tool_use_id": "t9",
            "duration_ms": 5}
    got = pipe_read_hook(json.dumps(hook).encode(), kind)
    assert got["tool_use_id"] == "t9" and got["duration_ms"] == 5 and got["hook_event_name"] == "PostToolUse"


def test_emit_big_pretty_printed_input(tmp_path):
    """JSON s mezerami za čárkami: druhý průchod koncem hledá i čárky s mezerou."""
    hook = json.loads(big_hook(1))
    data = json.dumps(hook, ensure_ascii=False, indent=1).encode()
    got = pipe_read_hook(data)
    assert got["tool_use_id"] == "toolu_ok" and got["duration_ms"] == 1234


EMIT_ISOLATED = """import sys
sys.path.insert(0, {root!r})
sys.argv = ["familiar-emit", "claude-code"]
from familiar import emit
emit.main()
"""


def test_emit_big_input_isolated_without_json_import(runtime):
    """Jako ze spouštěče (-I -S): 32 MB z roury, datagram správný, nic na stdout, exit 0,
    a ani chyba v uříznutém tool_response nenačte json/re, ani os."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(5)
    code = EMIT_ISOLATED.format(root=ROOT).replace(
        "emit.main()", "import atexit; atexit.register(lambda: sys.stderr.write(repr(sorted("
        "m for m in ('json', 'json.decoder', 're', 'os') if m in sys.modules))))\nemit.main()")
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code], input=big_hook(32), capture_output=True,
                       env=dict(os.environ, XDG_RUNTIME_DIR=runtime), timeout=10)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"[]")
    raw = json.loads(s.recv(65536))["raw"]
    s.close()
    assert raw["tool_use_id"] == "toolu_ok" and raw["duration_ms"] == 1234 and raw["command"] == "cat big"
    assert "tool_response" not in raw


def test_emit_invalid_input_isolated_is_silent(runtime):
    for stdin in (b"{ rozbit\xc3\xa9", b'{"a": "neukon', b"\xff\xfe", b""):
        r = subprocess.run([sys.executable, "-I", "-S", "-c", EMIT_ISOLATED.format(root=ROOT)], input=stdin,
                           capture_output=True, env=dict(os.environ, XDG_RUNTIME_DIR=runtime), timeout=5)
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def _launcher_env(tmp_path):
    """Wheel ze _build, venv bez pipu a familiar-emit z wheelu jako odkaz v ~/.local/bin."""
    sys.path.insert(0, os.path.join(ROOT, "_build"))
    try:
        import familiar_build
    finally:
        sys.path.remove(os.path.join(ROOT, "_build"))
    whl = tmp_path / familiar_build.build_wheel(str(tmp_path))
    venv = tmp_path / ("v" * 120) / "venv"     # dlouhá cesta: instalátor by z #!python dělal trampolínu
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    site = venv / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
        info = z.getinfo(next(n for n in names if n.endswith(".data/scripts/familiar-emit")))
        assert info.external_attr >> 16 & 0o111
        assert "familiar-emit" not in z.read(next(n for n in names if n.endswith("entry_points.txt"))).decode()
        z.extractall(site, [n for n in names if n.startswith("familiar/")])
        launcher = venv / "bin" / "familiar-emit"
        launcher.write_bytes(z.read(info))
    launcher.chmod(0o755)
    link = tmp_path / "bin" / "familiar-emit"
    link.parent.mkdir()
    link.symlink_to(launcher)
    return venv, link


def test_launcher_runs_isolated_python_of_its_venv(tmp_path, runtime):
    venv, link = _launcher_env(tmp_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(5)
    for data in (json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"command": "ls"}}).encode(),
                 big_hook(2)):
        r = subprocess.run([str(link), "claude-code"], input=data, capture_output=True, timeout=10,
                           env=dict(os.environ, XDG_RUNTIME_DIR=runtime))
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
        msg = json.loads(s.recv(65536))
        assert msg["source"] == "claude-code" and msg["raw"]["command"] in ("ls", "cat big")
    s.close()
    # -I -S: bez site a bez os; ověřeno přímo spuštěním stejného příkazu, jaký sestaví sh
    code = "import sys; print(sys.flags.isolated, sys.flags.no_site, 'site' in sys.modules)"
    probe = venv / "bin" / "probe"
    probe.write_text(link.read_text().split("import sys\n", 1)[0] + code + "\n")
    probe.chmod(0o755)
    assert subprocess.run([str(probe)], capture_output=True, text=True).stdout.split() == ["1", "1", "False"]


def feed(cmd, data, stdin="pipe", env=None, timeout=10):
    """Spustí cmd a celé data mu zapíše jako Claude Code (roura nebo socket, jako to dělá
    Claude Code). Vrací (rc, stdout, stderr, zda zapisující dostal EPIPE/ECONNRESET)."""
    if stdin == "socket":
        ours, theirs = socket.socketpair()
        p = subprocess.Popen(cmd, stdin=theirs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        theirs.close()
        fd = ours.fileno()
    else:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        fd = p.stdin.fileno()
    out = {}
    readers = [threading.Thread(target=lambda k, f: out.__setitem__(k, f.read()), args=(k, f))
               for k, f in (("out", p.stdout), ("err", p.stderr))]
    for t in readers:
        t.start()
    broken = False
    try:
        mv = memoryview(data)
        while mv:
            mv = mv[os.write(fd, mv):]
    except (BrokenPipeError, ConnectionResetError):
        broken = True
    if stdin == "socket":
        ours.shutdown(socket.SHUT_WR)
    else:
        p.stdin.close()
    rc = p.wait(timeout)
    for t in readers:
        t.join(timeout)
    if stdin == "socket":
        ours.close()
    return rc, out["out"], out["err"], broken


def test_emit_big_input_from_socket(runtime):
    """Claude Code dává hookům stdin jako socket: splice ani F_SETPIPE_SZ nejdou, čte se."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(5)
    for data in (big_hook(9), json.dumps({"hook_event_name": "Stop", "tool_use_id": "x"}).encode()):
        r = feed([sys.executable, "-I", "-S", "-c", EMIT_ISOLATED.format(root=ROOT)], data, "socket",
                 env=dict(os.environ, XDG_RUNTIME_DIR=runtime))
        assert r == (0, b"", b"", False)
        raw = json.loads(s.recv(65536))["raw"]
        assert raw["tool_use_id"] in ("toolu_ok", "x")
    s.close()


def test_launcher_runs_with_socket_stdin_and_reports_claude_pid(tmp_path, runtime):
    venv, link = _launcher_env(tmp_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(5)
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime)
    for kind in ("socket", "pipe"):
        assert feed([str(link), "claude-code"], big_hook(3), kind, env) == (0, b"", b"", False)
        msg = json.loads(s.recv(65536))
        assert msg["pid"] == os.getpid() and msg["raw"]["tool_use_id"] == "toolu_ok"
    s.close()


def _no_tools_path(tmp_path, keep=()):
    """PATH jen s vybranými nástroji (bez realpath apod.)."""
    d = tmp_path / "path"
    d.mkdir(exist_ok=True)
    for tool in keep:
        (d / tool).symlink_to(shutil.which(tool))
    return str(d)


def test_launcher_without_realpath_uses_readlink(tmp_path, runtime):
    venv, link = _launcher_env(tmp_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(paths.sock())
    s.settimeout(5)
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime, PATH=_no_tools_path(tmp_path, ["readlink", "cat"]))
    assert feed([str(link), "claude-code"], b'{"hook_event_name": "Stop"}', env=env) == (0, b"", b"", False)
    assert json.loads(s.recv(65536))["raw"] == {"hook_event_name": "Stop"}
    s.close()


@pytest.mark.parametrize("fault", ["bez balíčku", "bez pythonu", "vadný python", "bez realpath i readlink",
                                   "python3 familiar-emit bez balíčku"])
@pytest.mark.parametrize("kind", ["pipe", "socket"])
def test_launcher_faults_are_silent_and_drain_stdin(tmp_path, runtime, fault, kind):
    """Při poruše prostředí: nic na stdout ani stderr, rc 0 a stdin dočtený (žádný EPIPE)."""
    venv, link = _launcher_env(tmp_path)
    cmd, env, data = [str(link), "claude-code"], dict(os.environ, XDG_RUNTIME_DIR=runtime), big_hook(4)
    if fault in ("bez balíčku", "python3 familiar-emit bez balíčku"):
        shutil.rmtree(venv / "lib")
    if fault == "python3 familiar-emit bez balíčku":
        cmd = [str(venv / "bin" / "python3"), "-I", str(link), "claude-code"]
    if fault == "bez pythonu":
        for name in ("python3", "python"):
            (venv / "bin" / name).unlink()
    if fault == "vadný python":
        (venv / "bin" / "python3").unlink()
        (venv / "bin" / "python3").write_bytes(b"\x7fELF nesmysl")
        (venv / "bin" / "python3").chmod(0o755)
    if fault == "bez realpath i readlink":     # najde se jen odkaz ~/.local/bin, ne prostředí
        env["PATH"] = _no_tools_path(tmp_path)
        data = b'{"hook_event_name": "Stop"}' * 1000    # dočítá se smyčkou read v sh (bez cat)
    assert feed(cmd, data, kind, env) == (0, b"", b"", False)


def test_doctor_reports_silent_failure(tmp_path, monkeypatch):
    """Emitter, který skončí 0 bez datagramu nebo s cizím obsahem, je pro doctor CHYBA.
    Limit doby se tu netestuje (na vytíženém stroji by p90 kolísalo): jen obsah datagramu."""
    monkeypatch.setattr(doctor, "EMIT_LIMIT_MS", 10 ** 6)
    monkeypatch.setattr(doctor, "EMIT_RUNS", 3)
    monkeypatch.setattr(doctor, "measure_emit", lambda exe, runs=3, warmup=0: doctor._measure(
        [exe, "claude-code"], runs, warmup, doctor.HOOK_JSON.encode(), check=doctor._datagram_error))
    fake = tmp_path / "familiar-emit"
    fake.write_text("#!/bin/sh\ncat >/dev/null\nexit 0\n")
    fake.chmod(0o755)
    ok, detail = doctor.emit_check(str(fake))
    assert not ok and "nedorazil" in detail
    wrong = tmp_path / "wrong-emit"     # datagram dorazí, ale s jiným obsahem
    wrong.write_text(f"#!{sys.executable}\nimport os, socket, sys\nsys.stdin.buffer.read()\n"
                     "s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)\n"
                     "s.sendto(b'{\"v\": 1}', os.environ['XDG_RUNTIME_DIR'] + '/familiar.sock')\n")
    wrong.chmod(0o755)
    ok, detail = doctor.emit_check(str(wrong))
    assert not ok and "nečekaným obsahem" in detail
    ok, detail = doctor.emit_check(EMIT)
    assert ok and "p90" in detail, detail


def test_private_runtime_dir_without_xdg(tmp_path, monkeypatch):
    base = str(tmp_path / "familiar-{uid}")
    monkeypatch.setattr(paths, "FALLBACK", base)
    monkeypatch.setattr(emit, "FALLBACK", base)
    d = base.format(uid=os.getuid())
    for value in ("", "relativni"):
        monkeypatch.setenv("XDG_RUNTIME_DIR", value)
        assert paths.runtime_dir() == d
        with pytest.raises(OSError):
            emit.sock_path()            # adresář ještě neexistuje
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert paths.secure_runtime_dir() == d and os.stat(d).st_mode & 0o777 == 0o700
    assert emit.sock_path() == paths.sock() == os.path.join(d, "familiar.sock")
    os.chmod(d, 0o755)                  # přístupný ostatním: nepoužít
    assert emit.sock_path() is None and paths.daemon_pid() is None
    with pytest.raises(PermissionError):
        paths.secure_runtime_dir()
    os.chmod(d, 0o700)
    os.rename(d, d + "-cil")
    os.symlink(d + "-cil", d)           # odkaz místo adresáře: nepoužít
    assert emit.sock_path() is None
    with pytest.raises(PermissionError):
        paths.secure_runtime_dir()


def test_python_m_familiar_exit_code():
    r = subprocess.run([sys.executable, "-m", "familiar", "config"], capture_output=True, cwd=ROOT)
    assert r.returncode == 2
