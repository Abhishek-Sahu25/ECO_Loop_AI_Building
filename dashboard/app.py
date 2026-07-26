"""
dashboard/app.py
Streamlit dashboard showing baseline vs AI-optimized closed-loop results,
with a button to run the whole pipeline live from the app itself.

Run:
    streamlit run dashboard/app.py
"""

import sys
import io
import json
import contextlib
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.append(str(Path(__file__).resolve().parents[1]))
import config
from controller.pipeline import run_closed_loop

st.set_page_config(page_title="EcoLoop Building AI Dashboard", layout="wide", page_icon="🏢")

# ---------------------------------------------------------------------------
# Light custom styling - keeps Streamlit's defaults but tightens up metric
# cards and headers so it reads less like a default demo and more like a
# finished product for the judges.
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background-color: rgba(46, 125, 50, 0.06);
        border: 1px solid rgba(46, 125, 50, 0.15);
        border-radius: 10px;
        padding: 14px 16px 10px 16px;
    }
    div[data-testid="stMetricLabel"] { font-weight: 600; opacity: 0.85; }
    .budget-ok { color: #2e7d32; font-weight: 600; }
    .budget-bad { color: #c62828; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

st.title("🏢 EcoLoop Building AI — Closed-Loop Optimization Dashboard")
st.caption("EnergyPlus simulation results, AI decisions, and quantified energy + comfort tradeoffs.")

# ---------------------------------------------------------------------------
# Sidebar: run the whole closed loop live from the dashboard.
#
# This calls controller.pipeline.run_closed_loop() directly in-process - the
# same function main.py calls from the terminal. Streamlit reruns this whole
# script top-to-bottom on every interaction, so clicking the button re-executes
# the script, hits this block, runs the full baseline+optimization pipeline
# synchronously (the UI is unresponsive for the duration - this is expected,
# a full run takes a few minutes since it's several real EnergyPlus
# simulations plus LLM calls), then triggers a rerun so the rest of the page
# picks up the freshly written cycle_history.json.
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ Run Optimization")
st.sidebar.caption(
    "Runs the baseline EnergyPlus simulation plus AI optimization cycles "
    "live, right from this dashboard. Takes a few minutes - the page will "
    "be busy until it finishes."
)
run_clicked = st.sidebar.button("▶ Run Full Closed-Loop Pipeline", type="primary", use_container_width=True)

if run_clicked:
    log_buffer = io.StringIO()
    with st.spinner("Running EnergyPlus baseline + AI optimization cycles... this can take a few minutes."):
        try:
            with contextlib.redirect_stdout(log_buffer):
                run_closed_loop()
            st.session_state["last_run_status"] = "success"
        except Exception as e:
            st.session_state["last_run_status"] = "error"
            st.session_state["last_run_error"] = str(e)
        finally:
            st.session_state["last_run_log"] = log_buffer.getvalue()
            st.session_state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.rerun()

if st.session_state.get("last_run_status") == "success":
    st.sidebar.success(f"Pipeline run complete at {st.session_state.get('last_run_time', '')}.")
elif st.session_state.get("last_run_status") == "error":
    st.sidebar.error(f"Pipeline failed: {st.session_state.get('last_run_error')}")

if st.session_state.get("last_run_log"):
    with st.sidebar.expander("View last run log"):
        st.code(st.session_state["last_run_log"], language="text")

st.sidebar.divider()
st.sidebar.caption(
    f"Comfort budget: {getattr(config, 'COMFORT_VIOLATION_THRESHOLD_PCT', 5.0):.1f}% • "
    f"Max cycles: {config.MAX_OPTIMIZATION_CYCLES} • "
    f"Model: {getattr(config, 'GROQ_MODEL', 'n/a')}"
)

# ---------------------------------------------------------------------------
# Load cycle history (may not exist yet on first-ever load)
# ---------------------------------------------------------------------------
if not config.CYCLE_HISTORY_FILE.exists():
    st.info(
        "No results yet. Click **▶ Run Full Closed-Loop Pipeline** in the sidebar to run the "
        "baseline simulation and AI optimization cycles, or run `python main.py` from the terminal first."
    )
    st.stop()

with open(config.CYCLE_HISTORY_FILE) as f:
    history = json.load(f)

completed = [h for h in history if h.get("metrics") is not None]
if not completed:
    st.error("Cycle history exists but contains no completed runs.")
    st.stop()

COMFORT_BUDGET_PCT = getattr(config, "COMFORT_VIOLATION_THRESHOLD_PCT", 5.0)

# ---------------------------------------------------------------------------
# Build the results table
# ---------------------------------------------------------------------------
rows = []
for h in completed:
    m = h["metrics"]
    rows.append({
        "Cycle": h["label"],
        "Cycle #": h["cycle"],
        "Total Energy (kWh)": m["total_energy_kwh"],
        "Cooling Energy (kWh)": m["cooling_energy_kwh"],
        "Heating Energy (kWh)": m["heating_energy_kwh"],
        "HVAC Electricity (kWh)": m["hvac_electricity_kwh"],
        "Comfort Violation (%)": m.get("comfort_violation_pct", 0.0),
        "Comfort Violations (raw)": m.get("comfort_violations", 0),
        "Occupied Timesteps Considered": m.get("comfort_timesteps_considered", 0),
        "Cooling Setpoint (C)": h["cooling_setpoint_c"],
        "Heating Setpoint (C)": h["heating_setpoint_c"],
        "Decision Source": h.get("decision_source") or "baseline",
        "Within Budget": m.get("comfort_violation_pct", 0.0) <= COMFORT_BUDGET_PCT,
    })

df = pd.DataFrame(rows)

# ---------------------------------------------------------------------------
# Best-cycle selection - MUST mirror controller/pipeline.py's _select_best
# exactly, or the dashboard will tell a different story than the terminal
# output and your architecture doc. Rule: among cycles within the comfort
# budget, pick lowest energy. If none qualify, pick lowest comfort violation,
# tie-broken by energy.
# ---------------------------------------------------------------------------
within_budget_df = df[df["Within Budget"]]
if not within_budget_df.empty:
    best_row = within_budget_df.loc[within_budget_df["Total Energy (kWh)"].idxmin()]
else:
    best_row = df.sort_values(["Comfort Violation (%)", "Total Energy (kWh)"]).iloc[0]

baseline_row = df.iloc[0]
baseline_energy = baseline_row["Total Energy (kWh)"]
baseline_comfort_pct = baseline_row["Comfort Violation (%)"]
savings_pct = round((baseline_energy - best_row["Total Energy (kWh)"]) / baseline_energy * 100, 2)

# ---------------------------------------------------------------------------
# Top-line metrics
# ---------------------------------------------------------------------------
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Baseline Energy", f"{baseline_energy:,.1f} kWh")
col2.metric("Best AI Result", f"{best_row['Total Energy (kWh)']:,.1f} kWh", f"-{savings_pct}%")
col3.metric("Best Cycle Comfort Violation", f"{best_row['Comfort Violation (%)']:.2f}%",
            f"{best_row['Comfort Violation (%)'] - baseline_comfort_pct:+.2f} pts vs baseline",
            delta_color="inverse")
col4.metric("Comfort Budget (ceiling)", f"{COMFORT_BUDGET_PCT:.1f}%")
col5.metric("Optimization Cycles Run", len(df) - 1)

if best_row["Within Budget"]:
    st.markdown(
        f"<span class='budget-ok'>✔ Selected cycle ({best_row['Cycle']}) stays within the "
        f"{COMFORT_BUDGET_PCT:.1f}% comfort budget while delivering {savings_pct}% energy savings.</span>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"<span class='budget-bad'>⚠ No cycle stayed within the {COMFORT_BUDGET_PCT:.1f}% comfort budget - "
        f"showing the least-uncomfortable option instead.</span>",
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Combined energy + comfort chart - the single most important chart for
# judges, since it visually proves the tradeoff being balanced rather than
# ignored. Energy as bars (left axis), comfort violation % as a line (right
# axis) with the budget ceiling drawn in as a reference line.
# ---------------------------------------------------------------------------
st.subheader("Energy Savings vs. Comfort Violation, per Cycle")

fig_combo = make_subplots(specs=[[{"secondary_y": True}]])

bar_colors = ["#9e9e9e" if c == "baseline" else
              ("#2e7d32" if row["Cycle"] == best_row["Cycle"] else "#42a5f5")
              for c, row in zip(df["Cycle"], df.to_dict("records"))]

fig_combo.add_trace(
    go.Bar(x=df["Cycle"], y=df["Total Energy (kWh)"], name="Total Energy (kWh)",
           marker_color=bar_colors, text=df["Total Energy (kWh)"].round(1), textposition="outside"),
    secondary_y=False,
)
fig_combo.add_trace(
    go.Scatter(x=df["Cycle"], y=df["Comfort Violation (%)"], name="Comfort Violation (%)",
               mode="lines+markers", line=dict(color="#e65100", width=3), marker=dict(size=9)),
    secondary_y=True,
)
fig_combo.add_hline(
    y=COMFORT_BUDGET_PCT, line_dash="dash", line_color="#c62828",
    annotation_text=f"Comfort budget ceiling ({COMFORT_BUDGET_PCT:.1f}%)",
    annotation_position="top left", secondary_y=True,
)

fig_combo.update_yaxes(title_text="Total Energy (kWh)", secondary_y=False)
fig_combo.update_yaxes(title_text="Comfort Violation (%)", secondary_y=True)
fig_combo.update_layout(
    height=460, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(t=60),
)
st.plotly_chart(fig_combo, use_container_width=True)
st.caption(
    "Green bar = selected best cycle. Grey = baseline. Blue = other optimization cycles. "
    "The dashed red line is the acceptable comfort budget - any cycle above it is excluded "
    "from consideration regardless of how much energy it saves."
)

st.divider()

# ---------------------------------------------------------------------------
# Energy breakdown by category
# ---------------------------------------------------------------------------
st.subheader("Energy Breakdown by Category")
breakdown_df = df.melt(
    id_vars="Cycle",
    value_vars=["Cooling Energy (kWh)", "Heating Energy (kWh)", "HVAC Electricity (kWh)"],
    var_name="Category", value_name="kWh",
)
fig_breakdown = px.bar(breakdown_df, x="Cycle", y="kWh", color="Category", barmode="group",
                        color_discrete_sequence=["#42a5f5", "#ef5350", "#ab47bc"])
fig_breakdown.update_layout(height=380)
st.plotly_chart(fig_breakdown, use_container_width=True)

# ---------------------------------------------------------------------------
# Setpoints over cycles
# ---------------------------------------------------------------------------
st.subheader("Thermostat Setpoints Chosen by the AI")
setpoint_df = df.dropna(subset=["Cooling Setpoint (C)"])
if not setpoint_df.empty:
    fig_setpoints = px.line(setpoint_df, x="Cycle", y=["Cooling Setpoint (C)", "Heating Setpoint (C)"],
                             markers=True, color_discrete_sequence=["#1565c0", "#ef6c00"])
    fig_setpoints.update_layout(height=360, yaxis_title="Setpoint (C)")
    st.plotly_chart(fig_setpoints, use_container_width=True)
else:
    st.info("No optimization cycles completed yet.")

st.divider()

# ---------------------------------------------------------------------------
# Reasoning log
# ---------------------------------------------------------------------------
st.subheader("🧠 AI Reasoning Log")
for h in history:
    m = h.get("metrics")
    pct = m.get("comfort_violation_pct") if m else None
    label_suffix = f" — comfort {pct:.2f}%" if pct is not None else ""
    best_tag = " ⭐ SELECTED AS BEST" if m and h["label"] == best_row["Cycle"] else ""
    with st.expander(f"{h['label']}{label_suffix}{best_tag}"):
        st.write(f"**Decision source:** {h.get('decision_source') or 'baseline'}")
        st.write(f"**Cooling setpoint:** {h.get('cooling_setpoint_c')} C")
        st.write(f"**Heating setpoint:** {h.get('heating_setpoint_c')} C")
        st.write(f"**Reasoning:** {h.get('reasoning')}")
        if m:
            zone_detail = m.get("comfort_violation_by_zone")
            if zone_detail:
                st.write("**Per-zone comfort detail (occupied hours only, plenum excluded):**")
                st.dataframe(pd.DataFrame(zone_detail).T, use_container_width=True)
            st.write("**Full metrics:**")
            st.json(m)

st.divider()
st.subheader("Full Data Table")
st.dataframe(
    df.drop(columns=["Within Budget"]).style.apply(
        lambda r: ["background-color: rgba(46,125,50,0.15)" if r["Cycle"] == best_row["Cycle"] else ""
                   for _ in r], axis=1
    ),
    use_container_width=True,
)

st.caption(
    f"Comfort violations are measured across occupied hours in occupied zones only "
    f"(unconditioned plenums and unoccupied hours excluded). Acceptable comfort budget: "
    f"{COMFORT_BUDGET_PCT:.1f}% of occupied hours outside the "
    f"{config.COMFORT_TEMP_MIN_C}-{config.COMFORT_TEMP_MAX_C}C comfort band."
)