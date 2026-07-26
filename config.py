"""
config.py
Central configuration for EcoLoop Building AI.
Every other module imports paths/settings from here so nothing is hard-coded twice.
"""

from pathlib import Path

# =========================================================
# PROJECT ROOT
# =========================================================
PROJECT_ROOT = Path(r"D:\EcoLoopBuildingAI")

# =========================================================
# ENERGYPLUS
# =========================================================
ENERGYPLUS_EXE = Path(r"C:\EnergyPlusV26-1-0\energyplus.exe")
IDD_FILE = Path(r"C:\EnergyPlusV26-1-0\Energy+.idd")

MODELS_DIR = PROJECT_ROOT / "energyplus" / "models"
WEATHER_DIR = PROJECT_ROOT / "energyplus" / "weather"

BASELINE_IDF = MODELS_DIR / "5ZoneAirCooled_AirBoundaries.idf"
WEATHER_FILE = WEATHER_DIR / "IND_Chennai-Madras.432790_ISHRAE.epw"

BASELINE_OUTPUT_DIR = PROJECT_ROOT / "energyplus" / "baseline_output"
OPTIMIZED_OUTPUT_DIR = PROJECT_ROOT / "energyplus" / "optimized_output"

# Where each optimization cycle's modified IDF gets written
MODIFIED_IDF_DIR = PROJECT_ROOT / "energyplus" / "modified_models"

# =========================================================
# LLM / GROQ
# =========================================================
# Groq exposes an OpenAI-compatible endpoint - we just swap base URL + model + auth.
# Get a free key at https://console.groq.com/keys and set it as an environment variable:
#   Windows (PowerShell):  setx GROQ_API_KEY "your-key-here"   (then reopen your terminal)
# Never hard-code the key in this file, especially if this repo is going public for the hackathon.
import os

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3.6-27b"   # Groq's current Qwen 3.6 27B reasoning model, verify at console.groq.com/docs/models
GROQ_TIMEOUT_SECONDS = 120

# =========================================================
# CONTROL LOOP
# =========================================================
MAX_OPTIMIZATION_CYCLES = 8       # SAFETY CAP, not a fixed target - the loop stops earlier if it
                                   # converges (see CONVERGENCE_PATIENCE below); this just prevents
                                   # a runaway loop from eating your whole demo window if the LLM
                                   # never converges
CONVERGENCE_PATIENCE = 2           # stop after this many consecutive cycles with no meaningful
                                   # improvement over the best-so-far (within-budget) energy result
MIN_IMPROVEMENT_PCT = 0.3          # a cycle only counts as "improved" if it beats the best-so-far
                                   # energy by at least this % - avoids stopping/continuing on tiny
                                   # float noise between near-identical results
COMFORT_TEMP_MIN_C = 22.0        # acceptable zone temperature band for occupant comfort
COMFORT_TEMP_MAX_C = 26.0

# Acceptable ceiling for % of occupied hours allowed outside the comfort band.
# This is an ABSOLUTE budget, not "must match baseline" - baseline can be near-perfect
# (e.g. 0.01%) simply because it barely stresses the HVAC system, which would make it
# mathematically un-beatable and defeat the purpose of optimizing at all. 5% is in line
# with real-world comfort standards (e.g. ASHRAE 55's adaptive comfort model accepts a
# bounded percentage of occupied hours outside the ideal band) - adjust if you want a
# stricter or looser story for your report.
COMFORT_VIOLATION_THRESHOLD_PCT = 5.0

# Setpoint bounds the AI is allowed to move within (safety rails so the LLM can't do something absurd)
COOLING_SETPOINT_MIN_C = 22.0
COOLING_SETPOINT_MAX_C = 26.0
HEATING_SETPOINT_MIN_C = 18.0
HEATING_SETPOINT_MAX_C = 21.0

# =========================================================
# LOGGING / DATA
# =========================================================
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
CYCLE_HISTORY_FILE = DATA_DIR / "cycle_history.json"

for _dir in (BASELINE_OUTPUT_DIR, OPTIMIZED_OUTPUT_DIR, MODIFIED_IDF_DIR, LOGS_DIR, DATA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)