"""
agent/optimizer.py
Wraps the LLM call with retry logic (self-correction) and a deterministic
rule-based fallback, so a single flaky LLM response can't crash the whole
closed-loop pipeline during a live demo.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from agent.llm import get_setpoint_decision, LLMError

MAX_RETRIES = 2

# CHANGED: threshold-based, not "any violation at all". A baseline with 0.01% comfort
# violation (2 timesteps out of 14,355) is effectively perfect - treating that as a trigger
# for "pull back" (as `if violations > 0` did) meant the fallback almost always assumed a
# comfort problem even when there wasn't a meaningful one. Prefer config.COMFORT_VIOLATION_THRESHOLD_PCT
# if you add it to config.py; otherwise this defaults to 2.0%.
DEFAULT_COMFORT_THRESHOLD_PCT = 2.0


def _rule_based_fallback(metrics: dict, prev_cooling: float, prev_heating: float,
                          prev_comfort_pct: float | None = None) -> dict:
    """
    Deterministic backup strategy: if comfort_violation_pct is at/above threshold, OR has
    gotten worse than the previous cycle, pull setpoints back toward the comfort band;
    otherwise nudge cooling setpoint up (saves energy) by 0.5C, staying within the
    configured safety bounds.
    """
    threshold = getattr(config, "COMFORT_VIOLATION_THRESHOLD_PCT", DEFAULT_COMFORT_THRESHOLD_PCT)
    current_pct = metrics.get("comfort_violation_pct", 0.0)

    got_worse = prev_comfort_pct is not None and current_pct > prev_comfort_pct
    above_threshold = current_pct > threshold

    if got_worse or above_threshold:
        cooling = max(config.COOLING_SETPOINT_MIN_C, prev_cooling - 0.5)
        heating = min(config.HEATING_SETPOINT_MAX_C, prev_heating + 0.5)
        reasoning = (
            f"Fallback rule: comfort_violation_pct={current_pct}% "
            f"(threshold={threshold}%, previous={prev_comfort_pct}%) - pulling setpoints "
            f"toward comfort band."
        )
    else:
        cooling = min(config.COOLING_SETPOINT_MAX_C, prev_cooling + 0.5)
        heating = max(config.HEATING_SETPOINT_MIN_C, prev_heating - 0.5)
        reasoning = (
            f"Fallback rule: comfort_violation_pct={current_pct}% is within threshold "
            f"({threshold}%) and not worse than previous cycle - relaxing setpoints "
            f"slightly to save energy."
        )

    return {
        "cooling_setpoint_c": cooling,
        "heating_setpoint_c": heating,
        "reasoning": reasoning,
        "source": "rule_based_fallback",
    }


def decide_next_setpoints(metrics: dict, cycle_number: int, prev_cooling: float, prev_heating: float,
                           prev_comfort_pct: float | None = None) -> dict:
    """
    Main entry point used by controller/pipeline.py.
    Tries the LLM up to MAX_RETRIES times; falls back to a deterministic rule
    if the LLM is unreachable or keeps returning bad output. This satisfies
    the "self-correcting loop" requirement even in a live-demo environment
    where the local LLM might hiccup.

    prev_comfort_pct: the comfort_violation_pct from the previous cycle (or baseline for
    cycle 1). Passed through to both the LLM prompt and the rule-based fallback so both
    paths can enforce "don't make comfort worse than last cycle."
    """
    system_prompt = SYSTEM_PROMPT.format(
        cooling_min=config.COOLING_SETPOINT_MIN_C, cooling_max=config.COOLING_SETPOINT_MAX_C,
        heating_min=config.HEATING_SETPOINT_MIN_C, heating_max=config.HEATING_SETPOINT_MAX_C,
        comfort_min=config.COMFORT_TEMP_MIN_C, comfort_max=config.COMFORT_TEMP_MAX_C,
        comfort_budget_pct=getattr(config, "COMFORT_VIOLATION_THRESHOLD_PCT", DEFAULT_COMFORT_THRESHOLD_PCT),
    )
    user_prompt = build_user_prompt(
        metrics, cycle_number, prev_cooling, prev_heating,
        comfort_min=config.COMFORT_TEMP_MIN_C, comfort_max=config.COMFORT_TEMP_MAX_C,
        prev_comfort_pct=prev_comfort_pct,
    )

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            decision = get_setpoint_decision(system_prompt, user_prompt)
            decision["source"] = "llm"
            decision["attempt"] = attempt
            return decision
        except LLMError as e:
            last_error = e
            print(f"[optimizer] LLM attempt {attempt} failed: {e}")

    print(f"[optimizer] All {MAX_RETRIES} LLM attempts failed ({last_error}). Using rule-based fallback.")
    return _rule_based_fallback(metrics, prev_cooling, prev_heating, prev_comfort_pct)