# EcoLoop Building AI

Autonomous closed-loop HVAC optimization: EnergyPlus + a local open-source LLM (via Ollama).

## Folder Structure

```
EcoLoopBuildingAI/
├── energyplus/
│   ├── models/            <- put 5ZoneAirCooled_AirBoundaries.idf here
│   ├── weather/            <- put the .epw file here
│   ├── baseline_output/    <- auto-generated
│   ├── optimized_output/   <- auto-generated, one subfolder per cycle
│   ├── modified_models/    <- auto-generated IDFs the AI produces
│   ├── runner.py           <- runs EnergyPlus
│   ├── reader.py           <- parses eplusout.csv into metrics
│   └── modifier.py         <- edits thermostat setpoints via eppy
├── agent/
│   ├── prompts.py          <- system/user prompt templates
│   ├── llm.py               <- Ollama client + JSON parsing
│   └── optimizer.py         <- decision logic with retry + fallback
├── controller/
│   └── pipeline.py          <- the actual closed loop
├── dashboard/
│   └── app.py                <- Streamlit dashboard
├── docs/
│   └── architecture.md      <- deliverable #4
├── data/                    <- cycle_history.json (generated)
├── logs/
├── config.py
├── main.py
└── requirements.txt
```

## Setup

1. Copy this whole folder to `D:\EcoLoopBuildingAI` (or update `PROJECT_ROOT` in `config.py`).
2. Place `5ZoneAirCooled_AirBoundaries.idf` in `energyplus/models/` and the `.epw` in `energyplus/weather/`.
3. Confirm `ENERGYPLUS_EXE` and `IDD_FILE` in `config.py` point to your real EnergyPlus install
   (needs both `energyplus.exe` and `Energy+.idd`).
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Get a free Groq API key at https://console.groq.com/keys and set it as an environment variable:
   ```
   # Windows PowerShell (then close and reopen the terminal)
   setx GROQ_API_KEY "your-key-here"

   # macOS/Linux
   export GROQ_API_KEY="your-key-here"
   ```
   The project uses `qwen/qwen3.6-27b` on Groq by default (`GROQ_MODEL` in `config.py`) —
   double check that model ID is still current at https://console.groq.com/docs/models
   before your demo, since hosted model lineups change.

## Run the full closed loop

```
python main.py
```

This runs the baseline simulation, then up to `MAX_OPTIMIZATION_CYCLES` (config.py) rounds of
AI-driven optimization, saving everything to `data/cycle_history.json`.

## View the dashboard

```
streamlit run dashboard/app.py
```

## Notes for the demo video

- Show `python main.py` running end-to-end in the terminal (this is the "live data transfer"
  the rubric asks for — you'll see EnergyPlus output, then the AI's JSON decision printed,
  then the next simulation starting).
- Then show the Streamlit dashboard with baseline vs optimized energy and the reasoning log.
