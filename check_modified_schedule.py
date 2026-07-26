"""
check_modified_schedule.py
Dumps the Clg-SetP-Sch fields from the most recently modified IDF, so we can
confirm modifier.py only changed the occupied setpoint and left the
design-day / setback values alone.

Run from project root:
    python check_modified_schedule.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import config
from eppy.modeleditor import IDF

IDF.setiddname(str(config.IDD_FILE))

# Grab the most recently modified IDF automatically
modified_files = sorted(config.MODIFIED_IDF_DIR.glob("*.idf"), key=lambda p: p.stat().st_mtime)
if not modified_files:
    print("No modified IDFs found in", config.MODIFIED_IDF_DIR)
    sys.exit(1)

latest_idf = modified_files[-1]
print(f"Checking: {latest_idf}")
print()

idf = IDF(str(latest_idf))

for sched_name in ["Clg-SetP-Sch", "Htg-SetP-Sch"]:
    print("=" * 70)
    print(f"SCHEDULE: {sched_name}")
    print("=" * 70)
    matches = [s for s in idf.idfobjects["SCHEDULE:COMPACT"] if s.Name == sched_name]
    if not matches:
        print("  NOT FOUND")
        continue
    sched = matches[0]
    for fieldname in sched.fieldnames:
        val = getattr(sched, fieldname, None)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            continue
        print(f"  {fieldname}: {val!r}")
    print()