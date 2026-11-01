from familiar.topic import ELEKTRONIKA, KOD, RESERSE, TopicTracker


def ev(ts, kind, **data):
    return {"ts": ts, "kind": kind, "data": data}


def test_no_topic_without_evidence():
    t = TopicTracker(0)
    t.feed(ev(1, "user.prompt", text="ahoj"))
    assert t.topic is None


def test_electronics_from_prompt():
    t = TopicTracker(0)
    t.feed(ev(1, "user.prompt", text="přerouti desku v KiCadu, footprint U11 nesedí"))
    assert t.topic == ELEKTRONIKA


def test_tools_and_commands_count():
    t = TopicTracker(0)
    for k in range(6):
        t.feed(ev(k, "tool.start", tool="WebSearch"))
    assert t.topic == RESERSE
    t2 = TopicTracker(0)
    for k in range(10):
        t2.feed(ev(k, "tool.start", tool="Bash", cmd="python3 -m pytest -q"))
    assert t2.topic == KOD


def test_topic_switches_and_fades():
    t = TopicTracker(0)
    t.feed(ev(1, "user.prompt", text="oprav routing na desce, konektor J5"))
    assert t.topic == ELEKTRONIKA
    t.feed(ev(4000, "user.prompt", text="refaktoruj funkci a pusť testy v pythonu"))
    assert t.topic == KOD
    assert t.advance(20000) is None


def test_cwd_hints_topic():
    t = TopicTracker(0)
    t.feed(ev(0, "session.start", cwd="/home/x/kicad-pcb", how="startup"))
    t.feed(ev(1, "user.prompt", text="pokračuj se schématem"))
    assert t.topic == ELEKTRONIKA
