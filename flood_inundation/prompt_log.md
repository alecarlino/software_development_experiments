# Prompt Log - Experiment 4: Flood Inundation Analysis (DEM-based)

**Author:** Alessandro Carlino
**Course:** Software Development
**Date:** 2026-06-02

## AI Agent Settings

**Platform:** Claude Code
**Model:** Opus 4.8 (Max Effort)
**Plugin:** Superpowers (for TDD)
**Agent configuration file:** `CLAUDE.md` (provided in the directory)

---

## First Iterations

My working directory held two files: `CLAUDE.md`, with the project rules and the domain background, and an empty `prompt_log.md`.

### Prompt Used
"I am a computer science master's student building a flood inundation analysis system using Digital Elevation Model (DEM) data. Write Python code in a file named `flood_inundation.py`. For now create the DEM, providing two separate functions:
   - A function that generates a synthetic 100×100 grid with elevation values between 30–80m (using numpy.random for random terrain or a simple slope pattern)
   - A function that loads real DEM data (e.g. from USGS Earth Explorer or OpenTopography)

In parallel, create a test file named `test_flood_inundation.py` following TDD practices, with unit tests covering both DEM creation functions."

### AI Output Summary

Before writing anything, the agent stopped to check the two open questions in the prompt. For the synthetic terrain it pointed out that a random grid would make flooding look like scattered speckle, with no real basin, and suggested a smooth slope with mild noise on top so the low ground stays connected; I agreed. For the "load real DEM" function it noted there is no real dataset in scope and that the stack is limited to numpy/pandas/matplotlib (so no GeoTIFF reader), and proposed loading a local `.npy` file instead; I agreed to that as well.

It then built `flood_inundation.py` with two functions. `generate_synthetic_dem(size=100, low=30, high=80, seed=None)` lays down a diagonal slope from 30 m in one corner to 80 m in the opposite one, adds mild Gaussian noise, and clips the result back into the 30–80 m band. The `seed` argument makes a run reproducible, which lets the tests check exact values. `load_real_dem(path)` calls `np.load`, checks the array is 2D, and returns it as float, raising a clear error if the file is missing or the shape is wrong. The matching test file went into `tests/`, and I created a local `.venv` for the project because the system Python on this machine is externally managed (PEP 668) and refuses a direct pip install.

### Verifications

The test suite has 12 unit tests and all of them pass. For the synthetic generator the tests check: the default grid is 100×100; every value sits inside the 30–80 m range; the array is floating-point; the same seed gives an identical grid twice while two different seeds give different grids; a custom `size` (50) produces a 50×50 grid; and the terrain is coherent rather than noise, since neighbouring cells differ less, on average, than randomly paired cells. For the loader the tests check: a DEM saved to a temporary `.npy` round-trips back unchanged; an integer array comes back as float; a missing path raises `FileNotFoundError`; a 1D array raises `ValueError`; and the default path points at `dem/dem_data.npy`. On top of the tests I ran the generator by hand and confirmed the numbers made sense: min 30.00 m, max 80.00 m, mean around 55 m, with the top-left corner near 30 m and the bottom-right near 80 m, the slope I expected.

### Changes Made

After the first result I asked for a few corrections, which the agent applied one at a time:

- **Folder layout.** The test file was moved into a `tests/` folder, and the loader's default path was set to `dem/dem_data.npy`, with the `dem/` folder reserved for real DEM data.
- **No path hacks.** The first version added a `conftest.py` that edited `sys.path` to make the import work. I pushed back on that. We first replaced it with an empty `conftest.py` in the root, then dropped the file entirely: running the suite as `python -m pytest` from the project root already puts the root on the path, so `import flood_inundation` works with no extra file.
- **Generate the data file.** A `__main__` block was added so that running `python flood_inundation.py` generates the synthetic DEM and saves it as `dem_data.npy`.
- **Where the synthetic DEM lives.** Since `dem/` is only for real DEMs, the generated synthetic file was moved out of it and saved in the project root (`dem_data.npy`) instead.

---

## Second Interaction

The working directory now contained four files: `CLAUDE.md` (unchanged), the updated `prompt_log.md` with the first iteration logged, `dem_data.npy`, `flood_inundation.py` and the `tests/` folder containing `test_flood_inundation.py`.

### Prompt Used
"Implement building footprints as barriers to flooding inside the generated dem file. Update the TDD consequently."

### AI Output Summary

The agent first laid out how it would treat buildings. Since they have to live "inside the generated DEM file", it chose to burn them straight into the elevation grid by raising the building cells to a barrier height well above the terrain (100 m, against a terrain that tops out at 80 m). Flooding is defined as `elevation < water_level`, so a cell parked at 100 m never goes underwater at any sensible level, and the building behaves as an impermeable barrier without needing a separate mask. To recover the buildings later, they are the cells where `dem >= barrier_height`.

It added one function, `add_buildings(dem, footprints, barrier_height=100.0)`, where each footprint is a `(row, col, n_rows, n_cols)` rectangle. The function works on a copy of the DEM rather than mutating the original, which keeps the generator pure and makes it safe to reuse. It left the two earlier functions untouched. It also updated the `__main__` block so that, before saving `dem_data.npy`, it burns three building footprints into the low ground (the area that would otherwise flood first), and the saved DEM already carries the barriers.

### Verifications

The agent added six more tests on top of the existing ones, taking the suite to 21, all green. The building tests check: the footprint cells are set to the barrier height; the cells outside the footprint are left unchanged; the input array is not mutated (a copy is returned); several footprints can be burned at once; an empty footprint list returns an identical but distinct array; and the default barrier height sits above the terrain maximum, so flooding can never cover a building. I also regenerated `dem_data.npy` and checked the numbers by hand: 446 cells are now at or above 100 m, which is exactly `8×12 + 15×10 + 10×20`, the three rectangles I asked for, while the highest terrain cell (ignoring buildings) is still 80.00 m, so adding the barriers left the underlying terrain untouched.

### Changes Made

Every one of the 21 tests passed on the first run, so this iteration needed no corrections.

---

## Third Interaction

The working directory held the same files as before, with `flood_inundation.py` now carrying the building function and `dem_data.npy` regenerated accordingly.

### Prompt Used
"In the existing file `flood_inundation.py` add the following functions to my existing code that:
1. Simulates flooding at a given water level
2. Creates a boolean mask for flooded cells (elevation < water_level)
3. Calculates inundation depth for flooded cells
4. Calculates flooded area percentage
5. Returns the mask, depth array, and percentage
6. Implements flood routing, where water spreads to adjacent cells (connected-component flooding from a source, rather than a simple elevation threshold)
7. Uses building footprints as barriers to flooding, assuming the building footprints are already implemented in the code

In parallel, add corresponding unit tests to my existing `test_flood_inundation.py` file following TDD practices, covering the flood mask, depth calculation, area percentage, flood routing, and building barriers."

### AI Output Summary

The agent split the request into small, single-purpose functions rather than one big routine, which lined up with the list of tests I asked for. It added `flood_mask(dem, water_level)` for the boolean mask using a strict `elevation < water_level` (the inequality the domain spec in `CLAUDE.md` calls for), `inundation_depth(dem, water_level)` returning `water_level - elevation` where flooded and 0 elsewhere, and `flooded_percentage(mask)` for the flooded-cell percentage. `simulate_flood(dem, water_level)` then composes those three and returns the `(mask, depth, percentage)` triple. This is the "bathtub" model, which floods every cell below the level regardless of whether water could reach it.

For the next point it added `flood_routing(dem, water_level, source)`, a breadth-first flood fill from a source cell using 4-connectivity: a cell floods only if it is below the water level *and* connected to the source through other flooded cells, so isolated low pockets stay dry. Buildings needed no special handling: since they sit at 100 m they are never "below the water level", so the bathtub mask excludes them and they block the spread in the routing model without any special-casing. The DEM generation did not change, so I left `dem_data.npy` as it was.

### Verifications

Seventeen new tests took the suite to 38, all passing. They cover each function in isolation: the mask marks the right cells and excludes equal-elevation and building cells; depth is `level - elevation` where wet and 0 where dry, with the maximum depth equal to `level - min(elevation)`; the percentage is 0 / 50 / 100 on hand-made masks and stays inside 0–100 on the real DEM; `simulate_flood` returns three consistent outputs (depth positive exactly where the mask is true) and the flooded area grows with the water level; and routing floods only the connected region, floods nothing when the source is on high ground, stops at a wall of buildings, and never includes a cell above the water level. On top of that I ran the functions on the saved DEM and checked the physics from the assignment by hand: the flooded percentage rises monotonically (2.61 → 7.84 → 30.72 → 62.61 → 95.24 %), the maximum depth equals `water_level - 30` at every level, the percentage stays within 0–100, the routed region is a subset of the bathtub one (2786 of 3072 cells at level 50, the rest being disconnected pockets), and no building cell floods even at 80 m.

### Changes Made

The 38 tests passed on the first run, so nothing needed changing here.

---

## Fourth Interaction

The working directory now held the updated `prompt_log.md`, `flood_inundation.py`, and `test_flood_inundation.py`, with the other files unchanged.

### Prompt Used
"Implemnt an additional function inside `flood_inundation.py`to calculate flood volume as depth × cell area × count."

### AI Output Summary

Before coding the agent flagged a subtlety in the formula. Taken literally, "depth × cell area × count" only works when every flooded cell has the same depth, but in a real DEM the depths vary cell by cell. The physically correct version is the sum of the per-cell depths times the cell area, which is the same thing as mean depth × cell area × flooded count (since a sum is the mean times the count). I agreed to implement that.

It added `flood_volume(depth, cell_area=1.0)`, which takes the depth array already produced by `inundation_depth` / `simulate_flood` and returns `depth.sum() × cell_area`. Dry cells carry a depth of 0, so summing the whole array counts only the flooded ones. `cell_area` is the ground area of one cell in square metres (for example 900 for a 30 m DEM); it defaults to 1 so the bare cell count comes through when no resolution is given. Nothing else in the file changed.

### Verifications

The agent added five tests, taking the suite to 43, all passing. They check: the volume equals the summed depth times the cell area; the literal "depth × area × count" still holds for a uniform depth; an all-zero depth gives zero volume; the default cell area is 1; and the result matches what you get straight from `simulate_flood`'s depth output. I also ran it on the saved DEM with a 30 m cell (900 m²) and the volume grows with the water level as it should: about 2.73×10⁶ m³ at 40 m, 1.91×10⁷ m³ at 50 m, and 6.09×10⁷ m³ at 60 m.

### Changes Made

The 43 tests passed on the first run, so the volume function needed no corrections. Afterwards I asked the agent to add more comments to the test file: it added a module docstring, a one-line docstring to every test class explaining what that group covers, and an inline comment on each test method describing the specific behaviour and the chosen inputs. The edits touched only comments, not test logic, and the suite still passes at 43.

---

## Fifth Interaction

The working directory now held `flood_inundation.py` with the DEM generation and loader, the building barriers, the flood mask, depth, percentage, `simulate_flood` and connected-component routing, and the flood-volume function, plus the `tests/test_flood_inundation.py` suite covering them, alongside `CLAUDE.md`, `prompt_log.md` and `dem_data.npy`.

### Prompt Used
"In `flood_inundation.py` write a additional code to visualize the flood inundation results using matplotlib. The visualization should include:
1. The original DEM displayed as a grayscale image
2. The flood extent shown as a blue overlay on the terrain
3. An inundation depth heatmap using a blue color scheme
4. A side-by-side comparison of flood inundation at different water levels
5. A colorbar and title for each plot

In parallel, add corresponding unit tests to my existing `test_flood_inundation.py` file following TDD practices, verifying that the plotting functions run without errors and produce the expected figure objects."

### AI Output Summary

The agent added four plotting functions, each of which builds and returns a matplotlib `Figure` rather than showing it on screen, which keeps them easy to test and lets me save the result wherever I want. `plot_dem` draws the elevation grid in grayscale with an elevation colorbar. `plot_flood_extent` draws the terrain in grayscale and lays a semi-transparent blue overlay over the flooded cells, masking out the dry ones, with the flooded percentage in the title. `plot_inundation_depth` shows the depth as a blue `Blues` heatmap with the dry cells left blank and a depth colorbar. `plot_water_level_comparison` puts one flood-extent panel per water level side by side under a shared title. On the "colorbar and title for each plot" point the agent flagged a small judgement call: a colorbar is meaningful only on the first three plots, so on the comparison it used a per-panel title (level and flooded percentage) plus an overall title instead of a colorbar over a binary overlay, and I was fine with that.

For testing it installed matplotlib into the `.venv` (it was in the intended stack but not yet present) and set the headless `Agg` backend at the top of the test file, so figures are built in memory without trying to open a window.

### Verifications

Four new tests took the suite to 47, all passing. They confirm each function returns a `Figure`, that the DEM and depth plots carry a colorbar (which shows up as a second axis on the figure) and a non-empty title, that the flood-extent plot builds and is titled, and that the comparison has exactly one titled subplot per water level. A fixture closes all figures after each test so they don't accumulate. Beyond the tests I rendered all four figures from the saved DEM and wrote them to PNG to confirm they produce real images: they came out at roughly 69–141 KB each, with the expected number of axes (two for the single plots, three for the comparison).

### Changes Made

All 47 tests passed on the first run, so the plotting code needed no corrections; the only extra step was installing matplotlib into the `.venv`. I left the deliverable PNG files (`flood_extent_40m.png`, `flood_extent_50m.png`, `flood_curve.png`) for a later step, since this prompt asked only for the plotting functions and their tests.

Right after, I asked the agent to produce those deliverables. It added a fifth plotting function, `plot_flood_curve(dem, water_levels)`, which plots flooded-area percentage against water level (titled, both axes labelled, with a grid), and covered it with two more tests, one checking the figure is labelled with one point per level and one checking the plotted curve never decreases, taking the suite to 49, all green. It then wired the `__main__` block to save the three PNGs: flood extent at 40 m and 50 m via `plot_flood_extent`, and the curve over the 30–80 m range. Running the script produced all three files (about 37–58 KB each). I opened them to check: the curve is the expected S-shape rising from 0 % at 30 m to about 95 % at 80 m (it plateaus below 100 % because the buildings never flood), and the 50 m extent map shows the blue flood filling the low ground with the three building rectangles standing out as dry white blocks.

Later I asked for a legend on the blocks that stop the flooding. The agent gave the building barriers their own colour (brown) and added a legend to the two flood-overlay plots, `plot_flood_extent` (a legend in the corner) and `plot_water_level_comparison` (a shared legend under the panels), labelling the two overlays "Flooded" and "Building (barrier)". The buildings are detected as the cells at or above the barrier height, exposed as a `barrier_height` argument on both functions. Two more tests checked that each of those figures carries a legend with a "Building" entry, taking the suite to 62, all green. I regenerated the deliverables and confirmed the three building blocks now show up in brown with the legend, instead of blending into the terrain as white.

---

## Sixth Interaction

The working directory now held `CLAUDE.md`, the updated `prompt_log.md`, `dem_data.npy`, `flood_inundation.py` with the flooding and plotting functions, the three deliverable PNGs (`flood_extent_40m.png`, `flood_extent_50m.png`, `flood_curve.png`), and `tests/test_flood_inundation.py` covering the code.

### Prompt Used
"In `flood_inundation.py` add a dynamic simulation:
1. Loops through water levels from 40m to 50m
2. Calculates the flooded percentage at each level
3. Creates a plot of Water Level vs. Flooded Percentage
4. Verifies whether the flooded area increases monotonically as the water level rises
5. Documents any unexpected behavior (e.g. non-monotonic jumps or plateaus) in comments or printed output

In parallel, add corresponding unit tests to my existing `test_flood_inundation.py` file following TDD practices, covering the water-level sweep, the flooded-percentage calculation across levels, and the monotonicity check."

### AI Output Summary

The agent pointed out that most of the pieces already existed, the per-level flooded percentage and the level-vs-percentage plot were both in the file already, so it kept this step small. It added two small, pure functions. `simulate_dynamic_flood(dem, start=40, stop=50, step=1)` loops over the water levels from 40 m to 50 m (the end included) and returns the levels together with the flooded-area percentage at each one. `is_monotonic_non_decreasing(values)` returns True when a sequence never goes down, which is the monotonicity check. For the plot it reused the existing `plot_flood_curve`, so it added no new figure file: the deliverable `flood_curve.png` already covers the 30–80 m range, which includes the 40–50 m sweep. The `__main__` block now prints the per-level table for the 40→50 m sweep and a verdict line; if the area ever dipped it would print which steps went down, with a comment noting that on a smooth DEM that should not happen and would point to NaN/nodata cells or too coarse a step.

### Verifications

The agent added seven tests, taking the suite to 56, all passing. Four cover the sweep: it runs inclusively from 40 to 50 and only rises; there is exactly one percentage per level and each stays within 0–100; the swept percentages match a direct per-level computation; and the flooded area comes out monotonic on the synthetic terrain. Three more cover the helper on its own: increasing values come out monotonic, a flat sequence still counts as non-decreasing, and the helper rejects a single downward step. Running the script printed the sweep in full, 7.84 % at 40 m rising to 30.72 % at 50 m, followed by "OK: flooded area increases monotonically", so the verification passed on real data.

### Changes Made

The 56 tests passed on the first run, so this step needed no corrections.

---

## Seventh Interaction

The working directory held the same files as after the previous step, with `flood_inundation.py` now also carrying the dynamic-simulation sweep and its monotonicity check.

### Prompt Used
"Inside `flood_inundation.py` write additional functions that use the results of the dynamic simulation to create an animated GIF of rising water levels:
1. Reuses the water levels and flood results already computed by the dynamic simulation (rather than recomputing them)
2. Renders the flood inundation map at each simulated water level (e.g. DEM with blue flood overlay)
3. Optionally annotates each frame with its water level and flooded percentage
4. Combines the frames into an animated GIF and saves it to disk
5. Allows configuring parameters such as frames per second

In parallel, add corresponding unit tests to my existing `test_flood_inundation.py` file following TDD practices, covering the reuse of simulation results, the frame generation, and verifying that the GIF file is created successfully."

### AI Output Summary

The agent first checked how to make a GIF without leaving the numpy/pandas/matplotlib stack, and pointed out that matplotlib can write GIFs through its Pillow writer, with Pillow already coming in as a matplotlib dependency, so nothing new had to be installed. It added `create_flood_gif(dem, levels, percentages=None, path="flood_animation.gif", fps=2, annotate=True)`. The function takes the `levels` and `percentages` that `simulate_dynamic_flood` already produced and reuses them; the percentages feed the per-frame label, and the function does not recompute them. Each frame is the terrain drawn once in grayscale with a blue overlay on the cells flooded at that level, and, when annotation is on, a small caption with the level and its flooded percentage. The frames are stitched with `ArtistAnimation` and saved with `PillowWriter`, with `fps` controlling the speed. The `__main__` block now calls it on the 40→50 m results from the dynamic step and writes `flood_animation.gif`. The agent flagged one thing: the GIF is not in the fixed deliverable list in `CLAUDE.md`, but task 8 asks for it, so it saved it under a configurable path and pointed this out rather than deciding silently.

### Verifications

Four more tests took the suite to 60, all passing. They check that the file is written and begins with the GIF magic bytes; that reusing the simulation's levels yields exactly one frame per level (read back with Pillow); that `fps` is honoured, so 4 fps gives a 250 ms per-frame duration in the GIF metadata; and that the function returns the path it wrote to. Beyond the tests I ran the script and opened the result: an 11-frame GIF at 500 ms per frame (2 fps), 1280×960, about 628 KB, whose first frame is captioned "40 m - 7.8%", matching the 7.84 % the dynamic simulation reported at 40 m, with the blue flood in the low corner and the three buildings staying dry.

### Changes Made

All 60 tests passed on the first run, so the GIF code needed no corrections. Later I asked to keep the building legend in the GIF as well. The agent split the figure construction out into a helper, `_build_flood_figure`, so the legend could be tested on the figure object, drew the building barriers in the same brown and added the "Flooded" / "Building (barrier)" legend that stays on every frame, and exposed a `barrier_height` argument. It added one test checking the animation figure carries the building legend, taking the suite to 63. A first attempt left a matplotlib warning (an animation built but never rendered in the test); the agent removed it by having the helper return only the figure and frames and creating the animation inside `create_flood_gif`, so the suite is green with no warnings. I regenerated the GIF and confirmed the legend and brown buildings now appear on the frames.

Finally I asked to add an elevation bar to the GIF as well, matching the other static plots (`plot_dem`, `plot_flood_extent`). The agent captured the terrain `imshow` return in `_build_flood_figure` and attached a `fig.colorbar(terrain, ax=ax, label="Elevation (m)")` to it; because the terrain layer is drawn once as a static background, the colorbar appears on every frame of the GIF at no extra cost. The agent touched no other code, the 63 tests still pass, and the regenerated `flood_animation.gif` now carries the elevation scale next to the panel.

---

## Eighth Interaction

The working directory now also held `flood_animation.gif` and the `create_flood_gif` function in `flood_inundation.py`, on top of the earlier deliverables and tests.

### Prompt Used
"Write a dedicated validation script, named `validate_flood_inundation.py`, to be placed in the test folder, that performs physical validation of the flood model. The script should:
1. Enforce the physical constraint that flooded area MUST increase (monotonically, non-decreasing) as the water level rises
2. Check the elevation units (meters vs. feet) and flag a warning if results look physically wrong, suggesting a likely unit mismatch
3. Verify whether the flooded area increases monotonically across the simulated water levels
4. Document any unexpected behavior (e.g. non-monotonic jumps, plateaus, or implausible values)
5. Produce a summary Markdown (.md) report capturing the validation results, including the monotonicity check, the unit check, any anomalies found, and a pass/fail verdict

Keep this as a standalone validation script separate from the unit tests in `test_flood_inundation.py`."

### AI Output Summary

The agent stressed that, because I asked for this to stay separate from the unit tests, it would not add anything to `test_flood_inundation.py`; the script itself is the check, verified by running it. It wrote `tests/validate_flood_inundation.py`. Since the script lives in `tests/` but is not a `test_*` file, pytest does not collect it; to let it run on its own it puts the project root on `sys.path` at the top, which it noted is the usual pattern for a runnable script in a subfolder and different from the conftest discussion earlier. It loads the saved `dem_data.npy` if present (so it validates the real artifact) and otherwise falls back to a deterministic synthetic DEM. The script runs three checks. Monotonicity: it sweeps the water level across the whole DEM range and confirms the flooded area never decreases, recording any drops and any flat plateaus. A unit check: it flags a likely metres-vs-feet mismatch using Mount Everest (~8849 m) as the ceiling: if the maximum elevation is above that, the values are implausible as metres and probably in feet, and it reports the converted value. A value check: it looks for implausible results, namely a flooded percentage outside 0–100 % or a maximum depth that does not equal water level minus the minimum elevation. It then writes `validation_report.md` with a level-vs-percentage table, the outcome of each check, any anomalies, and a PASS/FAIL verdict, and exits non-zero on failure so the monotonicity constraint is enforced. The agent flagged that the Everest threshold and the report location are its own choices, and that the script and report are not in the fixed deliverable list but are what this prompt asked for.

### Verifications

I ran the script: it printed "Validation PASS", exited 0, and wrote `validation_report.md`. The report is physically sensible: the flooded area climbs monotonically from 0 % at 30 m to about 95.5 % near the top, with no drops, and the report flags the five flat plateaus above ~80 m (past the terrain's maximum only the buildings stay dry, so the flooded area sticks at 95.54 %, which is 10000 minus the 446 building cells). The unit check passed, calling 100 m plausible as metres, and there were no anomalies. I also exercised the unit heuristic both ways by hand: a normal metres DEM passes, while it flags a DEM topping out at 12000 m as a likely feet mismatch, with the ~3658 m conversion shown. Finally I confirmed the existing pytest suite is untouched and still reports 63 passing, since the validation script is not collected.

### Changes Made

The script worked on the first run and the validation passed, so no corrections were needed. I made no changes to the unit-test file, since the prompt asked for the validation to stay separate. Afterwards I asked for the report to live in the test folder rather than the project root: the agent pointed the report path at the script's own directory (`tests/`), leaving `dem_data.npy` read from the root, removed the report it had written to the root, and re-ran the script to regenerate `tests/validation_report.md`, still PASS, exit 0.

---

## Refinement

After the elevation-bar change I ran `/simplify` to review the diff for reuse, simplification, efficiency, and altitude, quality only rather than bug hunting.

### AI Output

The slash command spawned four reviewers in parallel, one per angle, each handed the two-line change in `_build_flood_figure` (capturing the terrain `imshow` return and attaching `fig.colorbar(terrain, ax=ax, label="Elevation (m)")`).

- **Reuse.** The new pair matches the exact pattern already used in `plot_dem` and `plot_flood_extent`. Extracting a shared "imshow + colorbar" helper would save three lines across the codebase at the cost of obscuring the matplotlib flow at each call site, so the reviewer recommended against it, citing the CLAUDE.md "three similar lines beats a premature abstraction" rule.
- **Simplification.** The `terrain` intermediate variable is required by the `fig.colorbar` signature (it needs the `ScalarMappable` returned by `imshow`); inlining it into a single statement would be harder to read and would push the clarifying comment off the `imshow` line. The existing comment ("static terrain background, shown every frame") is still accurate after the addition.
- **Efficiency.** The colorbar is built once at figure-construction time, outside the per-frame loop, so there is no per-frame cost. It reuses the existing `terrain` artist's norm and cmap, so no extra copy of the DEM and no recomputation.
- **Altitude.** The colorbar is attached at the same level as in the sibling plot functions: each top-level figure builder creates its own `fig, ax` and attaches its own colorbar. Pushing the call down into `_overlay_buildings` would be the wrong layer (that helper draws buildings, not terrain) and a "draw terrain layer" helper would still have to hand the image back so the caller can attach the colorbar to its own `fig`, for a net zero saving.

### Verifications

All four angles came back clean, so there were no fixes to apply. To double-check, I re-ran the pytest suite after the review and it is still green at 63 passing, and the regenerated `flood_animation.gif` still shows the elevation colorbar on every frame.

### Changes Made

No code or documentation changes came out of `/simplify`: every reviewer confirmed the elevation-bar addition was already minimal, consistent with the existing convention, and at the right altitude. The only file touched in this refinement step is this log entry.

---
