import json

from familiar import transcript
from familiar.transcript import (INTERRUPTED, INTERRUPTED_TOOL, TranscriptWatcher,
                                 TranscriptWatchers, detect)


def rec(type_="user", text=None, content=None, **extra):
    if content is None:
        content = [{"type": "text", "text": text}]
    o = {"type": type_, "message": {"role": "assistant" if type_ == "assistant" else "user",
                                    "content": content}, "uuid": "u1", **extra}
    return json.dumps(o) + "\n"


INT = rec(text="[Request interrupted by user]", interruptedMessageId="m1")
INT_TOOL = rec(text="[Request interrupted by user for tool use]")
PROMPT = rec(text="ahoj, uprav soubor")


def kinds(hits):
    return [k for k, _ in hits]


def write(p, s, mode="a"):
    with open(p, mode, encoding="utf-8") as f:
        f.write(s)


def test_detect_variants():
    assert detect(INT.encode()) == INTERRUPTED
    assert detect(INT_TOOL.encode()) == INTERRUPTED_TOOL
    assert detect(rec(content="[Request interrupted by user]").encode()) == INTERRUPTED
    assert detect(PROMPT.encode()) is None


def test_detect_ignores_lookalikes():
    # marker v tool_result, v odpovědi asistenta, uprostřed promptu, v sidechainu, rozbitý JSON
    tr = rec(content=[{"type": "tool_result", "content": "[Request interrupted by user]"}])
    assert detect(tr.encode()) is None
    assert detect(rec("assistant", text="[Request interrupted by user]").encode()) is None
    assert detect(rec(text="viz [Request interrupted by user] v logu").encode()) is None
    assert detect(rec(text="[Request interrupted by user]", isSidechain=True).encode()) is None
    assert detect(rec("api-request-blob", text="[Request interrupted by user]").encode()) is None
    assert detect(b'{"type": "user", "[Request interrupted by user') is None


def test_starts_at_end_of_existing_file(tmp_path):
    p = tmp_path / "s.jsonl"
    write(p, PROMPT + INT)
    w = TranscriptWatcher(str(p))
    assert w.poll() == []           # staré přerušení se nehlásí
    write(p, PROMPT + INT_TOOL)
    assert kinds(w.poll()) == [INTERRUPTED_TOOL]
    assert w.poll() == []           # každé jen jednou


def test_partial_line(tmp_path):
    p = tmp_path / "s.jsonl"
    write(p, PROMPT)
    w = TranscriptWatcher(str(p))
    write(p, INT[:20])
    assert w.poll() == []
    write(p, INT[20:])
    assert kinds(w.poll()) == [INTERRUPTED]


def test_attach_mid_line_skips_rest(tmp_path):
    p = tmp_path / "s.jsonl"
    write(p, PROMPT + INT[:30])
    w = TranscriptWatcher(str(p))
    write(p, INT[30:] + INT)
    assert kinds(w.poll()) == [INTERRUPTED]   # useknutý řádek se nepočítá, celý další ano


def test_missing_file_then_created(tmp_path):
    p = tmp_path / "s.jsonl"
    w = TranscriptWatcher(str(p))
    assert w.poll() == []
    write(p, PROMPT + INT)
    assert kinds(w.poll()) == [INTERRUPTED]


def test_truncation_and_rotation(tmp_path):
    p = tmp_path / "s.jsonl"
    write(p, PROMPT * 5)
    w = TranscriptWatcher(str(p))
    write(p, INT, mode="w")             # zkrácení
    assert kinds(w.poll()) == [INTERRUPTED]
    q = tmp_path / "new.jsonl"
    write(q, INT_TOOL)
    q.replace(p)                        # výměna souboru (jiný inode)
    assert kinds(w.poll()) == [INTERRUPTED_TOOL]
    p.unlink()
    assert w.poll() == []
    write(p, INT)
    assert kinds(w.poll()) == [INTERRUPTED]


def test_large_growth_reads_only_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, "MAX_READ", 4096)
    p = tmp_path / "s.jsonl"
    write(p, "")
    w = TranscriptWatcher(str(p))
    write(p, INT + PROMPT * 100 + INT_TOOL)   # staré přerušení za stropem se zahodí
    assert kinds(w.poll()) == [INTERRUPTED_TOOL]
    assert w.offset == p.stat().st_size


def test_huge_line_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript, "MAX_READ", 4096)
    monkeypatch.setattr(transcript, "MAX_LINE", 1024)
    p = tmp_path / "s.jsonl"
    write(p, "")
    w = TranscriptWatcher(str(p))
    write(p, '{"type": "attachment", "x": "' + "a" * 3000)
    assert w.poll() == []
    write(p, "a" * 3000 + '"}\n')
    assert w.poll() == []
    write(p, INT)
    assert kinds(w.poll()) == [INTERRUPTED]


def test_watchers_by_pid(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write(a, PROMPT)
    write(b, PROMPT)
    ws = TranscriptWatchers()
    ws.watch(1, str(a))
    ws.watch(2, str(b))
    ws.watch(3, "relativni.jsonl")      # neplatné cesty se ignorují
    ws.watch(4, "/etc/passwd")
    ws.watch(5, None)
    assert len(ws) == 2 and 1 in ws and 3 not in ws
    write(a, INT)
    write(b, INT_TOOL)
    assert sorted(p[:2] for p in ws.poll_all()) == [(1, INTERRUPTED), (2, INTERRUPTED_TOOL)]
    ws.watch(1, str(a))                 # stejná cesta → offset zůstává
    assert ws.poll_all() == []
    c = tmp_path / "c.jsonl"            # /clear → nový transcript
    ws.watch(1, str(c))
    write(c, INT)
    assert [p[:2] for p in ws.poll_all()] == [(1, INTERRUPTED)]
    ws.unwatch(1)
    ws.unwatch(99)
    write(c, INT)
    assert ws.poll_all() == []


def test_hit_carries_record_time():
    line = rec(text="[Request interrupted by user]", timestamp="2026-10-22T16:51:36.500Z").encode()
    assert transcript.hit(line) == (INTERRUPTED, 1792687896.5)
    assert transcript.hit(INT.encode()) == (INTERRUPTED, None)          # bez času
    assert transcript.hit(rec(text="[Request interrupted by user]", timestamp="včera").encode())[1] is None


# --- kontext ---------------------------------------------------------------------

def asst(inp, read=0, create=0, model="claude-opus-5-5", **extra):
    o = {"type": "assistant", "isSidechain": False, "uuid": "a1",
         "message": {"role": "assistant", "model": model, "content": [{"type": "text", "text": "odpověď"}],
                     "usage": {"input_tokens": inp, "cache_read_input_tokens": read,
                               "cache_creation_input_tokens": create, "output_tokens": 99}}}
    o.update(extra)
    return json.dumps(o) + "\n"


def compact(post=13265):
    return json.dumps({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
                       "compactMetadata": {"trigger": "auto", "preTokens": 900000, "postTokens": post}}) + "\n"


def test_okno_podle_modelu():
    assert transcript.okno("claude-opus-5-5") == transcript.OKNO_1M
    assert transcript.okno("claude-sonnet-4-6") == transcript.OKNO_1M
    assert transcript.okno("claude-haiku-4-5") == transcript.OKNO
    assert transcript.okno("claude-haiku-4-5[1m]") == transcript.OKNO_1M
    assert transcript.okno("us.anthropic.claude-opus-4-8") == transcript.OKNO_1M
    assert transcript.okno("claude-sonnet-4-5") == transcript.OKNO
    assert transcript.okno("claude-sonnet-4-5", used=250_000) == transcript.OKNO_1M   # přeteklo → 1M
    assert transcript.okno(None) == transcript.OKNO


def test_context_hit():
    assert transcript.context_hit(asst(10, 1000, 50).encode()) == ("usage", 1060, "claude-opus-5-5")
    assert transcript.context_hit(asst(10, isSidechain=True).encode()) is None            # subagent
    assert transcript.context_hit(asst(0, model="<synthetic>").encode()) is None          # chyba API
    assert transcript.context_hit(asst(5, isApiErrorMessage=True).encode()) is None
    assert transcript.context_hit(compact(500).encode()) == ("compact", 500)
    assert transcript.context_hit(PROMPT.encode()) is None
    assert transcript.context_hit(b'{"type": "assistant", "usage"') is None
    bad = json.loads(asst(10))
    bad["message"]["usage"] = {"input_tokens": "x", "cache_read_input_tokens": True}
    assert transcript.context_hit(json.dumps(bad).encode()) == ("usage", 0, "claude-opus-5-5")


def test_kontext_pri_napojeni_a_prirustcich(tmp_path):
    p = tmp_path / "s.jsonl"
    write(p, PROMPT + asst(3, 40000, 2000) + PROMPT)
    ws = TranscriptWatchers()
    ws.watch(1, str(p))
    assert ws.context(1) == {"used": 42003, "window": 1_000_000, "model": "claude-opus-5-5"}
    assert ws.poll_context() == [(1, transcript.CONTEXT, ws.context(1))]   # stav z konce souboru
    assert ws.poll_context() == []
    write(p, asst(1, 50000, 500, isSidechain=True) + INT)
    assert [h[:2] for h in ws.poll_all()] == [(1, INTERRUPTED)]            # přerušení dál stejně
    assert ws.poll_context() == []                                          # subagent kontext nemění
    write(p, asst(1, 60000, 500))
    assert ws.poll_all() == []
    assert ws.poll_context() == [(1, "context", {"used": 60501, "window": 1_000_000, "model": "claude-opus-5-5"})]
    write(p, compact(13000))                                                # compact → reset
    ws.poll_all()
    assert ws.poll_context() == [(1, "context", {"used": 13000, "window": 1_000_000, "model": "claude-opus-5-5"})]
    write(p, asst(1, 14000, 0, model="claude-haiku-4-5"))
    ws.poll_all()
    assert ws.context(1)["window"] == 200_000
    assert ws.context(2) is None


def test_kontext_po_compactu_v_konci_souboru(tmp_path):
    p = tmp_path / "s.jsonl"
    write(p, asst(1, 900000, 0, model="claude-sonnet-4-6") + compact(9000) + PROMPT)
    w = TranscriptWatcher(str(p))
    assert w.context == {"used": 9000, "window": 1_000_000, "model": "claude-sonnet-4-6"}
    q = tmp_path / "novy.jsonl"
    write(q, PROMPT)
    assert TranscriptWatcher(str(q)).context is None
    assert TranscriptWatcher(str(tmp_path / "neni.jsonl")).context is None
