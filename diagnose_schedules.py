"""
diagnose_schedules.py
One-off diagnostic: prints the exact schedule names your thermostat objects
reference, plus every Schedule:Compact / Schedule:Constant name in the IDF.
Run this once, paste me the output, and I'll fix modifier.py's matching logic
to use your exact names instead of guessing by keyword.

Run from project root:
    python diagnose_schedules.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import config
from eppy.modeleditor import IDF

IDF.setiddname(str(config.IDD_FILE))
idf = IDF(str(config.BASELINE_IDF))

print("=" * 70)
print("THERMOSTATSETPOINT:DUALSETPOINT objects")
print("=" * 70)
dualsetpoints = idf.idfobjects.get("THERMOSTATSETPOINT:DUALSETPOINT", [])
if not dualsetpoints:
    print("None found. Your model may use a different thermostat object type "
          "(e.g. ThermostatSetpoint:SingleCooling / SingleHeating, or ZoneControl:Thermostat "
          "referencing a different control type list). Paste the ZoneControl:Thermostat "
          "objects instead.")
for obj in dualsetpoints:
    print(f"Name: {obj.Name}")
    print(f"  Cooling schedule -> {obj.Cooling_Setpoint_Temperature_Schedule_Name}")
    print(f"  Heating schedule -> {obj.Heating_Setpoint_Temperature_Schedule_Name}")
    print()

print("=" * 70)
print("All Schedule:Compact names")
print("=" * 70)
for sched in idf.idfobjects.get("SCHEDULE:COMPACT", []):
    print(f"  - {sched.Name}")

print("=" * 70)
print("All Schedule:Constant names")
print("=" * 70)
for sched in idf.idfobjects.get("SCHEDULE:CONSTANT", []):
    print(f"  - {sched.Name}  (value: {sched.Hourly_Value})")

print("=" * 70)
print("ZoneControl:Thermostat objects (in case DualSetpoint wasn't found above)")
print("=" * 70)
for obj in idf.idfobjects.get("ZONECONTROL:THERMOSTAT", []):
    print(f"Name: {obj.Name}, Zone: {obj.Zone_or_ZoneList_Name}")
    print(f"  Control type schedule -> {obj.Control_Type_Schedule_Name}")