"""
dump_schedule_fields.py
Prints every field of Clg-SetP-Sch and Htg-SetP-Sch from the baseline IDF,
exactly as eppy sees them - so we can see whether the schedule has a single
constant value or different values for occupied/unoccupied hours (a setback
schedule), which changes how modifier.py needs to handle it.

Run from project root:
    python dump_schedule_fields.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import config
from eppy.modeleditor import IDF

IDF.setiddname(str(config.IDD_FILE))
idf = IDF(str(config.BASELINE_IDF))

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