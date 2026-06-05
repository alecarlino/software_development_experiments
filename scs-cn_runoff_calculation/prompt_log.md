# Prompt Log - Experiment 2: Hydrological Modeling SCS-CN Runoff Calculation

**Author:** Alessandro Carlino
**Course:** Software Development
**Date:** 2026-04-11

## AI Agent Settings

**Platform:** Claude Code
**Model:** Opus 4.7 (High Effort)
**Plugin:** Superpowers (for TDD)
**Agent configuration file:** `CLAUDE.md` (provided in the directory)

---

## First Iterations

My working directory held two files: `CLAUDE.md`, with the project rules and domain background, and an empty `prompt_log.md`.

### Prompt Used
"I am a computer science master's student building a hydrological model in Python. I want to implement the Soil Conservation Service Curve Number (SCS-CN) method for estimating direct runoff from rainfall.
  Write a function `calculate_runoff(P, CN)` in a file `scscn_runoff.py` that:
  1) Calculates S = (25400 / CN) - 254
  2) Calculates Ia = 0.2 * S
  3) Returns Q = 0 if P < Ia
  4) Otherwise returns Q = (P - Ia)² / (P - Ia + S)
  5) Ensures Q never exceeds P

  All quantities are in millimeters (mm). Include type hints and a docstring describing parameters, return value, and a usage example"

### AI Output Summary

Before writing code, the agent enabled the TDD habit from the `Superpowers` plugin and read the rules from `CLAUDE.md`. Its first question concerned the domain.

The case it isolated was `CN = 0`. The formula computes `25400 / CN`, so zero raises a division error, while `CLAUDE.md` defines `CN = 0` as a physical condition (fully pervious surface) that must return `Q = 0`. The agent proposed a guard for that case and asked me to push back if I disagreed. It also raised input validation for out-of-range values, then skipped raising errors there to honour the "no features beyond what was asked" rule.

The file it produced, `scscn_runoff.py`, is short: the formula, type hints, a docstring with the equations, two worked examples, and a final `min(Q, P)` clamp to enforce the `Q <= P` constraint from the spec.

### Verifications

I checked a small set of reference cases by hand to confirm the formula was transcribed correctly:

- `P=50, CN=80   -> Q ≈ 13.80` (matches the verification example printed in the experiment guide)
- `P=5,  CN=80   -> Q = 0` (rainfall below the initial abstraction)
- `P=100, CN=100 -> Q = 100` (impervious surface, all runoff)
- `P=100, CN=0   -> Q = 0` (fully pervious, the explicit guard kicked in)

All four results matched expectation, and `Q in [0, P]` held in every case. The value at `P=50, CN=80` matched the guide's worked example (`13.8 mm`) to two decimals, the check that confirmed the transcription rather than a plausible-looking approximation.

### Changes Made

The code worked, so no behavioural change was needed. I edited a few comments by hand to trim redundancy.

---
## Second Interaction

The working directory now held three files: the unchanged `CLAUDE.md`, the updated `prompt_log.md` with the first iteration logged, and the flat script `scscn_runoff.py` with the requested `calculate_runoff(P, CN)`.

### Prompt Used
"Add a function `route_time_area` to `scscn_runoff.py`, it must take the excess rainfall produced and route it into an outflow hydrograph using the time-area method. Don't modify `calculate_runoff`,keep it backward-compatible.
The new function must take incremental rainfall (mm per step), the curve number, a time-area diagram (area fraction per interval), watershed area (km2), and the time step (hours), and returns the hydrograph (m3/s).
This method is nonlinear and works on cumulative rainfall, so get each step's excess as the difference in cumulative runoff between consecutive steps, don't compute runoff on each interval independently. Convert each excess pulse to a discharge, then convolve with the time-area diagram. Normalize the diagram."

### AI Output Summary

This time the agent ran the Superpowers TDD habit at full strength, backed by the rules in `CLAUDE.md`. It wrote `test_scscn.py` first and only then touched `scscn_runoff.py`. The edit to the existing file was surgical, as I had asked: an import of `Sequence` at the top, the new function appended at the bottom, and no change inside `calculate_runoff`.

The design call worth recording involved how SCS-CN behaves inside a routing loop. Applying `calculate_runoff` to each rainfall interval on its own gives the wrong answer, because the method is nonlinear in cumulative depth. The agent built the incremental excess as the first difference of cumulative runoff (`Q(P_cum_k) - Q(P_cum_{k-1})`), the physically correct approach, and stated this in its summary so I could check the reasoning against the diff.

The agent flagged two smaller decisions rather than burying them. The `time_area` normalization runs internally, so any positive-sum vector works, and a zero-sum vector raises `ValueError` as I had asked. The convolution uses a plain nested loop in pure Python instead of `numpy.convolve`; the agent's argument was that the function already returns `list[float]` and the inputs are short, and it noted that switching to NumPy is a one-line change once I run long rainfall series, which is fair.

### Verifications

The TDD cycle worked as intended. The first run, before any implementation, produced `ImportError: cannot import name 'route_time_area'`. That is the correct result at this stage: the test harness is wired up and the function does not exist yet. The agent then opened `scscn_runoff.py` and wrote the code.

The agent added four tests for the routing function:

- a `ValueError` when `time_area` sums to zero, since a zero-sum diagram can't be normalized;
- a length check on the output hydrograph (`len(rainfall) + len(time_area) - 1`, the standard length of a discrete convolution);
- a mass-conservation check;
- a second mass-conservation check fed with an un-normalized `time_area` like `[3.0, 7.0]`, to confirm the internal normalization step works.

I relied on the mass-conservation test more than the others. It checks a physical invariant instead of a textbook number: water in equals water out, both sides converted to cubic meters. A convolution indexed off by one step, a wrong mm-to-m³/s factor, or a normalization that dropped part of the diagram would all break that equality. It held, which is when I stopped worrying about the routing.

The four `calculate_runoff` tests from the previous iteration stayed green without any edits, direct evidence that the "don't touch `calculate_runoff`" constraint held.

### Changes Made

The TDD pass came out clean, so the agent's output stayed as written.

---
## Third Interaction

The working directory now held four files: `CLAUDE.md`, `prompt_log.md`, `scscn_runoff.py`, and `test_scscn.py`.

### Prompt Used
"I've got a `calculate_runoff` function (SCS-CN method) taking a rainfall depth and curve number. The curve number assumes average soil moisture (AMC II), but catchments are sometimes drier or wetter, which changes the runoff. Add a way to adjust the curve number for antecedent moisture conditions, down to AMC I when dry, up to AMC III when wet, using the standard conversion formulas, and wire it into the runoff calculation so I can pick a condition and get the right answer.

Keep `calculate_runoff` behaving exactly as now if no adjustment is requested (default AMC II), and let me choose the condition through a clean I/II/III parameter. Match the existing docstring style and type hints, and add tests: the dry and wet conversions against known values, the AMC II passthrough, and the CN = 0 and CN = 100 edge cases."

### AI Output Summary

Adding AMC support to `calculate_runoff` had several reasonable shapes: the conversion could go inline or in a helper, the parameter could be a string, an integer, or an enum, and the validation could be silent or loud. The agent listed all of these in plain language before editing the file, rather than picking one in silence.

The decisions it landed on were small and reasonable. It put the conversion in a separate helper, `adjust_cn_for_amc(CN, amc)`, so the formula is testable on its own without the full SCS-CN computation behind it. It made the `amc` parameter on `calculate_runoff` optional with `"II"` as the default, so every existing call site keeps working unchanged. It gave the parameter a `Literal["I", "II", "III"]` type hint, so a type checker and a reader can see which strings are valid.

For the conversion math the agent picked the Sobhani formulas: `CN_I = 4.2·CN / (10 − 0.058·CN)` and `CN_III = 23·CN / (10 + 0.13·CN)`. This time it named the sources, the NRCS National Engineering Handbook (Part 630, Ch. 10) and Chow, Maidment & Mays, an improvement over the first interaction, where it had pointed at a "standard reference" without naming one. Both formulas map `CN = 0` to `0` and `CN = 100` to `100`, so the two edge cases I asked it to test fall out of the math and the helper needs no special-case `if CN == 0` branch. The agent pointed this out and skipped the redundant guard.

The agent surfaced two more calls. First, it added a `ValueError` for invalid AMC strings even though I hadn't asked for it, arguing that a typo falling through to AMC II would be a worse, harder-to-find bug than a clear error at the boundary, and asked me to push back if I disagreed. Second, it left `route_time_area` alone instead of extending it to accept an AMC parameter, noting that wiring AMC through routing later would be a one-line change, which is true.

The implementation was small: a new `Literal` import, the helper defined above `calculate_runoff` so the dependency reads top-down, a single line `CN = adjust_cn_for_amc(CN, amc)` at the start of the runoff body, and an updated docstring in the same NumPy-style layout as the original. `calculate_runoff` now takes three parameters instead of two, but the default keeps every previous call equivalent.

### Verifications

Same TDD cycle as the previous round. The first run, before any new code in `scscn_runoff.py`, produced `ImportError: cannot import name 'adjust_cn_for_amc'`, confirming the test file was wired up and the function did not exist yet.

After the implementation went in, I focused on the seven new AMC tests. The dry and wet conversions for `CN_II = 80` matched the Sobhani values to two decimals (`CN_I ≈ 62.69` and `CN_III ≈ 90.20`). The AMC II passthrough returned the curve number unchanged for every value I tested (`0, 50, 75, 80, 100`). The `CN = 0` and `CN = 100` edge cases mapped to themselves under all three conditions, the algebraic property of the Sobhani formulas written as an assertion. The `ValueError` on a bad AMC string (`"IV"`) fired as expected.

The smallest test, `test_calculate_runoff_default_matches_amc_ii`, did the most work. It calls `calculate_runoff(P, CN)` without the new parameter and asserts the result equals `calculate_runoff(P, CN, "II")`. That one line turns backward compatibility from a promise into a contract: if anyone later changes the default or drops the AMC II passthrough, the test fails and forces the change to be deliberate.

The eight tests from the previous two rounds stayed green untouched, confirming the new `amc` parameter defaulted to the old behaviour and that the existing call inside `route_time_area` still worked.

### Changes Made

The TDD pass was clean again, so nothing in the agent's output needed changing.

---
## Fourth Interaction

The working directory held `CLAUDE.md`, `prompt_log.md`, `scscn_runoff.py`, and `test_scscn.py`, now covering the SCS-CN calculation, the time-area routing, and the AMC adjustment.

### Prompt Used
"Add a second, independent runoff method, the Rational method, so I can compare the two. Don't modify `calculate_runoff`; the new method should sit alongside it, not chain off it.

Make sure the outputs are actually comparable: SCS-CN returns a runoff depth while the Rational method natively gives a peak discharge, so expose results in matching quantities for example both as a depth, or both as a discharge so a direct comparison is meaningful. Validate inputs and use consistent, clearly documented units.

Match the existing docstring style and type hints, and add tests covering a known case, the unit handling, and the input-validation edge cases."

### AI Output Summary

The Rational method returns a peak discharge in m3/s, while `calculate_runoff` returns a depth in mm, so the two are not comparable as written. My prompt had flagged this and offered the agent two routes: match on depth, or match on discharge.

The agent picked depth and explained why before writing code. Converting SCS-CN to a peak discharge would have required calling `route_time_area`, chaining the two methods together and breaking the "independent, not chained off it" requirement I had set. Matching on depth means computing `C · i · duration` (mm) and lining the result up against the SCS-CN depth on the same axis. I hadn't considered the chaining argument when I wrote the prompt, and the agent's reasoning held up.

The function it produced, `rational_runoff(C, i, duration)`, is three lines of input validation and one line of math. The docstring spells out the units (`C` dimensionless in `[0, 1]`, `i` in mm/h, `duration` in h, output in mm) and notes the classical peak-discharge form `q_peak = C · i · A / 3.6`, explaining why that variant is *not* exposed here. A later reader sees the omission as a deliberate choice.

The agent labelled two smaller decisions. The first was input validation: it added a `ValueError` for `C` outside `[0, 1]`, negative `i`, and negative `duration`, while treating `i = 0` and `duration = 0` as valid (they produce zero runoff, the correct result). The second was placement: the new function went at the end of `scscn_runoff.py`, after `route_time_area`, not between `calculate_runoff` and the routing code. The agent's reason was that `rational_runoff` is an alternative method outside the SCS-CN family, so appending it leaves the module's existing flow untouched.

### Verifications

Same TDD cycle as the previous rounds. The first run produced `ImportError: cannot import name 'rational_runoff' from 'scscn_runoff'`, the expected RED state: the import path is correct and the function is missing, not misspelled.

The five new tests for `rational_runoff` covered what I had asked for:

- a known case (`C = 0.6`, `i = 20 mm/h`, `duration = 2 h` → `24 mm`) to verify the formula end to end;
- a dimensional sanity check confirming that `(mm/h) · h` comes out as mm;
- the `C = 0` boundary, returning zero runoff regardless of intensity;
- the `C = 1` boundary cross-checked against `calculate_runoff(P, 100)` for the same total rainfall, which is the bridge test between the two methods;
- a single parameterized test exercising the four invalid-input cases (`C < 0`, `C > 1`, `i < 0`, `duration < 0`), reporting each combination independently via `subTest` so a future failure would point at the exact bad input.

`test_impervious_matches_scs_cn` carried the most weight. It is the one test that ties the two methods together: it picks the single physical point where they must agree, an impervious surface produces runoff equal to total rainfall, and asserts the two outputs are equal. Change the units of `rational_runoff`, or stop it returning a depth, and the test fails, taking the "two methods are comparable" claim with it. I would keep a cross-method invariant like this in a real codebase.

The fifteen tests from the earlier iterations stayed green without any edits, direct evidence that adding the Rational method on the side left the SCS-CN family unchanged.

### Changes Made

No behavioural edits were necessary; all twenty tests passed on the first GREEN run. The file had grown to a reasonable size, so I went through the comments by hand to make them readable and consistent across functions.

---
## Fifth Interaction

The working directory now held the working `scscn_runoff.py` with all four functions (SCS-CN, AMC, time-area routing, Rational), plus the `test_scscn.py` suite covering them.

### Prompt Used
"Create a new file `sensitivity_analysis.py` that visualizes the results of all the calculations in `scscn_runoff.py`. Import the functions from that module rather than reimplementing them, and don't modify `scscn_runoff.py`.

The file should produce three things:
1) A plot comparing curve number (CN) values — runoff Q as a function of rainfall P, with one curve per CN across a representative range, so the effect of CN on runoff is clear.

2) A comparison between the two runoff methods (SCS-CN and the Rational method), plotted in matching, comparable quantities so the two are directly visualized against each other over a shared range of inputs.

3) An interactive plot with sliders for P and CN, letting the user vary both and see the runoff response update live."

### AI Output Summary

This round turned on a design decision: how to compare two methods that do not produce the same quantity. The agent matched on depth for both sides and gave the same reasoning as the previous round. Converting SCS-CN to a peak discharge would have meant calling `route_time_area` and breaking the "independent" requirement, so the Rational side stays `C · i · duration` (mm), plotted against the SCS-CN depth on a shared axis.

The file has three plot functions and a `main` orchestrator, all importing `calculate_runoff` and `rational_runoff` from `scscn_runoff` and reimplementing nothing. The first plot, fixed by the deliverables list as `runoff_comparison.png`, draws SCS-CN runoff against rainfall for several curve numbers and saves the PNG. The second draws three `(CN, C)` pairs in matching colours, SCS-CN solid and Rational dashed, so the linear-versus-nonlinear contrast shows. The third is interactive, with two sliders for `P` and `CN` and a red marker that tracks the picked point on the live curve. The slider widgets are stored on the figure as `fig._sliders` so they survive garbage collection after the function returns; the agent flagged this as a documented matplotlib pattern, not something it invented for this code.

The first smoke test produced a `RuntimeWarning: invalid value encountered in scalar divide`. The agent traced it to a real bug in `calculate_runoff`: at `P = 0` and `CN = 100` the formula runs with `S = Ia = 0`, and the guard `P < Ia` misses the boundary. The correct fix sat inside `calculate_runoff`, which I had told it not to modify. It worked around the case by starting `np.linspace` at `1e-9` instead of `0` in three places, and surfaced the bug with a one-line proposed fix (`if P <= Ia`) for me to apply later. The workaround came labelled in the code as a bandaid, so its temporary status is clear.

### Verifications

I ran the smoke test headless with the matplotlib `Agg` backend, so it needed no display. The three plot factories returned valid `Figure` objects: the first had five lines (one per CN value 60, 70, 80, 90, 100), the second had six (three SCS-CN solid plus three Rational dashed), the third had a main axes plus two slider axes with the two `Slider` widgets attached. `runoff_comparison.png` landed at the expected path as a valid PNG of about 99 KB.

I reran the `test_scscn` suite right after, to confirm nothing in the existing module had changed: twenty tests, all green. Direct proof that I held the "don't modify `scscn_runoff.py`" constraint by adding a new file instead of editing the old one.

### Changes Made

The one change around the agent's output was on the dependency side. The system Python here is the Homebrew build under PEP 668, which blocks a global `pip3 install matplotlib`. The agent tried `--user` first (also blocked), then asked how to proceed before doing anything destructive. I picked `--break-system-packages` and installed matplotlib `3.10.9` system-wide. No edits to the file were needed at that stage; the only follow-up was the `1e-9` workaround above, which I removed once the Refinement step fixed the underlying bug.

---
## Refinement

### AI Output

I asked the agent to run a structured review pass (the `/simplify` skill at extra-high effort), find the real bugs in the diff, and fix what it could. The skill ran nine finder angles inline; the codebase was small enough that spawning agents would have cost more than reading the three files directly.

Four findings survived the verification phase:

- two real crashes in `scscn_runoff.py`: `calculate_runoff(0, 100)` divides by zero (the edge case from the previous round's smoke test), and `route_time_area` divides by `dt` with no precondition check, so `dt = 0` crashes and `dt < 0` flips the sign of each discharge;
- one slider-driven crash in `sensitivity_analysis.py` (dragging `P` to `0` with `CN` at `100` calls `calculate_runoff(0, 100)` from the marker callback);
- one cleanup item (a redundant `intensities` variable that held the same numbers as `P` once `duration = 1` was substituted).

The initial pass applied the two findings inside `sensitivity_analysis.py`: the slider fix via `max(p, 1e-9)` at the two call sites that used a slider or init value, and the removal of the redundant `intensities` variable. The agent surfaced the two real bugs in `scscn_runoff.py` but left them unfixed, because I had been firm about not modifying that file across the earlier prompts. It offered a one-line fix for each and waited for permission.

I then gave the go-ahead, and the agent fixed both bugs at the root. `if P < Ia` became `if P <= Ia` inside `calculate_runoff` (one character, mathematically equivalent for every well-defined input and correct at the impervious boundary), and `route_time_area` gained an `if dt <= 0: raise ValueError(...)` guard at the top. The agent added two regression tests: one for `calculate_runoff(0, 100) == 0`, and one parametrized via `subTest` covering `dt = 0` and `dt = -1`. With the root cause fixed, it deleted the `1e-9` workarounds from `sensitivity_analysis.py`: three `linspace` lines went back to starting at `0`, and the two `max(p, 1e-9)` clamps in the marker computation became plain `p`.

### Verifications

The new tests this round were the two regressions guarding the fixes: a check that `calculate_runoff(0.0, 100) == 0.0` (which would have crashed before the `P <= Ia` change), and a parameterized `route_time_area` test asserting `ValueError` for `dt = 0` and `dt = -1`. Both failed first against the unpatched code (the `dt = 0` case raising `ZeroDivisionError` instead of `ValueError`, the `dt = -1` case raising nothing), and both turned green after the fixes.

I added a few checks on physical correctness that the previous rounds had missed: monotonicity (`test_higher_cn_produces_more_runoff`) confirms that holding P fixed and raising CN never lowers Q, and a grid sweep (`test_runoff_never_exceeds_rainfall`) confirms `Q ≤ P` across a `[0, 200] × [0, 100]` grid of `(P, CN)` pairs. I also added the experiment guide's worked example (`P = 50, CN = 80 → Q ≈ 13.80`) as a dedicated test, alongside the older `P = 100, CN = 75` reference value, so the link between the code and the printed assignment is explicit.

I re-ran the smoke test for `sensitivity_analysis.py` with `-W error::RuntimeWarning`, so any leftover NaN-producing divide would become a hard failure. It stayed silent. As a final manual check the agent simulated the slider worst case: it drove `slider_p.set_val(0.0)` and `slider_cn.set_val(100.0)` and called the callback, then called `plot_interactive(p_init=0.0, cn_init=100.0)` to exercise the init path. Both paths ran without raising, which settled the original bug.

I re-ran the previous suite untouched and it stayed green, twenty-seven tests total at the end of the round.

### Changes Made

No further edits to the agent's output were necessary. The `/simplify` pass had held back the two `scscn_runoff.py` bugs on its first run; it fixed both cleanly on the second once I gave permission, and removed the workaround code in the same pass, so the project carries no dead bandaid.

---
