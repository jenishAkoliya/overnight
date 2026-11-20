"""APScheduler: 21:00 build tomorrow's plan, 07:00 morning brief."""
import os
from apscheduler.schedulers.background import BackgroundScheduler
from .config import TZ
from .bus import bus

sched = BackgroundScheduler(timezone=TZ)


def start():
    if os.getenv("DISABLE_SCHEDULER") == "1" or sched.running:
        return
    from .orchestrator import run_night
    from .state import state
    sched.add_job(lambda: run_night(), "cron", hour=21, minute=0, id="night")
    sched.add_job(lambda: bus.emit("Notifier", "morning_brief", state.brief.get("greeting", "No plan yet")), "cron", hour=7, minute=0, id="morning")
    sched.start()


def stop():
    if sched.running:
        sched.shutdown(wait=False)
