import os

os.environ["OVERNIGHT_OFFLINE"] = "1"   # tests never touch hosted services
os.environ["SOURCES_MOCK"] = "1"        # ...nor real Gmail/Calendar


def pytest_sessionfinish(session, exitstatus):
    import json, time
    from pathlib import Path
    Path(__file__).resolve().parent.parent.joinpath(".test_status.json").write_text(
        json.dumps({"collected": session.testscollected, "failed": session.testsfailed, "exit": int(exitstatus), "ts": time.time()}))
