# EcoLoop Building AI — System Architecture

## 1. Problem

Buildings account for ~40% of global energy use. Traditional BMS use static, rule-based
schedules that can't adapt to real-time weather, occupancy, or comfort feedback. EcoLoop
closes that loop: EnergyPlus simulates a real building, and an open-source LLM (Qwen3.6-27B, hosted on Groq's
low-latency inference API) reasons over the results to autonomously adjust thermostat
setpoints, then re-runs the simulation to verify the effect — a supervisory, closed-loop
controller.

## 2. Architecture

```
        ┌────────────────────┐
        │  Baseline IDF/EPW  │
        └─────────┬──────────┘
                   │
                   ▼
        ┌────────────────────┐
        │  runner.py          │  subprocess -> EnergyPlus.exe
        └─────────┬──────────┘
                   │ eplusout.csv
                   ▼
        ┌────────────────────┐
        │  reader.py           │  pandas -> structured metrics dict
        └─────────┬──────────┘
                   │ JSON metrics
                   ▼
        ┌────────────────────┐
        │  agent/optimizer.py  │  builds prompt, calls LLM, retries, falls back
        └─────────┬──────────┘
                   │ {cooling_setpoint_c, heating_setpoint_c, reasoning}
                   ▼
        ┌────────────────────┐
        │  modifier.py          │  eppy edits Schedule:Compact/Constant, clamps to safety bounds
        └─────────┬──────────┘
                   │ new IDF
                   └────────────► back to runner.py (next cycle)

  All cycles logged to data/cycle_history.json → dashboard/app.py (Streamlit)
```

## 3. Tool-Calling / Agentic Design

The LLM is not given free-form control of the building. It is treated as a decision function
inside a constrained tool pipeline:

1. **Structured input tool** (`reader.py`) — converts raw EnergyPlus CSV output into a compact
   JSON metrics object (energy totals, zone temperatures, comfort violations). This keeps the
   prompt short and deterministic instead of dumping the entire simulation log at the model.
2. **Structured output contract** — the system prompt forces the LLM to respond with a single
   JSON object (`cooling_setpoint_c`, `heating_setpoint_c`, `reasoning`). `agent/llm.py` strips
   markdown fences and extracts the JSON object defensively, since local open-source models
   sometimes wrap output in prose despite instructions.
3. **Actuation tool** (`modifier.py`) — the only way the LLM's decision reaches the simulation
   is through this module, which clamps every value to safety bounds defined in `config.py`
   before writing a new IDF. The LLM can propose, but it can never bypass the safety rails.
4. **Self-correction** (`agent/optimizer.py`) — if the LLM call fails or returns malformed JSON,
   the optimizer retries up to `MAX_RETRIES` times, then falls back to a deterministic
   rule-based controller (tighten setpoints on comfort violation, relax them when comfort is
   satisfied) so a flaky local LLM never crashes a live demo.

## 4. Prompt Engineering Strategy

- **System prompt** encodes hard constraints (setpoint bounds, comfort band, required JSON
  shape) once, so the per-cycle user prompt can stay short.
- **User prompt** is templated from the metrics dict and includes the *previous* setpoints, so
  the model reasons incrementally ("previous setpoints did X, energy/comfort turned out Y,
  adjust from here") instead of guessing from a blank slate each cycle.
- **Low temperature (0.2)** is used to keep setpoint decisions stable and reproducible across
  demo runs, since this is a control system, not a creative task.

## 5. Handling Long Simulation Logs

Raw EnergyPlus stdout/`.err` logs can be thousands of lines. We never feed these to the LLM.
Instead:
- `reader.py` reduces a full annual simulation's CSV output to a small set of aggregate
  numbers (kWh totals, per-zone temperature summary stats, a single comfort-violation count).
- Full raw outputs are still kept on disk (`eplusout.csv`, `.err`, `.audit`) for debugging and
  are linked in `cycle_history.json`, but only the compact summary is ever sent to the LLM —
  keeping token usage and latency low enough for multiple optimization cycles within a demo.

## 6. Latency Management

Each optimization cycle costs one full EnergyPlus run (seconds to ~1 min for a small model)
plus one Groq API call. Groq's LPU inference is fast (typically well under 2s for a short
JSON response from Qwen3.6-27B), which keeps multi-cycle demos snappy without needing local
GPU hardware. `config.py` caps `MAX_OPTIMIZATION_CYCLES` (default 3) so a live demo stays
within a predictable time budget and API rate limit; this can be raised for longer post-demo
evaluation runs.

## 7. What We Deliberately Did Not Build (and why)

Given the same-day deadline, we used the official `subprocess` call to `EnergyPlus.exe`
(Method 1) rather than the `pyenergyplus` runtime callback API (Method 2). The callback API
enables true intra-timestep control but requires substantially more integration work and is
less reliable to demo live. The supervisory loop (run → read → decide → modify → re-run) still
satisfies the hackathon's closed-loop requirement while being robust enough to demo confidently.
