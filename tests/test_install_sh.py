# install.sh bez uv a pipx: záložní venv se závislostmi z site-packages python3.
#
# Běží v dočasném HOME s PATH jen z vybraných nástrojů (žádné pipx, uv je atrapa, která
# selže), PySide6 a tomlkit jsou atrapy přes PYTHONPATH, aby test nezávisel na systému.
import json, os, shutil, subprocess, sys, tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = ("dirname", "date", "sed", "rm")
FAKE_UV = """#!/bin/sh
[ "$1 $2" = "tool dir" ] && { echo "$UV_TOOL_DIR"; exit 0; }
echo "$*" >> "$UV_LOG"
exit 1
"""

pytestmark = pytest.mark.skipif(not all(shutil.which(t) for t in TOOLS), reason="chybí nástroje")


@pytest.fixture
def env(tmp_path):
    src = tmp_path / "klon"      # kopie repozitáře, build nic nezapíše do skutečného
    src.mkdir()
    for name in ("install.sh", "pyproject.toml", "LICENSE"):
        shutil.copy(os.path.join(REPO, name), src / name)
    for name in ("familiar", "_build", "LICENSES"):
        shutil.copytree(os.path.join(REPO, name), src / name, ignore=shutil.ignore_patterns("__pycache__"))
    bin_ = tmp_path / "nastroje"
    bin_.mkdir()
    os.symlink(sys.executable, bin_ / "python3")
    for t in TOOLS:
        os.symlink(shutil.which(t), bin_ / t)
    (bin_ / "uv").write_text(FAKE_UV)
    (bin_ / "uv").chmod(0o755)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"theme": "dark"}\n')
    rt = tempfile.mkdtemp(prefix="fam", dir="/tmp")     # krátká cesta pro socket
    yield {"src": src, "home": home, "tmp": tmp_path, "env": {
        "HOME": str(home), "PATH": f"{home}/.local/bin:{bin_}", "LANG": "C.UTF-8",
        "XDG_RUNTIME_DIR": rt, "UV_TOOL_DIR": str(tmp_path / "uvtools"), "UV_LOG": str(tmp_path / "uv.log"),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/bus"}}
    shutil.rmtree(rt, ignore_errors=True)


def fake_deps(root, broken=False):
    """Atrapy PySide6 a tomlkit; broken: tomlkit nejde importovat."""
    (root / "PySide6").mkdir(parents=True)
    (root / "PySide6" / "__init__.py").write_text("__version_info__ = (6, 11, 0)\n")
    for mod in ("QtWidgets", "QtDBus"):
        (root / "PySide6" / f"{mod}.py").write_text("")
    (root / "tomlkit.py").write_text("raise ImportError('atrapa')\n" if broken else "")
    return str(root)


def run_install(env, deps):
    e = dict(env["env"], PYTHONPATH=deps)
    return subprocess.run(["/bin/sh", str(env["src"] / "install.sh")], env=e, capture_output=True,
                          text=True, timeout=300)


def uv_calls(env):
    log = env["tmp"] / "uv.log"
    return log.read_text().splitlines() if log.exists() else []


def test_without_deps_fails_clearly_and_leaves_nothing(env):
    r = run_install(env, fake_deps(env["tmp"] / "deps", broken=True))
    assert r.returncode == 1
    assert "CHYBA: bez sítě potřebuju PySide6" in r.stderr
    data = env["home"] / ".local" / "share" / "familiar"
    assert not list(data.glob("venv-*"))        # rozpracovaný venv smazán
    assert json.loads((env["home"] / ".claude" / "settings.json").read_text()) == {"theme": "dark"}
    calls = uv_calls(env)
    assert calls and len(calls) == len(set(calls))      # uv se zkouší, ale nikdy dvakrát stejně


def test_venv_fallback_installs_copy_with_hooks(env):
    r = run_install(env, fake_deps(env["tmp"] / "deps"))
    assert r.returncode == 0, r.stderr
    venvs = list((env["home"] / ".local" / "share" / "familiar").glob("venv-*"))
    assert len(venvs) == 1
    emit = env["home"] / ".local" / "bin" / "familiar-emit"
    assert os.path.realpath(emit) == str(venvs[0] / "bin" / "familiar-emit")
    assert '/python3" -I -S "$p"' in emit.read_text()    # spouštěč z _build: emitter bez site a .pth
    settings = json.loads((env["home"] / ".claude" / "settings.json").read_text())
    assert settings["theme"] == "dark" and len(settings["hooks"]) == 13
    shutil.rmtree(env["src"])       # nainstalovaný familiar na klonu nezávisí
    e = dict(env["env"])
    r = subprocess.run([str(emit), "claude-code"], input='{"hook_event_name": "Stop", "session_id": "t"}',
                       env=e, capture_output=True, text=True, timeout=10)
    assert (r.returncode, r.stdout) == (0, "")
    r = subprocess.run([str(env["home"] / ".local" / "bin" / "familiar"), "--version"], env=e,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "familiar" in r.stdout
