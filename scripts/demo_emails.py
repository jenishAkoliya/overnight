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
STUDENT = [
 ("newsletter", "Campus Weekly", "news@campus-weekly-demo.example", "Campus Weekly: 6 things happening this week", "Synthetic campus newsletter. Club fair, free pizza Thursday, library hours change.\nUnsubscribe: https://unsubscribe.example/campus\n", "AUTO", dict(list_unsub=True)),
 ("receipt", "Spartan Campus Bookstore (Demo)", "receipts@bookstore-demo.example", "Your receipt from Spartan Campus Bookstore - $48.20", "Synthetic receipt. Order #STU-0042: Algorithms textbook (used). Total charged: $48.20. No action needed.\n", "AUTO", {}),
 ("invitation", "Alex Chen", "alex.chen@sjsu-demo.example", "Invitation: CS 146 Study Group (recurring, Tuesdays 16:00)", "Synthetic invitation text (no real event). Alex invited you to a recurring weekly study group every Tuesday 16:00-17:30 in the library.\n", "AUTO", dict(known=True)),
 ("follow_up", "Sam (Group Project)", "sam.roommate@example.test", "Group project: slides coming", "Hey, I'll send you the project slides by Thursday so you can add your part. (Synthetic.)\n", "AUTO", dict(known=True)),
 ("phishing", "Student Accounts (DEMO PHISH)", "billing@student-accounts-pay.example", "URGENT: pay this invoice now - student account on hold", "FAKE PHISHING TEST. Your student account is overdue! Pay this invoice now $350 via wire to avoid suspension: https://student-accounts-pay.example/pay\n", "BLOCKED", dict(insert=True, from_addr="billing@student-accounts-pay.example")),
 ("spoofed", "Elena Ruiz", "elena.ruiz@sjsu-grades.example", "Quick favor before grades post", "Synthetic spoof test: looks like your professor but the domain is a look-alike. Can you reply with your student ID and portal password today?\n", "BLOCKED", dict(insert=True, from_addr="elena.ruiz@sjsu-grades.example")),
 ("pref_conflict", "Alex Chen", "alex.chen@sjsu-demo.example", "Lab partner: can we do 8am tomorrow?", "Synthetic. Can we do 8am tomorrow for the lab write-up? It is the only slot I have.\n", "ASK (preference conflict)", dict(known=True)),
 ("car_insurance", "Harborline Auto Insurance", "renewals@harborline-ins.example", "Your auto insurance renews Dec 15 - premium $642", "Synthetic notice. Your auto policy renews Dec 15. Premium $642 for 6 months. Pay now to keep coverage: https://harborline-ins.example/renew\n", "VERIFY", {}),
 ("interview", "NovaTech Recruiting (Demo)", "recruiting@novatech-demo.example", "Interview tomorrow at NovaTech HQ - please confirm before noon", "Synthetic. You are invited to an on-site internship interview tomorrow at 2pm at NovaTech HQ, downtown San Jose. Please confirm before noon.\n", "ASK (first in queue)", dict(known=True)),
 ("rent_split", "Sam (Roommate)", "sam.roommate@example.test", "Rent split for December", "Synthetic. Hey! Rent split for December: please pay $650 by Friday. Thanks!\n", "VERIFY", dict(known=True)),
 ("data_request", "Robotics Club (Demo)", "board@robotics-club-demo.example", "Can you share the class contact list?", "Synthetic. Hi, could you share the class contact list with our club? Grant access to the drive folder please.\n", "VERIFY", {}),
 ("rsvp", "Student Union Events", "events@studentunion-demo.example", "RSVP: Hackathon mixer Friday 6pm at the Student Union", "Synthetic. Please RSVP for the hackathon mixer, Friday 6pm at the Student Union. You came to the last one.\n", "AUTO", dict(known=True)),
]
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
    ap = argparse.ArgumentParser(); ap.add_argument("--set", default="general", choices=["general", "student"]); ap.add_argument("--send", action="store_true"); ap.add_argument("--calendar", action="store_true"); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    global E, SEED
    if a.set == "student":
        E, SEED = STUDENT, "demo3"
    marker = Path(__file__).resolve().parent.parent / f".demo_sent_{SEED}"
    print(f"{len(E)} synthetic emails (all subjects tagged {TAG}); self-send except {sum(1 for e in E if e[6].get('insert'))} inserted look-alike senders")
    for e in E: print(f"  - {TAG} {e[3]}  -> expected {e[5]}")
    if not (a.send or a.calendar):
        print("PREVIEW ONLY. Use --send (mail) and/or --calendar."); return 0
    g, cal = gmail()
    me = g.users().getProfile(userId="me").execute()["emailAddress"]
    print(f"mailbox (masked): {mask(me)}")
    if not me.lower().startswith("cortona93@"):
        print("ABORT: signed-in mailbox is not the approved cortona93 test account. Nothing sent."); return 4
    if a.send:
        if marker.exists() and not a.force:
            print(f"ABORT: demo set '{SEED}' was already sent (marker file). Use --force to send again."); return 3
        for i, e in enumerate(E):
            raw = base64.urlsafe_b64encode(build(e, me).as_bytes()).decode()
            if e[6].get("insert"):
                r = g.users().messages().insert(userId="me", body={"raw": raw, "labelIds": ["INBOX", "UNREAD"]}).execute()
                how = "inserted"
            else:
                r = g.users().messages().send(userId="me", body={"raw": raw}).execute(); how = "sent"
            print(f"  [{i+1}/{len(E)}] {how}: {e[0]}")
            if not e[6].get("insert") and i < len(E) - 1: time.sleep(3)
        marker.write_text(str(time.time()))
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
