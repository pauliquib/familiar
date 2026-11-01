from familiar.fsm import (ActivityFSM, ERROR, GONE, IDLE, LINGER_S, LISTENING, SLEEP_S,
                          SLEEPING, SUCCESS, THINKING, WAITING, WORKING)


def ev(ts, kind, **data):
    return {"v": 1, "source": "test", "session": "s", "pid": 1, "ts": ts, "kind": kind, "data": data}


def play(*events, until=None):
    fsm = ActivityFSM(0.0)
    for e in events:
        fsm.feed(e)
    if until is not None:
        fsm.advance(until)
    return fsm


def states(fsm):
    return [new for _, _, new, _ in fsm.log]


def test_clean_round():
    fsm = play(ev(1, "user.prompt", text="ahoj"),
               ev(5, "tool.start", tool="Read", id="t1"),
               ev(5.1, "tool.end", tool="Read", id="t1"),
               ev(20, "agent.done", background=0),
               until=30)
    assert states(fsm) == [LISTENING, THINKING, WORKING, THINKING, SUCCESS, IDLE]


def test_working_lingers_between_quick_tools():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="t1"),
               ev(5.2, "tool.end", tool="Bash", id="t1"),
               ev(5.2 + LINGER_S - 0.5, "tool.start", tool="Bash", id="t2"),
               until=6.5)
    assert states(fsm) == [LISTENING, THINKING, WORKING]


def test_parallel_tools_keep_working():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Read", id="a"),
               ev(5, "tool.start", tool="Read", id="b"),
               ev(5.1, "tool.end", tool="Read", id="a"),
               until=30)
    assert fsm.state == WORKING
    fsm.feed(ev(31, "tool.end", tool="Read", id="b"))
    assert fsm.advance(31 + LINGER_S) == THINKING


def test_error_flash_returns_to_open_tool():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="a"),
               ev(5, "tool.start", tool="Bash", id="b"),
               ev(6, "tool.error", tool="Bash", id="a", code=1),
               until=10)
    assert states(fsm)[-2:] == [ERROR, WORKING]


def test_round_with_error_ends_idle_not_success():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="a"),
               ev(6, "tool.error", tool="Bash", id="a", code=1),
               ev(20, "agent.done"))
    assert fsm.state == IDLE


def test_queued_prompt_keeps_round_errors():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="a"),
               ev(6, "tool.error", tool="Bash", id="a", code=1),
               ev(8, "user.prompt", text="a ještě tohle"),
               ev(20, "agent.done"))
    assert fsm.state == IDLE


def test_permission_wait_ends_with_tool():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="a"),
               ev(5.1, "agent.waiting", tool="Bash", why="permission"),
               until=100)
    assert fsm.state == WAITING and fsm.waiting == "permission"
    fsm.feed(ev(101, "tool.end", tool="Bash", id="a"))
    assert fsm.state == THINKING and fsm.waiting is None


def test_rejected_permission_is_new_prompt():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="a"),
               ev(5.1, "agent.waiting", tool="Bash", why="permission"),
               ev(30, "user.prompt", text="ne, to nedělej"),
               until=31)
    assert fsm.state == THINKING and not fsm.tools


def test_tool_left_open_by_interrupt_is_dropped():
    fsm = play(ev(1, "user.prompt"),
               ev(5, "tool.start", tool="Bash", id="lost"),
               ev(9, "user.prompt", text="stop"),
               ev(12, "tool.start", tool="Read", id="b"),
               ev(12.1, "tool.end", tool="Read", id="b"),
               until=12.1 + LINGER_S)
    assert fsm.state == THINKING and not fsm.stale


def test_subagent_tools_do_not_move_main_state():
    fsm = play(ev(1, "user.prompt"),
               ev(3, "subagent.start", agent="x", type="general-purpose"),
               ev(4, "agent.done", background=1),
               ev(10, "tool.start", tool="Bash", id="s1", agent="x"),
               ev(11, "tool.error", tool="Bash", id="s1", agent="x", code=1),
               until=20)
    assert fsm.state == IDLE and fsm.subagents == {"x"} and fsm.background == 1
    fsm.feed(ev(21, "subagent.done", agent="x", type="general-purpose"))
    assert not fsm.subagents


def test_subagent_activity_postpones_sleep():
    fsm = play(ev(1, "agent.done"), ev(500, "tool.start", tool="Bash", id="s", agent="x"),
               until=1 + SLEEP_S + 10)
    assert fsm.state == IDLE
    assert fsm.advance(500 + SLEEP_S) == SLEEPING


def test_failure_flashes_error_then_idle():
    fsm = play(ev(1, "user.prompt"), ev(9, "agent.failed", error="rate_limit"), until=20)
    assert states(fsm)[-2:] == [ERROR, IDLE]


def test_sleep_and_wake():
    fsm = play(ev(1, "session.start", how="startup"), until=1 + SLEEP_S)
    assert fsm.state == SLEEPING
    fsm.feed(ev(2000, "user.prompt"))
    assert fsm.state == LISTENING


def test_gone_until_new_session():
    fsm = play(ev(1, "session.end", reason="clear"), ev(2, "user.prompt"))
    assert fsm.state == GONE
    fsm.feed(ev(3, "session.start", how="clear"))
    assert fsm.state == IDLE


def test_compact_start_keeps_round():
    fsm = play(ev(1, "user.prompt"), ev(5, "tool.start", tool="Bash", id="a"),
               ev(6, "session.start", how="compact"))
    assert fsm.state == WORKING and fsm.in_round


def test_timed_transition_is_logged_at_due_time():
    fsm = play(ev(1, "user.prompt"), until=100)
    assert fsm.log[-1][0] == 1.6 and fsm.log[-1][2] == THINKING
