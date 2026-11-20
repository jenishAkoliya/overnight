"""Generate synthetic [OVERNIGHT DEMO] emails and (optionally) send them to the ONE approved demo recipient.
Safety:
- Recipient comes ONLY from DEMO_RECIPIENT in .env. If missing -> nothing is sent (exit 2).
- `--to` may be given only to double-check: it must equal DEMO_RECIPIENT, otherwise abort.
- Default is PREVIEW (no network). Sending needs `--send`.
- Every subject carries [OVERNIGHT DEMO]; all names/companies/links are synthetic (.example domains).
- Only Gmail messages.send of these generated messages. No Calendar writes. No other recipients (no Cc/Bcc).
Usage: python scripts/send_demo_emails.py [--send] [--to ADDRESS]"""
import argparse
import base64
import os
import sys
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

TAG = "[OVERNIGHT DEMO]"


def demo_messages() -> list[dict]:
    return [
        {"kind": "newsletter", "from_name": "Demo Daily Digest", "subject": f"{TAG} Weekly digest: 5 synthetic stories", "list_unsub": True,
         "body": "This is synthetic demo content.\n\nTop stories this week (all fictional):\n1. Acme Demo Corp launches a pretend product\n2. Example Weather predicts imaginary sun\n\nUnsubscribe: https://unsubscribe.example/demo\n"},
        {"kind": "receipt", "from_name": "Sample Cafe (Demo)", "subject": f"{TAG} Your receipt from Sample Cafe - $12.40",
         "body": "Synthetic receipt. Thanks for your fake purchase!\nOrder #DEMO-0001\nTotal charged: $12.40\nNo action needed.\n"},
        {"kind": "calendar_invitation", "from_name": "Pat Example", "subject": f"{TAG} Invitation: Weekly Sync (recurring, Mondays 10:00)",
         "body": "Synthetic invitation text only (no real calendar event is created).\nPat Example invited you to a recurring weekly sync, every Monday 10:00-10:30.\nOrganizer: pat@example.test\n"},
        {"kind": "follow_up", "from_name": "Jordan Sample", "subject": f"{TAG} Following up: numbers by Wednesday",
         "body": "Hi, I'll send you the sample numbers by Wednesday so you can fold them into the deck. (Synthetic demo message.)\n"},
        {"kind": "phishing", "from_name": "Billing Dept (DEMO PHISH)", "subject": f"{TAG} URGENT: pay this invoice now to avoid suspension",
         "reply_to": "billing@pay-invoice-now.example", "body": "THIS IS A FAKE PHISHING TEST FOR DEMO PURPOSES.\nYour account is overdue! Pay this invoice now $4,980 via wire to avoid suspension: https://pay-invoice-now.example/pay\nReply with confirmation immediately.\n"},
        {"kind": "spoofed_sender", "from_name": "Priya Nair", "subject": f"{TAG} Quick favor",
         "reply_to": "priya.nair@northwind-pay.example", "body": "Synthetic spoof test: display name looks like a colleague but the reply address is a look-alike domain.\nHi, can you share the payout details for the vendor today?\n"},
        {"kind": "preference_conflict", "from_name": "Dana Sample (CEO, Demo)", "subject": f"{TAG} Can we do 8am tomorrow?",
         "body": "Synthetic demo message. Can you do 8am tomorrow? I need your take on the board deck.\n"},
        {"kind": "insurance", "from_name": "Example Auto Insurance", "subject": f"{TAG} Your car insurance renews Dec 15 - premium up 22%",
         "body": "Synthetic demo notice. Your 6-month policy renews Dec 15. New premium $1,284 (up 22% from $1,052). Pay now to keep coverage: https://insurance.example/renew\n"},
    ]


def mask(addr: str) -> str:
    u, _, d = addr.partition("@")
    return (u[:2] + "***@" + d[:1] + "***" + d[d.rfind("."):]) if d else "***"


def build(msg: dict, to: str, sender: str) -> EmailMessage:
    m = EmailMessage()
    m["To"] = to
    m["From"] = formataddr((msg["from_name"], sender))
    m["Subject"] = msg["subject"]
    if msg.get("reply_to"):
        m["Reply-To"] = msg["reply_to"]
    if msg.get("list_unsub"):
        m["List-Unsubscribe"] = "<https://unsubscribe.example/demo>"
    m["X-Overnight-Demo"] = "synthetic"
    m.set_content(msg["body"] + "\n-- \nSynthetic data generated for the Overnight hackathon demo. Not a real message.\n")
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--to", default="")
    a = ap.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    to = (os.getenv("DEMO_RECIPIENT") or "").strip()
    if not to:
        print("DEMO RECIPIENT MISSING: set DEMO_RECIPIENT in .env to the approved demo address. Nothing was sent.")
        return 2
    if a.to and a.to.strip().lower() != to.lower():
        print("ABORT: --to does not match the configured DEMO_RECIPIENT. Nothing was sent.")
        return 3
    msgs = demo_messages()
    assert all(m["subject"].startswith(TAG) for m in msgs)
    print(f"Messages: {len(msgs)} | recipient: {mask(to)} | data: all synthetic")
    for m in msgs:
        print(f"  - {m['subject']}")
    if not a.send:
        print("PREVIEW ONLY (no network). Re-run with --send to deliver to the approved recipient.")
        return 0
    from backend.integrations.real_sources import RealGmail, run_async
    gm = RealGmail()

    async def go():
        g = gm._conn()
        sender = to  # sending from the authenticated mailbox; From display names are synthetic
        n = 0
        for m in msgs:
            raw = base64.urlsafe_b64encode(build(m, to, sender).as_bytes()).decode()
            await g.execute("messages", "create", {"raw": raw})
            n += 1
        return n
    n = run_async(go())
    print(f"SENT {n} synthetic demo messages to {mask(to)}. Verify with: make ingest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
