"""LLM provider interface. Mock returns None (callers fall back to deterministic logic).
Real (Phase 3): Claude via ANTHROPIC_API_KEY; optional OpenAI-compatible (Arcee/OpenRouter)."""
from ..config import use_mock


class MockLLM:
    name = "mock"
    calls = 0

    def complete(self, prompt: str, system: str = "", json_mode: bool = False) -> str | None:
        return None


_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = MockLLM()
    return _llm
