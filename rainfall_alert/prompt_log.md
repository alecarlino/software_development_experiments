# Prompt Log - Experiment 1: Short-Term Rainfall Forecasting & Alert System

**Author:** Alessandro Carlino
**Course:** Software Development
**Date:** 2026-03-24

## AI Agent Settings

**Platform:** Claude Code
**Model:** Opus 4.7 (High Effort)
**Plugin:** Superpowers (for TDD)
**Agent configuration file:** `CLAUDE.md` (provided in the directory)

---

## First Iterations

My working directory held two files: `CLAUDE.md`, with the project requirements, and an empty `prompt_log.md`.

### Prompt Used
"I am a computer science master's student building a rainfall monitoring system. Please write Python code to fetch current weather data for a city specified by the user via input using the OpenWeatherMap API. The code should:
1. Use the requests library to make the API call, reading the API key from the OWM_API_KEY environment variable
2. Extract the rainfall amount from the response (rain.1h field, in mm) and classify the intensity
3. Handle API errors gracefully, including network timeouts, invalid API key (401), city not found (404), and missing rain field when it is not raining
4. Include comments explaining each step

API endpoint: https://api.openweathermap.org/data/2.5/weather"

### AI Output Summary

The agent read every file in the working directory and pulled the rules from its configuration files. The code request triggered the Superpower skill `\brainstorming`, so the agent began with follow-up questions.

It asked how to structure the initial request, since `CLAUDE.md` had told it that the final project would land in a single file named `weather_monitor.py`. It proposed three options:

- A flat script: a file already named `weather_monitor.py` with a few core functions, to be extended step by step with new features.
- A throwaway script: a minimal file for a single task, to be discarded later when building the real project.
- The final structure upfront: design `weather_monitor.py` as the end state with stubs for future requests, implementing only the necessary parts initially.

I chose the flat script approach and asked it to create a file with that name, populated with top-level functions. Future iterations would add more advanced functionality.

The agent then drafted a plan for the initial implementation. It defined a single file `weather_monitor.py` with four core functions:

- `get_api_key`: reads the API key from the environment and exits if missing.
- `fetch_weather`: calls the API with city, key, metric units, and a timeout, returning parsed JSON.
- `classify_rainfall`: maps rainfall in mm/h to "Green", "Yellow", or "Red" using fixed thresholds.
- `main`: handles user input, orchestrates the flow, and prints the result.

The plan also covered safe extraction of rainfall from the response, defaulting to `0.0 mm/h` if missing, and error handling for timeouts, network issues, invalid API keys, unknown cities, other HTTP errors, and malformed JSON.

The plan kept comments minimal, listed verification steps, and deferred advanced features to later iterations.

The agent asked for approval before proceeding. I approved, and it wrote `weather_monitor.py` to match the plan.

### Verifications

I first tested that my OpenWeatherMap key was active. A terminal request returned a valid response (note: a new key takes at least two hours to activate).

I then ran the CLI on three cities from different climates: Milan (IT), London (UK), Beijing (CN). All three returned `0.00 mm/h` during the test window, matching the local weather reported by independent sources. These values are plausible: when the area is dry, OpenWeatherMap returns no rain, and `CLAUDE.md` flags this as expected behaviour. I never saw anomalous readings such as 50+ mm/h on a dry city, which would point to a parsing bug.

I also exercised the error paths with bad inputs:
- Unset API key, no value submitted.
- Invalid API keys, with wrong alphanumeric codes (HTTP 401).
- Nonexistent cities, with city not found (HTTP 404).

Each case produced the expected error message and exit.

### Changes Made

No code changes were needed.

---
## Second Interaction

The working directory now held three files: the unchanged `CLAUDE.md`, the updated `prompt_log.md` with the previous entry, and the flat script `weather_monitor.py` with the first requested functions.

### Prompt Used
"Now I want you to implement a threshold-based alerting based on rainfall intensity, follow these requirements:
- Green, rainfall < 10 mm/h (Normal)
- Yellow, 10 <= rainfall < 20 mm/h (Moderate)
- Red, rainfall >= 20 mm/h (Heavy - ALERT)
When red, the program must trigger an alert that displays a warning message and create/update a log event to a file with timestamp. When there is a dashboard, it should also appear on the dashboard."

### AI Output Summary

The agent drafted a second plan adding Red-alert handling to `weather_monitor.py` with no change to the file structure and no new dependencies. The plan called for:
- A new function `log_red_alert(city, rainfall_mm)` that appends red events to `alert_log.txt` with a UTC ISO 8601 timestamp, city, and rainfall value.
- A change to `main` so it always prints the status. On "Red" it also prints a warning and logs the event; "Yellow" and "Green" stay unchanged.

The dashboard would come later; for now the log file and console output were the source of truth. Verification used synthetic inputs to check log appending and ISO 8601 UTC formatting.

I approved the plan and ran the Superpower skill `/execute-plans`. The agent edited the code and tested it step by step.

### Verifications

To force yellow, green, and red conditions on demand (real Red rainfall is rare), I added a test function that takes mock data and skips the API call.

I then ran a `--simulate` matrix across every branch of `classify_rainfall` and the Red-alert side effects:

  | `--simulate <mm/h>` | Expected level | Alert printed | Log line written |
  |---|---|---|---|
  | 0    | Green  | no  | no |
  | 5    | Green  | no  | no |
  | 9.99 | Green  | no  | no |
  | 10   | Yellow | no  | no |
  | 15   | Yellow | no  | no |
  | 19.99| Yellow | no  | no |
  | 20   | Red    | yes | yes |
  | 25   | Red    | yes | yes |

All eight runs matched expectation. The boundary at `20 mm/h` triggered the alert; `19.99 mm/h` did not. After the matrix, `alert_log.txt` contained two new lines, one per red case. A sample line:

```
2026-04-25T08:50:54.588967+00:00 | Milan | 20.00 mm/h
```

I parsed the timestamp prefix with `datetime.fromisoformat`. It parsed without error, with a UTC offset of zero seconds, so the ISO 8601 format required by `CLAUDE.md` held.

I re-ran the same tests on the cities from the previous iteration. Each one produced `0.00 mm/h - Green` and left the log file alone. Real conditions did not trigger a false red, and every reading stayed within plausible physical bounds.

### Changes Made

The changes in this phase were small and aimed at making debugging easier:

- I added `"units": "metric"` to the API call in `fetch_weather` to get metric units. The change was tiny, so I made it by hand.

- A `--simulate <mm>` CLI flag, suggested by the agent, lets me exercise the Yellow/Red branches without waiting for real heavy rain. It uses `argparse` and leaves the production code path untouched.

- A `simulated: bool` parameter on `log_red_alert` and a `| SIMULATED` suffix on log lines keep test runs out of the historical record. The agent suggested this too.

---
## Third Interaction

The working directory now held four files: `CLAUDE.md`, `prompt_log.md`, `weather_monitor.py`, and the new `alert_log.txt` from the simulated alerts.

### Prompt Used
"The next step is the implementation of:
- An email notifications system for alerts, take in input a user email address and send it automatically a notification when an alert is defined by the previous implemented system. Integrate an email service (SMTP or external provider such as SendGrid/Mailgun).
- A rainfall prediction system using historical trends contained in the API. Apply statistical or lightweight ML approaches like moving averages, exponential smoothing, or ARIMA-like modeling."

### AI Output Summary

Since the two requests sat in different domains, the agent said it would handle them one at a time and asked which to start with. I picked the predictive system. It then laid out the options.

*Rainfall Prediction System*

It proposed three methods:
- Save a local CSV to build a dataset once the program is running.
- Download the precomputed prediction results already available from the API.
- Upgrade my API plan to get full historical data and a ready-to-use dataset.

I chose the second option, the only one that produced an immediate result without waiting for observations or paying for an upgrade. The agent then drafted the plan.

The design adds a rainfall prediction step on top of the API data. It calls the OpenWeather forecast endpoint, pulls up to 40 rainfall values at 3-hour intervals, and defaults missing values to `0.0 mm/h`. Two pure functions drive the prediction: a moving average with `window=3` to flatten spikes, and exponential smoothing with `alpha=0.5` to weight recent data. The two run in sequence for a steadier forecast.

The system outputs a 24-hour rainfall estimate, a short-term prediction, and an "imminent alert" flag when smoothed values cross `20 mm/h`. Predicted alerts do not go into the log file.

A new CLI flag `--predict` uses real forecast data and can combine with `--simulate`. Unit tests cover the smoothing functions on simple series, and live calls cover real cities.

*Mail Alert Notification System*

The agent proposed an SMTP flow built on Python's `smtplib`. A new CLI flag `--email <recipient>` turns on email notifications without changing default behaviour.

When the flag is set, the system sends an email only on red alerts from the current weather flow. It works with `--simulate` and `--predict`, so I could run end-to-end tests without waiting for real conditions. A dedicated function `send_alert_email()` builds a plain-text body with city, rainfall intensity, UTC timestamp, and a "SIMULATED" marker during simulation runs.

Delivery uses a standard SMTP flow (STARTTLS, auth, `send_message`). SMTP errors trigger `sys.exit`, in line with the rest of the error handling.

### Verifications

I tested both the prediction system and the email system with synthetic data, then with real API data where possible.

For the prediction part, I fed five synthetic forecast scenarios to `report_prediction` to check the smoothed-imminent flag:

  | Scenario | Input pattern | Expected `imminent` |
  |---|---|---|
  | All-dry forecast | `[0.0] * 40` | no |
  | Single 3-hour spike | bucket 2 = 90 mm (= 30 mm/h), rest 0 | no, the smoothing dampens isolated spikes by design |
  | Sustained heavy rain | first 8 buckets at 90 mm (= 30 mm/h), rest 0 | yes |
  | Sustained at threshold | first 8 buckets at 60 mm (= 20 mm/h), rest 0 | yes |
  | Sustained below threshold | first 8 buckets at 30 mm (= 10 mm/h), rest 0 | no |

All five matched expectation, so the test passed.

I ran the email path end-to-end with `--simulate 25` against a real Gmail SMTP account. The email arrived with subject `Rainfall ALERT: <city>` and a body containing the city, mm/h value, ISO 8601 UTC timestamp, and the "SIMULATED" marker. I also forced missing-env scenarios for `SMTP_HOST`, `SMTP_USER`, and `SMTP_PASSWORD`, alone and in combination. In every case the code exited with an error message listing the missing variables.

For real data I fetched forecasts on Milan, London, and Beijing. The next-24h totals were `0.00 mm`, `0.45 mm`, and `5.21 mm`, all plausible and in line with the regional weather at the time.

### Changes Made

Verification was clean, so the code stayed as written.

One piece of agent push-back is worth noting. My prompt asked for "a rainfall prediction system using historical trends contained in the API", but the free OWM tier has no history endpoint. The agent flagged the gap and proposed the forecast-based approach instead of pretending to build something the API could not support.

---
## Fourth Interaction

The working directory now held a full CLI implementation, with every function in place.

### Prompt Used
"Implement a final GUI using Streamlit and Folium. The interface must integrate all data processed in previous steps (weather, alerts, and predictions) and follow this functional structure:
- City Selection and Data Retrieval, implement a search and selection mechanism to allow the user to choose a city from the API dataset. Upon selection, the app must fetch and display the current weather, rain/alert status, and the computed rain prediction
- Geospatial Visualization, create an interactive map using Folium representing the city's weather status dynamically, using markers or color-coded layers based on the severity of the alert/rain
- Alert Subscription Interface, include a dedicated section where users can input their email address to subscribe to future weather alerts for the selected city. This system should be prepared to store the email/city pair
- UX and Feedback, use Streamlit layout components to ensure that high-priority alerts are highlighted for immediate visibility"

### AI Output Summary

The agent drafted the largest plan of the project so far. The Streamlit and Folium dashboard would pull four UI subsystems into one app. The agent asked me to push back on anything before it started writing code.

The whole app stays in `weather_monitor.py`, in line with the `CLAUDE.md` rule against extra modules. The agent detects the runtime via `st.runtime.exists()`: running the file directly keeps the existing CLI untouched; running it with `streamlit run` hands off to a new `streamlit_app()` function. New dependencies: streamlit, folium, pandas, plus streamlit-folium for the embedded map and streamlit-autorefresh for the periodic refresh.

City selection uses OpenWeatherMap's Geocoding API. A free-text search returns up to five candidates that the user picks from a selectbox, which sidesteps cases like Milan, Italy vs. Milan, Ohio. Once the user picks a city, the existing weather and forecast functions handle the rest with no refactor.

The layout flows top to bottom: title, a five-minute auto-refresh, the city search, then a two-column row with current rainfall on the left and a colour-coded alert badge on the right. Below sits a Folium map centred on the selected city with a single marker coloured by alert level, then a prediction block with three metrics and a line chart of the five-day forecast. At the bottom, a subscription form writes email plus city into `subscriptions.json`. The CLI keeps the job of actually sending mail.

The agent closed with one question: should the chart show the smoothed forecast series (works immediately) or a rolling history buffer (empty on first run, populates over time)? It recommended the first option so the dashboard could ship at once. I agreed and ran `/execute-plans`.

### Verifications

The plan walked through loading the page, geocoding "Milan", then "London" and "Beijing", and checking that the metric, badge, map, and prediction rendered. I then poked the subscription form, ran a CLI smoke test for regressions, and left the page open for five minutes to confirm the auto-refresh ticked.

I started with a first-load smoke test using a placeholder API key. With no city entered, the test reported 0 exceptions, 0 errors. The title `Rainfall Monitor` rendered and the info banner `"Type a city name to begin."` showed.

For the city search path with the placeholder key, I set the search box to `"Milan"` and triggered `geocode_city`. It returned HTTP 401. The dashboard caught the `SystemExit` and rendered `"Invalid API key (HTTP 401)."` as a Streamlit error. No crash.

For the live render I opened the page in a real browser and walked through the title, the geocoded matches, the populated metric and badge, the map, the prediction block, and the subscription form. I left the page open and the 5-minute refresh ticked as expected.

I re-ran the CLI to check for regressions after the dashboard work. The CLI menu kept working. Finally I drove the dashboard through Milan, London, and Beijing with a real API key. Each one produced rainfall values in line with the local weather at the time, all `0.00 mm/h` on dry days. No anomalous values appeared.

### Changes Made

During the first verification pass, Streamlit would not load. The agent had not installed `folium`, `streamlit-folium`, or `streamlit-autorefresh`. I installed them by hand with `pip install folium streamlit-folium streamlit-autorefresh`.

After that, every verification step passed and the code stayed as written.

---
## Fifth Interaction

The working directory now held a working CLI and a first version of the dashboard.

The prompt also included a `png` screenshot of a reference dashboard.

### Prompt Used
"Reorganize the streamlit weather dashboard into a sidebar and 3 column layout. Keep all existing data fetching, API calls, alert logic, and business logic intact, only change the UI/layout.

Sidebar:
- App title and a small header/logo
- Text input or dropdown to select the city
- Email input for subscribing to rainfall alerts
- A subscribe button that wires into the existing alert subscription logic

Column 1 (left, ratio 1):
- Weather forecast section using st.metric for temperature, humidity, wind speed, and any other current-condition values already computed
- Alert status indicator below it, color-coded (green = none, yellow = watch, red = active alert), reflecting the current alert state
- An "About" expander at the bottom describing the data source and the thresholds used to trigger alerts

Column 2 (center, ratio 2 the largest):
- A contour / heatmap visualization of rainfall in millimeters, covering the selected city AND the surrounding region (not just a single point)
- Use a sequential blue colour map with a visible colour scale legend
- Use folium with a heatmap layer
- Title the section "Rainfall Map”

Column 3 (right, ratio 1):
- Rainfall history, a time-series chart of past rainfall for the selected zone (use the existing historical data source)
- Alert Forecast , predicted rainfall alerts for the upcoming period, shown as a chart or compact table

Style:
- Dark theme, rounded card-style containers, soft borders, similar vibe to the attached reference image
- Use st.container(border=True) to group related widgets within each column"

### AI Output Summary

The agent replied with a design proposal and held back implementation until I settled three contested points:

- The regional heatmap cannot be built from the single rainfall value the app holds. The agent offered an OWM precipitation tile overlay, a 3x3 grid of weather calls, or a synthetic Gaussian falloff, with the tile overlay as its default.
- The "existing historical data source" I had referenced does not exist on the free OWM tier. The agent offered to relabel the smoothed forecast or start a CSV rolling buffer, with the relabel as default.
- A dark theme needs a `.streamlit/config.toml` file that `CLAUDE.md` would normally forbid. The agent asked for explicit approval to add it and recommended against CSS injection for rounded corners.

The layout itself was uncontroversial. The agent proposed a wide page, a sidebar with the title, city search, and subscription form, and a main area split into three columns at a 1-2-1 ratio with bordered containers. The left column extends the weather card with three metrics from the existing API response and keeps the alert badge and banner.

I resolved the three contested points and asked the agent to build the new dashboard from the plan.


### Verifications

I tested the code first with the default CLI flow and then in the new GUI, checking that the new dashboard did not break anything from before.

I started with an AppTest run on the new dashboard in empty state. It returned 0 exceptions. The sidebar showed the title `Rainfall Monitor` and the subheaders `City` and `Subscribe to alerts`, and the main area showed the landing message. After I typed `"Milan"` with a fake key, `geocode_city` returned 401 and the message rendered as `st.error` inside the sidebar. No exception leaked.

For map regression I rendered `Milan, IT` and toggled the four OWM tile overlays (Precipitation, Clouds, Temperature, Wind) one at a time. Each one loaded. The HeatMap appeared when at least one nearby city in the `/find` response had non-zero rainfall and was absent on dry days, as expected.

I checked the layout invariants too. The bottom alignment of the last card in each column held at the viewport width I had open. The CSS-injected `min-height: 720px` plus `flex-grow: 1` on the last card kept the alignment.

For subscription persistence I submitted the form with a valid email. `subscriptions.json` was created with the expected `{email, city, country, subscribed_at}` record and an ISO 8601 UTC timestamp. A second submission appended a second record without overwriting the first.


### Changes Made

Verification turned up one real bug and a handful of cosmetic issues:

- **Heat map crash on dry days.** The dashboard crashed with `AttributeError: 'NoneType' object has no attribute 'get'` on the line filtering nearby cities by rainfall. The cause: OWM `/find` returns `"rain": null` for dry cities (not just an absent key), so `c.get("rain", {})` returned `None` instead of `{}`. The fix was to extract with `(c.get("rain") or {}).get("1h", 0)`. I checked the patched code against five rain-field shapes (`null`, missing, `{}`, `{"1h": 0}`, `{"1h": 5.5}`); only the last produced a heat point.
- **Layout polish.** I renamed a few window titles for clarity and dropped the map height from 520 px to 440 px so column 2 matched column 3's natural height. I redesigned the legend from discrete colour swatches into continuous gradient bars so the underlying tile palette stayed legible.
- **Layer control legend.** The default Folium layer panel listed `cartodbdark_matter` as a togglable base layer. I removed it by passing `tiles=None` to `folium.Map(...)`, so only the four OWM overlays remain.

---
## Refinement

The working directory now held the finished code. I ran Claude Code's built-in `/simplify` command to clean up the comments and the structure of the file. The observable behaviour did not change; the agent rewrote the code to read better.

### AI Output

The `/simplify` review dispatched three agents in parallel: Reuse, Quality, and Efficiency.

They flagged three latent issues that did not affect observable behaviour but were worth fixing:
- A stray `f` prefix on a Streamlit caption with no interpolation (`st.caption(f"Enter your email...")`).
- A possible `KeyError` on `color_map[level]` if `classify_rainfall` ever returned something outside `{"Green", "Yellow", "Red"}`. Replaced with `colour_by_level.get(level, "blue")`.
- An inconsistency between `0` and `0.0` defaults across the rain-extraction sites. Unified via a new `_rain_amount` helper.

The review also restructured the file for clarity:
- Pulled out a `_fetch_owm` helper, collapsing the four near-identical `fetch_*` functions from about 80 duplicated lines down to about 25.
- Pulled out `smoothed_forecast` so the prediction recipe (MA(3) -> EWMA(0.5)) lives in one place, shared by the CLI and the dashboard.
- Added `# === ... ===` section banners for Constants, OWM Client, Classification & Prediction, Alerting, Subscriptions, CLI Entry Point, Streamlit Dashboard, and Entry-Point Dispatch.
- Replaced narration-only comments with short docstrings on every public function.

The injected CSS and the legend HTML moved to module-level constants (`_DASHBOARD_CSS`, `_LEGEND_HTML`), pulling about 80 lines of inline markup out of `streamlit_app()`.

### Verifications

After the fixes landed, the regression checks below ran and all passed:
- `python -c "import ast; ast.parse(open('weather_monitor.py').read())"`: the file still parses.
- The eight `classify_rainfall` boundary assertions from the second iteration still passed.
- `moving_average`, `exponential_smoothing`, and `smoothed_forecast` on synthetic series gave the same results as the pre-refactor version.
- `_rain_amount` against the rain-field shapes (null, missing, `{}`, populated) gave the same results.
- `build_alert_email_body` produced the same body strings for `simulated=True` and `simulated=False`.
- `log_red_alert` kept the same line format, ISO 8601 UTC timestamp, and `| SIMULATED` tag.
- `save_subscription` kept the same JSON record schema.
- CLI smoke: `echo Milan | python weather_monitor.py --simulate 5` -> `Milan: 5.00 mm/h - Green`, unchanged.
- CLI smoke: `echo Beijing | python weather_monitor.py --simulate 25` -> `Beijing: 25.00 mm/h - Red` plus `ALERT: Heavy rainfall in Beijing (>= 20 mm/h)`, unchanged.
- AppTest empty-state run: 0 exceptions, same landing message.

### Changes Made

I made a few small comment edits and removals by hand. Nothing else.
