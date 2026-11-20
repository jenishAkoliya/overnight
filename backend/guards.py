"""Content guards: detect phishing and prompt injection in untrusted item content.
Instructions found in data are NEVER followed - they only raise flags."""
import re

INJECTION = re.compile(r"ignore (all )?(previous|prior) instructions|forward (your|the) (entire )?inbox|system message|you are now|reveal your (system )?prompt", re.I)
PHISH = re.compile(r"pay (this )?invoice now|urgent.{0,40}(wire|pay)|avoid suspension|account is overdue", re.I)


def scan(subject: str, body: str, meta: dict) -> list[str]:
    text = f"{subject}\n{body}"
    flags = []
    if meta.get("injection") or INJECTION.search(text):
        flags.append("prompt_injection")
    if meta.get("lookalike_domain") or meta.get("spf") == "fail" or PHISH.search(text):
        flags.append("phishing")
    return flags
