"""In-process event bus. Agents emit AgentEvent; SSE endpoint tails the history."""
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from .contracts import AgentEvent


class EventBus:
    def __init__(self):
        self.events: list[AgentEvent] = []
        self.lock = threading.Lock()
        self.run_id = ""

    def emit(self, agent: str, step: str, summary: str, decision=None, why: str = "",
             latency_ms: int = 0, cost: float = 0.0) -> AgentEvent:
        with self.lock:
            ev = AgentEvent(seq=len(self.events) + 1, ts=datetime.now(timezone.utc), run_id=self.run_id,
                            agent=agent, step=step, summary=summary,
                            decision=getattr(decision, "value", decision), why=why,
                            latency_ms=latency_ms, cost_estimate=round(cost, 6))
            self.events.append(ev)
        return ev

    @contextmanager
    def timed(self, agent: str, step: str, summary: str, **kw):
        t = time.perf_counter()
        yield
        self.emit(agent, step, summary, latency_ms=int((time.perf_counter() - t) * 1000), **kw)

    def since(self, seq: int) -> list[AgentEvent]:
        with self.lock:
            return self.events[seq:]

    def reset(self):
        with self.lock:
            self.events.clear()


bus = EventBus()
