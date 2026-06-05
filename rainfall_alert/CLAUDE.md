# CLAUDE.md

Behavioural and project-specific guidelines for building the Smart Water Lab rainfall monitoring experiment.

## Project Context

Build a real-time rainfall monitoring tool for urban flood management:

1. Fetch current weather from OpenWeatherMap.
2. Apply threshold-based alert logic.
4. Log Red alerts with timestamps.
5. Add multiple city monitoring.
6. Implement and email notification system for alerts
7. Create a rainfall prediction using historical trends
3. Display results in a Streamlit dashboard with:
    - Title: `Rainfall Monitor`
    - Current rainfall display (large metric)
    - Alert status indicator (colour-coded)
    - Historical data chart
    - Auto-refresh every 5 minutes
    - Map visualization using Folium


**Stack:** Python 3.10+, `requests`, `pandas`, `streamlit`,`Folium`.
**API:** `https://api.openweathermap.org/data/2.5/weather` — free tier, **60 calls/min rate limit**.

---

## Domain Specifications
Do Not "Correct" These Silently.
- **Alert threshold for this experiment: 20 mm/h** (Red colour).
- **Alert levels:**
  - Green: rainfall < 10 mm/h (Normal)
  - Yellow: 10 ≤ rainfall < 20 mm/h (Moderate)
  - Red: rainfall ≥ 20 mm/h (ALERT: log + display warning)
- **Zero rainfall is expected.** Most API responses will report no rain. That is not a bug and must not be treated as an error.
- **`rain` key may be absent** from the OpenWeatherMap response when it is not raining. Treat absence as `0.0 mm/h`.
- **Validate physical reasonableness.** Values like 50+ mm/h in a dry city are likelier a parsing bug than real weather; check units and the response structure before trusting.

---

## Deliverables
Fixed names, do not rename or add extras.
- `weather_monitor.py` — main application (API + alert logic + Streamlit dashboard).
- `alert_log.txt` — timestamped log of triggered Red alerts.

Do not introduce extra modules, config files, or dependencies unless the task requires them.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly (e.g. "I'm assuming `rain['1h']` is the target field, confirm?"). If uncertain, ask.
- If multiple interpretations exist, present them, don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear (API field, threshold, dashboard layout), stop. Name what's confusing. Ask.

For this project specifically:
- **Before writing code, confirm the target city** and whether the API key should be read from an env variable, a `.env` file, or hardcoded for the demo.
- **Before adding auto-refresh**, confirm the interval will not breach the 60 calls/min limit.

---

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what the assignment asks.
- No abstractions for single-use code (no `WeatherClient` class wrapping a single `requests.get`).
- No "flexibility" or "configurability" that wasn't requested (no multi-provider adapter, no plugin system).
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Test: "Would a senior engineer say this is over complicated?" If yes, simplify.

---

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it, don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove preexisting dead code unless asked.

Test: Every changed line should trace directly to the user's request.

---

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Fetch weather" -> "Call the API for Beijing and print a valid rainfall number (including 0.0)."
- "Add alerting" -> "With rainfall = 5, 15, 25 mm/h as inputs, the function returns Green, Yellow, Red respectively."
- "Build dashboard" -> "`streamlit run weather_monitor.py` opens a page showing current rainfall, a colour-coded alert badge, and a title with the city name."

For multistep work, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

Strong success criteria let you loop independently; weak ones ("make it work") force constant clarification.

---

## Project Specific Pitfalls

- **Rate limit.** Free tier = 60 calls/min. Auto-refresh ≥ 5 s between calls is safe; dashboard auto-refresh is specified as 5 min, keep it that way.
- **Missing `rain` key.** Use `data.get("rain", {}).get("1h", 0.0)`; do not index blindly.
- **API error handling.** Handle non-200 status, timeout, and JSON decode errors. Do not mask them silently, log and surface.
- **Timestamps in `alert_log.txt`.** Use ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`); do not use locale-dependent formats.
- **Streamlit auto-refresh.** Use `st.autorefresh` or the documented pattern — do not build a manual `while True` loop inside the Streamlit script.

---




