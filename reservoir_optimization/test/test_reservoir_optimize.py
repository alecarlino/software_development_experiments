"""Test suite for the reservoir-dispatch model (reservoir_optimize.py).

Importable because reservoir_optimize.py guards its pipeline behind main(), so
importing it only loads the parameters and solver functions (no files written).
Run with `pytest` or directly with `python test_reservoir_optimize.py`.
"""

import numpy as np
from scipy.optimize import linprog

import reservoir_optimize as ro

REV_OPTIMUM = 790_304.0          # known linear-proxy optimum revenue


def reference_schedule():
    """The hard-constraint revenue-optimal schedule (linprog reference)."""
    r = linprog(ro.c, A_ub=ro.A_ub, b_ub=ro.b_ub, bounds=ro.bounds, method="highs")
    assert r.success
    return r.x


def tradeoff_scales():
    """Normalisation ranges sized from the profit extreme, as main() does."""
    Q_profit = ro.solve_weighted(0.0, REV_OPTIMUM, ro.N * ro.Q_ECO)
    rev_scale = max(ro.revenue(Q_profit) - REV_OPTIMUM, 1.0)
    def_scale = max(ro.deficit(Q_profit), 1e-6)
    return rev_scale, def_scale


# ------------------------------------------------------------
# Constraint construction & helpers
# ------------------------------------------------------------
def test_storage_bounds_matrix_shape_and_values():
    A, b = ro.storage_bounds(ro.INFLOW, ro.V0, ro.V_MIN, ro.V_MAX)
    assert A.shape == (2 * ro.N, ro.N)
    assert b.shape == (2 * ro.N,)
    # The module-level matrices must be exactly this full-horizon build.
    assert np.allclose(A, ro.A_ub) and np.allclose(b, ro.b_ub)


def test_storage_helper_matches_mass_balance():
    Q = reference_schedule()
    S = ro.storage(Q)
    V = ro.V0
    for t in range(ro.N):
        V += (ro.INFLOW[t] - Q[t]) * ro.DT
        assert abs(V - S[t]) < 1e-3


def test_revenue_helpers_consistent():
    Q = reference_schedule()
    assert abs(ro.revenue(Q) - float(np.sum(Q * ro.PRICE * ro.DT))) < 1e-6
    assert abs(ro.neg_revenue(Q) + ro.revenue(Q)) < 1e-9


def test_head_endpoints_and_monotonic():
    assert abs(ro.head(ro.V_MIN) - ro.H_MIN) < 1e-9
    assert abs(ro.head(ro.V_MAX) - ro.H_MAX) < 1e-9
    levels = np.linspace(ro.V_MIN, ro.V_MAX, 11)
    heads = ro.head(levels)
    assert np.all(np.diff(heads) > 0)            # strictly increasing with storage


# ------------------------------------------------------------
# Reference optimum (linprog)
# ------------------------------------------------------------
def test_reference_is_feasible_and_optimal():
    Q = reference_schedule()
    assert np.all(Q >= ro.Q_ECO - 1e-6)          # ecological floor
    assert np.all(Q <= ro.Q_MAX + 1e-6)          # release cap
    assert ro.max_violation(Q) < 1e-3            # storage bounds
    assert ro.deficit(Q) < 1e-6                  # no ecological deficit
    assert abs(ro.revenue(Q) - REV_OPTIMUM) < 1.0


def test_reference_storage_within_bounds():
    S = ro.storage(reference_schedule())
    assert np.all(S >= ro.V_MIN - 1e-3)
    assert np.all(S <= ro.V_MAX + 1e-3)


# ------------------------------------------------------------
# Solver comparison
# ------------------------------------------------------------
def test_slsqp_matches_linprog():
    _, Q, _ = ro.solve_slsqp()
    assert abs(ro.revenue(Q) - REV_OPTIMUM) < 50.0     # within solver tolerance
    assert ro.max_violation(Q) < 1000.0                # tiny active-set slop


def test_lbfgsb_feasible_and_not_above_optimum():
    _, Q, _ = ro.solve_lbfgsb()
    assert ro.revenue(Q) <= REV_OPTIMUM + 1e-6         # penalty cannot beat the LP
    assert ro.revenue(Q) > 0.0
    assert ro.max_violation(Q) < 1.0                   # penalty keeps it feasible


# ------------------------------------------------------------
# Trade-off
# ------------------------------------------------------------
def test_tradeoff_endpoints():
    rev_scale, def_scale = tradeoff_scales()
    Q_profit = ro.solve_weighted(0.0, rev_scale, def_scale)
    Q_eco = ro.solve_weighted(0.95, rev_scale, def_scale)
    assert ro.deficit(Q_eco) < 1e-3                    # ecology-first -> no deficit
    assert ro.revenue(Q_profit) >= ro.revenue(Q_eco) - 1e-6


def test_tradeoff_monotonic_in_weight():
    rev_scale, def_scale = tradeoff_scales()
    revs, defs = [], []
    for lam in (0.0, 0.25, 0.5, 0.75, 0.95):
        Q = ro.solve_weighted(lam, rev_scale, def_scale)
        revs.append(ro.revenue(Q))
        defs.append(ro.deficit(Q))
    # More ecology weight -> revenue and deficit both non-increasing.
    assert all(revs[i + 1] <= revs[i] + 1e-3 for i in range(len(revs) - 1))
    assert all(defs[i + 1] <= defs[i] + 1e-6 for i in range(len(defs) - 1))


def test_eco_cost_small_and_positive():
    rev_scale, def_scale = tradeoff_scales()
    Q_profit = ro.solve_weighted(0.0, rev_scale, def_scale)
    eco_cost = ro.revenue(Q_profit) - REV_OPTIMUM
    assert 0.0 < eco_cost < 0.02 * REV_OPTIMUM         # a fraction of a percent here


# ------------------------------------------------------------
# Rolling horizon
# ------------------------------------------------------------
def test_rolling_full_horizon_recovers_optimum():
    rev, fail_day = ro.rolling_horizon(ro.N)
    assert fail_day is None
    assert abs(rev - REV_OPTIMUM) < 1.0


def test_rolling_single_day_infeasible_on_day_4():
    rev, fail_day = ro.rolling_horizon(1)
    assert rev is None
    assert fail_day == 4                               # drained before the low-inflow day


def test_rolling_feasible_from_two_days_and_optimal():
    for H in range(2, ro.N + 1):
        rev, fail_day = ro.rolling_horizon(H)
        assert fail_day is None
        assert abs(rev - REV_OPTIMUM) < 1.0


# ------------------------------------------------------------
# Inflow uncertainty
# ------------------------------------------------------------
def test_inflow_scenarios_shape_and_nonnegative():
    assert ro.inflow_scen.shape == (ro.K, ro.N)
    assert np.all(ro.inflow_scen >= 0.0)


def test_deterministic_optimum_is_fragile():
    p = ro.violation_prob(reference_schedule())
    assert 0.0 <= p <= 1.0
    assert p > 0.5                                     # rides the bounds -> fragile


def test_robust_margin_monotone_trade_off():
    revs, probs = [], []
    for margin in (0.0, 150_000.0, 300_000.0):
        Q, rev = ro.robust_solve(margin)
        assert Q is not None
        revs.append(rev)
        probs.append(ro.violation_prob(Q))
    # Wider margin -> revenue down, violation probability down.
    assert all(revs[i + 1] <= revs[i] + 1e-6 for i in range(len(revs) - 1))
    assert all(probs[i + 1] <= probs[i] + 1e-9 for i in range(len(probs) - 1))


# ------------------------------------------------------------
# Water quality
# ------------------------------------------------------------
def test_water_quality_floor_enforced_and_costly():
    Q12, rev12 = ro.wq_solve(12.0)
    assert Q12 is not None
    assert np.all(Q12 >= 12.0 - 1e-6)                  # dilution floor enforced
    assert rev12 < REV_OPTIMUM                         # costs revenue vs unconstrained


def test_water_quality_infeasible_above_budget():
    Qhi, _ = ro.wq_solve(20.0)
    assert Qhi is None                                 # exceeds the drought water budget


# ------------------------------------------------------------
# Physical head-coupled model
# ------------------------------------------------------------
def test_physical_revenue_positive_and_feasible():
    Q = ro.solve_physical()
    assert np.all(Q >= ro.Q_ECO - 1e-6) and np.all(Q <= ro.Q_MAX + 1e-6)
    assert ro.max_violation(Q) < 1.0                   # sub-m3 SLSQP slop on a 1e6 store
    assert ro.revenue_physical(Q) > 0.0


def test_physical_defers_drawdown_vs_linear_proxy():
    Q_phys = ro.solve_physical()
    Q_lin = reference_schedule()
    # Head-coupling rewards keeping storage high, so it releases less on the
    # linear-proxy's big drawdown day (day 6) and holds more water overall.
    assert Q_phys[5] < Q_lin[5]
    assert ro.storage(Q_phys).mean() > ro.storage(Q_lin).mean()


def test_eps_physical_frontier_monotone_and_feasible():
    revs = []
    for eps in (0.0, 1.0, 2.0, 3.0):
        Q = ro.solve_eps_physical(eps)
        assert np.all(Q >= -1e-6) and np.all(Q <= ro.Q_MAX + 1e-6)
        assert ro.max_violation(Q) < 100.0              # storage bounds (SLSQP slop)
        assert ro.deficit(Q) <= eps + 1e-3              # deficit budget respected
        revs.append(ro.revenue_physical(Q))
    # Allowing more deficit cannot lower the achievable physical revenue.
    assert all(revs[i + 1] >= revs[i] - 1.0 for i in range(len(revs) - 1))


if __name__ == "__main__":
    import sys

    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
