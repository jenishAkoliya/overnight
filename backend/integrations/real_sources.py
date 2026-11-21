"""REAL source connectors. Gmail/Slack via airbyte-agent-sdk (OSS/local auth), Calendar via google-api-python-client.
All share the MockSource contract: fetch() -> list[SourceItem]; execute(op, params) -> dict; every write is recorded in the
effects log. Writes are additionally gated by DRY_RUN in the Executor (default on) and never include send/pay without approval.
Slack/Notion/Linear paths are UNTESTED (no tokens yet)."""
import asyncio
import base64
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from .. import config
from ..contracts import SourceItem
from .airbyte_client import effects, RateLimited, ServiceUnavailable, AuthExpired

LOOKBACK_DAYS = int(os.getenv("INGEST_LOOKBACK_DAYS", "2"))
MAX_MESSAGES = int(os.getenv("INGEST_MAX_MESSAGES", "60"))
RECEIPT_RE = re.compile(r"receipt|your order|order confirmation|invoice (paid|available)|payment (received|confirmation)|statement (is )?ready", re.I)


def run_async(coro):
    return asyncio.run(coro)


def _d(x):
    """Normalize SDK results (pydantic / dict / wrapper with .data) to plain python."""
    if hasattr(x, "data") and not isinstance(x, dict):
        x = x.data
    if hasattr(x, "model_dump"):
        x = x.model_dump(mode="json")
    if isinstance(x, list):
        return [_d(i) for i in x]
    return x


def _map_error(e: Exception, service: str):
    s = str(e)
    if "accessNotConfigured" in s or "has not been used in project" in s:
        return AuthExpired(f"{service}: the {service} API is NOT ENABLED in the Google Cloud project - enable it in Cloud Console > APIs & Services (manual step), then retry")
    code = getattr(getattr(e, "resp", None), "status", None) or getattr(e, "status_code", None)
    if code == 404 or "notFound" in s:
        return ValueError(f"{service}: not found - the item no longer exists on {service}")
    if code in (401, 403) or "invalid_grant" in s or "401" in s[:40]:
        return AuthExpired(f"{service}: {s[:120]}")
    if code == 429 or "rateLimit" in s or "429" in s[:40]:
        return RateLimited(f"{service}: 429 {s[:80]}", retry_after=2.0)
    if code in (500, 502, 503, 504) or "timed out" in s.lower() or "timeout" in s.lower():
        return ServiceUnavailable(f"{service}: {s[:120]}")
    return e


class _Real:
    name = ""

    def __init__(self):
        self.keys: dict[str, str] = {}

    def _log_exec(self, op, params, fn):
        key = params.get("idempotency_key", "")
        if key and key in self.keys:
            effects.add(self.name, op, params, key, True, deduped=True)
            return {"ok": True, "op": op, "id": self.keys[key], "deduped": True}
        try:
            out = fn()
        except Exception as e:
            err = _map_error(e, self.name)
            effects.add(self.name, op, params, key, False, error=f"{type(err).__name__}: {str(err)[:140]}")
            raise err
        rid = str((out or {}).get("id", "")) if isinstance(out, dict) else ""
        if key:
            self.keys[key] = rid
        effects.add(self.name, op, params, key, True)
        return {"ok": True, "op": op, "id": rid}


# ---------------------------------------------------------------- Gmail (Airbyte agent SDK)
class RealGmail(_Real):
    name = "gmail"
    LABEL = "Overnight/Receipts"

    def _conn(self):
        from airbyte_agent_sdk.connectors.gmail import GmailConnector, GmailAuthConfig
        return GmailConnector(auth_config=GmailAuthConfig(refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"], client_id=os.environ["GOOGLE_CLIENT_ID"],
                                                          client_secret=os.environ["GOOGLE_CLIENT_SECRET"]))

    # ---- read
    def fetch(self) -> list[SourceItem]:
        try:
            return run_async(self._fetch())
        except Exception as e:
            raise _map_error(e, "gmail")

    async def _fetch(self) -> list[SourceItem]:
        g = self._conn()
        lst = _d(await g.execute("messages", "list", {"q": f"newer_than:{LOOKBACK_DAYS}d -in:spam -in:trash", "max_results": MAX_MESSAGES}))
        stubs = lst.get("messages", lst) if isinstance(lst, dict) else lst
        sem = asyncio.Semaphore(8)

        async def one(stub):
            async with sem:
                return _d(await g.execute("messages", "get", {"message_id": stub["id"], "format": "full"}))
        msgs = await asyncio.gather(*[one(s) for s in (stubs or [])[:MAX_MESSAGES]], return_exceptions=True)
        known = self.known_contacts_sync_from(msgs)
        items = [self.to_item(m, known) for m in msgs if isinstance(m, dict)]
        return [i for i in items if i]

    @staticmethod
    def known_contacts_sync_from(msgs) -> set[str]:
        out = set()
        for m in msgs:
            if isinstance(m, dict) and "SENT" in (m.get("labelIds") or m.get("label_ids") or []):
                for _, addr in getaddresses([RealGmail._hdr(m, "To"), RealGmail._hdr(m, "Cc")]):
                    if addr:
                        out.add(addr.lower())
        return out

    def known_contacts(self) -> set[str]:
        """Addresses Maya has emailed in the last 90 days (metadata only)."""
        async def go():
            g = self._conn()
            lst = _d(await g.execute("messages", "list", {"q": "in:sent newer_than:90d", "max_results": 80}))
            stubs = lst.get("messages", lst) if isinstance(lst, dict) else lst
            sem = asyncio.Semaphore(8)

            async def one(s):
                async with sem:
                    return _d(await g.execute("messages", "get", {"message_id": s["id"], "format": "metadata", "metadata_headers": "To,Cc"}))
            res = await asyncio.gather(*[one(s) for s in (stubs or [])[:80]], return_exceptions=True)
            out = set()
            for m in res:
                if isinstance(m, dict):
                    for _, a in getaddresses([self._hdr(m, "To"), self._hdr(m, "Cc")]):
                        if a:
                            out.add(a.lower())
            return out
        try:
            out = run_async(go())
        except Exception:
            out = set()
        if os.getenv("DEMO_SELF_SEND", "").lower() == "true":   # synthetic demo colleagues (demo mode only)
            out |= {"priya.nair@northwind.example", "dana.cruz@northwind.example", "pat@example.test", "jordan.sample@example.test",
                    "alex.chen@sjsu-demo.example", "elena.ruiz@sjsu-demo.example", "sam.roommate@example.test", "recruiting@novatech-demo.example", "events@studentunion-demo.example"}
        return out

    @staticmethod
    def _hdr(m: dict, name: str) -> str:
        for h in (m.get("payload") or {}).get("headers", []) or []:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    @staticmethod
    def _body(payload: dict) -> str:
        def walk(p):
            if not p:
                return ""
            if p.get("mimeType") == "text/plain" and (p.get("body") or {}).get("data"):
                return base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "replace")
            for part in p.get("parts") or []:
                t = walk(part)
                if t:
                    return t
            if (p.get("body") or {}).get("data"):
                return re.sub(r"<[^>]+>", " ", base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "replace"))
            return ""
        return re.sub(r"\n{3,}", "\n\n", walk(payload)).strip()[:4000]

    def to_item(self, m: dict, known: set[str]) -> SourceItem | None:
        frm = self._hdr(m, "From")
        name_addr = getaddresses([frm])
        disp, addr = (name_addr[0] if name_addr else ("", frm))
        addr = addr.lower()
        subject = self._hdr(m, "Subject")
        labels = m.get("labelIds") or m.get("label_ids") or []
        ts = datetime.fromtimestamp(int(m.get("internalDate") or m.get("internal_date") or 0) / 1000, tz=timezone.utc) if (m.get("internalDate") or m.get("internal_date")) else datetime.now(timezone.utc)
        to = [a.lower() for _, a in getaddresses([self._hdr(m, "To"), self._hdr(m, "Cc")]) if a]
        body = self._body(m.get("payload") or {})
        meta = {"labels": labels, "thread_id": m.get("threadId") or m.get("thread_id"), "display_name": disp}
        if self._hdr(m, "List-Unsubscribe"):
            meta["list_unsubscribe"] = True
        if RECEIPT_RE.search(subject) and not meta.get("list_unsubscribe"):
            meta["receipt"] = True
        if "SENT" in labels:
            meta["direction"] = "sent"
        demo_self = os.getenv("DEMO_SELF_SEND", "").lower() == "true" and bool(self._hdr(m, "X-Overnight-Seed"))
        if demo_self:   # demo mode: self-sent mail; the story's sender lives in Reply-To / display name, not From
            rt = getaddresses([self._hdr(m, "Reply-To")])
            if rt and rt[0][1]:
                addr = rt[0][1].lower()
            if self._hdr(m, "X-Overnight-Known-Contact"):
                meta["known_contact"] = True
            meta.pop("direction", None)
        if addr in known:
            meta["known_contact"] = True
        from .. import runtime
        for key, pat in (runtime.load("guards_rules.yaml").get("content_signals") or {}).items():
            if re.search(pat, f"{subject}\n{body}", re.I):
                meta[key] = True
        if re.search(r"spf=fail|dkim=fail", self._hdr(m, "Authentication-Results"), re.I):
            meta["spf"] = "fail"
        if re.search(r"invitation:|updated invitation:", subject, re.I) or "text/calendar" in str(m.get("payload"))[:3000]:
            meta["invite"] = True
            meta["recurring"] = bool(re.search(r"weekly|daily|monthly|every", subject + body[:300], re.I))
        return SourceItem(id=f"gmail-{m['id']}", source="gmail", type="email", author=addr or frm, participants=to, timestamp=ts, subject=subject, body=body, metadata=meta)

    # ---- write
    def _rid(self, params) -> str:
        return str(params.get("message_id") or params.get("in_reply_to") or "").removeprefix("gmail-")

    async def _label_id(self, g, name):
        labs = _d(await g.execute("labels", "list", {}))
        labs = labs.get("labels", labs) if isinstance(labs, dict) else labs
        for l in labs or []:
            if l.get("name") == name:
                return l["id"]
        return _d(await g.execute("labels", "create", {"name": name}))["id"]

    def execute(self, op: str, params: dict) -> dict:
        async def go():
            g = self._conn()
            if op == "messages.update":
                return _d(await g.execute("messages", "update", {"message_id": self._rid(params), "add_label_ids": params.get("add_label_ids", []), "remove_label_ids": params.get("remove_label_ids", [])}))
            if op == "labels.apply":
                lid = await self._label_id(g, self.LABEL)
                add = [lid] + [x for x in params.get("add_label_ids", []) if not x.startswith("Label_")]
                return _d(await g.execute("messages", "update", {"message_id": self._rid(params), "add_label_ids": add, "remove_label_ids": params.get("remove_label_ids", [])}))
            if op in ("drafts.create", "messages.send"):
                orig = _d(await g.execute("messages", "get", {"message_id": self._rid(params), "format": "metadata", "metadata_headers": "From,Reply-To,Subject,Message-ID"}))
                em = EmailMessage()
                em["To"] = self._hdr(orig, "Reply-To") or self._hdr(orig, "From")   # standard: reply goes to Reply-To when present
                if self._hdr(orig, "Message-ID"):
                    em["In-Reply-To"] = self._hdr(orig, "Message-ID"); em["References"] = self._hdr(orig, "Message-ID")
                subj = self._hdr(orig, "Subject")
                em["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
                em.set_content(params.get("body") or "(drafted by Overnight)")
                raw = base64.urlsafe_b64encode(em.as_bytes()).decode()
                tid = orig.get("threadId")
                if op == "drafts.create":
                    return _d(await g.execute("drafts", "create", {"message": {"raw": raw, **({"thread_id": tid} if tid else {})}}))
                return _d(await g.execute("messages", "create", {"raw": raw, **({"thread_id": tid} if tid else {})}))
            raise PermissionError(f"gmail: unsupported op {op}")
        return self._log_exec(op, params, lambda: run_async(go()))


# ---------------------------------------------------------------- Google Calendar (google-api-python-client)
class RealCalendar(_Real):
    name = "calendar"

    def _svc(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"], client_id=os.environ["GOOGLE_CLIENT_ID"],
                            client_secret=os.environ["GOOGLE_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token")
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def fetch(self) -> list[SourceItem]:
        try:
            now = config.tonight()
            tmin = (now - timedelta(days=LOOKBACK_DAYS)).astimezone(timezone.utc).isoformat()
            tmax = (now + timedelta(days=4)).astimezone(timezone.utc).isoformat()
            evs = self._svc().events().list(calendarId="primary", timeMin=tmin, timeMax=tmax, singleEvents=True, orderBy="startTime", maxResults=100).execute().get("items", [])
        except Exception as e:
            raise _map_error(e, "calendar")
        out, seen = [], set()
        for e in evs:
            if e.get("status") == "cancelled" or "dateTime" not in (e.get("start") or {}):
                continue
            st = datetime.fromisoformat(e["start"]["dateTime"]); en = datetime.fromisoformat(e["end"]["dateTime"])
            atts = e.get("attendees") or []
            me = next((a for a in atts if a.get("self")), {})
            org = (e.get("organizer") or {}).get("email", "")
            meta = {"end": en.isoformat(), "recurring": bool(e.get("recurringEventId")), "rsvp": me.get("responseStatus", "accepted" if not atts else "needsAction"),
                    "organizer": org, "attendees": len(atts), "link": e.get("htmlLink")}
            if st.utcoffset() != st.astimezone(config.TZ).utcoffset():
                meta["tz_note"] = f"Scheduled in UTC{st.strftime('%z')}"
            out.append(SourceItem(id=f"cal-{e['id']}", source="calendar", type="event", author=org, participants=[a.get("email", "") for a in atts],
                                  timestamp=st, subject=e.get("summary", "(no title)"), body=(e.get("description") or "")[:500], metadata=meta))
        return out

    def execute(self, op: str, params: dict) -> dict:
        def go():
            svc = self._svc()
            eid = str(params.get("event_id", "")).removeprefix("cal-")
            if op == "events.accept":
                ev = svc.events().get(calendarId="primary", eventId=eid).execute()
                atts = ev.get("attendees", [])
                for a in atts:
                    if a.get("self"):
                        a["responseStatus"] = "accepted"
                return svc.events().patch(calendarId="primary", eventId=eid, body={"attendees": atts}, sendUpdates="none").execute()
            if op in ("events.insert", "reminders.create"):
                start = params.get("start") or ""
                try:
                    st = datetime.fromisoformat(start) if "T" in str(start) else datetime.combine(datetime.fromisoformat(str(start)).date(), datetime.min.time().replace(hour=9), config.TZ)
                except Exception:
                    st = (config.tonight() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
                if st.tzinfo is None:
                    st = st.replace(tzinfo=config.TZ)
                dur = int(params.get("duration_min", 15))
                body = {"id": "ov" + hashlib.sha1(params.get("idempotency_key", str(st)).encode()).hexdigest()[:30],  # deterministic id = natural idempotency
                        "summary": params.get("title", "Reminder"), "start": {"dateTime": st.isoformat(), "timeZone": config.TZ.key},
                        "end": {"dateTime": (st + timedelta(minutes=dur)).isoformat(), "timeZone": config.TZ.key},
                        "description": "Added by Overnight after your approval" + (f" (from email {params['from_email']})" if params.get("from_email") else ""),
                        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]}}
                if params.get("recurrence"):
                    body["recurrence"] = params["recurrence"]
                try:
                    return svc.events().insert(calendarId="primary", body=body).execute()
                except Exception as e:
                    if getattr(getattr(e, "resp", None), "status", None) == 409:   # already created with this id
                        return {"id": body["id"]}
                    raise
            if op == "events.delete":
                svc.events().delete(calendarId="primary", eventId=eid, sendUpdates="none").execute()
                return {"id": eid}
            raise PermissionError(f"calendar: unsupported op {op}")
        return self._log_exec(op, params, go)


# ---------------------------------------------------------------- Slack / Notion / Linear (Airbyte SDK, UNTESTED: no tokens yet)
class RealSlack(_Real):
    name = "slack"

    def _conn(self):
        from airbyte_agent_sdk.connectors.slack import SlackConnector, SlackTokenAuthenticationAuthConfig
        return SlackConnector(auth_config=SlackTokenAuthenticationAuthConfig(api_token=os.environ["SLACK_TOKEN"]))

    def fetch(self) -> list[SourceItem]:
        async def go():
            s = self._conn()
            chs = _d(await s.execute("channels", "list", {"limit": 30, "types": "public_channel,private_channel"}))
            chs = (chs.get("channels", chs) if isinstance(chs, dict) else chs) or []
            oldest = str((config.tonight() - timedelta(days=LOOKBACK_DAYS)).timestamp())
            items = []
            for ch in chs[:12]:
                msgs = _d(await s.execute("channel_messages", "list", {"channel": ch["id"], "limit": 25, "oldest": oldest}))
                for m in (msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs) or []:
                    if m.get("text"):
                        items.append(SourceItem(id=f"slack-{ch['id']}-{m['ts']}", source="slack", type="message", author=m.get("user", ""), participants=[],
                                                timestamp=datetime.fromtimestamp(float(m["ts"]), tz=timezone.utc), subject=f"#{ch.get('name', ch['id'])}", body=m["text"], metadata={"channel": ch["id"]}))
            return items
        try:
            return run_async(go())
        except Exception as e:
            raise _map_error(e, "slack")

    def execute(self, op: str, params: dict) -> dict:
        async def go():
            if op in ("messages.create", "drafts.create"):
                return _d(await self._conn().execute("messages", "create", {"channel": params["channel"], "text": params.get("text", "")}))
            raise PermissionError(f"slack: unsupported op {op}")
        return self._log_exec(op, params, lambda: run_async(go()))
