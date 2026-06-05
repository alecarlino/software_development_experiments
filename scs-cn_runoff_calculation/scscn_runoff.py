"""SCS-CN direct runoff estimation, with AMC adjustment, routing and a Rational baseline.

Four functions build on one another:

* ``calculate_runoff`` — the core SCS-CN equation (rainfall P, curve number
  CN -> runoff depth Q) with the physical boundaries: no runoff below the
  initial abstraction, Q clamped to P, and CN = 0 / CN = 100 handled without
  a divide-by-zero.
* ``adjust_cn_for_amc`` — converts a curve number between antecedent moisture
  conditions (AMC I dry, II average, III wet) via the Sobhani formulas; wired
  into ``calculate_runoff`` through its ``amc`` argument.
* ``route_time_area`` — routes excess rainfall into an outflow hydrograph
  (m³/s) with the time-area method, respecting the nonlinearity of SCS-CN.
* ``rational_runoff`` — the Rational method as an independent estimate,
  returned as a depth so it lines up against SCS-CN on the same axis.
"""

from collections.abc import Sequence
from typing import Literal


# ===========================================================================
# CURVE NUMBER & RUNOFF
# ===========================================================================

def adjust_cn_for_amc(CN: float, amc: Literal["I", "II", "III"]) -> float:
    """Convert an AMC II curve number to the dry (I) or wet (III) condition.

    ``CN`` is the AMC II curve number in [0, 100] and ``amc`` selects the
    target condition; "II" returns ``CN`` unchanged. Uses the Sobhani formulas
    and raises ``ValueError`` on an unknown ``amc`` rather than silently
    defaulting to AMC II.
    """
    # AMC II is the reference condition: nothing to convert.
    if amc == "II":
        return float(CN)
    # Sobhani dry-soil formula: lowers CN toward its dry equivalent.
    if amc == "I":
        return 4.2 * CN / (10 - 0.058 * CN)
    # Sobhani wet-soil formula: raises CN toward its wet equivalent.
    if amc == "III":
        return 23 * CN / (10 + 0.13 * CN)
    # Fail fast on a typo rather than silently falling back to AMC II.
    raise ValueError(f"amc must be 'I', 'II', or 'III'; got {amc!r}")


def calculate_runoff(
    P: float,
    CN: float,
    amc: Literal["I", "II", "III"] = "II",
) -> float:
    """Estimate SCS-CN direct runoff depth Q (mm) from rainfall ``P`` and ``CN``.

    ``P`` is the rainfall depth (mm, non-negative) and ``CN`` the AMC II curve
    number in [0, 100]; ``amc`` adjusts the curve number first ("II" is a
    no-op). Returns Q with ``0 <= Q <= P`` — zero while rainfall stays below
    the initial abstraction, and clamped to ``P`` at the impervious end.
    """
    # Convert CN to the requested AMC (no-op for the default "II").
    CN = adjust_cn_for_amc(CN, amc)

    # Fully pervious surface: no runoff, and also avoids 1/0 below.
    if CN == 0:
        return 0.0

    # Potential maximum retention and initial abstraction (both mm).
    S = 25400 / CN - 254
    Ia = 0.2 * S

    # No runoff while rainfall has not exceeded the initial abstraction.
    # `<=` (not `<`) also covers the impervious edge case CN=100, where
    # S = Ia = 0 and P = 0 would otherwise reach 0/0 in the formula below.
    if P <= Ia:
        return 0.0

    # SCS-CN runoff equation, clamped to the physical bound Q <= P.
    Q = (P - Ia) ** 2 / (P - Ia + S)
    return min(Q, P)


# ===========================================================================
# TIME-AREA ROUTING
# ===========================================================================

def route_time_area(
    rainfall: Sequence[float],
    CN: float,
    time_area: Sequence[float],
    area: float,
    dt: float,
) -> list[float]:
    """Route SCS-CN excess rainfall through a time-area diagram.

    Takes incremental ``rainfall`` (mm per interval), the ``CN``, an
    incremental ``time_area`` diagram (area fractions, normalized internally),
    the watershed ``area`` (km²) and the routing step ``dt`` (h). Returns the
    outflow hydrograph (m³/s) of length ``len(rainfall) + len(time_area) - 1``.
    Raises ``ValueError`` if ``time_area`` sums to zero or ``dt`` is not
    strictly positive.
    """
    # dt must be strictly positive: it appears in the pulse denominator
    # and a negative dt would silently flip the sign of every discharge.
    if dt <= 0:
        raise ValueError(f"dt must be strictly positive; got {dt}")
    # Normalize the diagram to 1.0 so the convolution conserves mass.
    ta_sum = sum(time_area)
    if ta_sum == 0:
        raise ValueError("time_area must not sum to zero")
    ta_norm = [w / ta_sum for w in time_area]

    # SCS-CN is nonlinear: incremental excess is the first difference of
    # cumulative runoff, not calculate_runoff applied per interval.
    cumulative_P = 0.0
    prev_Q = 0.0
    pulses: list[float] = []
    for p in rainfall:
        cumulative_P += p
        cum_Q = calculate_runoff(cumulative_P, CN)
        excess = cum_Q - prev_Q
        prev_Q = cum_Q
        # mm * km² / h -> m³/s using the 1/3.6 conversion factor.
        pulses.append(excess * area / (3.6 * dt))

    # Discrete convolution of discharge pulses with the time-area weights.
    n, m = len(pulses), len(ta_norm)
    hydrograph = [0.0] * (n + m - 1)
    for i, q in enumerate(pulses):
        for j, w in enumerate(ta_norm):
            hydrograph[i + j] += q * w
    return hydrograph


# ===========================================================================
# RATIONAL METHOD
# ===========================================================================

def rational_runoff(C: float, i: float, duration: float) -> float:
    """Compute total runoff depth (mm) via the Rational method.

    ``C`` is the runoff coefficient in [0, 1], ``i`` the average intensity
    (mm/h, non-negative) and ``duration`` the storm length (h, non-negative).
    Returns ``C * i * duration`` — the same depth scale as ``calculate_runoff``
    for a direct comparison — and raises ``ValueError`` on out-of-range input.
    """
    # Validate inputs; i = 0 and duration = 0 are allowed (give zero runoff).
    if not 0 <= C <= 1:
        raise ValueError(f"C must be in [0, 1]; got {C}")
    if i < 0:
        raise ValueError(f"i must be non-negative; got {i}")
    if duration < 0:
        raise ValueError(f"duration must be non-negative; got {duration}")
    # (mm/h) * h = mm — same scale as calculate_runoff for direct comparison.
    return C * i * duration
