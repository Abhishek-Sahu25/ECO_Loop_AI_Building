"""
agent/prompts.py
Prompt templates for the LLM optimization agent.
Kept in one place so prompt-engineering iteration doesn't touch pipeline logic.
"""

SYSTEM_PROMPT = """You are EcoLoop, an autonomous HVAC optimization agent for a building
energy management system. You are given simulation results from EnergyPlus and must decide
new thermostat setpoints that reduce energy consumption WITHOUT worsening occupant thermal
comfort.

Rules you must always follow:
1. Cooling setpoint must stay between {cooling_min}C and {cooling_max}C.
2. Heating setpoint must stay between {heating_min}C and {heating_max}C.
3. Zone temperatures should remain within {comfort_min}C - {comfort_max}C as much as possible.
4. "Comfort violation %" below is measured ONLY across occupied hours in occupied zones
   (plenums and unoccupied hours are already excluded) - treat it as the authoritative
   comfort signal, not the raw zone temperature list.
5. Your objective is: maximize energy savings SUBJECT TO comfort_violation_pct staying at
   or below {comfort_budget_pct}% (an absolute ceiling, not just "no worse than last cycle").
   You cannot simulate the outcome of a setpoint change before it happens, so treat setpoint
   changes cautiously, especially as comfort_violation_pct approaches the ceiling:
   - If the previous cycle's comfort_violation_pct is below half the ceiling, a full 0.5C
     step is reasonable.
   - If it is above half the ceiling, only make a small step (0.25C or less) or hold steady,
     since comfort violations can increase non-linearly near the edges of the comfort band
     (small setpoint changes can cause disproportionately large comfort loss during extreme
     outdoor conditions).
   - Never jump straight to the maximum/minimum allowed setpoint bound in a single step
     purely because the previous cycle looked "stable" - stability at one setpoint does not
     predict the outcome at a different one.
6. You must respond with ONLY a JSON object, no prose, no markdown fences, in exactly this shape:
{{
  "cooling_setpoint_c": <number>,
  "heating_setpoint_c": <number>,
  "reasoning": "<one or two sentence explanation>"
}}
"""

USER_PROMPT_TEMPLATE = """Here are the results from the last simulation cycle (cycle {cycle_number}):

Total facility energy: {total_energy_kwh} kWh
Cooling energy: {cooling_energy_kwh} kWh
Heating energy: {heating_energy_kwh} kWh
HVAC electricity: {hvac_electricity_kwh} kWh

Comfort violation % (occupied hours, occupied zones only): {comfort_violation_pct}%
Previous cycle's comfort violation %: {prev_comfort_pct}
  -> Your chosen setpoints must not push comfort violation % above this previous value.

Outdoor air temperature (mean/min/max): {outdoor_summary}
Occupied zone temperature summary (plenum/unconditioned spaces excluded): {zone_summary}

Previous setpoints used: cooling={prev_cooling}C, heating={prev_heating}C

Decide the next cooling and heating setpoints to reduce energy use further while keeping
comfort violation % at or below the previous cycle's value. Respond with the JSON object only.
"""


def build_user_prompt(metrics: dict, cycle_number: int, prev_cooling: float, prev_heating: float,
                       comfort_min: float, comfort_max: float, prev_comfort_pct: float | None = None) -> str:
    # CHANGED: only summarize occupied zones - plenums/unconditioned spaces are excluded so the
    # LLM never reasons about a temperature nobody actually experiences (e.g. return-air plenum
    # readings, which can run much hotter than any occupied space and were previously being
    # cited by the LLM as if they were a comfort problem).
    zone_temps = metrics.get("zone_temperatures", {})
    occupied_zone_temps = {name: vals for name, vals in zone_temps.items() if "plenum" not in name.lower()}

    zone_summary = ", ".join(
        f"{name}: mean {vals['mean']}C (min {vals['min']}, max {vals['max']})"
        for name, vals in occupied_zone_temps.items()
    ) or "no occupied zone temperature data found"

    outdoor = metrics.get("outdoor_air_temp")
    outdoor_summary = (
        f"mean {outdoor['mean']}C / min {outdoor['min']}C / max {outdoor['max']}C"
        if outdoor else "not available"
    )

    # comfort_violation_pct may not exist yet if called against older/dummy metrics dicts -
    # fall back gracefully instead of throwing a KeyError.
    comfort_violation_pct = metrics.get("comfort_violation_pct")
    if comfort_violation_pct is None:
        comfort_violation_pct = "not available"

    prev_comfort_display = prev_comfort_pct if prev_comfort_pct is not None else "not available (first cycle)"

    return USER_PROMPT_TEMPLATE.format(
        cycle_number=cycle_number,
        total_energy_kwh=metrics.get("total_energy_kwh"),
        cooling_energy_kwh=metrics.get("cooling_energy_kwh"),
        heating_energy_kwh=metrics.get("heating_energy_kwh"),
        hvac_electricity_kwh=metrics.get("hvac_electricity_kwh"),
        comfort_violation_pct=comfort_violation_pct,
        prev_comfort_pct=prev_comfort_display,
        outdoor_summary=outdoor_summary,
        zone_summary=zone_summary,
        prev_cooling=prev_cooling,
        prev_heating=prev_heating,
    )