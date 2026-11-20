"""PolicyEngine: AUTO / ASK / VERIFY per task. Hard rules override model scores."""
import yaml
from pathlib import Path
from .contracts import Task, Decision, TaskStatus, Value

RULES_PATH = Path(__file__).parent / "policy_rules.yaml"


def load_rules(path: Path = RULES_PATH) -> dict:
    return yaml.safe_load(path.read_text())


class PolicyEngine:
    def __init__(self, rules: dict | None = None):
        self.rules = rules or load_rules()

    def reload(self):
        self.rules = load_rules()

    def decide(self, t: Task) -> Task:
        r = self.rules
        flags = set(t.flags)
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
