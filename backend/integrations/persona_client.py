"""Persona identity step-up. Mock = fake verification that passes after 2s.
Real (Phase 4): Inquiries API in SANDBOX."""
import time
import uuid


class MockPersona:
    mode = "mock"

    def __init__(self, delay_s: float = 2.0):
        self.delay_s = delay_s
        self.inquiries: dict[str, dict] = {}

    def start(self, reference_id: str, task_id: str) -> dict:
        iid = f"inq_mock_{uuid.uuid4().hex[:8]}"
        self.inquiries[iid] = {"id": iid, "task_id": task_id, "reference_id": reference_id, "t0": time.time(), "forced": None}
        return {"id": iid, "link": None, "mode": self.mode}

    def status(self, iid: str) -> str:
        q = self.inquiries.get(iid)
        if not q:
            return "failed"
        if q["forced"]:
            return q["forced"]
        return "completed" if time.time() - q["t0"] >= self.delay_s else "pending"

    def simulate_pass(self, iid: str):
        if iid in self.inquiries:
            self.inquiries[iid]["forced"] = "completed"


persona = MockPersona()


def get_persona():
    return persona  # Phase 4: RealPersona when PERSONA_API_KEY + PERSONA_TEMPLATE_ID set
