from familiar.mood import HOLD_S, MoodEngine, norm, own_words, sharp


def ev(ts, kind, **data):
    return {"ts": ts, "kind": kind, "data": data}


def settle(m, ts):
    m.advance(ts)
    return m.advance(ts + HOLD_S)[0]


def test_norm_strips_diacritics():
    assert norm("Děkuji, PARÁDA") == "dekuji, parada"


def test_own_words_skip_agents_images_and_paths():
    assert own_words("<agent-message from=x>díky</agent-message>") == ""
    assert own_words("[Image #3] koukni /home/x/a.png") == "koukni"


def test_sharp_needs_real_shouting():
    assert sharp("NEBO NESEDI S PCB")
    assert sharp("zatím nic nemaž!!")
    assert not sharp("oprav README a CLAUDE.md prosím")


def test_thanks_makes_joy_and_heart():
    m = MoodEngine(0)
    assert m.feed(ev(1, "user.prompt", text="super, díky")) == ["heart"]
    assert settle(m, 1) == "radost"


def test_thanks_in_pasted_email_is_ignored():
    m = MoodEngine(0)
    text = "tohle mi přišlo, odpověz: " + "x" * 200 + " Děkuji za odpověď"
    assert m.feed(ev(1, "user.prompt", text=text)) == []


def test_image_prompt_shows_camera():
    assert MoodEngine(0).feed(ev(1, "user.prompt", text="[Image #1] tady")) == ["camera"]


def test_error_streak_frustrates():
    m = MoodEngine(0)
    for k in range(3):
        m.feed(ev(1 + k, "tool.error", code=1))
    assert settle(m, 4) == "frustrace"


def test_two_corrections_confuse():
    m = MoodEngine(0)
    m.feed(ev(1, "user.prompt", text="ne, to jsem nemyslel"))
    m.feed(ev(30, "user.prompt", text="zase špatně, nesedí to"))
    assert settle(m, 31) == "zmatek"


def test_questions_make_curious():
    m = MoodEngine(0)
    m.feed(ev(1, "user.prompt", text="jak funguje ten automat?"))
    m.feed(ev(20, "user.prompt", text="a proč je tam hystereze?"))
    assert settle(m, 21) == "zvedavost"


def test_passing_tests_cheer():
    m = MoodEngine(0)
    assert m.feed(ev(1, "tool.end", tool="Bash", cmd="python3 -m pytest -q tests")) == ["check"]
    assert m.feed(ev(2, "tool.end", tool="Bash", cmd="ls")) == []


def test_clean_round_in_joy_blooms_flower():
    m = MoodEngine(0)
    assert m.feed(ev(1, "agent.done")) == []                # bez radosti nic
    m.feed(ev(2, "user.prompt", text="super, díky"))
    assert settle(m, 2) == "radost"
    assert m.feed(ev(8, "agent.done")) == ["flower"]
    m.feed(ev(9, "tool.error", code=1))
    assert m.feed(ev(10, "agent.done")) == []               # kolo končí chybou
    m.feed(ev(11, "agent.done", agent="a1"))
    assert m.feed(ev(12, "agent.done", agent="a1")) == []   # subagent ne


def test_rate_limit_coffee():
    assert MoodEngine(0).feed(ev(1, "agent.failed", error="rate_limit")) == ["coffee"]


def test_long_active_session_tires_but_rest_helps():
    m = MoodEngine(0)
    t = 0
    for _ in range(45):
        t += 60
        m.feed(ev(t, "user.prompt", text="pokračuj"))
        m.feed(ev(t + 30, "agent.done"))
    assert settle(m, t + 31) == "unava"
    m.feed(ev(t + 3600, "user.prompt", text="jdeme dál"))
    assert m.fatigue < 0.1


def test_subagent_errors_do_not_count():
    m = MoodEngine(0)
    for k in range(3):
        m.feed(ev(1 + k, "tool.error", agent="a1"))
    assert settle(m, 4) == "klid"


def test_mood_fades_back_to_calm():
    m = MoodEngine(0)
    m.feed(ev(1, "user.prompt", text="díky moc"))
    assert settle(m, 1) == "radost"
    assert settle(m, 600) == "klid"


def test_nalada_zvolena_v_panelu_plati_hned_a_pak_vyprsi():
    m = MoodEngine(0.0)
    m.take("frustrace", 10.0)
    assert m.advance(10.5) == ("frustrace", True)       # přechod palety se přehraje jednou
    assert m.advance(11.0) == ("frustrace", False)
    assert m.advance(10.0 + m.c["rucne_s"] - 1)[0] == "frustrace"
    end = 10.0 + m.c["rucne_s"]
    m.advance(end)
    assert m.advance(end + HOLD_S + 1) == ("klid", True)   # pak zase rozhodují čísla


def test_nalada_z_panelu_s_nulou_jen_zapise():
    m = MoodEngine(0.0)
    m.c = {**m.c, "rucne_s": 0}
    m.take("radost", 1.0)
    assert m.advance(2.0) == ("klid", False)
