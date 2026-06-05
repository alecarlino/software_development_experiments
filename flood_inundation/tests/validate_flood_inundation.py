#!/usr/bin/env python3
"""Standalone physical-validation script for the flood inundation model.

This is NOT a pytest unit test (it is deliberately kept separate from
`test_flood_inundation.py`). It runs the flood model over a sweep of water
levels and checks that it behaves physically: the flooded area must never
shrink as the water rises, the elevation values must be plausible as metres
(a unit-mismatch heuristic), and no implausible results should appear. It
writes a Markdown report and exits non-zero if validation fails.

Run from the project root:
    python tests/validate_flood_inundation.py
"""

import os
import sys

# This script lives in tests/; put the project root on the path so that
# `import flood_inundation` works when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402 - must follow the sys.path tweak above

from flood_inundation import (  # noqa: E402
    add_buildings,
    generate_synthetic_dem,
    inundation_depth,
    is_monotonic_non_decreasing,
    simulate_dynamic_flood,
)


# ===========================================================================
# CONSTANTS
# ===========================================================================

# Highest point on Earth in metres (Mount Everest). A DEM whose maximum
# exceeds this is physically implausible as metres and is likely in feet.
EARTH_MAX_ELEVATION_M = 8849.0
FEET_PER_METRE = 3.28084

DEM_PATH = os.path.join(_ROOT, "dem_data.npy")
REPORT_PATH = os.path.join(_HERE, "validation_report.md")


# ===========================================================================
# DEM INPUT
# ===========================================================================

def load_dem():
    """Use the saved project DEM if present, else a deterministic synthetic one."""
    if os.path.exists(DEM_PATH):
        return np.load(DEM_PATH)
    return add_buildings(generate_synthetic_dem(seed=0), [(10, 10, 8, 12)])


# ===========================================================================
# PHYSICAL CHECKS
# ===========================================================================

def check_monotonicity(dem):
    """Sweep the water level across the DEM range and inspect the flooded area."""
    start = float(np.floor(dem.min()))
    stop = float(np.ceil(dem.max()))
    step = (stop - start) / 20.0
    levels, percentages = simulate_dynamic_flood(dem, start, stop, step)

    diffs = np.diff(percentages)
    drops = [(float(levels[i]), float(levels[i + 1]), float(diffs[i]))
             for i in np.where(diffs < 0)[0]]
    plateaus = [(float(levels[i]), float(levels[i + 1]))
                for i in np.where(diffs == 0)[0]]
    return {
        "levels": levels,
        "percentages": percentages,
        "passed": is_monotonic_non_decreasing(percentages),
        "drops": drops,
        "plateaus": plateaus,
    }


def check_units(dem):
    """Heuristic metres-vs-feet check based on plausible terrestrial elevation."""
    max_elev = float(dem.max())
    if max_elev > EARTH_MAX_ELEVATION_M:
        message = (
            f"Maximum elevation {max_elev:.1f} exceeds Earth's highest point "
            f"(~{EARTH_MAX_ELEVATION_M:.0f} m). The values look implausible as "
            f"metres and may actually be in feet "
            f"(~{max_elev / FEET_PER_METRE:.1f} m if converted)."
        )
        return False, message
    message = (f"Maximum elevation {max_elev:.1f} m is within a plausible range "
               f"for metres; no unit mismatch detected.")
    return True, message


def check_values(dem, levels, percentages):
    """Collect any implausible results (out-of-range %, wrong maximum depth)."""
    anomalies = []
    if np.any(percentages < 0) or np.any(percentages > 100):
        anomalies.append("Flooded percentage fell outside the valid 0-100% range.")

    # The deepest water at a given level is over the lowest cell:
    # max depth must equal water_level - min(elevation).
    test_level = float(np.median(levels))
    depth = inundation_depth(dem, test_level)
    expected_max = max(0.0, test_level - float(dem.min()))
    if not np.isclose(float(depth.max()), expected_max):
        anomalies.append(
            f"Maximum depth {depth.max():.2f} m at {test_level:g} m does not match "
            f"the expected {expected_max:.2f} m (water_level - min elevation)."
        )
    return anomalies


# ===========================================================================
# REPORT
# ===========================================================================

def build_report(mono, unit_ok, unit_msg, anomalies, verdict):
    """Assemble the Markdown validation report as a string."""
    lines = [
        "# Flood Inundation - Physical Validation Report",
        "",
        f"**Verdict: {verdict}**",
        "",
        "## 1. Monotonicity of flooded area",
        "",
        ("The flooded area must never decrease as the water level rises."),
        "",
        f"- Result: {'PASS' if mono['passed'] else 'FAIL'}",
        f"- Water levels swept: {mono['levels'][0]:g} m to "
        f"{mono['levels'][-1]:g} m ({len(mono['levels'])} steps)",
    ]
    if mono["drops"]:
        lines.append(f"- Non-monotonic drops detected: {mono['drops']}")
    else:
        lines.append("- Non-monotonic drops detected: none")
    if mono["plateaus"]:
        lines.append(
            f"- Plateaus (flat steps, allowed but noted): {len(mono['plateaus'])} "
            f"step(s), e.g. {mono['plateaus'][:3]}"
        )
    else:
        lines.append("- Plateaus: none")

    lines += [
        "",
        "### Water level vs. flooded area",
        "",
        "| Water level (m) | Flooded area (%) |",
        "| ---: | ---: |",
    ]
    for level, pct in zip(mono["levels"], mono["percentages"]):
        lines.append(f"| {level:.1f} | {pct:.2f} |")

    lines += [
        "",
        "## 2. Unit check (metres vs. feet)",
        "",
        f"- Result: {'PASS' if unit_ok else 'WARNING'}",
        f"- {unit_msg}",
        "",
        "## 3. Anomalies / unexpected behaviour",
        "",
    ]
    if anomalies:
        lines += [f"- {item}" for item in anomalies]
    else:
        lines.append("- None: all checked values are within physical expectations.")

    lines += ["", "---", f"Final verdict: **{verdict}**", ""]
    return "\n".join(lines)


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def main():
    dem = load_dem()

    mono = check_monotonicity(dem)
    unit_ok, unit_msg = check_units(dem)
    anomalies = check_values(dem, mono["levels"], mono["percentages"])

    passed = mono["passed"] and unit_ok and not anomalies
    verdict = "PASS" if passed else "FAIL"

    report = build_report(mono, unit_ok, unit_msg, anomalies, verdict)
    with open(REPORT_PATH, "w") as handle:
        handle.write(report)

    print(f"Validation {verdict}. Report written to {REPORT_PATH}")
    if not unit_ok:
        print(f"  WARNING (units): {unit_msg}")
    if mono["drops"]:
        print(f"  Monotonicity violated at: {mono['drops']}")
    for item in anomalies:
        print(f"  Anomaly: {item}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
