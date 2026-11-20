"""MemoryAgent: Cognee life graph (mock: local store). Also holds user tasks, preferences, lessons, feedback."""
import re
from datetime import date
from ..bus import bus
from ..contracts import SourceItem
from ..integrations.cognee_client import get_cognee
from ..integrations.airbyte_client import load_seed


class MemoryAgent:
    def __init__(self):
        self.reset()

    def reset(self):
        self.cog = get_cognee()
        self.cog.reset()
        seed = load_seed()
        self.preferences: list[str] = list(seed["preferences"])
        self.known_contacts: set[str] = set(seed["known_contacts"])
        self.user_tasks: list[dict] = []
        self.lessons: list[str] = []
        self.feedback: list[dict] = []
        self.people: dict[str, dict] = {}
        self.items: dict[str, SourceItem] = {}

    # ---- ingest ----
    def ingest(self, items: list[SourceItem]):
        for it in items:
            self.items[it.id] = it
            hdr = f"From: {it.author}\nTo: {', '.join(it.participants)}\nDate: {it.timestamp.isoformat()}\nSubject: {it.subject}\n\n{it.body}"
            self.cog.remember(hdr, dataset=it.source, node_set=[it.source], meta={"id": it.id})
            for p in {it.author, *it.participants}:
                if p and "@" in p or p:
                    self.people.setdefault(p, {"name": p, "n": 0})["n"] += 1
        bus.emit("MemoryAgent", "ingest", f"Remembered {len(items)} items into the life graph (Cognee)")

    def remember_user_task(self, text: str) -> dict:
        t = {"id": f"ut-{len(self.user_tasks) + 1}", "text": text}
        self.user_tasks.append(t)
        self.cog.remember(text, dataset="user_memory", node_set=["user_tasks"])
        if re.search(r"prefer\w*\s+(the\s+)?(mornings?|afternoons?|evenings?)", text, re.I):
            m = re.search(r"prefer\w*\s+(the\s+)?(mornings?|afternoons?|evenings?)", text, re.I).group(0)
            self.preferences.append(f"Maya {m}")
            self.cog.remember(f"Preference: {m}", dataset="user_memory", node_set=["preferences"])
            bus.emit("MemoryAgent", "preference", f"Learned preference: {m}")
        bus.emit("MemoryAgent", "user_task", f"Stored user task: {text}")
        return t

    def record_feedback(self, task_id: str, accepted: bool, reason: str = "", action_type: str = "", author: str = ""):
        self.feedback.append({"task_id": task_id, "accepted": accepted, "reason": reason, "action_type": action_type, "author": author})
        score = 5 if accepted else 1
        self.cog.remember(f"Feedback on {action_type} from {author}: score {score}. {reason}", dataset="user_memory", node_set=["feedback"])
        bus.emit("MemoryAgent", "feedback", f"Recorded {'approval' if accepted else 'rejection'} ({action_type})", why=reason)

    def record_lesson(self, text: str):
        self.lessons.append(text)
        self.cog.remember(f"Lesson: {text}", dataset="user_memory", node_set=["lessons"])
        bus.emit("MemoryAgent", "lesson", f"Lesson stored: {text}")

    def rejections(self, action_type: str, author: str) -> int:
        return sum(1 for f in self.feedback if not f["accepted"] and f["action_type"] == action_type and f["author"] == author)

    def prefers(self, word: str) -> bool:
        return any(word in p.lower() for p in self.preferences)

    def context_for(self, d: date) -> dict:
        return {"date": d.isoformat(), "preferences": self.preferences, "user_tasks": self.user_tasks,
                "lessons": self.lessons, "n_docs": len(self.cog.docs)}

    def recall(self, query: str) -> list[dict]:
        return self.cog.recall(query)

    # ---- graph for the UI ----
    def graph(self) -> dict:
        nodes, edges, seen = [], [], set()

        def node(i, label, kind):
            if i not in seen:
                seen.add(i); nodes.append({"id": i, "label": label, "kind": kind})
        node("maya", "Maya Chen", "person")
        for p, info in sorted(self.people.items(), key=lambda x: -x[1]["n"])[:14]:
            if "maya" in p.lower():
                continue
            node(f"p:{p}", p.split("@")[0], "person"); edges.append({"from": "maya", "to": f"p:{p}", "label": f"{info['n']} items"})
        for it in self.items.values():
            if it.type == "event":
                node(it.id, it.subject, "event"); edges.append({"from": "maya", "to": it.id, "label": "attends"})
        for s in self.preferences:
            node(f"pref:{s}", s, "preference"); edges.append({"from": "maya", "to": f"pref:{s}", "label": "prefers"})
        for t in self.user_tasks:
            node(t["id"], t["text"], "task"); edges.append({"from": "maya", "to": t["id"], "label": "asked"})
        for i, s in enumerate(self.lessons):
            node(f"les:{i}", s[:60], "lesson"); edges.append({"from": "maya", "to": f"les:{i}", "label": "learned"})
        return {"nodes": nodes, "edges": edges, "docs": len(self.cog.docs)}


memory = MemoryAgent()
