"""Print the readiness report. Exit 1 if any SAFETY problem. Run: make ready"""
import json
import sys
sys.path.insert(0, ".")
from backend.readiness import report
r = report()
print(json.dumps(r, indent=2, default=str))
print("\nREADY" if r["ready"] else "\nNOT READY: " + "; ".join(r["safety_problems"]))
sys.exit(0 if r["ready"] else 1)
