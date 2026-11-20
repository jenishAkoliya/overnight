import os

os.environ["OVERNIGHT_OFFLINE"] = "1"   # tests never touch hosted services
os.environ["SOURCES_MOCK"] = "1"        # ...nor real Gmail/Calendar
