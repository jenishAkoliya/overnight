"""LLM provider interface. Order: hosted SIE generation (Qwen/Qwen3.5-4B via /v1/chat/completions) -> mock (None).
Callers MUST fall back to deterministic logic when complete() returns None. Anthropic/Claude is wired in Phase 3b."""
import json
import re
from .sie_client import get_sie, hosted_available


class MockLLM:
    name = "mock"
    def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str | None:
        return None


class SIEGen:
    @property
    def name(self):
        from .sie_client import GEN_MODEL
        return GEN_MODEL

    def complete(self, prompt: str, system: str = "", json_mode: bool = False, max_tokens: int = 400) -> str | None:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        out = get_sie().chat(msgs, max_tokens)
        if out is None:
            return None
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
        return out or None

    def json(self, prompt: str, system: str = "") -> dict | None:
        out = self.complete(prompt + "\nReturn ONLY a JSON object.", system)
        if not out:
            return None
        m = re.search(r"\{.*\}", out, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None


_mock, _gen = MockLLM(), SIEGen()


def get_llm():
    return _gen if hosted_available() else _mock
