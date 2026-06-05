# CLAUDE.md

Behavioural and project-specific guidelines for building the Smart Water Lab Flood Inundation Analysis (DEM-based).

## Project Context

This experiment focuses on analyzing flood inundation using Digital Elevation Model (DEM) data. Implement a spatial comparison algorithm to identify flooded areas based on water level, create visual flood extent maps, and calculate flooded area percentages for flood risk assessment and emergency management.

1. Create synthetic DEM using random function or load real data (USGS Earth Explorer - OpenTopography)
2. Implement flood inundation calculation by simulating flooding, creating boolean mask for flooded cells, calculating inundation depth and percentage.
4. Visualize the original DEM greyscale image, flood extent as blue overlay, inundation depth heat-map (blue), side by side comparison at different water levels. Include colour bar and title.
5. Implement a dynamic simulation with a loop and verify that the flooded area increase monotonically and document any unexpected behaviour.
6. Implement flood routing with water spreading to adjacent cells.
7. Add building footprints as barriers tom flooding.
8. Create animated GIF of rising water levels
9. Calculate flood volume (depth x cell area x count)
10. Validate physical correctness:
    - Verify flooded area increases with water level
    - Check that maximum depth equals (water_level - min_elevation)
    - Confirm flooded percentage is between 0-100%
    - Validate edge cases (water below min elevation, above max elevation)

**Stack:** Python 3.10+, `numpy`, `pandas`, `matplotlib`.

---

## Domain Specifications
Do Not "Correct" These Silently.
- **DEM:**
A DEM is a 2D grid where each cell contains an elevation value (in meters). Common sources include USGS SRTM (30m resolution) and ALOS PALSAR (12.5m resolution).
- **Flood inundation logic:**
  `Flooding Condition:  A location is FLOODED if: Elevation < Flood_Water_Level  Inundation Depth: Depth = Flood_Water_Level - Elevation (if flooded) Depth = 0 (if not flooded)  Flooded Area Percentage: % = (Number of flooded cells / Total cells) × 100`
---

## Deliverables
Fixed names, do not rename or add extras.

- `flood_inundation.py` - Main implementation
- `dem_data.npy` - DEM data file (or generation script)
- `flood_extent_40m.png` - Visualization at 40m water level
- `flood_extent_50m.png` - Visualization at 50m water level
- `flood_curve.png` - Water level vs. flooded percentage plot
- `prompt_log.md` - Documentation of AI interactions
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
- "Build visualization" -> "the function produced the required images."

For multistep work, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

Strong success criteria let you loop independently; weak ones ("make it work") force constant clarification.

---