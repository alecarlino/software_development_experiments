# Problem Formulation — Reservoir Dispatch Optimisation

Mathematical statement of the 7-day drought reservoir-dispatch problem solved in
`reservoir_optimize.py`.

## Indices and horizon

- $t \in \{1, \dots, T\}$ — day index, with horizon $T = 7$ days.
- $\Delta t = 86{,}400$ s — seconds per day (used to convert flows to volumes).

## Parameters

| Symbol | Meaning | Value |
|--------|---------|-------|
| $V_0$ | initial storage | $500{,}000\ \text{m}^3$ |
| $V_{\min}$ | minimum storage | $100{,}000\ \text{m}^3$ |
| $V_{\max}$ | maximum storage | $1{,}000{,}000\ \text{m}^3$ |
| $Q_{\text{eco}}$ | minimum ecological release | $10\ \text{m}^3/\text{s}$ |
| $Q_{\max}$ | maximum release | $100\ \text{m}^3/\text{s}$ |
| $I_t$ | inflow forecast | $[15, 12, 10, 8, 12, 15, 18]\ \text{m}^3/\text{s}$ |
| $p_t$ | hydropower price | $[0.08, 0.08, 0.08, 0.08, 0.10, 0.12, 0.10]\ \$/\text{kWh}$ |

## Decision variables

$$
Q_t \ge 0, \quad t = 1, \dots, T
$$

the water release rate on day $t$, in $\text{m}^3/\text{s}$ (7 variables).

The end-of-day storage $V_t$ is a *derived* quantity (a linear function of the
$Q_t$), not an independent decision variable.

## Objective

Maximise total hydropower revenue. Following the brief's specification
$\text{revenue} = \text{release} \times \text{price}$, this is taken as the
**linear proxy**

$$
\max_{Q} \;\; R(Q) = \sum_{t=1}^{T} Q_t \, p_t \, \Delta t .
$$

Because $R$ is linear in $Q$, the core problem is a **linear program (LP)** and is
solved exactly with `scipy.optimize.linprog` (HiGHS); `SLSQP` and `L-BFGS-B`
(`scipy.optimize.minimize`) are used for comparison.

> **Physical variant (comparison only).** The physically accurate revenue is
> $\sum_t p_t \, \eta \rho g \, Q_t \, H(V_t)\, \Delta t$ with head
> $H(V) = H_{\min} + (H_{\max}-H_{\min})\,(V-V_{\min})/(V_{\max}-V_{\min})$. Since
> $H$ depends on storage, this objective is **nonlinear** in $Q$; it is solved
> separately with SLSQP (section 10 of the code) and is *not* part of the LP.

## Constraints

**1. Release bounds** (ecological minimum and physical capacity):

$$
Q_{\text{eco}} \le Q_t \le Q_{\max}, \quad t = 1, \dots, T .
$$

**2. Storage mass balance** (reservoir continuity):

$$
V_t = V_{t-1} + (I_t - Q_t)\,\Delta t, \quad t = 1, \dots, T, \qquad V_0 = 500{,}000 .
$$

Unrolling the recursion gives storage as a linear function of the releases:

$$
V_t = V_0 + \Delta t \sum_{k=1}^{t} (I_k - Q_k).
$$

**3. Storage bounds:**

$$
V_{\min} \le V_t \le V_{\max}, \quad t = 1, \dots, T .
$$

## Compact LP form

Substituting the mass balance into the storage bounds turns them into linear
inequalities in $Q$ alone. With $\mathbf{c} = -[\,p_t \Delta t\,]$ the problem is

$$
\min_{Q} \; \mathbf{c}^\top Q
\quad \text{s.t.} \quad
A_{\text{ub}} Q \le b_{\text{ub}}, \quad
Q_{\text{eco}} \le Q_t \le Q_{\max},
$$

where each storage bound contributes one row. For $V_t \ge V_{\min}$:

$$
\Delta t \sum_{k=1}^{t} Q_k \;\le\; V_0 - V_{\min} + \Delta t \sum_{k=1}^{t} I_k,
$$

and for $V_t \le V_{\max}$:

$$
-\,\Delta t \sum_{k=1}^{t} Q_k \;\le\; V_{\max} - V_0 - \Delta t \sum_{k=1}^{t} I_k .
$$

This is exactly the matrix built by `storage_bounds()` in the code
($2T$ inequality rows for the $T$ upper and $T$ lower storage limits).

## Multi-objective extension (trade-off analysis)

For the revenue-vs-ecology trade-off the ecological minimum is **relaxed** from a
hard bound to a soft objective. Releases may fall to $0$, and the shortfall below
$Q_{\text{eco}}$ is the ecological deficit

$$
D(Q) = \sum_{t=1}^{T} \max\!\big(0,\; Q_{\text{eco}} - Q_t\big).
$$

The two objectives are blended with a weight $\lambda \in [0, 1]$ (objectives
normalised by their ranges), keeping the storage and mass-balance constraints
hard:

$$
\min_{0 \le Q_t \le Q_{\max}} \;\;
-(1-\lambda)\,\frac{R(Q)}{R_{\text{scale}}}
\;+\; \lambda\,\frac{D(Q)}{D_{\text{scale}}} .
$$

Sweeping $\lambda$ from $0$ (pure revenue) to $1$ (pure ecology) traces the Pareto
frontier; the revenue gap between the two extremes is the cost of maintaining the
minimum ecological flow.
