"""Advisor: turns user facts (backend/user_profile.yaml) into a concrete suggestion for each task.
Rules always run; the Superlinked swarm may rephrase/extend when hosted models are allowed for the item.
Suggestions never trigger actions; they only inform the user and the council."""
import re
from pathlib import Path
import yaml
from ..contracts import Task

PROFILE_PATH = Path(__file__).resolve().parent.parent / "user_profile.yaml"


def profile() -> dict:
    try:
        return yaml.safe_load(PROFILE_PATH.read_text()) or {}
    except Exception:
        return {}


def facts_text(p: dict | None = None) -> str:
    p = p or profile()
    bits = [p.get("role", ""), "no car" if p.get("has_car") is False else "", f"lives in {p['city']}" if p.get("city") else "",
            ("gets around by " + ", ".join(p.get("transport", []))) if p.get("transport") else ""]
    return "; ".join(b for b in bits if b)


def rule_suggestion(t: Task, p: dict | None = None) -> tuple[str, list[str]]:
    """Returns (suggestion, extra_flags)."""
    p = p or profile()
    text = f"{t.title} {(t.item or {}).get('subject', '')}".lower()
    flags = []
    if set(t.flags) & {"phishing", "prompt_injection", "spoofed_sender"}:
        return ("Don't reply, click links or share anything — this message is blocked as unsafe.", flags)
    if p.get("has_car") is False and re.search(r"\b(car|auto|vehicle)\b.{0,30}(insurance|renew|registration|parking)|(insurance|renew\w*).{0,30}\b(car|auto)\b", text):
        flags.append("profile_mismatch")
        return ("You told me you don't own a car — this renewal probably isn't yours. Don't pay; check whether it's an old policy to cancel or a scam.", flags)
    if p.get("role") == "student" and t.action_type in ("file_receipt", "label") or (p.get("role") == "student" and re.search(r"subscription|bookstore", text)):
        return ("Student budget: check for a student discount or a used/rental option next time.", flags)
    if p.get("role") == "student" and t.action_type == "payment" or re.search(r"\brent\b|split", text):
        return ("Student budget: confirm the amount with the sender before paying; never pay from an email link.", flags)
    if re.search(r"8 ?am|7 ?am|before (9|10)", text):
        return ("This clashes with your 'no meetings before 10' preference — propose 10:30 or later.", flags)
    in_person = re.search(r"interview|on-?site|in person|mixer|study group|meet(up|ing)? at|dinner|lunch|party|student union|\bhq\b", text)
    if p.get("has_car") is False and in_person and t.action_type in ("reply", "schedule", "rsvp", "accept_recurring", "confirm_meeting"):
        how = " or ".join((p.get("transport") or ["transit"])[:2])
        return (f"No car: plan {how} from {p.get('city', 'home')} and leave ~{p.get('transit_buffer_min', 30)} min early.", flags)
    return ("", flags)
