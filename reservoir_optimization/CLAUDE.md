# CLAUDE.md

Behavioural and project-specific guidelines for building the Smart Water Lab Water Resources Optimization Reservoir Dispatch.

## Project Context

This experiment focuses on solving a multi-objective optimization problem for reservoir management. During drought periods, a reservoir must balance two competing objectives: maintaining downstream ecological flow while maximizing storage for hydropower generation.

1. Formulate multi-objective optimization problems including rolling horizon one
2. Use scipy.optimize for solving constrained optimization
3. Analyze trade-offs between competing objectives
4. Generate optimal release schedules
5. Validate constraints are satisfied
6. Add and manage uncertainty in inflow forecasts
7. Add water quality constraints
8. Compare different optimization algorithm such SLSQP and L-BFGS-B
9. Plot a Pareto frontier graph to show the results

**Stack:** Python 3.10+, `scipy`, `numpy`, `matplotlib`.

---

## Domain Specifications
Do Not "Correct" These Silently.
- **Scenario:**
A reservoir with the following characteristics must optimize water release over a 7-day period during a drought:
    - Current Storage: 500,000 m3
    - Minimum Storage (V_min): 100,000 m3
    - Maximum Storage (V_max): 1,000,000 m3
    - Minimum Ecological Release (Q_eco): 10 m3/s
    - Maximum Release (Q_max): 100 m3/s
    - Inflow Forecast: [15, 12, 10, 8, 12, 15, 18] m3/s
    - Hydropower Price: [0.08, 0.08, 0.08, 0.08, 0.10, 0.12, 0.10] $/kWh
- **Objectives:**
  - Maximize Hydropower revenue (release × price)
  - Minimize Ecological deficit (violations of minimum release)

- **Constraints:**
  - Storage bounds V_min ≤ V_storage ≤ V_max
  - Release bounds Q_eco ≤ Q_release ≤ Q_max
  - Storage balance V_t+1 = V_t + (Inflow - Release) x delta_t

---

## Deliverables
Fixed names, do not rename or add extras.
- `reservoir_optimize.py` - Optimization implementation
- `optimal_schedule.csv` - 7-day optimal release schedule
- `tradeoff_analysis.png` - Pareto frontier plot
- `prompt_log.md` - Documentation of AI interactions
- `validation_report.txt` - Constraint verification results

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
- **Before writing code, check the function** and the produced results.
---

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what the assignment asks.
- No abstractions for single-use code.
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
- "Implement the formula" -> "Does it work and provide reasonable results?."
- "Handle physical constraint" -> "The produced result are inside the boundaries?."
- "Build visualization" -> the produced Pareto plot is the required one?"

For multistep work, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

Strong success criteria let you loop independently; weak ones ("make it work") force constant clarification.

---