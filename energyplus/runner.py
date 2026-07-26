"""
energyplus/runner.py
Runs EnergyPlus from Python for any given IDF + weather file combination.
This is the refactored, reusable version of your original run_simulation.py.
"""

import subprocess
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config


def run_simulation(idf_path: Path, output_dir: Path, weather_path: Path = config.WEATHER_FILE) -> dict:
    """
    Runs EnergyPlus for the given IDF file and returns a result dict.

    Returns:
        {
            "success": bool,
            "output_dir": Path,
            "stdout": str,
            "stderr": str,
            "returncode": int
        }
    """
    idf_path = Path(idf_path)
    output_dir = Path(output_dir)

    if not idf_path.exists():
        raise FileNotFoundError(f"IDF file not found: {idf_path}")
    if not weather_path.exists():
        raise FileNotFoundError(f"Weather file not found: {weather_path}")
    if not config.ENERGYPLUS_EXE.exists():
        raise FileNotFoundError(
            f"EnergyPlus executable not found at {config.ENERGYPLUS_EXE}. "
            "Update ENERGYPLUS_EXE in config.py."
        )

    # Clean previous output so we never accidentally read stale results
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    command = [
        str(config.ENERGYPLUS_EXE),
        "-w", str(weather_path),
        "-d", str(output_dir),
        "-r",                    # run ReadVarsESO automatically -> produces eplusout.csv
        str(idf_path),
    ]

    print("=" * 60)
    print(f"Running EnergyPlus Simulation for: {idf_path.name}")
    print("=" * 60)

    result = subprocess.run(command, capture_output=True, text=True)

    success = result.returncode == 0
    if success:
        print("\nSimulation Completed Successfully!")
        print(f"Results saved in: {output_dir}")
    else:
        print("\nSimulation Failed")
        print(result.stderr)

    return {
        "success": success,
        "output_dir": output_dir,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def run_baseline() -> dict:
    """Runs the unmodified baseline IDF. Use this once at the start of the pipeline."""
    return run_simulation(config.BASELINE_IDF, config.BASELINE_OUTPUT_DIR)


if __name__ == "__main__":
    run_baseline()
