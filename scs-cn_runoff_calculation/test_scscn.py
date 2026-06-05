"""Unit tests for scscn_runoff module."""

import unittest

from scscn_runoff import (
    adjust_cn_for_amc,
    calculate_runoff,
    rational_runoff,
    route_time_area,
)


class TestCalculateRunoff(unittest.TestCase):
    """calculate_runoff: textbook reference value plus the four physical boundaries."""

    def test_reference_value(self):
        # Canonical SCS-CN case P=100, CN=75 -> Q ≈ 41.14 mm.
        self.assertAlmostEqual(calculate_runoff(100.0, 75), 41.137, places=2)

    def test_below_initial_abstraction_gives_zero(self):
        # P < Ia: rainfall fully absorbed, no runoff produced.
        self.assertEqual(calculate_runoff(5.0, 80), 0.0)

    def test_impervious_returns_full_rainfall(self):
        # CN=100 (impervious): every mm of rain becomes runoff.
        self.assertEqual(calculate_runoff(100.0, 100), 100.0)

    def test_fully_pervious_returns_zero(self):
        # CN=0 (fully pervious): the special-case guard returns 0 and skips 25400/0.
        self.assertEqual(calculate_runoff(100.0, 0), 0.0)

    def test_zero_rainfall_on_impervious_surface_returns_zero(self):
        # CN=100, P=0: S=0 -> Ia=0 -> P<=Ia branch returns 0 cleanly.
        # Before the P<=Ia fix this hit (0**2)/0 and raised ZeroDivisionError.
        self.assertEqual(calculate_runoff(0.0, 100), 0.0)

    def test_zero_rainfall_returns_zero_for_any_cn(self):
        # P=0 must produce Q=0 across the realistic CN range, not just CN=100.
        for cn in (10, 30, 50, 75, 95):
            with self.subTest(CN=cn):
                self.assertEqual(calculate_runoff(0.0, cn), 0.0)

    def test_p_equals_ia_returns_zero(self):
        # At P=Ia exactly the runoff equation gives 0/S = 0; the P<=Ia guard
        # also returns 0 cleanly. CN=80 -> Ia = 0.2 * (25400/80 - 254) = 12.7 mm.
        self.assertEqual(calculate_runoff(12.7, 80), 0.0)

    def test_guide_example_p50_cn80(self):
        # Verification example from the experiment guide:
        # P=50 mm, CN=80 -> Q = 37.3^2 / 100.8 = 13.80 mm.
        self.assertAlmostEqual(calculate_runoff(50.0, 80), 13.80, places=2)

    def test_higher_cn_produces_more_runoff(self):
        # Monotonicity: holding P fixed, increasing CN never decreases Q.
        cns = [40, 55, 70, 85, 100]
        for P in (20.0, 50.0, 100.0, 200.0):
            with self.subTest(P=P):
                qs = [calculate_runoff(P, cn) for cn in cns]
                for q_low, q_high in zip(qs, qs[1:]):
                    self.assertLessEqual(q_low, q_high)

    def test_runoff_never_exceeds_rainfall(self):
        # Q <= P must hold across the full physical (P, CN) grid.
        # Tolerance covers floating-point dust at the impervious boundary.
        for P in range(0, 201, 25):
            for cn in range(0, 101, 10):
                with self.subTest(P=P, CN=cn):
                    self.assertLessEqual(calculate_runoff(float(P), cn), P + 1e-9)


class TestRouteTimeArea(unittest.TestCase):
    """route_time_area: error path, output shape, and the mass-conservation invariant."""

    def test_raises_on_zero_sum_time_area(self):
        # A zero-sum time-area diagram cannot be normalized -> ValueError.
        with self.assertRaises(ValueError):
            route_time_area(
                rainfall=[10.0, 20.0],
                CN=80,
                time_area=[0.0, 0.0, 0.0],
                area=1.0,
                dt=1.0,
            )

    def test_raises_on_non_positive_dt(self):
        # dt <= 0 is unphysical and would divide by zero in the pulse
        # conversion; ValueError must fire before that point is reached.
        for bad_dt in (0.0, -1.0):
            with self.subTest(dt=bad_dt):
                with self.assertRaises(ValueError):
                    route_time_area(
                        rainfall=[10.0, 20.0],
                        CN=80,
                        time_area=[0.5, 0.5],
                        area=1.0,
                        dt=bad_dt,
                    )

    def test_output_length(self):
        # Discrete convolution of N pulses with M weights yields N+M-1 samples.
        rainfall = [5.0, 10.0, 15.0, 20.0]
        time_area = [0.3, 0.5, 0.2]
        hydrograph = route_time_area(
            rainfall, CN=80, time_area=time_area, area=1.0, dt=1.0
        )
        self.assertEqual(len(hydrograph), len(rainfall) + len(time_area) - 1)

    def test_mass_conservation(self):
        # Physical invariant: water in == water out, both expressed in m³.
        rainfall = [5.0, 15.0, 25.0, 10.0]
        CN = 75
        time_area = [0.1, 0.4, 0.3, 0.2]
        area = 2.5  # km²
        dt = 1.0    # h

        hydrograph = route_time_area(rainfall, CN, time_area, area, dt)

        # Input volume (m³): total runoff depth (mm) × area (km²) × 1000 (m³ per mm·km²).
        total_excess_mm = calculate_runoff(sum(rainfall), CN)
        excess_volume_m3 = total_excess_mm * area * 1000

        # Output volume (m³): integral of discharge over time = Σ q · dt · 3600.
        outflow_volume_m3 = sum(hydrograph) * dt * 3600

        # The two volumes must match to within floating-point noise.
        self.assertAlmostEqual(outflow_volume_m3, excess_volume_m3, places=6)

    def test_unnormalized_time_area_still_conserves_mass(self):
        # Diagram [3.0, 7.0] sums to 10, not 1; the internal normalization
        # must still produce a mass-conserving hydrograph.
        rainfall = [20.0, 30.0]
        CN = 80
        time_area = [3.0, 7.0]
        area = 1.0
        dt = 1.0

        hydrograph = route_time_area(rainfall, CN, time_area, area, dt)
        expected_m3 = calculate_runoff(sum(rainfall), CN) * area * 1000
        actual_m3 = sum(hydrograph) * dt * 3600
        self.assertAlmostEqual(actual_m3, expected_m3, places=6)


class TestAMCAdjustment(unittest.TestCase):
    """AMC adjustment: Sobhani conversions, edge cases, validation, and backward-compat."""

    def test_amc_ii_returns_cn_unchanged(self):
        # AMC II is the reference condition: every CN passes through unmodified.
        for cn in (0, 50, 75, 80, 100):
            self.assertEqual(adjust_cn_for_amc(cn, "II"), float(cn))

    def test_amc_i_dry_conversion_known_value(self):
        # CN_II = 80 -> CN_I = 4.2*80 / (10 - 0.058*80) = 336 / 5.36 ≈ 62.687
        self.assertAlmostEqual(adjust_cn_for_amc(80, "I"), 62.687, places=2)

    def test_amc_iii_wet_conversion_known_value(self):
        # CN_II = 80 -> CN_III = 23*80 / (10 + 0.13*80) = 1840 / 20.4 ≈ 90.196
        self.assertAlmostEqual(adjust_cn_for_amc(80, "III"), 90.196, places=2)

    def test_cn_zero_maps_to_zero_for_all_amc(self):
        # Both Sobhani formulas have CN in the numerator: CN=0 forces output 0.
        for amc in ("I", "II", "III"):
            self.assertEqual(adjust_cn_for_amc(0, amc), 0.0)

    def test_cn_hundred_maps_to_hundred_for_all_amc(self):
        # Algebraic fixed point: CN=100 maps to 100 under both Sobhani formulas.
        for amc in ("I", "II", "III"):
            self.assertAlmostEqual(adjust_cn_for_amc(100, amc), 100.0, places=9)

    def test_calculate_runoff_default_matches_amc_ii(self):
        # Backward-compat contract: omitting `amc` must equal passing amc="II".
        # If this ever fails, the default value silently changed behavior.
        self.assertEqual(
            calculate_runoff(100.0, 75),
            calculate_runoff(100.0, 75, "II"),
        )

    def test_invalid_amc_raises_value_error(self):
        # Typo on the AMC string must fail fast, not fall back to AMC II.
        with self.assertRaises(ValueError):
            adjust_cn_for_amc(75, "IV")


class TestRationalRunoff(unittest.TestCase):
    """rational_runoff: known case, dimensions, boundaries, cross-method check, validation."""

    def test_known_case(self):
        # C=0.6, i=20 mm/h, duration=2 h -> depth = 0.6 * 20 * 2 = 24 mm
        self.assertEqual(rational_runoff(0.6, 20.0, 2.0), 24.0)

    def test_units_mm_per_hour_times_hours_gives_mm(self):
        # Dimensional check: (mm/h) * h = mm. Two combinations cross-verify it.
        self.assertEqual(rational_runoff(1.0, 10.0, 1.0), 10.0)
        self.assertEqual(rational_runoff(1.0, 5.0, 3.0), 15.0)

    def test_zero_C_gives_zero_runoff(self):
        # C=0 means no fraction of rainfall runs off, regardless of intensity.
        self.assertEqual(rational_runoff(0.0, 50.0, 10.0), 0.0)

    def test_impervious_matches_scs_cn(self):
        # Cross-method invariant. At C=1 / CN=100 both methods must give the
        # same depth (full rainfall = full runoff). This is the only test
        # that makes the Rational and SCS-CN methods compare directly.
        i, duration = 20.0, 2.0
        P = i * duration
        self.assertEqual(
            rational_runoff(1.0, i, duration),
            calculate_runoff(P, 100),
        )

    def test_input_validation_raises_value_error(self):
        # Each invalid combination must raise ValueError; subTest reports
        # them one by one so a future failure points at the exact bad input.
        invalid_inputs = [
            (-0.1, 20.0, 2.0),   # C < 0
            (1.5, 20.0, 2.0),    # C > 1
            (0.5, -10.0, 2.0),   # i < 0
            (0.5, 20.0, -1.0),   # duration < 0
        ]
        for C, i, duration in invalid_inputs:
            with self.subTest(C=C, i=i, duration=duration):
                with self.assertRaises(ValueError):
                    rational_runoff(C, i, duration)


if __name__ == "__main__":
    unittest.main()
