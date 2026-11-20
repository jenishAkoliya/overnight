"""Demo mailbox seeding (self-send). AUTHORIZED writes only: synthetic [OVERNIGHT DEMO] mail from the test mailbox to ITSELF
(users.messages.send) + two look-alike-sender messages via users.messages.insert + synthetic Calendar items on the same account.
Default = preview. `--send` sends/inserts; `--calendar` creates events (sendUpdates=none). Refuses to run twice unless --force.
Usage: python scripts/demo_emails.py [--send] [--calendar] [--force]"""
import argparse
import base64
import os
import sys
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
TAG = "[OVERNIGHT DEMO]"
SEED = "demo2"
# (name, from_display, reply_to, subject, body, expected, flags)
E = [
 ("newsletter", "Demo Daily Digest", "digest@demo-news.example", "Weekly digest: 5 synthetic stories", "Synthetic demo content.\nTop stories (fictional): Acme Demo Corp launches a pretend product.\nUnsubscribe: https://unsubscribe.example/demo\n", "AUTO", dict(list_unsub=True)),
 ("receipt", "Sample Cafe (Demo)", "receipts@sample-cafe.example", "Your receipt from Sample Cafe - $12.40", "Synthetic receipt. Order #DEMO-0001. Total charged: $12.40. No action needed.\n", "AUTO", {}),
 ("invitation", "Pat Example", "pat@example.test", "Invitation: Weekly Sync (recurring, Mondays 10:00)", "Synthetic invitation text (no real event). Pat Example invited you to a recurring weekly sync every Monday 10:00-10:30.\n", "AUTO", dict(known=True)),
 ("follow_up", "Jordan Sample", "jordan.sample@example.test", "Following up: numbers by Wednesday", "Hi, I'll send you the sample numbers by Wednesday so you can fold them into the deck. (Synthetic.)\n", "AUTO", dict(known=True)),
 ("phishing", "Billing Dept (DEMO PHISH)", "billing@pay-invoice-now.example", "URGENT: pay this invoice now to avoid suspension", "FAKE PHISHING TEST. Your account is overdue! Pay this invoice now $4,980 via wire to avoid suspension: https://pay-invoice-now.example/pay\n", "BLOCKED", dict(insert=True, from_addr="billing@pay-invoice-now.example")),
 ("spoofed", "Priya Nair", "priya.nair@northwind-pay.example", "Quick favor", "Synthetic spoof test: display name looks like a colleague but the address is a look-alike domain. Can you share the payout details for the vendor today?\n", "BLOCKED", dict(insert=True, from_addr="priya.nair@northwind-pay.example")),
 ("pref_conflict", "Dana Sample (CEO, Demo)", "dana.cruz@northwind.example", "Can we do 8am tomorrow?", "Synthetic. Hi, can you do 8am tomorrow? I need your take on the board deck.\n", "ASK (preference conflict)", dict(known=True)),
 ("insurance", "Harborline Insurance", "renewals@harborline-ins.example", "Your car insurance renews Dec 15 - premium up 22%", "Synthetic notice. Your 6-month policy renews Dec 15. New premium $1,284 (up 22% from $1,052). Pay now to keep coverage: https://harborline-ins.example/renew\n", "VERIFY", {}),
 ("customer_urgent", "Acme Demo Customer Success", "success@acme-demo.example", "Customers cannot log in - need your call before noon", "Synthetic. Customers cannot log in since 6am. Need your decision on rollback before noon.\n", "ASK (first in queue)", dict(known=True)),
 ("data_request", "Vendor CRM (Demo)", "jordan@vendorcrm-demo.example", "Can you share the Q4 customer list?", "Synthetic. Hi, for our partnership could you share the Q4 customer list with our team? Please grant access to the drive folder.\n", "VERIFY", {}),
]


def gmail():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    c = Credentials(None, refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"], client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"], token_uri="https://oauth2.googleapis.com/token")
    return build("gmail", "v1", credentials=c, cache_discovery=False), build("calendar", "v3", credentials=c, cache_discovery=False)


def mask(a): u, _, d = a.partition("@"); return u[:2] + "***@" + d[:1] + "***" + d[d.rfind("."):]


def build(item, me):
    name, disp, reply, subj, body, exp, f = item
    m = EmailMessage()
    m["To"] = me
    m["From"] = formataddr((disp, f.get("from_addr", me)))
    m["Reply-To"] = reply
    m["Subject"] = f"{TAG} {subj}"
    m["X-Overnight-Seed"] = SEED
    if f.get("known"): m["X-Overnight-Known-Contact"] = "1"
    if f.get("list_unsub"): m["List-Unsubscribe"] = "<https://unsubscribe.example/demo>"
    if f.get("insert"): m["Authentication-Results"] = "mx.google.com; spf=fail smtp.mailfrom=" + f["from_addr"].split("@")[1]
    m.set_content(body + "\n-- \nSynthetic data for the Overnight hackathon demo. Not a real message.\n")
    return m


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true"); ap.add_argument("--calendar", action="store_true"); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    print(f"{len(E)} synthetic emails (all subjects tagged {TAG}); self-send except {sum(1 for e in E if e[6].get('insert'))} inserted look-alike senders")
    for e in E: print(f"  - {TAG} {e[3]}  -> expected {e[5]}")
    if not (a.send or a.calendar):
        print("PREVIEW ONLY. Use --send (mail) and/or --calendar."); return 0
    g, cal = gmail()
    me = g.users().getProfile(userId="me").execute()["emailAddress"]
    print(f"mailbox (masked): {mask(me)}")
    if a.send:
        existing = g.users().messages().list(userId="me", q=f'subject:"{TAG}" newer_than:3d', maxResults=50).execute().get("messages", [])
        if len(existing) >= 8 and not a.force:
            print(f"ABORT: {len(existing)} demo messages already exist (use --force to add more)."); return 3
        for i, e in enumerate(E):
            raw = base64.urlsafe_b64encode(build(e, me).as_bytes()).decode()
            if e[6].get("insert"):
                r = g.users().messages().insert(userId="me", body={"raw": raw, "labelIds": ["INBOX", "UNREAD"]}).execute()
                how = "inserted"
            else:
                r = g.users().messages().send(userId="me", body={"raw": raw}).execute(); how = "sent"
            print(f"  [{i+1}/{len(E)}] {how}: {e[0]}")
            if not e[6].get("insert") and i < len(E) - 1: time.sleep(3)
    if a.calendar:
        tz = "America/Los_Angeles"; d = (datetime.now() + timedelta(days=1)).date()
        items = [("Design review", 13, 0, 60), ("Customer call: Harborline Demo", 15, 0, 45), ("Zurich sync (17:00 CET) demo", 8, 0, 45)]
        for t, h, mi, dur in items:
            s = datetime(d.year, d.month, d.day, h, mi); en = s + timedelta(minutes=dur)
            cal.events().insert(calendarId="primary", sendUpdates="none", body={"summary": f"{TAG} {t}", "description": "Synthetic demo event (Overnight).",
                "start": {"dateTime": s.isoformat(), "timeZone": tz}, "end": {"dateTime": en.isoformat(), "timeZone": tz},
                "extendedProperties": {"private": {"overnightDemo": SEED}}}).execute()
            print(f"  calendar: created {t} on {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
