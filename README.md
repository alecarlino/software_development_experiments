# Smart Water Lab: Software Development Experiments

I built this for the 2025–2026 **Software Development course** at **Xi'an Jiaotong University**, one of the first university courses in China and worldwide to teach **AI-driven software engineering**.

Each experiment solves one water-engineering problem in Python. I built every required feature, then added the full list of *Optional Extensions* from each assignment, plus a second solution method to cross-check the first and a test suite per project. The tables below list the required features first and the extras after, all of them built and working.

---

## 1 · Rainfall Forecasting & Alert System

Monitors rainfall for any city from the OpenWeatherMap free tier, sorts the rate on a green / yellow / red scale, and logs red alerts with a UTC timestamp. Runs as a command-line tool or a Streamlit dashboard.

| Feature | Status |
|---------|--------|
| Fetch and parse OpenWeatherMap weather, handle API errors | ✅ Required |
| Green / Yellow / Red thresholds (10, 20 mm/h), warn and log on Red | ✅ Required |
| Streamlit dashboard: rainfall metric, alert badge, chart, 5-min auto-refresh | ✅ Required |
| Folium map with 4 weather layers and a nearby-city rain heatmap | ⭐ Extra · implemented |
| 5-day forecast smoothed into a 24-hour alert prediction | ⭐ Extra · implemented |
| Email alerts over SMTP (`--email`) | ⭐ Extra · implemented |
| `--simulate` mode, email subscriptions, geocoding city search | ⭐ Extra · implemented |
| pytest suite on thresholds and logging | ⭐ Extra · implemented |

📂 [README](rainfall_alert/README.md) · 🧾 [Prompt log](rainfall_alert/prompt_log.md)

---

## 2 · SCS-CN Runoff Calculation

Implements the SCS-CN method for direct runoff, turning a rainfall depth `P` and a curve number `CN` into a runoff depth `Q`. It handles the physical edges: no runoff below the initial abstraction, `Q ≤ P`, and no divide-by-zero at `CN` 0 or 100. The core module uses only the standard library.

| Feature | Status |
|---------|--------|
| `calculate_runoff(P, CN)` with all four physical boundaries | ✅ Required |
| Boundary test suite (`P=0`, `P<Ia`, `P=Ia`, `P=50/CN=80`, `CN=100`, `Q≤P`) | ✅ Required |
| Sensitivity plots: `Q` vs `CN` and rainfall vs runoff across curve numbers | ✅ Required |
| Time-area watershed routing | ⭐ Extra · implemented |
| Antecedent moisture (AMC I / III) adjustment | ⭐ Extra · implemented |
| Interactive plot with `P` and `CN` sliders | ⭐ Extra · implemented |
| Rational-method comparison | ⭐ Extra · implemented |
| 27-test suite with a mass-conservation check and a `Q ≤ P` grid sweep | ⭐ Extra · implemented |

📂 [README](scs-cn_runoff_calculation/README.md) · 🧾 [Prompt log](scs-cn_runoff_calculation/prompt_log.md)

---

## 3 · Reservoir Dispatch Optimization

Optimises seven days of reservoir releases during a drought, trading hydropower revenue against downstream ecological flow. Solves the dispatch as a linear program with scipy and traces the trade-off as a Pareto frontier. Holding the ecological minimum costs 0.44% of revenue. Revenue here is a linear proxy (release × price × Δt), so the schedule maximises that proxy and won't match the example schedule in the guide. I also include a head-coupled dollar model for comparison.

| Feature | Status |
|---------|--------|
| 7-variable problem: revenue objective, release and storage bounds, mass balance | ✅ Required |
| Constrained solve with `scipy.optimize` | ✅ Required |
| Pareto frontier and the cost of holding ecological flow | ✅ Required |
| Validation report: storage, ecology, mass balance, revenue | ✅ Required |
| Inflow uncertainty (Monte Carlo plus robust safety margins) | ⭐ Extra · implemented |
| Rolling-horizon dispatch | ⭐ Extra · implemented |
| Water-quality dilution floor | ⭐ Extra · implemented |
| SLSQP vs L-BFGS-B vs LP solver comparison | ⭐ Extra · implemented |
| Head-coupled physical model, ε-constraint frontier, 22-test suite | ⭐ Extra · implemented |

📂 [README](reservoir_optimization/README.md) · 🧾 [Prompt log](reservoir_optimization/prompt_log.md)

---

## 4 · Flood Inundation Analysis

Maps flood inundation over a Digital Elevation Model: which cells flood at a given water level, how deep, and what share of the map. Builds a synthetic 100×100 terrain, floods it with a bathtub fill and connected-component routing, and renders static maps plus a rising-water GIF.

| Feature | Status |
|---------|--------|
| Synthetic or real DEM, flood mask, depth, flooded-area percentage | ✅ Required |
| Visuals: grayscale DEM, blue overlay, depth heatmap, side-by-side, colorbar | ✅ Required |
| Dynamic 40→50 m sweep with a monotonicity check | ✅ Required |
| Physical validation: max depth, 0–100% range, edge cases | ✅ Required |
| Real DEM loader (`.asc` / `.npy`) | ⭐ Extra · implemented |
| Connected-component flood routing | ⭐ Extra · implemented |
| Building footprints as flood barriers | ⭐ Extra · implemented |
| Animated GIF of rising water | ⭐ Extra · implemented |
| Flood volume (`depth × cell area × count`) | ⭐ Extra · implemented |
| 63-test suite and a standalone physics validator | ⭐ Extra · implemented |

📂 [README](flood_inundation/README.md) · 🧾 [Prompt log](flood_inundation/prompt_log.md)

---

## Tests and validation

Each project has its own test suite, and I check the numbers against the worked examples in the assignment guides. All four suites pass.

| Experiment | Tests | What the suite checks |
|------------|-------|-----------------------|
| Rainfall Alert | 26 | Green / Yellow / Red thresholds at 10 and 20 mm/h, API error handling, a UTC-timestamped alert log |
| SCS-CN Runoff | 27 (+114 subtests) | `calculate_runoff(50, 80) = 13.80 mm`, the 13.8 mm worked out in the guide; `Q ≤ P` and runoff growing with `CN` across a full `P`×`CN` grid |
| Reservoir Dispatch | 22 | all five constraints hold; the storage mass-balance error is about 6×10⁻¹¹ m³ |
| Flood Inundation | 63 | the flooded area never shrinks as the water rises, the deepest point equals water level minus the lowest elevation, and the flooded share stays between 0 and 100% |
| **Total** | **138** | |

Run a project's suite from inside its folder:

```bash
python -m pytest
```

Each folder's `requirements.txt` lists the libraries that project needs.

---

**Stack:** Python 3.10+, with `numpy`, `scipy`, `matplotlib`, `requests`, `streamlit`, and `folium` split across the projects. Each folder has its own `requirements.txt`; run `pip install -r requirements.txt` inside a folder to install what that experiment needs. Open any folder's README for setup, usage, and tests.
