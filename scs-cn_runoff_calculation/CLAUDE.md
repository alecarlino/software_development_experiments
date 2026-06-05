# CLAUDE.md

Behavioural and project-specific guidelines for building the Smart Water Lab SCS-CN Runoff Calculation experiment.

## Project Context

Implement the Soil Conservation Service Curve Number (SCS-CN) method for estimating direct runoff from rainfall.

1. Translate the mathematical formulas into Python code.
2. Handle the physical boundary conditions.
4. Perform parameter sensitivity analysis.
5. Implement time-area method for watershed routing.
6. Compare SCS-CN with other rational method
7. Create a visualization of runoff behaviour using interactive plot with sliders for P and CN

**Stack:** Python 3.10+, `numpy`, `pandas`, `matplotlib`.

---

## Domain Specifications
Do Not "Correct" These Silently.
- **The SCS-CN Formula:**
Runoff Calculation Formula:
`Q = (P - Ia)² / (P - Ia + S)`
    Where:
    - Q = Runoff depth (mm)
    - P = Rainfall depth (mm)
    - S = Potential maximum retention (mm)
    - Ia = Initial abstraction (mm) = 0.2 × S
    - S = (25400 / CN) - 254
    - CN = Curve Number (0-100)
- **Curve Number (CN) Values:**
  - Woods, good condition: 60-70
  - Pasture, fair condition: 75-85
  - Cultivated, straight row: 80-90
  - Urban, residential: 75-90
  - Paved areas: 95-100
- **Physical Boundary Conditions:**
  - If `P<Ia`: No runoff occurs, `Q=0`
   - If `CN=100`: Impervious surface, maximum runoff
   - If `CN=0`: All water infiltrates, `Q=0`
   - Runoff cannot exceed rainfall: `Q<=P`
---

## Deliverables
Fixed names, do not rename or add extras.
- `scscn_runoff.py` — main implementation with calculate_runoff() function
- `test_scscn` — comprehensive test suite
- `sensitivity_analysis.py` - visualization code
- `runoff_comparison.png` - generated plot comparing CN values
- `prompt_log.md` - documentation of AI interactions

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
- "Build visualization" -> "`sensitivity_analysis.py` produced the required plot."

For multistep work, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

Strong success criteria let you loop independently; weak ones ("make it work") force constant clarification.

---