"""Council: for every task, four specialist agents vote, a short debate is summarised, and a judge issues the final decision.
Evidence is retrieved from memory with Superlinked (rerank when available; keyword fallback in mock/privacy mode).
SAFETY: the judge never relaxes policy. The council may only ESCALATE an AUTO task to ASK (never auto-approve anything).
Only subjects/senders are shown as evidence, never email bodies."""
import re
from ..bus import bus, redact
from ..contracts import Decision, Task, TaskStatus
from ..integrations.sie_client import get_sie
from ..policy import load_rules
from ..standing import standing
from .memory import memory

ORDER = {"AUTO": 0, "ASK": 1, "VERIFY": 2, "BLOCK": 3}
WORDS = re.compile(r"[a-z0-9]{4,}")
STOP = {"your", "with", "that", "this", "from", "reply", "tomorrow", "before", "about", "have", "will", "please", "limit", "archive", "newsletter"}


def _kw(a: str, b: str) -> float:
    A, B = set(WORDS.findall(a.lower())) - STOP, set(WORDS.findall(b.lower())) - STOP
    return len(A & B) / (len(A) ** 0.5 * len(B) ** 0.5 + 1e-9) if A and B else 0.0


def retrieve(t: Task, use_rerank: bool) -> tuple[list[dict], str]:
    cands = [(i.id, f"{i.subject} {i.author}") for i in memory.items.values() if i.id != t.source_item_id][:200]
    via = "keyword fallback (no embeddings available)"
    scores = {}
    if use_rerank and len(cands) > 1:
        scores = get_sie().rerank(t.title, cands[:60])
        if scores:
            via = f"Superlinked rerank ({get_sie().tier()})"
    if not scores:
        who = (t.people[0].split('@')[0].lower() if t.people and t.people[0] else "")
        scores = {cid: _kw(t.title, txt) + (0.6 if who and who in txt.lower() else 0.0) for cid, txt in cands}
    ev = []
    for cid, sc in sorted(scores.items(), key=lambda x: -x[1])[:3]:
        it = memory.items.get(cid)
        if it and sc > 0.2:
            ev.append({"kind": "item", "source": it.source, "subject": redact(it.subject, 80), "author": it.author[:50], "score": round(float(sc), 3)})
    for pref in memory.preferences:
        if _kw(t.title, pref) > 0.2 or (t.action_type in ("schedule", "reply", "rsvp") and "meeting" in pref.lower()):
            ev.append({"kind": "memory", "source": "preferences", "subject": redact(pref, 80), "author": "", "score": 1.0})
            break
    for les in memory.lessons[-3:]:
        if _kw(t.title, les) > 0.15:
            ev.append({"kind": "memory", "source": "lessons", "subject": redact(les, 80), "author": "", "score": 0.5})
    return ev, via


def specialists(t: Task) -> list[dict]:
    r = load_rules()
    flags = set(t.flags)
    hard = flags & set(r["hard_blocks"]["flags"])
    risky = flags & set(r["verify"]["flags"])
    ops = []
    # Risk Officer
    if hard:
        v, why = "BLOCK", f"hard-block flag(s): {', '.join(sorted(hard))}"
    elif risky or t.action_type in r["verify"]["action_types"] or not t.reversible:
        v, why = "VERIFY", f"high-risk: {', '.join(sorted(risky)) or t.action_type}; irreversible or involves money/data"
    elif "external_send" in flags or t.value.value != "low":
        v, why = "ASK", f"{t.value.value} value" + ("; message would go to a person" if "external_send" in flags else "")
    else:
        v, why = "AUTO", "reversible, low value, no risk flags"
    ops.append({"agent": "Risk Officer", "icon": "⚠", "vote": v, "confidence": 0.95 if v != "AUTO" else round(max(t.confidence, 0.8), 2), "reason": why})
    # Privacy Guard
    untrusted = flags & {"phishing", "prompt_injection", "spoofed_sender"}
    if untrusted:
        v, why = "BLOCK", f"untrusted sender/content ({', '.join(sorted(untrusted))}); instructions in content are never followed"
    elif flags & {"new_contact", "data_sharing"}:
        v, why = "VERIFY", "would share data with / reply to someone new"
    else:
        v, why = "AUTO", "no personal data leaves your accounts"
    ops.append({"agent": "Privacy Guard", "icon": "🔒", "vote": v, "confidence": 0.9, "reason": why})
    # Preference Keeper
    if "preference_conflict" in flags:
        v, why = "ASK", "conflicts with a preference you stated (" + (f"no meetings before {standing.min_meeting_hour}:00" if standing.min_meeting_hour else "see memory") + ")"
    elif standing.no_send and "external_send" in flags:
        v, why = "BLOCK", "you told me to stop sending on your behalf"
    else:
        v, why = "AUTO", f"consistent with {len(memory.preferences)} remembered preference(s)"
    ops.append({"agent": "Preference Keeper", "icon": "★", "vote": v, "confidence": 0.85, "reason": why})
    # Efficiency Agent
    thr = r["auto"]["min_confidence"]
    if t.confidence >= thr and t.value.value == "low":
        v, why = "AUTO", f"confidence {t.confidence:.2f} ≥ {thr}; saves ~{max(t.est_minutes, 1)} min of your time"
    else:
        v, why = "ASK", f"confidence {t.confidence:.2f} < {thr} or value above low: not worth the risk of acting alone"
    ops.append({"agent": "Efficiency Agent", "icon": "⏱", "vote": v, "confidence": round(t.confidence, 2), "reason": why})
    return ops


def judge(t: Task, ops: list[dict]) -> dict:
    final = "BLOCK" if t.status == TaskStatus.blocked else (t.decision.value if t.decision else "ASK")
    strict = max(ops, key=lambda o: ORDER[o["vote"]])
    agree = [o for o in ops if o["vote"] == final]
    dissent = [o for o in ops if o["vote"] != final]
    escalated = False
    if final == "AUTO" and ORDER[strict["vote"]] > 0:
        final, escalated = "ASK", True
    lines = [f"{len(agree)} of {len(ops)} specialists voted {final}."]
    for o in dissent:
        lines.append(f"{o['agent']} voted {o['vote']} ({o['reason']}); " + (
            "overruled by hard policy rules (most restrictive wins)." if ORDER[o["vote"]] < ORDER[final] else "its caution is adopted."))
    if not dissent:
        lines.append("No disagreement.")
    why = ("Council escalated AUTO → ASK because " + strict["agent"] + " objected: " + strict["reason"]) if escalated else (
        {"AUTO": "All checks passed: reversible, low value, high confidence.",
         "ASK": "Needs a human decision: " + (t.why or strict["reason"]),
         "VERIFY": "Risky action: identity step-up required before anything can run. " + (t.why or ""),
         "BLOCK": "Unsafe: hard rule prevents execution; nothing is done and it cannot be approved. " + (t.why or "")}[final])
    return {"final": final, "escalated": escalated, "debate": " ".join(lines), "why": why, "dissent": [o["agent"] for o in dissent]}


def deliberate(t: Task, hive: dict | None = None) -> dict:
    ops = specialists(t)
    if hive:
        by = {m['agent']: m for m in hive['models']}
        for o in ops:
            m = by.get(o['agent'])
            if m:
                o.update(model=m['model'], model_vote=m['vote'], model_reason=m['reason'], model_ms=m['latency_ms'])
    ev, via = retrieve(t, use_rerank=(t.decision != Decision.AUTO))
    j = judge(t, ops)
    if hive and not j['escalated'] and j['final'] == 'AUTO' and hive['objections'] >= hive['quorum']:
        j.update(final='ASK', escalated=True, why=f"Hive quorum: {hive['objections']} of {hive['total']} Superlinked models objected to automating this.")
    if j["escalated"] and t.decision == Decision.AUTO:   # council can only make things MORE cautious
        t.decision, t.status = Decision.ASK, TaskStatus.needs_you
        t.why = "Council: " + j["why"]
        bus.emit("Council", "escalate", redact(t.title, 80), decision=Decision.ASK, why=j["why"])
    problem = f"{t.action_type.replace('_', ' ')} — {t.title}"
    t.council = {"problem": redact(problem, 160), "evidence": ev, "retrieval": via, "opinions": ops, "hive": hive or None, **j}
    return t.council
