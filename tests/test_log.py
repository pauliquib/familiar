import logging

import pytest

from familiar import log as flog

SECRET = "TAJNY-PROMPT-" + "x" * 1000


@pytest.fixture
def logger(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    lg = logging.getLogger(flog.NAME)
    old = lg.handlers[:]
    lg.handlers = []
    yield flog.setup(logging.DEBUG)
    for h in lg.handlers:
        h.close()
    lg.handlers = old


def read(tmp_path):
    for h in logging.getLogger(flog.NAME).handlers:
        h.flush()
    return (tmp_path / "familiar" / "familiar.log").read_text(encoding="utf-8")


def test_path_default(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert flog.log_path() == tmp_path / ".local" / "state" / "familiar" / "familiar.log"


def test_setup_creates_rotating_file(logger, tmp_path):
    hs = logger.handlers
    assert len(hs) == 1 and hs[0].maxBytes == flog.MAX_BYTES and hs[0].backupCount == flog.BACKUPS
    assert flog.setup(logging.INFO) is logger and len(logger.handlers) == 1   # bez duplicit
    assert logger.level == logging.INFO
    logging.getLogger("familiar.dock").warning("start %d", 42)   # potomek jde do stejného souboru
    assert "familiar.dock: start 42" in read(tmp_path)


def test_messages_truncated_to_one_line(logger, tmp_path):
    logger.info("prompt: %s", "a\nb" + SECRET)
    text = read(tmp_path)
    line = text.splitlines()[-1]
    assert len(text.splitlines()) == 1 and "a b" in line
    assert len(line.split(": ", 1)[1]) <= flog.MAX_MSG + len("prompt")


def test_exception_message_truncated(logger, tmp_path):
    try:
        raise ValueError(SECRET)
    except ValueError:
        logger.exception("chyba")
    text = read(tmp_path)
    assert "ValueError" in text and "x" * 300 not in text


def test_safe_keeps_only_safe_fields():
    msg = {"v": 1, "source": "claude-code", "pid": 1234, "ts": 5.5, "raw": {
        "hook_event_name": "PostToolUseFailure", "session_id": "abcdef12-3456",
        "transcript_path": "/home/u/.claude/projects/-home-u-tajny-projekt/abc.jsonl",
        "cwd": "/home/u/tajny-projekt", "prompt": SECRET, "command": "rm " + SECRET,
        "error": "Exit code 1\n" + SECRET, "tool_name": "Bash", "duration_ms": 12,
        "tool_input": {"command": SECRET}, "background_tasks": [{}, {}], "is_interrupt": False}}
    s = flog.safe(msg)
    assert s == {"source": "claude-code", "pid": 1234, "ts": 5.5,
                 "hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "duration_ms": 12,
                 "is_interrupt": False, "session_id": "abcdef12", "prompt_len": len(SECRET),
                 "command_len": len(SECRET) + 3, "error_len": len(SECRET) + 12,
                 "background_tasks": 2, "transcript": "abc.jsonl"}
    assert "TAJNY" not in repr(s) and "tajny" not in repr(s)


def test_safe_on_bare_raw_and_garbage():
    assert flog.safe({"hook_event_name": "Stop", "prompt": "x"}) == {
        "hook_event_name": "Stop", "prompt_len": 1}
    assert flog.safe(None) == {} and flog.safe({"tool_name": {"x": 1}}) == {}


def test_dict_args_go_through_safe(logger, tmp_path):
    raw = {"hook_event_name": "UserPromptSubmit", "prompt": SECRET, "cwd": "/home/u/tajny"}
    logger.info("zpráva %s", raw)
    logger.info("obálka %s, seznam %s", {"v": 1, "raw": raw}, [SECRET])
    logger.info(raw)
    text = read(tmp_path)
    assert "TAJNY" not in text and "tajny" not in text
    assert "UserPromptSubmit" in text and f"'prompt_len': {len(SECRET)}" in text and "<list 1>" in text


def test_exception_text_not_logged(logger, tmp_path):
    try:
        try:
            raise KeyError(SECRET[:20])
        except KeyError as e:
            raise ValueError("Expecting value: " + SECRET) from e
    except ValueError:
        logger.exception("vadná zpráva")
    text = read(tmp_path)
    assert "TAJNY" not in text
    assert "ValueError (text výjimky se neloguje)" in text and "KeyError" in text
