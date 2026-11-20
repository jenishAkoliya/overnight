"""PolicyEngine: AUTO / ASK / VERIFY per task. Hard rules override model scores.
Rules are read from policy_rules.yaml on every decision (patchable by the SRE agent)."""
from . import runtime
from .contracts import Task, Decision, TaskStatus, Value


def load_rules() -> dict:
    return runtime.load("policy_rules.yaml")


class PolicyEngine:
    @property
    def rules(self) -> dict:
        return load_rules()

    def reload(self):
        pass

    def decide(self, t: Task) -> Task:
        r = self.rules
        flags = set(t.flags)
        # 0. tasks the user typed themselves
        if t.user_added:
            t.decision, t.status = Decision.ASK, TaskStatus.needs_you
            t.why = "You asked for this"
            return t
        # 1. hard blocks
        hb = flags & set(r["hard_blocks"]["flags"])
        if hb:
            t.decision, t.status = Decision.ASK, TaskStatus.blocked
            t.why = f"BLOCKED ({', '.join(sorted(hb))}): hard rule, no action taken; shown for your review"
            return t
        # 2. VERIFY: money / irreversible / new contact / delete / data sharing
        vf = flags & set(r["verify"]["flags"])
        if vf or t.action_type in r["verify"]["action_types"] or not t.reversible:
            why = ", ".join(sorted(vf)) or ("irreversible" if not t.reversible else t.action_type)
            t.decision, t.status = Decision.VERIFY, TaskStatus.needs_you
            t.why = f"Needs identity step-up ({why}); hard rule overrides score {t.confidence:.2f}"
            return t
        # 2b. ASK flags (e.g. preference conflicts) always need the user
        af = flags & set(r["ask"].get("flags", []))
        if af:
            t.decision, t.status = Decision.ASK, TaskStatus.needs_you
            t.why = f"Ask: {', '.join(sorted(af))} - conflicts with something you told me"
            return t
        # 3. AUTO: reversible, confident, low value, allowed type, no external send
        a = r["auto"]
        ext = "external_send" in flags
        if (t.action_type in a["action_types"] and t.confidence >= a["min_confidence"]
                and t.value.value in a["allowed_value"] and t.reversible and not ext):
            t.decision, t.status = Decision.AUTO, TaskStatus.planned
            t.why = f"Reversible, {t.action_type}, low value, confidence {t.confidence:.2f} >= {a['min_confidence']}"
            return t
        # 4. ASK
        reasons = []
        if t.confidence < a["min_confidence"]:
            reasons.append(f"confidence {t.confidence:.2f} < {a['min_confidence']}")
        if t.value != Value.low:
            reasons.append(f"{t.value.value} value")
        if ext:
            reasons.append("sends to a contact")
        if t.action_type in r["ask"]["action_types"]:
            reasons.append(f"{t.action_type} needs your judgment")
        t.decision, t.status = Decision.ASK, TaskStatus.needs_you
        t.why = "Ask: " + ("; ".join(reasons) or "not covered by an auto rule")
        return t
