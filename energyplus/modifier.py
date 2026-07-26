"""
energyplus/modifier.py
Applies AI-decided setpoint changes to a copy of the IDF, using eppy.

We deliberately work on the SCHEDULE:COMPACT / SCHEDULE:CONSTANT objects that
back the thermostat setpoints (rather than hand-rolling regex on the raw IDF
text) because that's the robust, EnergyPlus-native way to do it and eppy
already understands IDF syntax and validates against Energy+.idd.

Install once:  pip install eppy
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config

from eppy.modeleditor import IDF


def _init_idf():
    """eppy needs the IDD registered once per process before you can open any IDF."""
    if IDF.getiddname() is None:
        IDF.setiddname(str(config.IDD_FILE))


def _is_cooling_setpoint_schedule(name: str) -> bool:
    n = name.lower()
    if "plenum" in n:
        return False  # plenums are unconditioned space - never touch their setpoints
    has_cooling_word = "cool" in n or "clg" in n
    has_setpoint_word = "setp" in n  # covers "setpoint" and the common "SetP" abbreviation
    return has_cooling_word and has_setpoint_word


def _is_heating_setpoint_schedule(name: str) -> bool:
    n = name.lower()
    if "plenum" in n:
        return False
    has_heating_word = "heat" in n or "htg" in n
    has_setpoint_word = "setp" in n
    return has_heating_word and has_setpoint_word


def _set_occupied_setpoint(sched, new_value_c: float, comfort_target_c: float):
    """
    Surgically updates ONLY the occupied-hours setpoint value inside a
    Schedule:Compact, leaving everything else untouched:

      - SummerDesignDay / WinterDesignDay blocks are SKIPPED ENTIRELY. These
        drive EnergyPlus's HVAC autosizing (the "Performing Zone Sizing
        Simulation" step). Overwriting them silently changes your equipment
        capacity every cycle, which is what was making energy/comfort behave
        unpredictably before this fix.
      - Night/weekend SETBACK values are left alone on purpose - that's the
        building's existing energy-saving strategy, not something the AI is
        trying to control here.
      - Only the single value CLOSEST to the comfort band's midpoint is
        treated as "the occupied setpoint" and updated. In a typical setback
        schedule that value sits near the comfort band (e.g. 23.9C) while
        setback values sit far outside it (e.g. 29.4C), so this heuristic
        reliably finds the right field without hard-coding field positions.
    """
    current_block = ""
    candidates = []  # (fieldname, current_value)

    for fieldname in sched.fieldnames:
        if not fieldname.startswith("Field_"):
            continue
        val = getattr(sched, fieldname, "")
        if not isinstance(val, str):
            continue
        val = val.strip()
        if val == "":
            continue

        if val.lower().startswith("for:"):
            current_block = val.lower()
            continue
        if val.lower().startswith("through:") or val.lower().startswith("until:"):
            continue

        try:
            num = float(val)
        except (ValueError, TypeError):
            continue

        if "designday" in current_block:
            continue  # never touch HVAC autosizing periods

        candidates.append((fieldname, num))

    if not candidates:
        return False

    # Pick the candidate closest to the comfort band midpoint - that's the
    # occupied setpoint, as opposed to a setback value sitting far outside it.
    best_fieldname, _ = min(candidates, key=lambda c: abs(c[1] - comfort_target_c))
    setattr(sched, best_fieldname, new_value_c)
    return True


def apply_setpoints(source_idf: Path, cooling_setpoint_c: float, heating_setpoint_c: float, cycle_number: int) -> Path:
    """
    Loads source_idf, overwrites all THERMOSTATSETPOINT:DUALSETPOINT-linked
    schedules' constant values with the new setpoints, and saves the result
    as a new IDF file so the original baseline is never mutated.

    Returns the path to the newly written IDF.
    """
    # Safety clamp - never let the LLM push setpoints outside physically sane / safe bounds
    cooling_setpoint_c = max(config.COOLING_SETPOINT_MIN_C, min(config.COOLING_SETPOINT_MAX_C, cooling_setpoint_c))
    heating_setpoint_c = max(config.HEATING_SETPOINT_MIN_C, min(config.HEATING_SETPOINT_MAX_C, heating_setpoint_c))

    _init_idf()
    idf = IDF(str(source_idf))

    modified_count = {"cooling": 0, "heating": 0}
    comfort_mid = (config.COMFORT_TEMP_MIN_C + config.COMFORT_TEMP_MAX_C) / 2

    # Most simple models use Schedule:Compact objects named like "Cooling Setpoint" / "Heating Setpoint".
    # We match by name heuristically, which covers common example files (e.g. 5ZoneAirCooled).
    for sched in idf.idfobjects.get("SCHEDULE:COMPACT", []):
        if _is_cooling_setpoint_schedule(sched.Name):
            if _set_occupied_setpoint(sched, cooling_setpoint_c, comfort_mid):
                modified_count["cooling"] += 1
        elif _is_heating_setpoint_schedule(sched.Name):
            if _set_occupied_setpoint(sched, heating_setpoint_c, comfort_mid):
                modified_count["heating"] += 1

    for sched in idf.idfobjects.get("SCHEDULE:CONSTANT", []):
        if _is_cooling_setpoint_schedule(sched.Name):
            sched.Hourly_Value = cooling_setpoint_c
            modified_count["cooling"] += 1
        elif _is_heating_setpoint_schedule(sched.Name):
            sched.Hourly_Value = heating_setpoint_c
            modified_count["heating"] += 1

    if modified_count["cooling"] == 0 and modified_count["heating"] == 0:
        print(
            "WARNING: No setpoint schedules matched by name heuristics. "
            "Open the IDF and check the exact Schedule:Compact / Schedule:Constant "
            "names feeding your ThermostatSetpoint:DualSetpoint object, then adjust "
            "the matching logic in modifier.py accordingly."
        )

    timestamp = datetime.now().strftime("%H%M%S")
    out_path = config.MODIFIED_IDF_DIR / f"cycle{cycle_number}_{timestamp}.idf"
    idf.saveas(str(out_path))

    print(f"Applied setpoints -> cooling: {cooling_setpoint_c}C, heating: {heating_setpoint_c}C")
    print(f"Modified objects -> {modified_count}")
    print(f"New IDF written to: {out_path}")

    return out_path


if __name__ == "__main__":
    # Manual smoke test
    new_idf = apply_setpoints(config.BASELINE_IDF, cooling_setpoint_c=25.0, heating_setpoint_c=19.0, cycle_number=1)
    print("Done:", new_idf)