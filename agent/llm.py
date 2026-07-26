"""
agent/llm.py
Thin client for Groq's hosted Qwen3.6 model (OpenAI-compatible /chat/completions endpoint).

Prereqs:
    1. Get a free API key: https://console.groq.com/keys
    2. Set it as an environment variable (don't hard-code it, especially in a public repo):
         Windows (PowerShell):   setx GROQ_API_KEY "your-key-here"     then reopen the terminal
         macOS/Linux:             export GROQ_API_KEY="your-key-here"
    3. pip install requests

Note: qwen/qwen3.6-27b is a reasoning model - by default it may emit its chain-of-thought
inside <think>...</think> tags before the actual answer. We ask Groq to hide that via
`reasoning_format: "hidden"` so `message.content` is just the final answer, which keeps our
JSON extraction simple and reliable.
"""

import sys
import json
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
load_dotenv()

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config


class LLMError(Exception):
    pass


def call_groq(system_prompt: str, user_prompt: str) -> str:
    """Sends a chat request to Groq and returns the raw text response."""
    if not config.GROQ_API_KEY:
        raise LLMError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "and set it as an environment variable, then restart your terminal."
        )

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,          # low temperature - this is a control decision, not creative writing
        "max_completion_tokens": 512,  # cap output so a reasoning model can't burn its whole budget on <think>
        "response_format": {"type": "json_object"},  # ask Groq to enforce valid JSON output
        "reasoning_effort": "none",   # Qwen3 models: skip chain-of-thought entirely, go straight to the JSON answer
    }

    try:
        response = requests.post(config.GROQ_BASE_URL, headers=headers, json=payload,
                                  timeout=config.GROQ_TIMEOUT_SECONDS)
    except requests.exceptions.ConnectionError as e:
        raise LLMError("Could not reach Groq's API. Check your internet connection.") from e
    except requests.exceptions.Timeout as e:
        raise LLMError(f"Groq request timed out after {config.GROQ_TIMEOUT_SECONDS}s.") from e

    if response.status_code == 401:
        raise LLMError("Groq rejected the request: invalid or missing GROQ_API_KEY.")
    if response.status_code == 429:
        raise LLMError("Groq rate limit hit. Wait a moment and retry, or check your plan's limits.")
    if response.status_code >= 400:
        raise LLMError(f"Groq API error {response.status_code}: {response.text}")

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected Groq response shape: {data}") from e


def _extract_json(text: str) -> dict:
    """
    Defensive JSON extraction in case reasoning_format='hidden' still leaves stray
    <think> tags, markdown fences, or prose around the JSON object.
    """
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise LLMError(f"No JSON object found in LLM response:\n{text}")

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned malformed JSON:\n{match.group(0)}") from e


def get_setpoint_decision(system_prompt: str, user_prompt: str) -> dict:
    """
    Calls the LLM and returns a validated decision dict:
    {"cooling_setpoint_c": float, "heating_setpoint_c": float, "reasoning": str}
    """
    raw_response = call_groq(system_prompt, user_prompt)
    decision = _extract_json(raw_response)

    for key in ("cooling_setpoint_c", "heating_setpoint_c"):
        if key not in decision:
            raise LLMError(f"LLM response missing required key '{key}': {decision}")
        decision[key] = float(decision[key])

    decision.setdefault("reasoning", "")
    decision["raw_response"] = raw_response
    return decision


if __name__ == "__main__":
    # Manual smoke test with dummy data
    from prompts import SYSTEM_PROMPT, build_user_prompt

    dummy_metrics = {
        "total_energy_kwh": 1200.5,
        "cooling_energy_kwh": 800.2,
        "heating_energy_kwh": 50.1,
        "hvac_electricity_kwh": 300.4,
        "comfort_violations": 12,
        "comfort_violation_pct": 0.8,  # CHANGED: added so build_user_prompt has a real value to show,
                                       # matching the new pct-based prompt instead of the old raw count
        "zone_temperatures": {"ZONE1": {"mean": 24.1, "min": 21.0, "max": 27.5}},
        "outdoor_air_temp": {"mean": 30.2, "min": 22.0, "max": 38.5},
    }

    sys_p = SYSTEM_PROMPT.format(
        cooling_min=config.COOLING_SETPOINT_MIN_C, cooling_max=config.COOLING_SETPOINT_MAX_C,
        heating_min=config.HEATING_SETPOINT_MIN_C, heating_max=config.HEATING_SETPOINT_MAX_C,
        comfort_min=config.COMFORT_TEMP_MIN_C, comfort_max=config.COMFORT_TEMP_MAX_C,
        # CHANGED: this key is required now - SYSTEM_PROMPT has a {comfort_budget_pct} placeholder
        # since the prompt patch. Without this, .format() raises a KeyError.
        comfort_budget_pct=config.COMFORT_VIOLATION_THRESHOLD_PCT,
    )
    user_p = build_user_prompt(dummy_metrics, cycle_number=1, prev_cooling=24.0, prev_heating=20.0,
                                comfort_min=config.COMFORT_TEMP_MIN_C, comfort_max=config.COMFORT_TEMP_MAX_C,
                                prev_comfort_pct=0.5)  # CHANGED: added so the "previous cycle" comparison prints

    print(get_setpoint_decision(sys_p, user_p))