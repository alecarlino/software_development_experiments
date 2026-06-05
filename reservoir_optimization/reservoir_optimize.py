"""Reservoir dispatch optimisation over a 7-day drought horizon.

Maximises hydropower revenue (release x price) subject to release bounds, storage
bounds, and the storage mass-balance equation, then explores several extensions.
Running the module executes, in order:

* linprog (HiGHS) reference optimum.
* The same LP via scipy.optimize.minimize (SLSQP with hard storage constraints,
  L-BFGS-B with a storage penalty), run in parallel and compared.
* Revenue-vs-ecology trade-off: a weighted-sum sweep on the linear proxy plus an
  epsilon-constraint frontier on the physical model, drawn as two panels.
* Validation of the optimal schedule and export of the deliverables.
* Rolling-horizon dispatch with a limited lookahead window.
* Inflow-forecast uncertainty: Monte Carlo fragility + robust re-optimisation.
* Water-quality (minimum dilution flow) constraint and its revenue cost.
* Comparison against a physically accurate head-coupled (nonlinear) revenue model.

Outputs: optimal_schedule.csv, validation_report.txt and tradeoff_analysis.png in
the working directory; rolling_horizon.png, uncertainty_analysis.png and
water_quality_analysis.png in additional_plots/.

Revenue is the linear proxy sum(Q * price * dt); see the validation report.
"""

import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import linprog, minimize


# ===========================================================================
# PARAMETERS & CONSTANTS
# ===========================================================================

# Domain parameters.
V0 = 500_000.0          # current storage [m3]
V_MIN = 100_000.0       # minimum storage [m3]
V_MAX = 1_000_000.0     # maximum storage [m3]
Q_ECO = 10.0            # minimum ecological release [m3/s]
Q_MAX = 100.0           # maximum release [m3/s]
INFLOW = np.array([15, 12, 10, 8, 12, 15, 18], dtype=float)        # [m3/s]
PRICE = np.array([0.08, 0.08, 0.08, 0.08, 0.10, 0.12, 0.10])       # [$/kWh]

N = 7                   # horizon [days]
DT = 86_400.0           # seconds per day [s]

# Derived quantities.
REV_COEF = PRICE * DT                            # revenue = REV_COEF @ Q
c = -REV_COEF                                    # linprog minimises -revenue
bounds = [(Q_ECO, Q_MAX)] * N                    # release bounds Q_ECO <= Q <= Q_MAX
eco_bounds = [(0.0, Q_MAX)] * N                  # release floor relaxed (trade-off)
X0 = INFLOW.copy()                               # feasible start (storage held at V0)

# Tuning constants for the individual methods / extensions.
PENALTY = 1e5           # L-BFGS-B storage-violation penalty weight
EPS = 1e-3              # trade-off tie-breaker (prefer more revenue, less deficit)
DEFER = 1.0             # rolling-horizon tie-breaker (prefer to defer releases)
LOAD = 12_000.0         # downstream pollutant load [g/s] (water quality)
TOL = 1e-3              # validation tolerance [m3 / (m3/s)]
SIGMA = 0.20            # inflow forecast error (relative std)
K = 2000                # Monte Carlo scenarios
RNG = np.random.default_rng(0)

# Optional-extension plots go here; the mandated deliverables stay at the top level.
PLOTS_DIR = "additional_plots"

# Physical hydropower model (comparison only)
ETA = 0.9               # turbine efficiency
RHO = 1000.0            # water density [kg/m3]
GRAV = 9.81             # gravitational acceleration [m/s2]
H_MIN = 10.0            # hydraulic head at V_min [m]
H_MAX = 50.0            # hydraulic head at V_max [m]


# ===========================================================================
# CONSTRAINT SETUP
# ===========================================================================

def storage_bounds(inflow, V_start, v_min, v_max):
    """Linear inequalities ``A @ Q <= b`` for ``v_min <= storage_t <= v_max``.

    End-of-day storage is ``S_t = V_start + dt * sum_{k<=t} (inflow_k - Q_k)``.
    Used for the full horizon and for the rolling-horizon / robust sub-problems.
    """
    w = len(inflow)
    tri = np.tril(np.ones((w, w)))               # tri[t, k] = 1 if k <= t
    cum = tri @ inflow                           # sum_{k<=t} inflow_k
    A = np.vstack([DT * tri, -DT * tri])
    b = np.concatenate([V_start - v_min + DT * cum,
                        (v_max - V_start) - DT * cum])
    return A, b


A_ub, b_ub = storage_bounds(INFLOW, V0, V_MIN, V_MAX)
eco_constraints = [{                             # storage bounds as hard constraints
    "type": "ineq",
    "fun": lambda Q: b_ub - A_ub @ Q,            # >= 0 when feasible
    "jac": lambda Q: -A_ub,
}]
# Monte Carlo inflow scenarios (fixed by the seed, so this is reproducible config).
inflow_scen = np.clip(INFLOW * (1.0 + RNG.normal(0.0, SIGMA, size=(K, N))), 0.0, None)


# ===========================================================================
# SHARED QUANTITIES
# ===========================================================================

def storage(Q):
    """End-of-day storage trajectory [m3]."""
    return V0 + DT * np.cumsum(INFLOW - Q)


def max_violation(Q):
    """Largest amount (m3) by which Q breaks any storage bound (0 if feasible)."""
    return float(max(0.0, np.max(A_ub @ Q - b_ub)))


def revenue(Q):
    return float(REV_COEF @ Q)


def neg_revenue(Q):
    return -revenue(Q)


def neg_revenue_grad(Q):
    return -REV_COEF


def deficit(Q):
    """Total ecological shortfall below Q_ECO [m3/s, summed over the horizon]."""
    return float(np.sum(np.maximum(0.0, Q_ECO - Q)))


# ===========================================================================
# SOLVERS
# ===========================================================================

def solve_slsqp():
    """SLSQP gets the storage bounds as native inequality constraints."""
    t0 = time.perf_counter()
    r = minimize(neg_revenue, X0, jac=neg_revenue_grad, method="SLSQP",
                 bounds=bounds, constraints=eco_constraints,
                 options={"maxiter": 200, "ftol": 1e-9})
    return "SLSQP", r.x, time.perf_counter() - t0


# L-BFGS-B handles bounds only, so the storage bounds become a quadratic penalty.
# Violations are scaled by DT (-> m3/s units) to keep the penalty well conditioned.
def penalized_obj(Q):
    excess = np.maximum(0.0, A_ub @ Q - b_ub)        # m3 over the bound
    return neg_revenue(Q) + PENALTY * float(excess @ excess) / DT**2


def penalized_grad(Q):
    excess = np.maximum(0.0, A_ub @ Q - b_ub)
    return neg_revenue_grad(Q) + (2.0 * PENALTY / DT**2) * (A_ub.T @ excess)


def solve_lbfgsb():
    """L-BFGS-B gets the storage bounds folded into the objective as a penalty."""
    t0 = time.perf_counter()
    r = minimize(penalized_obj, X0, jac=penalized_grad, method="L-BFGS-B",
                 bounds=bounds, options={"maxiter": 200, "ftol": 1e-12})
    return "L-BFGS-B", r.x, time.perf_counter() - t0


# ===========================================================================
# TRADE-OFF
# ===========================================================================

def solve_weighted(lam, rev_scale, def_scale):
    """Reuse SLSQP with a weighted blend of the two (normalised) objectives.

    The ``EPS`` terms are a tiny secondary preference (more revenue, less deficit)
    that only breaks ties: without them the extreme weights are degenerate
    (lam=0 leaves the deficit inflated, lam=1 collapses revenue), producing
    dominated points. EPS keeps every solve on the efficient frontier.
    """
    w_rev = (1 - lam) + EPS          # weight on -revenue
    w_def = lam + EPS                # weight on deficit

    def obj(Q):
        return -w_rev * revenue(Q) / rev_scale + w_def * deficit(Q) / def_scale

    def grad(Q):
        d_def = np.where(Q < Q_ECO, -1.0, 0.0)   # subgradient of the deficit
        return -w_rev * REV_COEF / rev_scale + w_def * d_def / def_scale

    r = minimize(obj, X0, jac=grad, method="SLSQP", bounds=eco_bounds,
                 constraints=eco_constraints, options={"maxiter": 300, "ftol": 1e-12})
    return r.x


def solve_eps_physical(eps):
    """epsilon-constraint point on the PHYSICAL frontier: maximise the nonlinear
    head-coupled revenue (see revenue_physical) subject to total deficit <= eps.

    Weighted-sum scalarisation collapses to the frontier vertices on this nearly
    linear problem, so the deficit is bounded directly instead, which populates the
    whole frontier. Per-day slack variables d_t >= max(0, Q_eco - Q_t) linearise the
    otherwise non-smooth deficit so SLSQP stays well-behaved; the variable vector is
    x = [Q_0..Q_6, d_0..d_6] and the budget sum(d_t) <= eps caps the deficit.
    """
    x0 = np.concatenate([X0, np.maximum(0.0, Q_ECO - X0)])
    bnds = [(0.0, Q_MAX)] * N + [(0.0, Q_ECO)] * N
    cons = [
        {"type": "ineq", "fun": lambda x: b_ub - A_ub @ x[:N]},          # storage bounds
        {"type": "ineq", "fun": lambda x: x[N:] - (Q_ECO - x[:N])},      # d_t >= Q_eco - Q_t
        {"type": "ineq", "fun": lambda x, e=eps: e - np.sum(x[N:])},     # sum(d_t) <= eps
    ]
    r = minimize(lambda x: -revenue_physical(x[:N]), x0, method="SLSQP",
                 bounds=bnds, constraints=cons, options={"maxiter": 800, "ftol": 1e-10})
    return r.x[:N]


# ===========================================================================
# ROLLING HORIZON
# ===========================================================================

def window_solve(t0, w, V_start):
    """Revenue-max LP over days [t0, t0+w) from storage V_start; None if infeasible.

    Within an equal-price window the revenue objective is indifferent to WHEN water
    is released, so it would happily drain the reservoir (a degenerate, solver-
    dependent choice). The DEFER tie-breaker penalises earlier days by at most
    DEFER * w, far below any real price gap, so the window prefers to keep water
    when prices tie, giving a well-defined, robust, conservative policy.
    """
    A, b = storage_bounds(INFLOW[t0:t0 + w], V_start, V_MIN, V_MAX)
    cost = -PRICE[t0:t0 + w] * DT + DEFER * np.arange(w, 0, -1)
    r = linprog(cost, A_ub=A, b_ub=b, bounds=[(Q_ECO, Q_MAX)] * w, method="highs")
    return r.x if r.success else None


def rolling_horizon(H):
    """Receding-horizon policy with an H-day lookahead. Returns (revenue, fail_day)."""
    V = V0
    releases = np.full(N, np.nan)
    for t in range(N):
        q = window_solve(t, min(H, N - t), V)
        if q is None:
            return None, t + 1                   # infeasible at this day
        releases[t] = q[0]
        V += (INFLOW[t] - q[0]) * DT
    return float(np.sum(releases * PRICE * DT)), None


# ===========================================================================
# INFLOW UNCERTAINTY
# ===========================================================================

def violation_prob(Q):
    """Share of inflow scenarios in which fixed schedule Q breaks a storage bound."""
    S = V0 + DT * np.cumsum(inflow_scen - Q, axis=1)          # K x N realised storages
    breached = np.any((S < V_MIN - 1.0) | (S > V_MAX + 1.0), axis=1)
    return float(breached.mean())


def robust_solve(margin):
    """Re-solve the revenue LP with storage bounds tightened by `margin` each side."""
    A, b = storage_bounds(INFLOW, V0, V_MIN + margin, V_MAX - margin)
    r = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method="highs")
    return (r.x, revenue(r.x)) if r.success else (None, None)


# ===========================================================================
# WATER QUALITY
# ===========================================================================

def wq_solve(q_wq):
    """Revenue LP with the release floor raised to max(Q_eco, q_wq); None if infeasible."""
    lb = max(Q_ECO, q_wq)
    r = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=[(lb, Q_MAX)] * N, method="highs")
    return (r.x, revenue(r.x)) if r.success else (None, None)


# ===========================================================================
# PHYSICAL HYDROPOWER MODEL (COMPARISON)
# ===========================================================================

def head(V):
    """Hydraulic head [m], rising linearly with storage between H_MIN and H_MAX."""
    return H_MIN + (H_MAX - H_MIN) * (V - V_MIN) / (V_MAX - V_MIN)


def revenue_physical(Q):
    """Physically accurate revenue [$]: energy = eta*rho*g*Q*H*dt, priced per kWh.

    The head H depends on storage, so revenue is NONLINEAR in Q and coupled to the
    storage trajectory (the mean of each day's start/end level sets the head).
    """
    S = storage(Q)
    V_begin = np.concatenate(([V0], S[:-1]))
    V_bar = 0.5 * (V_begin + S)
    energy_kwh = ETA * RHO * GRAV * Q * head(V_bar) * DT / 3.6e6
    return float(np.sum(PRICE * energy_kwh))


def solve_physical():
    """Maximise the nonlinear physical revenue with SLSQP (storage bounds hard)."""
    r = minimize(lambda Q: -revenue_physical(Q), X0, method="SLSQP",
                 bounds=bounds, constraints=eco_constraints,
                 options={"maxiter": 500, "ftol": 1e-9})
    return r.x


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def main():
    # ------------------------------------------------------------------
    # REFERENCE OPTIMUM — linprog (HiGHS)
    # ------------------------------------------------------------------
    ref = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if not ref.success:
        raise RuntimeError(f"linprog failed: {ref.message}")
    Q_ref = ref.x
    revenue_ref = revenue(Q_ref)

    # ------------------------------------------------------------------
    # MINIMIZE-BASED SOLVERS — run SLSQP and L-BFGS-B in parallel
    # ------------------------------------------------------------------
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(lambda f: f(), [solve_slsqp, solve_lbfgsb]))

    # ------------------------------------------------------------------
    # SOLVER COMPARISON — score both against the linprog reference
    # ------------------------------------------------------------------
    print("Reference optimum (linprog / HiGHS)\n")
    print(f"  Total revenue: {revenue_ref:,.2f}")
    print(f"  Release schedule [m3/s]: "
          + ", ".join(f"{q:.3f}" for q in Q_ref) + "\n")

    print("Solver comparison")
    header = (f"{'Method':>10} {'Revenue':>14} {'Rev. gap':>12} "
             f"{'Max viol [m3]':>14} {'||Q-Q_ref||':>12} {'Time [ms]':>11}")
    print(header)
    print(f"{'linprog':>10} {revenue_ref:>14,.2f} {0.0:>12.4f} "
          f"{max_violation(Q_ref):>14.4f} {0.0:>12.4f} {'-':>11}")
    for name, Q, dt in runs:
        rev = revenue(Q)
        print(f"{name:>10} {rev:>14,.2f} {revenue_ref - rev:>12.4f} "
              f"{max_violation(Q):>14.4f} {np.linalg.norm(Q - Q_ref):>12.4f} "
              f"{dt * 1e3:>11.2f}")

    # ------------------------------------------------------------------
    # TRADE-OFF ANALYSIS — revenue vs. ecological flow
    # ------------------------------------------------------------------
    # The ecological minimum is relaxed to a SOFT target (releases may drop to 0,
    # the shortfall below Q_ECO is a deficit to minimise alongside -revenue), and a
    # weight lam in [0, 1] blends the two; storage bounds and mass balance stay hard.
    # Pass 1: profit extreme (lam = 0) sizes the normalisation ranges.
    Q_profit = solve_weighted(0.0, revenue_ref, N * Q_ECO)
    rev_profit, def_profit = revenue(Q_profit), deficit(Q_profit)
    rev_scale = max(rev_profit - revenue_ref, 1.0)   # revenue range (guarded)
    def_scale = max(def_profit, 1e-6)                # deficit range (guarded)

    # Pass 2: sweep the weight. Stop just short of lam = 1: at the exact pure-ecology
    # endpoint the vanishing revenue weight makes SLSQP's active set drift a few
    # hundred m3 outside the storage bound, and the ecology vertex is reached earlier.
    lambdas = np.linspace(0.0, 0.95, 20)
    frontier = []
    for lam in lambdas:
        Q = solve_weighted(lam, rev_scale, def_scale)
        frontier.append((lam, revenue(Q), deficit(Q), max_violation(Q)))

    print("\nTrade-off analysis: revenue vs. ecological deficit "
          "(ecological minimum relaxed to a soft target)\n")
    print(f"{'lambda':>7} {'Revenue':>14} {'Deficit [m3/s]':>15} {'Max viol [m3]':>14}")
    for lam, rev, dfc, viol in frontier:
        print(f"{lam:>7.2f} {rev:>14,.2f} {dfc:>15.3f} {viol:>14.4f}")

    eco_cost = rev_profit - revenue_ref
    print("\nPrioritising ecology over revenue (lam -> 1):")
    print(f"  Releases are pushed back up to Q_ECO everywhere, so the deficit returns "
          f"to 0 m3/s\n  and revenue settles at the fully-compliant optimum "
          f"{revenue_ref:,.2f}.")
    print("\nPrioritising revenue over ecology (lam = 0):")
    print(f"  Revenue rises to {rev_profit:,.2f} by under-supplying ecology, "
          f"incurring a\n  deficit of {def_profit:.3f} m3/s.")
    print(f"\nCost of maintaining minimum ecological flow: {eco_cost:,.2f} "
          f"({eco_cost / rev_profit:.2%} of the unconstrained revenue).")

    # Non-dominated points of the linear weighted-sum sweep (sort by deficit asc,
    # revenue desc so ties keep the best revenue).
    pts = sorted({(round(dfc, 6), round(rev, 6)) for _, rev, dfc, _ in frontier},
                 key=lambda p: (p[0], -p[1]))
    pareto = []
    best_rev = -np.inf
    for dfc, rev in pts:                              # ascending deficit
        if rev > best_rev:                            # only if it buys more revenue
            pareto.append((dfc, rev))
            best_rev = rev
    defs, revs = zip(*pareto)

    # Physical (nonlinear) frontier by the epsilon-constraint method: bounding the
    # deficit directly populates the whole frontier, where weighted-sum on the
    # near-linear LP only returns the two vertices. The head-coupled revenue is
    # nonlinear, so this frontier is a genuine (if gently) CURVED trade-off, in
    # real $ rather than proxy units.
    Q_pp = solve_eps_physical(N * Q_ECO)              # deficit unbounded -> profit extreme
    def_max_p = deficit(Q_pp)
    phys = [(deficit(Q), revenue_physical(Q))
            for Q in (solve_eps_physical(e) for e in np.linspace(0.0, def_max_p, 16))]
    pdefs, prevs = zip(*phys)
    eco_cost_phys = prevs[-1] - prevs[0]
    print(f"\nPhysical model (head-coupled, real $): epsilon-constraint frontier "
          f"spans\n  deficit 0 -> {def_max_p:.3f} m3/s for ${prevs[0]:,.0f} -> "
          f"${prevs[-1]:,.0f}; cost of ecological flow ${eco_cost_phys:,.0f} "
          f"({eco_cost_phys / prevs[-1]:.2%}).")

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5))
    axL.plot(defs, revs, "o-", color="#1f77b4", label="Pareto frontier")
    axL.scatter([def_profit], [rev_profit], color="crimson", zorder=5,
                label=f"Profit-first (lam=0): deficit {def_profit:.2f} m3/s")
    axL.scatter([0.0], [revenue_ref], color="green", zorder=5,
                label="Ecology-first (lam=1): deficit 0")
    axL.annotate(f"cost of eco flow\n= {eco_cost:,.0f}",
                 xy=(0.0, revenue_ref), xytext=(def_profit * 0.4, revenue_ref),
                 arrowprops={"arrowstyle": "->"}, va="center")
    axL.set_xlabel("Ecological deficit  [m3/s, summed over horizon]")
    axL.set_ylabel("Hydropower revenue  [proxy units, Q * price * dt]")
    axL.set_title("Linear proxy (LP, weighted-sum):\nfrontier collapses to two vertices")
    axL.legend()
    axL.grid(True, alpha=0.3)

    axR.plot(pdefs, prevs, "o-", color="#9467bd", label="Pareto frontier")
    axR.scatter([def_max_p], [prevs[-1]], color="crimson", zorder=5,
                label=f"Profit-first: deficit {def_max_p:.2f} m3/s")
    axR.scatter([0.0], [prevs[0]], color="green", zorder=5,
                label="Ecology-first: deficit 0")
    axR.annotate(f"cost of eco flow\n= ${eco_cost_phys:,.0f}",
                 xy=(0.0, prevs[0]), xytext=(def_max_p * 0.35, prevs[0]),
                 arrowprops={"arrowstyle": "->"}, va="center")
    axR.set_xlabel("Ecological deficit  [m3/s, summed over horizon]")
    axR.set_ylabel("Hydropower revenue  [real $]")
    axR.set_title("Physical model (nonlinear, epsilon-constraint):\nfull frontier recovered (gently concave)")
    axR.legend()
    axR.grid(True, alpha=0.3)

    fig.suptitle("Revenue vs. ecological-flow trade-off (Pareto frontier)")
    fig.tight_layout()
    fig.savefig("tradeoff_analysis.png", dpi=150)
    print("Saved Pareto frontier to tradeoff_analysis.png")

    # ------------------------------------------------------------------
    # VALIDATION — optimal-schedule checks and CSV export
    # ------------------------------------------------------------------
    # The canonical "optimal schedule" is the linprog solution: maximum revenue with
    # the ecological minimum enforced as a hard bound, so it has zero deficit.
    # (Days 1-4 share the same price, so the optimum is degenerate: the revenue is
    # unique but the day-by-day split among those days is not.)
    Q_opt = Q_ref
    S_opt = storage(Q_opt)
    revenue_opt = revenue(Q_opt)

    with open("optimal_schedule.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["day", "inflow_m3s", "price_usd_per_kwh", "release_m3s",
                         "storage_end_m3", "revenue_proxy"])
        for t in range(N):
            writer.writerow([t + 1, INFLOW[t], PRICE[t], round(Q_opt[t], 6),
                             round(S_opt[t], 3), round(REV_COEF[t] * Q_opt[t], 4)])

    report = []
    checks = []                      # (name, passed) for the final summary

    def line(text=""):
        report.append(text)

    line("=" * 64)
    line("RESERVOIR DISPATCH - VALIDATION REPORT")
    line("=" * 64)
    line(f"Horizon: {N} days   dt = {DT:.0f} s   tolerance = {TOL:g}")
    line("Schedule under test: revenue-optimal (linprog, hard ecological bound)")
    line("")
    line("Optimal schedule")
    line(f"{'Day':>3} {'Inflow':>8} {'Price':>7} {'Release':>9} {'Storage_end':>13}")
    for t in range(N):
        line(f"{t + 1:>3} {INFLOW[t]:>8.1f} {PRICE[t]:>7.2f} "
             f"{Q_opt[t]:>9.3f} {S_opt[t]:>13,.1f}")
    line("")

    # 1. Storage bounds
    storage_bad = [(t + 1, S_opt[t]) for t in range(N)
                   if S_opt[t] < V_MIN - TOL or S_opt[t] > V_MAX + TOL]
    checks.append(("Storage within [V_min, V_max]", not storage_bad))
    line(f"[1] Storage bounds [{V_MIN:,.0f}, {V_MAX:,.0f}] m3: "
         f"{'PASS' if not storage_bad else 'FAIL'}")
    for day, val in storage_bad:
        line(f"      day {day}: {val:,.1f} m3 out of bounds")

    # 2. Ecological release minimum
    eco_bad = [(t + 1, Q_opt[t]) for t in range(N) if Q_opt[t] < Q_ECO - TOL]
    checks.append(("All releases >= Q_eco", not eco_bad))
    line(f"[2] Ecological release >= Q_eco ({Q_ECO:.0f} m3/s): "
         f"{'PASS' if not eco_bad else 'FAIL'}  "
         f"(deficit = {deficit(Q_opt):.4f} m3/s)")
    for day, val in eco_bad:
        line(f"      day {day}: {val:.3f} m3/s below minimum")

    # 3. Release upper bound
    qmax_bad = [(t + 1, Q_opt[t]) for t in range(N) if Q_opt[t] > Q_MAX + TOL]
    checks.append(("All releases <= Q_max", not qmax_bad))
    line(f"[3] Release <= Q_max ({Q_MAX:.0f} m3/s): "
         f"{'PASS' if not qmax_bad else 'FAIL'}")

    # 4. Mass balance, recomputed iteratively day by day
    mb_err = 0.0
    V_prev = V0
    for t in range(N):
        V_next = V_prev + (INFLOW[t] - Q_opt[t]) * DT
        mb_err = max(mb_err, abs(V_next - S_opt[t]))
        V_prev = V_next
    checks.append(("Mass balance V_t+1 = V_t + (I - Q) dt", mb_err <= TOL))
    line(f"[4] Mass balance (max daily error): {mb_err:.2e} m3  "
         f"{'PASS' if mb_err <= TOL else 'FAIL'}")

    # 5. Revenue calculation
    revenue_check = float(np.sum(Q_opt * PRICE * DT))
    rev_err = abs(revenue_check - revenue_opt)
    checks.append(("Revenue calculation", rev_err <= TOL))
    line(f"[5] Total revenue (proxy units, Q*price*dt): {revenue_opt:,.2f}")
    line(f"      recomputed independently: {revenue_check:,.2f}  "
         f"(diff {rev_err:.2e})  {'PASS' if rev_err <= TOL else 'FAIL'}")

    # Summary
    line("")
    line("-" * 64)
    n_pass = sum(ok for _, ok in checks)
    line(f"RESULT: {n_pass}/{len(checks)} checks passed")
    for name, ok in checks:
        line(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    violations = [name for name, ok in checks if not ok]
    line("")
    line("Constraint violations found: "
         + ("none" if not violations else "; ".join(violations)))
    line("=" * 64)

    with open("validation_report.txt", "w") as f:
        f.write("\n".join(report) + "\n")

    print(f"\nSaved 7-day schedule to optimal_schedule.csv")
    print(f"Saved validation results to validation_report.txt "
          f"({n_pass}/{len(checks)} checks passed)")

    # ------------------------------------------------------------------
    # ROLLING-HORIZON DISPATCH — limited-lookahead policy
    # ------------------------------------------------------------------
    # Each day we look ahead H days, optimise releases over that window from the
    # current storage, apply ONLY the first day's release, then advance and re-solve.
    # H = N keeps full foresight and recovers the global optimum; a smaller window
    # shows the cost of myopia and can drive the policy infeasible once the reservoir
    # is drained, since day 4's inflow of 8 < Q_eco cannot meet the minimum.
    print("\nRolling-horizon dispatch (apply first release, re-optimise each day)")
    print(f"{'H':>3} {'Feasible':>9} {'Revenue':>14} {'Gap vs optimum':>16}")
    roll = []
    for H in range(1, N + 1):
        rev, fail_day = rolling_horizon(H)
        roll.append((H, rev, fail_day))
        if rev is None:
            print(f"{H:>3} {'NO':>9} {'-':>14} {f'infeasible day {fail_day}':>16}")
        else:
            print(f"{H:>3} {'yes':>9} {rev:>14,.2f} {revenue_ref - rev:>16,.2f}")

    feas = [(H, rev) for H, rev, _ in roll if rev is not None]
    infeas = [H for H, rev, _ in roll if rev is None]
    y_floor = min(r for _, r in feas) if feas else revenue_ref

    plt.figure(figsize=(8, 5))
    if feas:
        hs, rs = zip(*feas)
        plt.plot(hs, rs, "o-", color="#1f77b4", label="Rolling-horizon revenue")
    plt.axhline(revenue_ref, color="green", ls="--",
                label=f"Full-horizon optimum {revenue_ref:,.0f}")
    for H in infeas:
        plt.scatter([H], [y_floor], marker="x", color="crimson", s=90, zorder=5)
        plt.annotate("infeasible", (H, y_floor), textcoords="offset points",
                     xytext=(0, 8), color="crimson", ha="center")
    plt.xlabel("Lookahead window H  [days]")
    plt.ylabel("Realised revenue  [proxy units]")
    plt.title("Rolling-horizon dispatch: cost of limited foresight")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    os.makedirs(PLOTS_DIR, exist_ok=True)
    roll_path = os.path.join(PLOTS_DIR, "rolling_horizon.png")
    plt.savefig(roll_path, dpi=150)
    print(f"Saved rolling-horizon plot to {roll_path}")

    # ------------------------------------------------------------------
    # INFLOW UNCERTAINTY — Monte Carlo fragility + robust re-optimisation
    # ------------------------------------------------------------------
    # Revenue depends only on the decided releases, so for a FIXED schedule inflow
    # uncertainty does not change revenue -- it threatens FEASIBILITY, because the
    # realised storage depends on the actual inflow. The deterministic optimum rides
    # the storage bounds, so a small surprise pushes it out of [V_min, V_max]. We
    # quantify the fragility by Monte Carlo, then buy robustness with a safety margin.
    p_det = violation_prob(Q_ref)
    print(f"\nInflow uncertainty (Gaussian sigma={SIGMA:.0%}, {K} scenarios, seed 0)")
    print(f"Deterministic optimum: revenue {revenue_ref:,.2f}, "
          f"storage-bound violation probability {p_det:.1%}")

    print("\nRobust re-optimisation with a storage safety margin")
    print(f"{'Margin [m3]':>12} {'Revenue':>14} {'Rev. cost':>12} {'Violation prob':>15}")
    margins = np.linspace(0, 300_000, 13)
    robust = []
    for m in margins:
        Q_m, rev_m = robust_solve(m)
        if Q_m is None:
            print(f"{m:>12,.0f} {'infeasible':>14}")
            continue
        p_m = violation_prob(Q_m)
        robust.append((m, rev_m, p_m))
        print(f"{m:>12,.0f} {rev_m:>14,.2f} {revenue_ref - rev_m:>12,.2f} {p_m:>15.1%}")

    # Recommended operating point: smallest margin keeping violation prob <= 5%.
    TARGET = 0.05
    ok = [(m, rev, p) for m, rev, p in robust if p <= TARGET]
    if ok:
        m_star, rev_star, p_star = ok[0]
        print(f"\nSmallest margin keeping violation prob <= {TARGET:.0%}: {m_star:,.0f} m3"
              f"  ->  revenue {rev_star:,.2f} "
              f"(cost {revenue_ref - rev_star:,.2f}, "
              f"{(revenue_ref - rev_star) / revenue_ref:.2%}), violation prob {p_star:.1%}")
    else:
        best_m, best_rev, best_p = min(robust, key=lambda r: r[2])
        print(f"\nNo static safety margin reaches a {TARGET:.0%} violation target: at "
              f"sigma={SIGMA:.0%} the per-day inflow errors accumulate into storage "
              f"uncertainty of order 1e5 m3,")
        print(f"comparable to the usable range, so the best margin tested ({best_m:,.0f} "
              f"m3) still leaves {best_p:.1%} violations at a revenue cost of "
              f"{revenue_ref - best_rev:,.2f}. Feedback (rolling horizon) is the real fix.")

    ms = [r[0] for r in robust]
    ps = [100 * r[2] for r in robust]
    revs_r = [r[1] for r in robust]
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(ms, ps, "o-", color="crimson", label="Violation probability")
    ax1.set_xlabel("Storage safety margin  [m3]")
    ax1.set_ylabel("Storage-bound violation probability  [%]", color="crimson")
    ax1.tick_params(axis="y", labelcolor="crimson")
    ax2 = ax1.twinx()
    ax2.plot(ms, revs_r, "s--", color="#1f77b4", label="Revenue")
    ax2.set_ylabel("Revenue  [proxy units]", color="#1f77b4")
    ax2.tick_params(axis="y", labelcolor="#1f77b4")
    ax1.set_title(f"Inflow uncertainty: robustness vs revenue (sigma={SIGMA:.0%})")
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    unc_path = os.path.join(PLOTS_DIR, "uncertainty_analysis.png")
    fig.savefig(unc_path, dpi=150)
    print(f"\nSaved uncertainty analysis to {unc_path}")

    # ------------------------------------------------------------------
    # WATER QUALITY — minimum dilution-flow constraint
    # ------------------------------------------------------------------
    # To keep a downstream concentration C = LOAD / Q below a limit C_max, the
    # release must provide a dilution flow Q_wq = LOAD / C_max, entering as a floor
    # Q >= max(Q_eco, Q_wq). When Q_wq > Q_eco it competes with holding releases at
    # the ecological minimum on cheap days; during drought it becomes infeasible once
    # the floor drains storage below V_min on the low-inflow trough (day 4, inflow 8
    # m3/s) - here at ~12.5 m3/s, well before the horizon-average budget would bind.
    Q_WQ = 12.0          # headline dilution flow (C_max = LOAD / Q_WQ = 1000 mg/L)
    Q_wq_opt, rev_wq = wq_solve(Q_WQ)
    print(f"\nWater-quality constraint: minimum dilution flow (LOAD = {LOAD:,.0f} g/s)")
    print(f"Headline Q_wq = {Q_WQ:.1f} m3/s  (C_max = LOAD/Q_wq = {LOAD / Q_WQ:,.0f} mg/L)")
    print(f"  Release schedule [m3/s]: " + ", ".join(f"{q:.3f}" for q in Q_wq_opt))
    print(f"  Revenue {rev_wq:,.2f}  (cost vs unconstrained {revenue_ref - rev_wq:,.2f}, "
          f"{(revenue_ref - rev_wq) / revenue_ref:.2%})")

    print("\nCost of water quality vs required dilution flow")
    print(f"{'Q_wq [m3/s]':>12} {'C_max [mg/L]':>13} {'Revenue':>14} {'Rev. cost':>12}")
    wq_sweep = np.linspace(Q_ECO, 14.0, 9)
    wq_pts = []
    infeasible_qs = []
    for q_wq in wq_sweep:
        Q_q, rev_q = wq_solve(q_wq)
        if Q_q is None:
            infeasible_qs.append(q_wq)
            print(f"{q_wq:>12.2f} {LOAD / q_wq:>13,.0f} {'infeasible':>14}")
            continue
        wq_pts.append((q_wq, rev_q))
        print(f"{q_wq:>12.2f} {LOAD / q_wq:>13,.0f} {rev_q:>14,.2f} "
              f"{revenue_ref - rev_q:>12,.2f}")

    infeasible_from = infeasible_qs[0] if infeasible_qs else None
    if infeasible_from is not None:
        print(f"\nDilution demand becomes infeasible at Q_wq ~ {infeasible_from:.2f} m3/s: "
              f"the drought water budget cannot sustain a higher constant release.")

    qs, rqs = zip(*wq_pts)
    plt.figure(figsize=(8, 5))
    plt.plot(qs, rqs, "o-", color="#1f77b4", label="Revenue")
    plt.scatter([Q_WQ], [rev_wq], color="crimson", zorder=5,
                label=f"Headline Q_wq = {Q_WQ:.0f} m3/s")
    if infeasible_from is not None:
        plt.axvline(infeasible_from, color="grey", ls=":",
                    label=f"Infeasible beyond ~{infeasible_from:.1f} m3/s")
    plt.xlabel("Required dilution flow Q_wq  [m3/s]")
    plt.ylabel("Revenue  [proxy units]")
    plt.title("Water-quality constraint: cost of the dilution requirement")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    wq_path = os.path.join(PLOTS_DIR, "water_quality_analysis.png")
    plt.savefig(wq_path, dpi=150)
    print(f"\nSaved water-quality analysis to {wq_path}")

    # ------------------------------------------------------------------
    # PHYSICAL MODEL — head-coupled (nonlinear) revenue comparison
    # ------------------------------------------------------------------
    # Everything above uses the brief's literal "revenue = release x price" as a
    # LINEAR proxy (sum Q*price*dt), which is what makes the problem an LP. The
    # physically accurate hydropower revenue is energy x price with energy =
    # eta*rho*g*Q*H*dt, where the head H rises with storage -- so revenue is
    # NONLINEAR in Q and coupled to the storage path. We solve that model here
    # (SLSQP) only as a comparison; it lands in real-dollar territory ($, not proxy
    # units) and rewards keeping storage (head) high, shifting the dispatch.
    Q_phys = solve_physical()
    print("\nPhysical hydropower model (comparison; energy = eta*rho*g*Q*H*dt)")
    print(f"  Head {H_MIN:.0f}-{H_MAX:.0f} m, eta={ETA}; revenue in real $ "
          f"(not the proxy units used above)")
    print(f"  Release schedule [m3/s]: " + ", ".join(f"{q:.3f}" for q in Q_phys))
    print(f"  Storage end [m3]:       " + ", ".join(f"{s:,.0f}" for s in storage(Q_phys)))
    print(f"  Physical revenue: ${revenue_physical(Q_phys):,.2f}")
    print(f"  Linear-proxy optimum schedule (reference): "
          + ", ".join(f"{q:.3f}" for q in Q_ref))
    print("  Head-coupling rewards holding storage high, so the physical optimum "
          "defers\n  drawdown compared with the linear-proxy optimum; this is the "
          "model the brief's\n  ~$45k sample implies, kept separate so the LP above "
          "stays a true linear program.")


if __name__ == "__main__":
    main()
