import json, os, shutil

import pytest

from familiar import install, paths

CALLS = []     # volání D-Bus (KWin reconfigure)
REAL_SETTINGS = os.path.expanduser("~/.claude/settings.json")
OTHER_RULE = """[aaaa]
Description=wine
wmclass=wine
wmclassmatch=2

[General]
count=1
rules=aaaa
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Dočasný HOME; XDG_* proměnné se odvodí z něj (paths.py)."""
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_BIN_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    CALLS.clear()
    monkeypatch.setattr(install, "dbus", lambda *a: CALLS.append(a) or "()")
    monkeypatch.setattr(install, "installed", lambda name: None)
    return tmp_path


def write_settings(home, data):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def foreign():
    return {
        "env": {"DISABLE_TELEMETRY": "1"},
        "permissions": {"allow": ["Bash", "Read"], "defaultMode": "auto"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify-send hotovo"}]}]},
        "theme": "dark",
        "autoMode": {"environment": ["x"]},
    }


def ours(settings, event):
    return [h for e in settings["hooks"].get(event, []) for h in e["hooks"] if h["command"] == install.CMD]


def test_install_adds_hooks_keeps_foreign_keys_and_is_idempotent(home, capsys):
    path = write_settings(home, foreign())
    install.install()
    data = json.loads(path.read_text())
    assert list(data) == ["env", "permissions", "hooks", "theme", "autoMode", "statusLine"]
    assert {k: v for k, v in data.items() if k not in ("hooks", "statusLine")} == \
        {k: v for k, v in foreign().items() if k != "hooks"}
    assert data["statusLine"] == {"type": "command", "command": install.CMD_STATUSLINE, "padding": 0}
    assert all(len(ours(data, ev)) == 1 for ev in install.EVENTS)
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "notify-send hotovo"
    assert data["hooks"]["PreToolUse"] == [{"matcher": "*", "hooks": [
        {"type": "command", "command": "familiar-emit claude-code", "timeout": 2}]}]
    assert "matcher" not in data["hooks"]["SessionStart"][0]

    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and "backup" not in p.parts}
    capsys.readouterr()
    install.install()
    assert "nic neměním" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in home.rglob("*") if p.is_file() and "backup" not in p.parts} == before


def test_uninstall_restores_original_hooks(home):
    path = write_settings(home, foreign())
    original = path.read_text()
    install.install()
    install.uninstall()
    assert path.read_text() == original


def test_uninstall_removes_hooks_key_when_only_ours(home):
    data = foreign()
    del data["hooks"]
    path = write_settings(home, data)
    install.install()
    assert "hooks" in json.loads(path.read_text())
    install.uninstall()
    assert json.loads(path.read_text()) == data


@pytest.mark.skipif(not os.path.exists(REAL_SETTINGS), reason="bez ~/.claude/settings.json")
def test_real_settings_copy(home):
    real = open(REAL_SETTINGS).read()
    path = home / ".claude" / "settings.json"
    path.parent.mkdir()
    shutil.copy(REAL_SETTINGS, path)
    install.install()
    if not install.missing_hooks(json.loads(real)) and install.statusline_status(json.loads(real)) != "chybi":
        assert path.read_text() == real          # hooky už jsou: soubor se nezmění
    install.uninstall()
    after = json.loads(path.read_text())
    before = json.loads(real)
    assert install.missing_hooks(after) == list(install.EVENTS)
    assert {k: v for k, v in after.items() if k != "hooks"} == \
        {k: v for k, v in before.items() if k != "hooks" and not (k == "statusLine" and install._ours_any(v))}
    install.install()
    assert not install.missing_hooks(json.loads(path.read_text()))


def test_statusline_foreign_is_kept(home, capsys):
    data = foreign()
    data["statusLine"] = {"type": "command", "command": "~/bin/moje-lista"}
    path = write_settings(home, data)
    install.install()
    assert json.loads(path.read_text())["statusLine"] == data["statusLine"]
    assert "statusLine v settings.json je cizí" in capsys.readouterr().out
    install.uninstall()
    assert json.loads(path.read_text())["statusLine"] == data["statusLine"]


def test_backup_before_overwrite(home):
    path = write_settings(home, foreign())
    original = path.read_bytes()
    install.install()
    backups = list((home / ".local/share/familiar/backup").glob("*/.claude/settings.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == original


def test_dry_run_writes_nothing(home, capsys):
    write_settings(home, foreign())
    before = sorted(p for p in home.rglob("*"))
    install.install(dry=True, autostart=True)
    out = capsys.readouterr().out
    assert "nanečisto: hooky" in out and "autostart" in out
    assert sorted(p for p in home.rglob("*")) == before
    assert CALLS == []


def test_kwin_rule_added_once_and_removed(home, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")       # pravidlo jen na KDE
    rules = home / ".config" / "kwinrulesrc"
    rules.parent.mkdir()
    rules.write_text(OTHER_RULE)
    install.install()
    text = rules.read_text()
    assert text.count("wmclass=familiar") == 1 and "count=2" in text
    rule_id = [g for g, _ in install._ini(text) if g not in ("aaaa", "General")][0]
    assert f"rules=aaaa,{rule_id}" in text
    assert CALLS == [("org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")]
    install.install()
    assert rules.read_text() == text and len(CALLS) == 1
    install.uninstall()
    assert rules.read_text() == OTHER_RULE and len(CALLS) == 2


def test_existing_familiar_rule_is_not_duplicated(home):
    text = install.add_rule(OTHER_RULE, "ruční")
    assert install.add_rule(text) == text
    assert install.remove_rule(text) == OTHER_RULE
    foreign_rule = OTHER_RULE.replace("Description=wine\nwmclass=wine", "Description=moje\nwmclass=familiar")
    assert install.has_rule(foreign_rule) and install.remove_rule(foreign_rule) == foreign_rule


def test_desktop_and_autostart_in_temp_xdg(home, tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    other = xdg / "autostart" / "jiny.desktop"
    other.parent.mkdir(parents=True)
    other.write_text("[Desktop Entry]\nName=Jiný\n")
    install.install(autostart=True)
    auto = xdg / "autostart" / "familiar.desktop"
    assert "Exec=familiar run" in auto.read_text()
    assert (home / ".local/share/applications/familiar.desktop").read_text() == auto.read_text()
    assert json.loads((home / ".local/share/familiar/install.json").read_text())["autostart"] is True
    install.uninstall()
    assert not auto.exists() and other.exists()
    assert not (home / ".local/share/applications/familiar.desktop").exists()
    assert not (home / ".local/share/familiar/install.json").exists()


def test_install_records_source(home, monkeypatch):
    monkeypatch.setattr(install, "_source_dir", lambda: None)    # jako nainstalovaný balíček
    install.install(source="/repo", via="uv")
    rec = install.read_record()
    assert rec["source"] == "/repo" and rec["via"] == "uv"
    install.install()       # bez --source zůstane poslední známý zdroj
    assert install.read_record()["source"] == "/repo"


def test_links_replace_repo_symlink_and_old_wrapper(home, monkeypatch):
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    repo_emit = home / "repo" / "familiar" / "emit.py"
    repo_emit.parent.mkdir(parents=True)
    repo_emit.write_text("")
    (bin_dir / "familiar-emit").symlink_to(repo_emit)
    (bin_dir / "familiar-dock").write_text("#!/bin/sh\nexec python3 -m familiar.dock \"$@\"\n")
    (bin_dir / "jiny").write_text("cizí")
    venv = home / "venv" / "bin"
    venv.mkdir(parents=True)
    for name in ("familiar", "familiar-emit"):
        (venv / name).write_text("")
    monkeypatch.setattr(install, "installed", lambda name: str(venv / name))

    install.install()
    assert os.readlink(bin_dir / "familiar-emit") == str(venv / "familiar-emit")
    assert os.readlink(bin_dir / "familiar") == str(venv / "familiar")
    assert not (bin_dir / "familiar-dock").exists() and (bin_dir / "jiny").exists()
    backup = next((home / ".local/share/familiar/backup").glob("*/.local/bin"))
    assert os.readlink(backup / "familiar-emit") == str(repo_emit)
    assert "familiar.dock" in (backup / "familiar-dock").read_text()
    assert f"Exec={bin_dir / 'familiar'} run" in (home / ".local/share/applications/familiar.desktop").read_text()


def test_invalid_settings_are_not_touched(home):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text("{ rozbité")
    with pytest.raises(SystemExit):
        install.install()
    assert path.read_text() == "{ rozbité"


def test_paths_follow_home(home):
    assert paths.claude_settings() == str(home / ".claude" / "settings.json")
    assert paths.autostart_file() == str(home / ".config" / "autostart" / "familiar.desktop")


def test_symlinked_settings_backup_has_content(home, tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text(json.dumps(foreign(), indent=2) + "\n")
    original = real.read_bytes()
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").symlink_to(real)
    install.install()
    assert (home / ".claude" / "settings.json").is_symlink()      # zapisuje se do cíle
    assert not install.missing_hooks(json.loads(real.read_text()))
    backup = next((home / ".local/share/familiar/backup").glob("*/.claude/settings.json"))
    assert not backup.is_symlink() and backup.read_bytes() == original


def test_foreign_shapes_are_kept(home, capsys):
    data = foreign()
    data["hooks"]["PreToolUse"] = []                      # cizí prázdný seznam
    data["hooks"]["Stop"] = {"divné": True}               # cizí tvar, ne seznam
    path = write_settings(home, data)
    original = path.read_text()
    install.install()
    after = json.loads(path.read_text())
    assert after["hooks"]["Stop"] == {"divné": True}
    assert "POZOR: hooky Stop" in capsys.readouterr().out
    assert len(ours(after, "PreToolUse")) == 1
    install.uninstall()
    assert path.read_text() == original


def test_empty_foreign_hooks_key_kept(home):
    data = foreign()
    data["hooks"] = {}
    path = write_settings(home, data)
    original = path.read_text()
    install.install()
    install.uninstall()
    assert path.read_text() == original


@pytest.mark.parametrize("text", ['{"hooks": {}, "theme": "a", "theme": "b"}', '{"x": 1e400}',
                                  '{"x": NaN}', '{"hooks": []}'])
def test_ambiguous_settings_refused(home, text, capsys):
    path = home / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(text)
    with pytest.raises(SystemExit) as e:
        install.install()
    assert "CHYBA" in str(e.value) and path.read_text() == text
