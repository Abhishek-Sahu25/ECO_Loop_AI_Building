from pathlib import Path
import subprocess
import shutil

# =====================================================
# PATHS
# =====================================================

PROJECT_ROOT = Path(r"D:\EcoLoopBuildingAI")

ENERGYPLUS_EXE = Path(r"C:\EnergyPlusV26-1-0\energyplus.exe")

IDF_FILE = PROJECT_ROOT / "energyplus" / "models" / "5ZoneAirCooled_AirBoundaries.idf"

WEATHER_FILE = PROJECT_ROOT / "energyplus" / "weather" / "IND_Chennai-Madras.432790_ISHRAE.epw"

OUTPUT_DIR = PROJECT_ROOT / "energyplus" / "output"

# =====================================================
# CLEAN OLD OUTPUT
# =====================================================

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)

OUTPUT_DIR.mkdir(parents=True)

# =====================================================
# BUILD COMMAND
# =====================================================

command = [
    str(ENERGYPLUS_EXE),
    "-w", str(WEATHER_FILE),
    "-d", str(OUTPUT_DIR),
    str(IDF_FILE)
]

print("=" * 60)
print("Running EnergyPlus Simulation...")
print("=" * 60)

# =====================================================
# RUN ENERGYPLUS
# =====================================================

result = subprocess.run(
    command,
    capture_output=True,
    text=True
)

print(result.stdout)

if result.returncode != 0:
    print("\nSimulation Failed\n")
    print(result.stderr)
else:
    print("\nSimulation Completed Successfully!")
    print(f"\nResults saved in:\n{OUTPUT_DIR}")