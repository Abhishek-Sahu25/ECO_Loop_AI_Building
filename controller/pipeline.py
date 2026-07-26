"""
controller/pipeline.py
The closed-loop controller that ties together every piece:

    Baseline run
        -> read metrics
    Loop (MAX_OPTIMIZATION_CYCLES times):
        -> LLM decides new setpoints
        -> modifier writes a new IDF
        -> runner runs EnergyPlus again
        -> reader extracts new metrics
    Save full cycle history for the dashboard.

Run directly:  python controller/pipeline.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config
from energyplus.runner import run_simulation, run_baseline
from energyplus.reader import read_results
from energyplus.modifier import apply_setpoints
from agent.optimizer import decide_next_setpoints


def run_closed_loop() -> list[dict]:
    history = []

    # ---- Baseline cycle (cycle 0, no AI involvement) ----
    print("\n########## BASELINE RUN ##########")
    baseline_run = run_baseline()
    if not baseline_run["success"]:
        raise RuntimeError(f"Baseline simulation failed:\n{baseline_run['stderr']}")

    baseline_metrics = read_results(config.BASELINE_OUTPUT_DIR)
    history.append({
        "cycle": 0,
        "label": "baseline",
        "idf_used": str(config.BASELINE_IDF),
        "cooling_setpoint_c": None,
        "heating_setpoint_c": None,
        "metrics": baseline_metrics,
        "decision_source": None,
        "reasoning": "Unmodified baseline schedule.",
        "timestamp": datetime.now().isoformat(),
    })
    print(f"Baseline total energy: {baseline_metrics['total_energy_kwh']} kWh")
    print(f"Baseline comfort violation: {baseline_metrics['comfort_violation_pct']}% "
          f"({baseline_metrics['comfort_violations']} / {baseline_metrics['comfort_timesteps_considered']} timesteps)")

    # ---- Optimization cycles ----
    current_idf = config.BASELINE_IDF
    prev_cooling, prev_heating = 24.0, 20.0  # reasonable starting assumption; adjust to your IDF defaults
    current_metrics = baseline_metrics
    prev_comfort_pct = baseline_metrics["comfort_violation_pct"]

    budget_pct = getattr(config, "COMFORT_VIOLATION_THRESHOLD_PCT", 5.0)
    min_improvement_pct = getattr(config, "MIN_IMPROVEMENT_PCT", 0.3)
    patience = getattr(config, "CONVERGENCE_PATIENCE", 2)

    # CHANGED: this is no longer "run exactly N cycles". It's a converge-until-no-improvement
    # loop, matching the hackathon's "closed loop" requirement more literally - the loop keeps
    # going as long as it's still finding better within-budget results, and stops itself once it
    # stalls, rather than stopping at an arbitrary fixed count. config.MAX_OPTIMIZATION_CYCLES is
    # now only a safety cap so a live demo can't run indefinitely.
    best_energy_within_budget = (
        baseline_metrics["total_energy_kwh"] if baseline_metrics["comfort_violation_pct"] <= budget_pct
        else float("inf")
    )
    cycles_without_improvement = 0

    for cycle in range(1, config.MAX_OPTIMIZATION_CYCLES + 1):
        print(f"\n########## OPTIMIZATION CYCLE {cycle} ##########")

        decision = decide_next_setpoints(current_metrics, cycle, prev_cooling, prev_heating, prev_comfort_pct)
        cooling_sp = decision["cooling_setpoint_c"]
        heating_sp = decision["heating_setpoint_c"]
        print(f"AI decision ({decision['source']}): cooling={cooling_sp}C heating={heating_sp}C")
        print(f"Reasoning: {decision.get('reasoning')}")

        new_idf = apply_setpoints(current_idf, cooling_sp, heating_sp, cycle_number=cycle)

        cycle_output_dir = config.OPTIMIZED_OUTPUT_DIR / f"cycle_{cycle}"
        run_result = run_simulation(new_idf, cycle_output_dir)

        if not run_result["success"]:
            print(f"Cycle {cycle} simulation FAILED - stopping loop early and keeping prior best result.")
            history.append({
                "cycle": cycle,
                "label": f"cycle_{cycle}_failed",
                "idf_used": str(new_idf),
                "cooling_setpoint_c": cooling_sp,
                "heating_setpoint_c": heating_sp,
                "metrics": None,
                "decision_source": decision["source"],
                "reasoning": decision.get("reasoning"),
                "error": run_result["stderr"],
                "timestamp": datetime.now().isoformat(),
            })
            break

        cycle_metrics = read_results(cycle_output_dir)
        history.append({
            "cycle": cycle,
            "label": f"cycle_{cycle}",
            "idf_used": str(new_idf),
            "cooling_setpoint_c": cooling_sp,
            "heating_setpoint_c": heating_sp,
            "metrics": cycle_metrics,
            "decision_source": decision["source"],
            "reasoning": decision.get("reasoning"),
            "timestamp": datetime.now().isoformat(),
        })

        print(f"Cycle {cycle} total energy: {cycle_metrics['total_energy_kwh']} kWh "
              f"(baseline: {baseline_metrics['total_energy_kwh']} kWh)")
        print(f"Cycle {cycle} comfort violation: {cycle_metrics['comfort_violation_pct']}% "
              f"(baseline: {baseline_metrics['comfort_violation_pct']}%)")

        current_idf = new_idf
        current_metrics = cycle_metrics
        prev_cooling, prev_heating = cooling_sp, heating_sp
        prev_comfort_pct = cycle_metrics["comfort_violation_pct"]

        # ---- Convergence check ----
        # Only cycles within the comfort budget are eligible to count as "improvement" -
        # a cycle that saves more energy by blowing past the comfort budget doesn't reset
        # the patience counter, since it's not a result we'd actually select as best anyway.
        if cycle_metrics["comfort_violation_pct"] <= budget_pct:
            improvement_pct = (
                (best_energy_within_budget - cycle_metrics["total_energy_kwh"])
                / best_energy_within_budget * 100
                if best_energy_within_budget != float("inf") else 100.0
            )
            if improvement_pct >= min_improvement_pct:
                print(f"Improved on best-so-far by {round(improvement_pct, 2)}% "
                      f"(threshold: {min_improvement_pct}%) - resetting patience counter.")
                best_energy_within_budget = cycle_metrics["total_energy_kwh"]
                cycles_without_improvement = 0
            else:
                cycles_without_improvement += 1
                print(f"No meaningful improvement within budget this cycle "
                      f"({round(improvement_pct, 2)}% < {min_improvement_pct}% threshold). "
                      f"Cycles without improvement: {cycles_without_improvement}/{patience}.")
        else:
            cycles_without_improvement += 1
            print(f"Cycle {cycle} exceeded the comfort budget ({budget_pct}%) - does not count as "
                  f"improvement. Cycles without improvement: {cycles_without_improvement}/{patience}.")

        if cycles_without_improvement >= patience:
            print(f"\nConverged: no within-budget improvement for {patience} consecutive cycles. "
                  f"Stopping the loop early at cycle {cycle} (safety cap was {config.MAX_OPTIMIZATION_CYCLES}).")
            break
    else:
        print(f"\nReached the safety cap of {config.MAX_OPTIMIZATION_CYCLES} cycles without formally "
              f"converging (patience={patience} was never exhausted). Consider raising "
              f"MAX_OPTIMIZATION_CYCLES if you have runtime budget to keep exploring.")

    _save_history(history)
    _print_summary(history)
    return history


def _save_history(history: list[dict]):
    with open(config.CYCLE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    print(f"\nFull cycle history saved to {config.CYCLE_HISTORY_FILE}")


def _select_best(history: list[dict]) -> dict:
    """
    Picks the best cycle using energy AND comfort, not energy alone.

    CHANGED vs original: the old version did
        best = min(completed, key=lambda h: h["metrics"]["total_energy_kwh"])
    which picks whichever cycle used the least energy full stop, with zero
    regard for comfort. That directly contradicts the "did it save energy at
    the expense of comfort" grading criterion.

    Rule now: among cycles whose comfort_violation_pct stays within an ABSOLUTE
    acceptable budget (config.COMFORT_VIOLATION_THRESHOLD_PCT), pick the lowest
    energy. This is deliberately NOT "must match baseline" - baseline can be
    near-perfect (e.g. 0.01%) simply because it's barely using the HVAC system
    at all, which would make it mathematically un-beatable and defeat the
    entire point of optimizing. A fixed budget (e.g. 5%, in line with
    real-world comfort standards like ASHRAE 55's adaptive comfort model,
    which accept a bounded percentage of hours outside the ideal band) is the
    defensible, real-world-consistent threshold. If no cycle stays within
    budget, fall back to whichever cycle has the lowest comfort_violation_pct,
    breaking ties by energy.
    """
    completed = [h for h in history if h["metrics"] is not None]
    budget_pct = getattr(config, "COMFORT_VIOLATION_THRESHOLD_PCT", 5.0)

    within_budget = [h for h in completed if h["metrics"]["comfort_violation_pct"] <= budget_pct]

    if within_budget:
        return min(within_budget, key=lambda h: h["metrics"]["total_energy_kwh"])

    # No cycle stayed within budget - prioritize comfort over energy
    return min(completed, key=lambda h: (h["metrics"]["comfort_violation_pct"],
                                          h["metrics"]["total_energy_kwh"]))


def _print_summary(history: list[dict]):
    baseline_metrics = history[0]["metrics"]
    baseline_energy = baseline_metrics["total_energy_kwh"]
    baseline_comfort_pct = baseline_metrics["comfort_violation_pct"]

    best = _select_best(history)
    budget_pct = getattr(config, "COMFORT_VIOLATION_THRESHOLD_PCT", 5.0)
    savings_pct = round((baseline_energy - best["metrics"]["total_energy_kwh"]) / baseline_energy * 100, 2)

    print("\n" + "=" * 60)
    print("CLOSED-LOOP OPTIMIZATION SUMMARY")
    print("=" * 60)
    print(f"Baseline energy:              {baseline_energy} kWh")
    print(f"Baseline comfort violation:   {baseline_comfort_pct}%")
    print(f"Acceptable comfort budget:    {budget_pct}% (cycles above this are rejected regardless of energy savings)")
    print(f"Best cycle:                   {best['label']} -> {best['metrics']['total_energy_kwh']} kWh")
    print(f"Best cycle comfort violation: {best['metrics']['comfort_violation_pct']}%")
    print(f"Energy savings:               {savings_pct}%")
    print("=" * 60)

    print("\nPer-cycle breakdown:")
    for h in [x for x in history if x["metrics"] is not None]:
        tag = "  <- SELECTED AS BEST" if h is best else ""
        print(f"  {h['label']:>12}: {h['metrics']['total_energy_kwh']:>10.2f} kWh | "
              f"comfort {h['metrics']['comfort_violation_pct']:>5.2f}%{tag}")


if __name__ == "__main__":
    run_closed_loop()