"""
energyplus/reader.py
Reads eplusout.csv (produced by runner.py) and converts it into the
structured metrics dictionary that the LLM agent consumes.

This is intentionally column-name-flexible: EnergyPlus column headers depend
on exactly which Output:Variable objects exist in your IDF, so instead of
hard-coding one exact string, we search for columns containing key phrases.
"""

import sys
import json
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config


def _find_columns(df: pd.DataFrame, keywords: list[str], exclude: list[str] | None = None) -> list[str]:
    """
    Return all column names that contain ALL of the given keywords (case-insensitive)
    and NONE of the excluded terms. By default we exclude Rate[W] columns from anything
    meant to be summed as energy, since a power reading is not directly additive into kWh
    the way an accumulated Energy[J] or Meter[J] column is.
    """
    exclude = exclude or []
    matches = []
    for col in df.columns:
        col_lower = col.lower()
        if all(kw.lower() in col_lower for kw in keywords) and not any(ex.lower() in col_lower for ex in exclude):
            matches.append(col)
    return matches


def _sum_energy_columns(df: pd.DataFrame, columns: list[str]) -> float:
    """
    Sums an energy column across the run period and converts Joules -> kWh.
    Only valid for columns reported in Joules (Output:Meter and most
    '...Energy' Output:Variable results). Never pass Rate[W] columns here -
    callers are responsible for filtering those out via _find_columns' exclude param.
    """
    if not columns:
        return 0.0
    total_j = df[columns].sum().sum()
    return round(total_j / 3_600_000, 3)  # J -> kWh


def read_results(output_dir: Path) -> dict:
    """
    Parses eplusout.csv inside output_dir and returns a metrics dictionary:

    {
        "total_energy_kwh": float,
        "cooling_energy_kwh": float,
        "heating_energy_kwh": float,
        "hvac_electricity_kwh": float,
        "zone_temperatures": {zone_name: {"mean": .., "min": .., "max": ..}},
        "outdoor_air_temp": {"mean": .., "min": .., "max": ..},
        "comfort_violations": int,          # raw count, kept for backward compatibility
        "comfort_timesteps_considered": int,# denominator used for the rate below
        "comfort_violation_pct": float,     # THE number to report/feed back to the LLM
        "comfort_violation_by_zone": {...}, # per-zone breakdown for debugging/reporting
        "comfort_occupancy_filtered": bool, # True only if an occupancy column was found
        "raw_columns_found": [...]          # for debugging / transparency in the report
    }
    """
    output_dir = Path(output_dir)
    csv_path = output_dir / "eplusout.csv"

    if not csv_path.exists():
        raise FileNotFoundError(
            f"eplusout.csv not found in {output_dir}. "
            "Make sure the simulation completed and that your IDF has "
            "an Output:Variable / Output:Table:SummaryReports set to produce CSV output."
        )

    df = pd.read_csv(csv_path)

    metrics: dict = {}

    # ---- Energy totals ----
    # Prefer whole-building Meter columns (Electricity:Facility etc.) for the top-line total -
    # these are already accumulated Joules per interval, unlike instantaneous Rate[W] readings.
    electricity_cols = _find_columns(df, ["electricity:facility"])
    if not electricity_cols:
        # fall back to any electricity Energy column, but never a Rate[W] column
        electricity_cols = _find_columns(df, ["electricity"], exclude=["rate"])

    # Cooling/heating: use ONLY the zone-level "delivered energy" variable. The same
    # thermal energy also gets reported at the coil and at the boiler/chiller - summing
    # all of those together would count the same energy multiple times.
    cooling_cols = _find_columns(df, ["zone air system sensible cooling energy"])
    heating_cols = _find_columns(df, ["zone air system sensible heating energy"])
    hvac_elec_cols = _find_columns(df, ["electricity:hvac"])
    if not hvac_elec_cols:
        hvac_elec_cols = [c for c in electricity_cols if "hvac" in c.lower() or "coil" in c.lower() or "fan" in c.lower()]

    metrics["total_energy_kwh"] = _sum_energy_columns(df, electricity_cols)
    metrics["cooling_energy_kwh"] = _sum_energy_columns(df, cooling_cols)
    metrics["heating_energy_kwh"] = _sum_energy_columns(df, heating_cols)
    metrics["hvac_electricity_kwh"] = _sum_energy_columns(df, hvac_elec_cols)

    # ---- Zone temperatures ----
    zone_temp_cols = _find_columns(df, ["zone", "mean air temperature"])
    zone_temps = {}
    for col in zone_temp_cols:
        zone_name = col.split(":")[0].strip()
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series):
            zone_temps[zone_name] = {
                "mean": round(series.mean(), 2),
                "min": round(series.min(), 2),
                "max": round(series.max(), 2),
            }
    metrics["zone_temperatures"] = zone_temps

    # ---- Outdoor air temp ----
    outdoor_cols = _find_columns(df, ["outdoor air drybulb"])
    if outdoor_cols:
        series = pd.to_numeric(df[outdoor_cols[0]], errors="coerce").dropna()
        metrics["outdoor_air_temp"] = {
            "mean": round(series.mean(), 2),
            "min": round(series.min(), 2),
            "max": round(series.max(), 2),
        }
    else:
        metrics["outdoor_air_temp"] = None

    # ---- Comfort violations (band check, normalized to a rate) ----
    # Plenums are unconditioned return-air space, not occupied space - including them would
    # unfairly penalize the AI for a temperature swing it was never trying to control.
    #
    # CHANGED vs original: the old version summed raw out-of-band timesteps across every
    # non-plenum zone with NO denominator and NO occupancy filter. That's why the number
    # (10,445) was uninterpretable - it mixed unoccupied overnight hours in with occupied
    # hours, and had nothing to divide by. This version adds both.
    occupied_zone_cols = _find_columns(df, ["zone", "people occupant count"])

    violations = 0
    total_considered = 0
    per_zone_detail = {}

    for zone_name, col in zip(zone_temps.keys(), zone_temp_cols):
        if "plenum" in zone_name.lower():
            continue

        temp_series = pd.to_numeric(df[col], errors="coerce")

        # Try to find a matching occupancy column for this zone to filter out unoccupied hours.
        occ_col = next((c for c in occupied_zone_cols if zone_name.lower() in c.lower()), None)
        if occ_col:
            occ_series = pd.to_numeric(df[occ_col], errors="coerce").fillna(0)
            mask = occ_series > 0
        else:
            # No occupancy variable available in this IDF's Output:Variable list -
            # fall back to counting all hours, but flag it so the report stays honest
            # about the fact that this zone's rate includes unoccupied hours.
            mask = pd.Series(True, index=temp_series.index)

        valid = temp_series[mask].dropna()
        zone_violations = int(
            ((valid < config.COMFORT_TEMP_MIN_C) | (valid > config.COMFORT_TEMP_MAX_C)).sum()
        )

        violations += zone_violations
        total_considered += len(valid)
        per_zone_detail[zone_name] = {
            "violations": zone_violations,
            "considered_timesteps": len(valid),
            "violation_pct": round((zone_violations / len(valid)) * 100, 2) if len(valid) else 0.0,
            "occupancy_filtered": occ_col is not None,
        }

    metrics["comfort_violations"] = violations
    metrics["comfort_timesteps_considered"] = total_considered
    metrics["comfort_violation_pct"] = (
        round((violations / total_considered) * 100, 2) if total_considered else 0.0
    )
    metrics["comfort_violation_by_zone"] = per_zone_detail
    metrics["comfort_occupancy_filtered"] = any(
        d["occupancy_filtered"] for d in per_zone_detail.values()
    )

    metrics["raw_columns_found"] = {
        "electricity": electricity_cols,
        "cooling": cooling_cols,
        "heating": heating_cols,
        "zone_temperature": zone_temp_cols,
        "outdoor_air": outdoor_cols,
        "occupancy": occupied_zone_cols,
    }

    return metrics


def save_metrics(metrics: dict, filename: str):
    """Persists metrics as JSON to the data/ folder for the dashboard to consume later."""
    out_path = config.DATA_DIR / filename
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved to {out_path}")


if __name__ == "__main__":
    # Quick manual test against the baseline run
    results = read_results(config.BASELINE_OUTPUT_DIR)
    print(json.dumps(results, indent=2))
    save_metrics(results, "baseline_metrics.json")