"""Pydantic contracts shared by all agents."""
from __future__ import annotations
from datetime import datetime, date
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class Decision(str, Enum):
    AUTO = "AUTO"
    ASK = "ASK"
    VERIFY = "VERIFY"


class Value(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskStatus(str, Enum):
    planned = "planned"
    done = "done"            # executed automatically
    needs_you = "needs_you"  # waiting on user (ASK / VERIFY)
    approved = "approved"
    rejected = "rejected"
    blocked = "blocked"      # hard block (phishing / prompt injection)
    failed = "failed"
    undone = "undone"


class SourceItem(BaseModel):
    id: str
    source: str                 # gmail | calendar | slack | notion | github | linear
    type: str                   # email | event | message | todo
    author: str = ""
    participants: list[str] = []
    timestamp: datetime         # tz-aware
    subject: str = ""
    body: str = ""
    metadata: dict[str, Any] = {}


class Task(BaseModel):
    id: str
    title: str
    source_item_id: Optional[str] = None
    due: Optional[date] = None
    people: list[str] = []
    amount: Optional[float] = None
    action_type: str = "other"  # archive|label|file_receipt|accept_recurring|rsvp|reminder|draft_reply|reply|payment|schedule|work|delete|share|other
    reversible: bool = True
    value: Value = Value.medium
    confidence: float = 0.5
    flags: list[str] = []       # phishing, prompt_injection, new_contact, external_send, money, delete, data_sharing
    est_minutes: int = 0
    # filled by policy / executor
    decision: Optional[Decision] = None
    why: str = ""
    status: TaskStatus = TaskStatus.planned
    result: Optional["ActionResult"] = None
    verified: bool = False
    user_added: bool = False
    triage_via: str = "sie"     # sie | llm | rule
    item: dict[str, Any] = {}      # source item summary {source,type,author,subject,ts} (no body)
    council: dict[str, Any] = {}   # evidence + specialist opinions + debate + judge
    signal: dict[str, Any] = {}   # raw triage signal {routine, kind, stakes, via}
    priority: int = 50          # 0-100, used to order the needs-you queue
    meta: dict[str, Any] = {}   # action parameters (e.g. meeting details)


class PlanBlock(BaseModel):
    start: datetime
    end: datetime
    title: str
    kind: str = "event"         # event | task | focus | break
    task_id: Optional[str] = None
    note: str = ""


class Plan(BaseModel):
    date: date
    tz: str
    blocks: list[PlanBlock] = []
    tasks: list[Task] = []
    summary: str = ""
    planner: str = "deterministic"
    metrics: dict[str, Any] = {}


class Action(BaseModel):
    id: str
    task_id: str
    kind: str                   # gmail.archive | gmail.label | gmail.draft | gmail.send | calendar.accept | calendar.reminder | slack.draft | pay.invoice
    params: dict[str, Any] = {}
    idempotency_key: str = ""


class ActionResult(BaseModel):
    action_id: str
    ok: bool
    status: str                 # done | dry_run | skipped | failed | duplicate
    why: str = ""
    dry_run: bool = False
    attempts: int = 1
    undo: Optional[dict[str, Any]] = None


class AgentEvent(BaseModel):
    seq: int = 0
    ts: datetime
    run_id: str = ""
    agent: str
    step: str
    summary: str
    decision: Optional[str] = None
    why: str = ""
    latency_ms: int = 0
    cost_estimate: float = 0.0


class CheckResult(BaseModel):
    id: str
    desc: str
    type: str
    category: str = ""
    passed: bool
    expected: Any = None
    observed: Any = None
    params: dict[str, Any] = {}


class ScenarioResult(BaseModel):
    id: str
    name: str
    description: str = ""
    status: str = "pass"          # pass | needs_attention
    passed: bool = True
    check_results: list[CheckResult] = []
    evidence: dict[str, Any] = {}
    duration_ms: int = 0
    detail: str = ""


Task.model_rebuild()
