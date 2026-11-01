# Automat činnosti hlavní postavičky (kapitola 3.1 konceptu).
#
# Je deterministický: čas bere jen z událostí a z advance(now), takže jde
# přehrávat nahrávky libovolnou rychlostí. Časovaný přechod se zapíše s časem,
# kdy měl nastat, ne kdy se na něj přišlo.

IDLE, LISTENING, THINKING, WORKING = "idle", "listening", "thinking", "working"
WAITING, ERROR, SUCCESS, SLEEPING, GONE = "waiting", "error", "success", "sleeping", "gone"

LISTEN_S = 0.6     # Listening → dál
FLASH_S = 1.5      # délka jednorázových stavů Error a Success
LINGER_S = 2.0     # Working vydrží po posledním nástroji (jen 9 % mezer je kratších)
SLEEP_S = 600.0    # Idle → Sleeping bez událostí


class ActivityFSM:
    def __init__(self, now=0.0, sleep_s=SLEEP_S):
        self.sleep_s = sleep_s  # [postavicka] usnuti_s v configu
        self.state, self.since = IDLE, now
        self.last_event = now
        self.tools = {}         # tool_use_id → nástroj, otevřené v tomto kole
        self.stale = set()      # otevřené přes nový prompt: doběhnou, nebo bylo přerušení
        self.tool_end = now     # kdy skončil poslední nástroj
        self.in_round = False
        self.round_errors = 0
        self.waiting = None     # "permission" / "question"
        self.background = 0     # úlohy na pozadí hlášené při agent.done
        self.subagents = set()
        self.log = []           # (ts, ze stavu, do stavu, příčina)

    def snapshot(self):
        return {"state": self.state, "since": self.since, "tools": len(self.tools),
                "waiting": self.waiting, "subagents": len(self.subagents),
                "background": self.background, "round_errors": self.round_errors}

    def _go(self, ts, new, cause):
        if new != self.state:
            self.log.append((ts, self.state, new, cause))
            self.state, self.since = new, ts

    def _busy(self):
        """Kam po Listening nebo jednorázovém stavu."""
        if self.tools:
            return WORKING
        return THINKING if self.in_round else IDLE

    def _due(self):
        """Příští časovaný přechod jako (čas, stav), nebo None."""
        s = self.state
        if s == LISTENING:
            return self.since + LISTEN_S, self._busy()
        if s == ERROR:
            return self.since + FLASH_S, self._busy()
        if s == SUCCESS:
            return self.since + FLASH_S, IDLE
        if s == WORKING and not self.tools:
            return max(self.since, self.tool_end) + LINGER_S, self._busy()
        if s == IDLE:
            return self.last_event + self.sleep_s, SLEEPING
        return None

    def advance(self, now):
        while (due := self._due()) and due[0] <= now and due[1] != self.state:
            self._go(due[0], due[1], "timer")
        return self.state

    def _end_round(self):
        self.in_round = False
        self.tools.clear()
        self.stale.clear()
        self.waiting = None

    def _start_round(self):
        if not self.in_round:
            self.in_round, self.round_errors = True, 0

    def feed(self, ev):
        ts, kind, data = ev["ts"], ev["kind"], ev["data"]
        self.advance(ts)
        self.last_event = ts
        cause = f"{kind}:{data['tool']}" if data.get("tool") else kind

        if kind == "session.start":
            if data.get("how") != "compact":
                self._end_round()
                self._go(ts, IDLE, cause)
            return self.state
        if self.state == GONE:
            return self.state
        if kind == "session.end":
            self._end_round()
            self._go(ts, GONE, cause)
        elif kind == "subagent.start":
            self.subagents.add(data.get("agent"))
        elif kind == "subagent.done":
            self.subagents.discard(data.get("agent"))
        elif data.get("agent"):
            pass    # nástroje a chyby subagentů jsou jen známka aktivity
        elif kind == "user.prompt":
            # prompt může přijít i do běžícího kola (fronta); otevřeným nástrojům
            # už nevěříme, protože mohlo jít o přerušení
            self.stale.update(self.tools)
            self.tools.clear()
            self.waiting = None
            self._start_round()
            self._go(ts, LISTENING, cause)
        elif kind == "tool.start":
            self.stale.clear()
            self.tools[data.get("id")] = data.get("tool")
            self._start_round()
            if self.state == WAITING and data.get("schvaleno"):
                self.waiting = None     # Gemini: nástroj startuje až po schválení
                self._go(ts, WORKING, cause)
            elif self.state not in (LISTENING, ERROR, WAITING):
                self._go(ts, WORKING, cause)
        elif kind in ("tool.end", "tool.denied", "tool.error"):
            self.tools.pop(data.get("id"), None)
            self.stale.discard(data.get("id"))
            self.tool_end = ts
            if kind == "tool.error":
                self.round_errors += 1
                self.waiting = None
                self._go(ts, ERROR, cause)
            elif self.state == WAITING:
                self.waiting = None
                self._go(ts, self._busy(), cause)
        elif kind == "agent.waiting":
            self.waiting = data.get("why")
            self._go(ts, WAITING, cause)
        elif kind == "agent.done":
            self.background = data.get("background", 0)
            self._end_round()
            self._go(ts, SUCCESS if not self.round_errors else IDLE, cause)
        elif kind == "agent.failed":
            self._end_round()
            self._go(ts, ERROR, cause)
        elif kind == "agent.interrupted":
            self._end_round()
            self._go(ts, IDLE, cause)
        return self.state
