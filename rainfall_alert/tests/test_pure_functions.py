"""Pure-function tests for weather_monitor.

Run from the project root with:

    pytest tests/

These tests cover the deterministic, side-effect-free parts of the
application (classification, smoothing, rain extraction, email body)
plus the two side-effectful helpers whose contract is worth pinning
in a regression test (`log_red_alert` writes one line in a known
format, `save_subscription` round-trips a JSON record).
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Make the project root importable regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import weather_monitor as wm  # noqa: E402


# ---------------------------------------------------------------------------
# classify_rainfall: boundary matrix from the project spec
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mm_per_hour, expected_level",
    [
        (0.0,   "Green"),
        (5.0,   "Green"),
        (9.99,  "Green"),
        (10.0,  "Yellow"),
        (15.0,  "Yellow"),
        (19.99, "Yellow"),
        (20.0,  "Red"),
        (25.0,  "Red"),
    ],
)
def test_classify_rainfall_boundaries(mm_per_hour, expected_level):
    assert wm.classify_rainfall(mm_per_hour) == expected_level


# ---------------------------------------------------------------------------
# moving_average
# ---------------------------------------------------------------------------

def test_moving_average_partial_window_at_start():
    # Output length matches input; first positions use partial windows.
    assert wm.moving_average([1, 2, 3, 4, 5], window=3) == [1.0, 1.5, 2.0, 3.0, 4.0]


def test_moving_average_constant_series_unchanged():
    assert wm.moving_average([7, 7, 7, 7], window=3) == [7.0, 7.0, 7.0, 7.0]


def test_moving_average_empty():
    assert wm.moving_average([], window=3) == []


# ---------------------------------------------------------------------------
# exponential_smoothing
# ---------------------------------------------------------------------------

def test_exponential_smoothing_alpha_one_passes_through():
    assert wm.exponential_smoothing([1, 2, 3], alpha=1.0) == [1, 2, 3]


def test_exponential_smoothing_alpha_zero_freezes_at_first_value():
    assert wm.exponential_smoothing([1, 2, 3], alpha=0.0) == [1, 1, 1]


def test_exponential_smoothing_known_recurrence():
    # s0 = 0; s1 = 0.5*4 + 0.5*0 = 2; s2 = 0.5*0 + 0.5*2 = 1
    assert wm.exponential_smoothing([0, 4, 0], alpha=0.5) == [0, 2.0, 1.0]


def test_exponential_smoothing_empty():
    assert wm.exponential_smoothing([], alpha=0.5) == []


# ---------------------------------------------------------------------------
# smoothed_forecast (composition: MA then EWMA)
# ---------------------------------------------------------------------------

def test_smoothed_forecast_dry_input_stays_zero():
    assert wm.smoothed_forecast([0.0] * 40) == [0.0] * 40


def test_smoothed_forecast_empty_input():
    assert wm.smoothed_forecast([]) == []


# ---------------------------------------------------------------------------
# _rain_amount: regression test for the OWM "rain": null bug found in Iter 5
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "item, expected",
    [
        ({"rain": None},          0.0),  # OWM /find returns rain: null on dry days
        ({},                       0.0),  # rain key absent entirely
        ({"rain": {}},             0.0),  # rain dict present but empty
        ({"rain": {"1h": 0.0}},    0.0),  # zero rain explicitly
        ({"rain": {"1h": 5.5}},    5.5),  # real rainfall value
    ],
)
def test_rain_amount_handles_all_shapes(item, expected):
    assert wm._rain_amount(item, "1h") == expected


# ---------------------------------------------------------------------------
# build_alert_email_body
# ---------------------------------------------------------------------------

def test_build_alert_email_body_real():
    body = wm.build_alert_email_body("Milan", 23.4, simulated=False)
    assert "Milan" in body
    assert "23.40 mm/h" in body
    assert "Red alert threshold" in body
    assert "SIMULATED" not in body


def test_build_alert_email_body_simulated():
    body = wm.build_alert_email_body("Rome", 50.0, simulated=True)
    assert "Rome" in body
    assert "50.00 mm/h" in body
    assert "SIMULATED" in body


# ---------------------------------------------------------------------------
# log_red_alert: line format + ISO 8601 UTC timestamp
# ---------------------------------------------------------------------------

def test_log_red_alert_appends_iso8601_utc_line(tmp_path, monkeypatch):
    log_path = tmp_path / "alert_log.txt"
    monkeypatch.setattr(wm, "LOG_FILE", str(log_path))

    wm.log_red_alert("Milan", 23.4)
    wm.log_red_alert("Rome", 50.0, simulated=True)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # Real alert: three pipe-separated fields, ISO 8601 UTC timestamp.
    parts = [p.strip() for p in lines[0].split("|")]
    assert len(parts) == 3
    timestamp, city, rate = parts
    assert city == "Milan"
    assert rate == "23.40 mm/h"
    parsed = datetime.fromisoformat(timestamp)
    assert parsed.utcoffset().total_seconds() == 0

    # Simulated alert: trailing SIMULATED marker.
    assert lines[1].endswith("| SIMULATED")


# ---------------------------------------------------------------------------
# save_subscription: round-trip into subscriptions.json
# ---------------------------------------------------------------------------

def test_save_subscription_round_trip(tmp_path, monkeypatch):
    sub_path = tmp_path / "subscriptions.json"
    monkeypatch.setattr(wm, "SUBSCRIPTIONS_FILE", str(sub_path))

    wm.save_subscription("a@example.com", "Milan", "IT")
    wm.save_subscription("b@example.com", "Rome", "IT")

    data = json.loads(sub_path.read_text(encoding="utf-8"))
    assert len(data) == 2

    first, second = data
    assert first["email"] == "a@example.com"
    assert first["city"] == "Milan"
    assert first["country"] == "IT"
    assert "subscribed_at" in first
    # Timestamp must parse as ISO 8601 UTC.
    assert datetime.fromisoformat(first["subscribed_at"]).utcoffset().total_seconds() == 0

    assert second["email"] == "b@example.com"
    assert second["city"] == "Rome"
