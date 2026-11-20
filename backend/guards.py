"""Content guards: detect phishing, prompt injection and sender spoofing in untrusted content.
Instructions found in data are NEVER followed - they only raise flags. Patterns live in guards_rules.yaml."""
import re
from . import runtime


def _norm_name(s: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", s.lower().replace(".", " ").replace("_", " ")).split())


def scan(subject: str, body: str, meta: dict, author: str = "", known_contacts=()) -> list[str]:
    g = runtime.load("guards_rules.yaml")
    text = f"{subject}\n{body}"
    flags = []
    if meta.get("injection") or any(re.search(p, text, re.I) for p in g["injection_patterns"]):
        flags.append("prompt_injection")
    if meta.get("lookalike_domain") or meta.get("spf") == "fail" or any(re.search(p, text, re.I) for p in g["phishing_patterns"]):
        flags.append("phishing")
    sp = g.get("spoofing", {})
    if sp.get("enabled") and meta.get("display_name") and author and author not in known_contacts:
        dn = _norm_name(meta["display_name"])
        if any(_norm_name(k.split("@")[0]) == dn for k in known_contacts):
            flags.append(sp.get("flag", "spoofed_sender"))
    return flags
