# Přehrávač nahrávek z fáze 0: hook → adaptér → automat, bez čekání.
#
#   python -m familiar.replay                  souhrn všech nahrávek
#   python -m familiar.replay 2b7684e5 -t      časová osa jedné session
#
# Texty promptů nevypisuje, nahrávky leží mimo repozitář (viz emit.py).
import argparse, collections, glob, json, os, sys

from familiar.adapters.claude_code import translate
from familiar.fsm import ActivityFSM, ERROR, GONE, IDLE, SUCCESS, SLEEPING, THINKING, WAITING, WORKING

REPLAYS = os.environ.get("FAMILIAR_REPLAYS") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    "familiar", "replays",
)
FLICKER_S = 1.0     # kratší pobyt v trvalém stavu = bliknutí
STUCK_S = 600.0     # Thinking/Working/Waiting déle = podezřelé


def events(path):
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            procs = rec.get("procs") or []
            pid = procs[0][0] if procs and procs[0][1] == "claude" else None
            yield from translate(rec["raw"], rec["ts"], pid)


def run(path):
    """Přehraje jednu nahrávku; vrací (automat, počty druhů, čas začátku, konce)."""
    fsm, kinds, t0, t1 = None, collections.Counter(), None, None
    for ev in events(path):
        if fsm is None:
            fsm, t0 = ActivityFSM(ev["ts"]), ev["ts"]
        fsm.feed(ev)
        kinds[ev["kind"]] += 1
        t1 = ev["ts"]
    if fsm is not None:
        fsm.advance(t1)
    return fsm, kinds, t0, t1


def stays(fsm, t0, t1):
    """Pobyty ve stavech: [(stav, začátek, délka)]."""
    out, state, since = [], IDLE, t0
    for ts, _, new, _ in fsm.log:
        out.append((state, since, ts - since))
        state, since = new, ts
    out.append((state, since, max(0.0, t1 - since)))
    return out


def fmt(s):
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def timeline(path):
    fsm, kinds, t0, t1 = run(path)
    if fsm is None:
        print("prázdná nahrávka")
        return
    for ts, old, new, cause in fsm.log:
        print(f"+{fmt(ts - t0):>8}  {old:>9} → {new:<9}  {cause}")
    print(f"délka {fmt(t1 - t0)}, události {dict(kinds)}")


def summary(paths):
    total = collections.Counter()
    kinds = collections.Counter()
    flicker = collections.Counter()
    entered = collections.Counter()
    waits = []
    stuck = []
    transitions = sessions = 0
    for path in paths:
        fsm, k, t0, t1 = run(path)
        if fsm is None:
            continue
        sessions += 1
        kinds += k
        transitions += len(fsm.log)
        entered.update(new for _, _, new, _ in fsm.log)
        name = os.path.basename(path)[:8]
        for state, since, dur in stays(fsm, t0, t1):
            total[state] += dur
            if state in (THINKING, WORKING, IDLE) and dur < FLICKER_S and since > t0:
                flicker[state] += 1
            if state == WAITING:
                waits.append(dur)
            if state in (THINKING, WORKING, WAITING) and dur > STUCK_S:
                stuck.append((dur, name, state, fmt(since - t0)))

    awake = sum(v for s, v in total.items() if s not in (SLEEPING, GONE))
    print(f"session {sessions}, přechodů {transitions}, bdělý čas {fmt(awake)}")
    print("\nčas ve stavech (mimo sleeping/gone):")
    for state, dur in total.most_common():
        if state not in (SLEEPING, GONE):
            print(f"  {state:<10} {fmt(dur):>9}  {100 * dur / awake:5.1f} %")
    print(f"\njednorázové stavy: error {entered[ERROR]}×, success {entered[SUCCESS]}×")
    print(f"bliknutí (< {FLICKER_S:.0f} s): {dict(flicker) or 'žádné'}")
    if waits:
        waits.sort()
        print(f"waiting: {len(waits)}×, medián {waits[len(waits) // 2]:.0f} s, max {fmt(waits[-1])}")
    print(f"\nnejdelší pobyty nad {fmt(STUCK_S)} v Thinking/Working/Waiting ({len(stuck)}):")
    for dur, name, state, at in sorted(stuck, reverse=True)[:10]:
        print(f"  {name}  {state:<9} {fmt(dur):>8}  od +{at}")
    print(f"\nudálosti: {dict(kinds.most_common())}")


def add_args(ap):
    ap.add_argument("sessions", nargs="*", help="začátky jmen nahrávek (výchozí: všechny)")
    ap.add_argument("-t", "--timeline", action="store_true", help="vypsat přechody jedné session")


def main(argv=None):
    ap = argparse.ArgumentParser(description="přehrávač nahrávek familiara")
    add_args(ap)
    report(ap.parse_args(argv))


def report(args):
    paths = sorted(glob.glob(os.path.join(REPLAYS, "*.jsonl")))
    if args.sessions:
        paths = [p for p in paths if any(os.path.basename(p).startswith(s) for s in args.sessions)]
    if not paths:
        sys.exit(f"žádné nahrávky v {REPLAYS}")
    if args.timeline:
        for p in paths:
            print(f"== {os.path.basename(p)}")
            timeline(p)
    else:
        summary(paths)


if __name__ == "__main__":
    main()
