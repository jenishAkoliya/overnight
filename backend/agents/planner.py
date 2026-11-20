"""PlannerAgent: tomorrow's time-blocked plan. Claude when key present (Phase 3); deterministic fallback now."""
from datetime import datetime, time, timedelta, date
from ..bus import bus
from ..config import TZ, tomorrow
from ..contracts import Plan, PlanBlock, SourceItem, Task, TaskStatus
from ..integrations.llm import get_llm
from .memory import memory

DAY_START, DAY_END = time(9, 30), time(18, 0)
LUNCH = (time(12, 0), time(13, 0))


class PlannerAgent:
    def build(self, items: list[SourceItem], tasks: list[Task], day=None) -> Plan:
        d = day or tomorrow()
        ctx = memory.context_for(d)
        blocks: list[PlanBlock] = []
        for it in items:
            if it.type == "event" and it.timestamp.astimezone(TZ).date() == d:
                end = datetime.fromisoformat(it.metadata["end"]).astimezone(TZ)
                st = it.timestamp.astimezone(TZ)
                note = it.metadata.get("tz_note", "")
                if note:
                    note += f" -> shown in {TZ.key}"
                blocks.append(PlanBlock(start=st, end=end, title=it.subject, kind="event", note=note))
        blocks.sort(key=lambda b: b.start)
        busy = [(b.start, b.end) for b in blocks] + [(datetime.combine(d, LUNCH[0], TZ), datetime.combine(d, LUNCH[1], TZ))]
        busy_sorted = sorted(busy)
        work = [t for t in tasks if t.action_type == "work" and t.due is None or (t.action_type == "work" and t.due and (t.due - d).days <= 3)]
        morning = memory.prefers("morning")
        work.sort(key=lambda t: (not t.user_added, t.due or date.max, -t.est_minutes))
        cursor = datetime.combine(d, DAY_START, TZ)
        end_of_day = datetime.combine(d, DAY_END, TZ)
        scheduled = set()
        for t in work:
            dur = timedelta(minutes=max(t.est_minutes, 15))
            slot = self._find_slot(cursor, end_of_day, dur, busy_sorted, morning_only=morning and t.user_added)
            if not slot:
                continue
            if t.user_added:
                note = "You asked for this" + ("; you prefer mornings" if morning and slot[0].hour < 12 else "")
            else:
                note = "Placed in the morning: you prefer mornings (memory)" if (morning and slot[0].hour < 12) else ""
            if t.due:
                note = (note + f" Due {t.due:%a %b %d}").strip()
            blocks.append(PlanBlock(start=slot[0], end=slot[1], title=t.title, kind="task", task_id=t.id, note=note))
            busy_sorted = sorted(busy_sorted + [slot])
            scheduled.add(t.id)
        blocks.sort(key=lambda b: b.start)
        self._llm = get_llm().complete("plan", json_mode=True)  # mock: None -> deterministic
        planner = "deterministic" if self._llm is None else "claude"
        bus.emit("PlannerAgent", "plan", f"Built plan for {d:%a %b %d}: {len(blocks)} blocks ({planner})", why="prefs: " + "; ".join(ctx["preferences"][:2]))
        return Plan(date=d, tz=TZ.key, blocks=blocks, tasks=tasks, planner=planner,
                    summary=f"{sum(1 for b in blocks if b.kind == 'event')} meetings, {len(scheduled)} focus tasks scheduled")

    @staticmethod
    def _find_slot(start, end, dur, busy, morning_only=False):
        cur = start
        for bs, be in busy + [(end, end)]:
            if bs > cur and bs - cur >= dur:
                slot = (cur, cur + dur)
                if not morning_only or slot[0].hour < 12:
                    return slot
            cur = max(cur, be)
        if end - cur >= dur and (not morning_only or cur.hour < 12):
            return (cur, cur + dur)
        return None


planner_agent = PlannerAgent()
