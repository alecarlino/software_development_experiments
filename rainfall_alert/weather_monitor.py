"""Rainfall monitoring: fetch weather, classify, alert, predict and visualise.

Two entry points share one file:

* CLI mode (``python weather_monitor.py``) — prompts for a city, fetches
  current weather, classifies rainfall against the project thresholds,
  optionally writes a Red-alert log line, sends an SMTP email and / or
  prints a smoothed 5-day forecast.
* Dashboard mode (``streamlit run weather_monitor.py``) — renders a
  three-column Streamlit page with metrics, a Folium map (OWM tile
  overlays + HeatMap from nearby cities), a forecast chart, an alert
  table and an email-subscription form.

The ``__main__`` block at the bottom dispatches between the two.
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests


# ===========================================================================
# CONSTANTS
# ===========================================================================

# OpenWeatherMap endpoints (free tier).
API_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
GEOCODE_URL = "https://api.openweathermap.org/geo/1.0/direct"
FIND_URL = "https://api.openweathermap.org/data/2.5/find"

REQUEST_TIMEOUT = 10  # seconds, applied to every outgoing HTTP request

# Local persistence files (created on first write).
LOG_FILE = "alert_log.txt"
SUBSCRIPTIONS_FILE = "subscriptions.json"


# ===========================================================================
# OPENWEATHERMAP CLIENT
# ===========================================================================

def get_api_key() -> str:
    """Return the OpenWeatherMap API key from the ``OWM_API_KEY`` env var."""
    api_key = os.environ.get("OWM_API_KEY")
    if not api_key:
        sys.exit("OWM_API_KEY environment variable is not set.")
    return api_key


def _fetch_owm(
    url: str,
    params: dict,
    label: str,
    not_found_msg: str | None = None,
) -> dict | list:
    """GET an OpenWeatherMap endpoint and return the parsed JSON.

    Surfaces network, auth, HTTP and JSON errors via ``sys.exit`` so the
    CLI prints a clean message; the dashboard catches ``SystemExit`` and
    re-displays the message via ``st.error``.

    ``label`` is the human name of the endpoint (``weather``, ``forecast``,
    ``geocoding``, ``find``) and is interpolated into error messages.
    ``not_found_msg``, if provided, replaces the generic non-200 message
    when the response is HTTP 404 — used by callers that have a city name
    available to make the message more helpful.
    """
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.Timeout:
        sys.exit(f"Request timed out while contacting OpenWeatherMap ({label}).")
    except requests.ConnectionError:
        sys.exit(f"Network error while contacting OpenWeatherMap ({label}).")

    if response.status_code == 401:
        sys.exit("Invalid API key (HTTP 401).")
    if response.status_code == 404 and not_found_msg is not None:
        sys.exit(not_found_msg)
    if response.status_code != 200:
        sys.exit(
            f"OpenWeatherMap {label} error (HTTP {response.status_code}): "
            f"{response.text[:200]}"
        )

    try:
        return response.json()
    except ValueError:
        sys.exit(f"Malformed JSON in {label} response.")


def fetch_weather(city: str, api_key: str) -> dict:
    """Return the raw current-weather payload for ``city``."""
    return _fetch_owm(
        API_URL,
        {"q": city, "appid": api_key, "units": "metric"},
        label="weather",
        not_found_msg=f"City not found: {city!r} (HTTP 404).",
    )


def fetch_forecast(city: str, api_key: str) -> list[float]:
    """Return the 5-day / 3-hour rainfall forecast as a list of mm-per-3h values."""
    payload = _fetch_owm(
        FORECAST_URL,
        {"q": city, "appid": api_key},
        label="forecast",
        not_found_msg=f"City not found: {city!r} (HTTP 404).",
    )
    return [_rain_amount(item, "3h") for item in payload.get("list", [])]


def geocode_city(query: str, api_key: str, limit: int = 5) -> list[dict]:
    """Resolve a free-text city name to candidate {name, country, state, lat, lon}s."""
    return _fetch_owm(
        GEOCODE_URL,
        {"q": query, "limit": limit, "appid": api_key},
        label="geocoding",
    )


def fetch_nearby_cities(
    lat: float, lon: float, api_key: str, count: int = 50
) -> list[dict]:
    """Return up to ``count`` cities near (lat, lon) with current weather data.

    Used by the dashboard to feed the Folium HeatMap with real point data.
    """
    payload = _fetch_owm(
        FIND_URL,
        {"lat": lat, "lon": lon, "cnt": count, "appid": api_key, "units": "metric"},
        label="find",
    )
    return payload.get("list", [])


def _rain_amount(item: dict, key: str) -> float:
    """Extract ``item['rain'][key]`` in mm; return 0.0 if absent or null.

    OWM's ``/find`` endpoint returns ``"rain": null`` (not just omitted) for
    dry cities, so a defensive ``or {}`` is needed before the inner lookup.
    Used uniformly so every endpoint is parsed the same way.
    """
    return (item.get("rain") or {}).get(key, 0.0)


# ===========================================================================
# CLASSIFICATION & PREDICTION (pure)
# ===========================================================================

def classify_rainfall(mm_per_hour: float) -> str:
    """Return ``Green``, ``Yellow`` or ``Red`` for the given rainfall rate.

    Thresholds are fixed by the project specification — do not adjust.
    """
    if mm_per_hour >= 20:
        return "Red"
    if mm_per_hour >= 10:
        return "Yellow"
    return "Green"


def moving_average(series: list[float], window: int = 3) -> list[float]:
    """Right-aligned boxcar moving average; output length matches input length.

    The first ``window - 1`` positions use a partial window so no values are
    dropped at the start of the series.
    """
    out = []
    for i in range(len(series)):
        chunk = series[max(0, i - window + 1) : i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def exponential_smoothing(series: list[float], alpha: float = 0.5) -> list[float]:
    """Standard EWMA: s[0] = series[0]; s[t] = α·x[t] + (1-α)·s[t-1]."""
    if not series:
        return []
    out = [series[0]]
    for value in series[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def smoothed_forecast(forecast_3h_mm: list[float]) -> list[float]:
    """Convert a 3h-bucket rainfall forecast (mm) into a smoothed mm/h series.

    Pipes the per-hour rates through MA(window=3) then EWMA(α=0.5) so
    single-bucket spikes are dampened and the near future is weighted more
    heavily. Used by both the CLI prediction and the dashboard chart.
    """
    hourly_rate = [bucket / 3 for bucket in forecast_3h_mm]
    return exponential_smoothing(moving_average(hourly_rate, window=3), alpha=0.5)


def report_prediction(city: str, forecast: list[float]) -> None:
    """Print a 24-hour summary derived from the smoothed forecast series."""
    if not forecast:
        sys.exit("Forecast returned no buckets; cannot predict.")

    smoothed = smoothed_forecast(forecast)

    next_3h_rate = smoothed[0]
    # 8 buckets × 3h = 24h; multiply mm/h by 3 to recover mm per bucket.
    next_24h_total_mm = sum(smoothed[:8]) * 3
    imminent = any(rate >= 20 for rate in smoothed[:8])

    print(f"Prediction for {city} (next 24h):")
    print(f"  Next 3h rate:   {next_3h_rate:.2f} mm/h")
    print(f"  Next 24h total: {next_24h_total_mm:.2f} mm")
    print(f"  Imminent alert: {'yes' if imminent else 'no'}")


# ===========================================================================
# ALERTING — LOG FILE & EMAIL
# ===========================================================================

def log_red_alert(city: str, rainfall_mm: float, simulated: bool = False) -> None:
    """Append one line per Red alert to ``alert_log.txt``.

    Timestamps are ISO 8601 UTC. ``--simulate``-driven alerts are tagged
    with ``| SIMULATED`` so they can be filtered out of the historical log
    later (e.g. ``grep -v SIMULATED alert_log.txt``).
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"{timestamp} | {city} | {rainfall_mm:.2f} mm/h"
    if simulated:
        line += " | SIMULATED"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_smtp_config() -> tuple[str, int, str, str]:
    """Read SMTP settings from env vars; ``SMTP_PORT`` defaults to 587 (STARTTLS)."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    port_raw = os.environ.get("SMTP_PORT", "587")

    missing = [
        name
        for name, value in (
            ("SMTP_HOST", host),
            ("SMTP_USER", user),
            ("SMTP_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Missing required SMTP env var(s): {', '.join(missing)}")

    try:
        port = int(port_raw)
    except ValueError:
        sys.exit(f"SMTP_PORT must be an integer, got: {port_raw!r}")

    return host, port, user, password


def build_alert_email_body(city: str, rainfall_mm: float, simulated: bool) -> str:
    """Return the plain-text body for a Red-alert email.

    Pure function — kept separate so the body format is testable without
    actually sending a message.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Heavy rainfall detected in {city}: {rainfall_mm:.2f} mm/h at {timestamp}.",
        "",
        "This rainfall has crossed the Red alert threshold (>= 20 mm/h).",
    ]
    if simulated:
        lines.append("")
        lines.append("[SIMULATED — generated via --simulate flag for testing]")
    return "\n".join(lines)


def send_alert_email(
    recipient: str, city: str, rainfall_mm: float, simulated: bool = False
) -> None:
    """Send a plain-text Red-alert email via SMTP + STARTTLS."""
    host, port, user, password = get_smtp_config()

    msg = EmailMessage()
    msg["Subject"] = f"Rainfall ALERT: {city}"
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content(build_alert_email_body(city, rainfall_mm, simulated))

    try:
        with smtplib.SMTP(host, port, timeout=REQUEST_TIMEOUT) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        sys.exit(f"SMTP error while sending alert email: {e}")
    except OSError as e:
        sys.exit(f"Network error while sending alert email: {e}")


# ===========================================================================
# SUBSCRIPTIONS
# ===========================================================================

def save_subscription(email: str, city: str, country: str) -> None:
    """Append an {email, city, country, subscribed_at} record to subscriptions.json.

    Read-modify-write of the whole file. Adequate for a course-project
    workload (low write rate, single user); not concurrency-safe.
    """
    record = {
        "email": email,
        "city": city,
        "country": country,
        "subscribed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = Path(SUBSCRIPTIONS_FILE)
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
        if not isinstance(data, list):
            data = []
    else:
        data = []
    data.append(record)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ===========================================================================
# CLI ENTRY POINT
# ===========================================================================

def main() -> None:
    """CLI mode: prompt for a city, optionally simulate / predict / email."""
    parser = argparse.ArgumentParser(description="Rainfall monitor.")
    parser.add_argument(
        "--simulate",
        type=float,
        metavar="MM",
        help="Bypass the API and use this rainfall value (mm/h) instead.",
    )
    parser.add_argument(
        "--predict",
        action="store_true",
        help="Also fetch the 5-day forecast and print a smoothed prediction.",
    )
    parser.add_argument(
        "--email",
        metavar="ADDR",
        help=(
            "Send a Red-alert email to this address. "
            "Requires SMTP_HOST, SMTP_USER, SMTP_PASSWORD env vars "
            "(SMTP_PORT defaults to 587)."
        ),
    )
    args = parser.parse_args()

    city = input("City: ").strip()
    if not city:
        sys.exit("City name cannot be empty.")

    if args.simulate is not None:
        rainfall_mm = args.simulate
    else:
        api_key = get_api_key()
        data = fetch_weather(city, api_key)
        rainfall_mm = _rain_amount(data, "1h")

    level = classify_rainfall(rainfall_mm)
    print(f"{city}: {rainfall_mm:.2f} mm/h - {level}")

    if level == "Red":
        print(f"ALERT: Heavy rainfall in {city} (>= 20 mm/h)")
        log_red_alert(city, rainfall_mm, simulated=args.simulate is not None)
        # Email is opt-in via --email; sent after logging so a flaky network
        # send doesn't lose the durable log entry.
        if args.email:
            send_alert_email(
                args.email, city, rainfall_mm, simulated=args.simulate is not None
            )

    # Prediction always uses the real forecast endpoint, regardless of --simulate.
    if args.predict:
        forecast = fetch_forecast(city, get_api_key())
        report_prediction(city, forecast)


# ===========================================================================
# STREAMLIT DASHBOARD
# ===========================================================================

def _city_label(match: dict) -> str:
    """Format a geocoded match as ``Name, State, Country`` (skipping missing parts)."""
    parts = [match.get("name", "")]
    if match.get("state"):
        parts.append(match["state"])
    if match.get("country"):
        parts.append(match["country"])
    return ", ".join(p for p in parts if p)


# CSS injected at the top of the dashboard page.
# Equalises column heights to col3's natural extent, then lets each column's
# last card stretch so any leftover space sits inside that card (not between
# cards). The selectors target Streamlit's data-testid attributes, which are
# version-dependent (validated against streamlit 1.32).
_DASHBOARD_CSS = """
<style>
section[data-testid="stMain"] div[data-testid="stColumn"] {
    min-height: 720px;
}
section[data-testid="stMain"] div[data-testid="stColumn"]
    > div > div[data-testid="stVerticalBlock"] {
    height: 100%;
    display: flex;
    flex-direction: column;
}
section[data-testid="stMain"] div[data-testid="stColumn"]
    > div > div[data-testid="stVerticalBlock"] > div:last-child {
    flex-grow: 1;
    display: flex;
    flex-direction: column;
}
section[data-testid="stMain"] div[data-testid="stColumn"]
    > div > div[data-testid="stVerticalBlock"] > div:last-child
    div[data-testid="stVerticalBlock"] {
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
</style>
"""

# Static HTML for the map legend — gradient bars for the four OWM overlays.
_LEGEND_HTML = """
<style>
.lg-row {display: flex; align-items: center;
         margin: 6px 0; font-size: 0.85em; gap: 8px;}
.lg-label {min-width: 110px; font-weight: 600;}
.lg-bar {flex: 1; height: 14px; border-radius: 3px;
         border: 1px solid #333;}
.lg-min, .lg-max {min-width: 80px; color: #aaa;
                  font-variant-numeric: tabular-nums;}
.lg-min {text-align: right;}
.lg-max {text-align: left;}
</style>
<div class="lg-row">
    <span class="lg-label">Precipitation</span>
    <span class="lg-min">0</span>
    <span class="lg-bar" style="background: linear-gradient(
        to right, #cce6ff, #66b3ff, #0066cc, #003366);"></span>
    <span class="lg-max">25+ mm/h</span>
</div>
<div class="lg-row">
    <span class="lg-label">Temperature</span>
    <span class="lg-min">-30</span>
    <span class="lg-bar" style="background: linear-gradient(
        to right, #3300cc, #00ccff, #33cc33,
        #ffff00, #ff6600, #cc0000);"></span>
    <span class="lg-max">35+ °C</span>
</div>
<div class="lg-row">
    <span class="lg-label">Clouds</span>
    <span class="lg-min">0</span>
    <span class="lg-bar" style="background: linear-gradient(
        to right, #1a1a1a, #888888, #ffffff);"></span>
    <span class="lg-max">100 %</span>
</div>
<div class="lg-row">
    <span class="lg-label">Wind</span>
    <span class="lg-min">0</span>
    <span class="lg-bar" style="background: linear-gradient(
        to right, #aaffaa, #ffcc33, #ff3333);"></span>
    <span class="lg-max">30+ m/s</span>
</div>
"""

# OWM tile-overlay catalogue: (UI label, tile slug, visible by default).
_OWM_TILE_LAYERS = [
    ("Precipitation", "precipitation_new", True),
    ("Clouds", "clouds_new", False),
    ("Temperature", "temp_new", False),
    ("Wind", "wind_new", False),
]


def streamlit_app() -> None:
    """Render the dashboard. Entered when invoked under ``streamlit run``."""
    # Dashboard-only imports kept inside the function so the CLI doesn't need
    # the heavier dependencies (folium, pandas, streamlit, etc.) installed.
    import altair as alt
    import folium
    import pandas as pd
    import streamlit as st
    from folium.plugins import HeatMap
    from streamlit_autorefresh import st_autorefresh
    from streamlit_folium import st_folium

    st.set_page_config(page_title="Rainfall Monitor", layout="wide")
    st_autorefresh(interval=300_000, key="rainfall_autorefresh")
    st.markdown(_DASHBOARD_CSS, unsafe_allow_html=True)

    api_key = os.environ.get("OWM_API_KEY")
    if not api_key:
        st.error("OWM_API_KEY environment variable is not set.")
        st.stop()

    # ------------------------------------------------------------------
    # SIDEBAR — city search + alert subscription
    # ------------------------------------------------------------------
    selected = None
    with st.sidebar:
        st.title("Rainfall Monitor")
        st.caption("Real-time rain alerts and forecasts")

        st.subheader("City")
        query = st.text_input("Search", placeholder="e.g. Beijing", key="city_query")

        if query:
            try:
                matches = geocode_city(query, api_key)
            except SystemExit as e:
                st.error(str(e))
                matches = []

            if not matches:
                st.warning(f"No cities found matching {query!r}.")
            else:
                choice_idx = st.selectbox(
                    "Select",
                    options=list(range(len(matches))),
                    format_func=lambda i: _city_label(matches[i]),
                    key="city_choice",
                )
                selected = matches[choice_idx]

        st.divider()
        st.subheader("Subscribe to alerts")
        st.caption("Enter your email to be notified of future alerts")
        with st.form("subscribe_form"):
            email_input = st.text_input("Email address", key="subscribe_email")
            submitted = st.form_submit_button("Subscribe")
            if submitted:
                if selected is None:
                    st.error("Pick a city first.")
                elif not email_input or "@" not in email_input:
                    st.error("Enter a valid email address.")
                else:
                    save_subscription(
                        email_input, selected["name"], selected.get("country", "")
                    )
                    st.success(f"Subscribed to {_city_label(selected)}.")

    if selected is None:
        st.title("Rainfall Monitor")
        st.info("Search and select a city in the sidebar to begin.")
        st.stop()

    # ------------------------------------------------------------------
    # FETCH — current weather and forecast for the selected city
    # ------------------------------------------------------------------
    city_name = selected["name"]
    country = selected.get("country", "")
    lat = selected["lat"]
    lon = selected["lon"]
    city_query = f"{city_name},{country}" if country else city_name

    try:
        data = fetch_weather(city_query, api_key)
    except SystemExit as e:
        st.error(str(e))
        st.stop()

    rainfall_mm = _rain_amount(data, "1h")
    level = classify_rainfall(rainfall_mm)
    temp = data.get("main", {}).get("temp")
    humidity = data.get("main", {}).get("humidity")
    wind = data.get("wind", {}).get("speed")

    try:
        forecast = fetch_forecast(city_query, api_key)
    except SystemExit as e:
        st.error(str(e))
        forecast = []

    smoothed = smoothed_forecast(forecast) if forecast else []

    # Top-of-page Red banner so an active alert is impossible to miss.
    if level == "Red":
        st.error(
            f"ALERT: Heavy rainfall in {city_name} "
            f"({rainfall_mm:.2f} mm/h, threshold 20 mm/h)"
        )

    # ------------------------------------------------------------------
    # MAIN AREA — three columns
    # ------------------------------------------------------------------
    col1, col2, col3 = st.columns([1, 2, 1.5])

    # ---- Column 1: weather metrics + alert status & info ----
    with col1:
        with st.container(border=True):
            st.subheader("Weather")
            st.metric("Rainfall", f"{rainfall_mm:.2f} mm/h")
            st.metric(
                "Temperature",
                f"{temp:.1f} °C" if isinstance(temp, (int, float)) else "—",
            )
            st.metric(
                "Humidity",
                f"{humidity}%" if humidity is not None else "—",
            )
            st.metric(
                "Wind",
                f"{wind:.1f} m/s" if isinstance(wind, (int, float)) else "—",
            )

        with st.container(border=True):
            st.subheader("Alert Status & Info")
            if level == "Red":
                st.error(f"Active alert: {level}")
            elif level == "Yellow":
                st.warning(f"Watch: {level}")
            else:
                st.success(f"No alert: {level}")
            st.markdown(
                """
                **Data source:** OpenWeatherMap

                **Alert thresholds (mm/h):**
                - Green: < 10 (Normal)
                - Yellow: 10 - 20 (Moderate)
                - Red: ≥ 20 (Heavy)

                **Auto-refresh:** every 5 minutes
                """
            )

    # ---- Column 2: rainfall map (multi-layer OWM overlays + HeatMap) ----
    with col2:
        with st.container(border=True):
            st.subheader("Rainfall Map")

            # Real point data for the HeatMap (nearby cities + current rainfall).
            try:
                nearby = fetch_nearby_cities(lat, lon, api_key, count=50)
            except SystemExit as e:
                st.warning(f"Nearby data unavailable: {e}")
                nearby = []

            # Build the map without a base tile, then add the dark Carto tile
            # with control=False so it doesn't appear in the LayerControl popup.
            fmap = folium.Map(location=[lat, lon], zoom_start=7, tiles=None)
            folium.TileLayer("cartodbdark_matter", control=False).add_to(fmap)

            # OWM weather tile overlays — sequential gradients on real model
            # data. Precipitation is visible by default; the rest are opt-in
            # from the layer-control panel on the map.
            for label, slug, visible in _OWM_TILE_LAYERS:
                folium.raster_layers.TileLayer(
                    tiles=(
                        f"https://tile.openweathermap.org/map/{slug}/"
                        f"{{z}}/{{x}}/{{y}}.png?appid={api_key}"
                    ),
                    attr="OpenWeatherMap",
                    name=label,
                    overlay=True,
                    control=True,
                    opacity=0.75,
                    show=visible,
                ).add_to(fmap)

            # HeatMap from real rainfall at the surrounding cities (skipped
            # for cities with no rain so dry days show no spurious points).
            heat_points = [
                [c["coord"]["lat"], c["coord"]["lon"], _rain_amount(c, "1h")]
                for c in nearby
                if _rain_amount(c, "1h") > 0
            ]
            if heat_points:
                HeatMap(
                    heat_points,
                    radius=35,
                    blur=25,
                    min_opacity=0.4,
                    gradient={
                        0.0: "#001f4d",
                        0.3: "#0066cc",
                        0.5: "#3399ff",
                        0.7: "#66ccff",
                        1.0: "#ccffff",
                    },
                    name="Rain HeatMap",
                ).add_to(fmap)

            # City marker on top, colour-coded by current alert level. ``.get``
            # falls back to a safe default if classify_rainfall ever returns
            # something unexpected.
            colour_by_level = {"Green": "green", "Yellow": "orange", "Red": "red"}
            folium.Marker(
                location=[lat, lon],
                popup=f"{city_name}: {rainfall_mm:.2f} mm/h - {level}",
                icon=folium.Icon(
                    color=colour_by_level.get(level, "blue"), icon="cloud"
                ),
            ).add_to(fmap)
            folium.LayerControl(collapsed=False).add_to(fmap)

            st_folium(fmap, width=None, height=525, returned_objects=[])

        with st.container(border=True):
            st.markdown("**Map legend**")
            st.markdown(_LEGEND_HTML, unsafe_allow_html=True)

    # ---- Column 3: rainfall forecast chart + alert forecast table ----
    with col3:
        with st.container(border=True):
            st.subheader("Rainfall Forecast (Next 5 days)")
            if smoothed:
                df_ts = pd.DataFrame(
                    {
                        "Hours from now": [3 * i for i in range(len(smoothed))],
                        "Rainfall (mm/h)": smoothed,
                    }
                )
                chart = (
                    alt.Chart(df_ts)
                    .mark_line()
                    .encode(
                        x=alt.X("Hours from now:Q", title="Hours from now (h)"),
                        y=alt.Y("Rainfall (mm/h):Q", title="Rainfall (mm/h)"),
                        tooltip=["Hours from now", "Rainfall (mm/h)"],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("Forecast unavailable.")

        with st.container(border=True):
            st.subheader("Alert Forecast (Next 24h)")
            if smoothed:
                rows = [
                    {
                        "Hour": f"+{i * 3}h",
                        "mm/h": round(rate, 2),
                        "Level": classify_rainfall(rate),
                    }
                    for i, rate in enumerate(smoothed[:8])
                ]
                df_alerts = pd.DataFrame(rows)
                st.dataframe(df_alerts, hide_index=True, use_container_width=True)
                if any(r["Level"] == "Red" for r in rows):
                    st.warning("Imminent alert within the next 24 hours.")
            else:
                st.info("Alert forecast unavailable.")


# ===========================================================================
# ENTRY-POINT DISPATCH
# ===========================================================================

if __name__ == "__main__":
    # Detect ``streamlit run`` vs plain ``python`` and dispatch accordingly.
    # If streamlit isn't installed at all, fall through to the CLI.
    try:
        import streamlit as _st

        if _st.runtime.exists():
            streamlit_app()
        else:
            main()
    except ImportError:
        main()
