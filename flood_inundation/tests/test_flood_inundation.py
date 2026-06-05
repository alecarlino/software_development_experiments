"""Unit tests for flood_inundation.py (TDD).

The suite is organised one class per public function. Each test targets a
single behaviour and uses small, hand-checkable inputs where possible, falling
back to the seeded synthetic DEM (reproducible) for the larger, end-to-end
checks. Run from the project root with: python -m pytest tests/
"""

import matplotlib

matplotlib.use("Agg")  # headless backend: build figures without opening windows

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.figure import Figure

from flood_inundation import (
    add_buildings,
    create_flood_gif,
    flood_mask,
    flood_routing,
    flood_volume,
    flooded_percentage,
    generate_synthetic_dem,
    inundation_depth,
    is_monotonic_non_decreasing,
    load_real_dem,
    plot_dem,
    plot_flood_curve,
    plot_flood_extent,
    plot_inundation_depth,
    plot_water_level_comparison,
    simulate_dynamic_flood,
    simulate_flood,
)


# ===========================================================================
# DEM INPUT TESTS
# ===========================================================================

class TestGenerateSyntheticDem:
    """Synthetic DEM generator: shape, value range, dtype, reproducibility."""

    def test_default_shape_is_100x100(self):
        # The assignment asks for a 100x100 grid by default.
        dem = generate_synthetic_dem()
        assert dem.shape == (100, 100)

    def test_values_within_elevation_range(self):
        # Elevations must stay inside the requested [low, high] band (clipped).
        dem = generate_synthetic_dem(low=30.0, high=80.0, seed=0)
        assert dem.min() >= 30.0
        assert dem.max() <= 80.0

    def test_returns_float_array(self):
        # Elevations are continuous, so the grid must be floating-point.
        dem = generate_synthetic_dem(seed=0)
        assert np.issubdtype(dem.dtype, np.floating)

    def test_seed_is_reproducible(self):
        # Same seed -> identical terrain, which is what lets other tests
        # assert on exact values.
        a = generate_synthetic_dem(seed=42)
        b = generate_synthetic_dem(seed=42)
        np.testing.assert_array_equal(a, b)

    def test_different_seeds_differ(self):
        # Different seeds must produce different terrain (the noise is random).
        a = generate_synthetic_dem(seed=1)
        b = generate_synthetic_dem(seed=2)
        assert not np.array_equal(a, b)

    def test_custom_size(self):
        # The grid size is configurable, not hard-coded to 100.
        dem = generate_synthetic_dem(size=50, seed=0)
        assert dem.shape == (50, 50)

    def test_has_spatial_structure_not_pure_noise(self):
        # A coherent (slope-based) terrain has neighbouring cells more similar
        # than randomly paired cells; pure uniform noise would not. We compare
        # the mean absolute difference of horizontal neighbours against the
        # same statistic on a shuffled copy of the same values.
        dem = generate_synthetic_dem(seed=0)
        neighbour_diff = np.abs(np.diff(dem, axis=1)).mean()
        shuffled = dem.flatten()
        np.random.default_rng(0).shuffle(shuffled)
        random_diff = np.abs(np.diff(shuffled)).mean()
        assert neighbour_diff < random_diff


class TestLoadRealDem:
    """Real-DEM loader: .npy and Esri ASCII (.asc) reading, validation, errors."""

    def test_loads_saved_npy(self, tmp_path):
        # A DEM saved to .npy must round-trip back unchanged.
        path = tmp_path / "dem_data.npy"
        original = np.linspace(30, 80, 100 * 100).reshape(100, 100)
        np.save(path, original)
        loaded = load_real_dem(str(path))
        np.testing.assert_array_equal(loaded, original)

    def test_returns_float_array(self, tmp_path):
        # Even an integer-typed file comes back as float (elevations are float).
        path = tmp_path / "dem_data.npy"
        np.save(path, np.arange(16, dtype=np.int32).reshape(4, 4))
        loaded = load_real_dem(str(path))
        assert np.issubdtype(loaded.dtype, np.floating)

    def test_missing_file_raises(self, tmp_path):
        # A missing path must fail loudly rather than return garbage.
        with pytest.raises(FileNotFoundError):
            load_real_dem(str(tmp_path / "does_not_exist.npy"))

    def test_non_2d_array_raises(self, tmp_path):
        # A DEM is a 2D grid; a 1D array is rejected.
        path = tmp_path / "bad.npy"
        np.save(path, np.arange(10))  # 1D
        with pytest.raises(ValueError):
            load_real_dem(str(path))

    def test_default_path_is_asc_in_dem_folder(self):
        # Default location/format for real DEM data is dem/dem_data.asc.
        import inspect

        sig = inspect.signature(load_real_dem)
        default = sig.parameters["path"].default
        assert default == "dem/dem_data.asc"

    def test_loads_esri_ascii_grid(self, tmp_path):
        # A minimal Esri ASCII grid: 6 header lines then the elevation rows.
        # The header must be parsed and skipped, leaving the 2x3 grid.
        path = tmp_path / "dem.asc"
        path.write_text(
            "ncols 3\n"
            "nrows 2\n"
            "xllcorner 0.0\n"
            "yllcorner 0.0\n"
            "cellsize 30.0\n"
            "NODATA_value -9999\n"
            "1 2 3\n"
            "4 5 6\n"
        )
        loaded = load_real_dem(str(path))
        assert loaded.shape == (2, 3)
        np.testing.assert_array_equal(loaded, [[1, 2, 3], [4, 5, 6]])

    def test_asc_nodata_becomes_nan(self, tmp_path):
        # Cells equal to NODATA_value must be converted to NaN, not kept as
        # the sentinel -9999 (which would corrupt min/max and flooding).
        path = tmp_path / "dem.asc"
        path.write_text(
            "ncols 3\n"
            "nrows 2\n"
            "xllcorner 0.0\n"
            "yllcorner 0.0\n"
            "cellsize 30.0\n"
            "NODATA_value -9999\n"
            "1 -9999 3\n"
            "4 5 6\n"
        )
        loaded = load_real_dem(str(path))
        assert np.isnan(loaded[0, 1])
        assert not np.isnan(loaded[0, 0])

    def test_missing_asc_raises(self, tmp_path):
        # A missing .asc path must also raise (open() does this for us).
        with pytest.raises(FileNotFoundError):
            load_real_dem(str(tmp_path / "missing.asc"))


# ===========================================================================
# BUILDING BARRIER TESTS
# ===========================================================================

class TestAddBuildings:
    """Building footprints burned into the DEM as flood barriers."""

    def test_footprint_cells_set_to_barrier_height(self):
        # Footprint (row=1, col=1, 2 rows, 3 cols) -> dem[1:3, 1:4] raised.
        dem = np.zeros((5, 5))
        out = add_buildings(dem, [(1, 1, 2, 3)], barrier_height=100.0)
        assert np.all(out[1:3, 1:4] == 100.0)

    def test_cells_outside_footprint_unchanged(self):
        # Only the footprint rectangle changes; everything else is untouched.
        dem = np.zeros((5, 5))
        out = add_buildings(dem, [(1, 1, 2, 3)], barrier_height=100.0)
        expected = np.zeros((5, 5))
        expected[1:3, 1:4] = 100.0
        np.testing.assert_array_equal(out, expected)

    def test_does_not_mutate_input(self):
        # The function works on a copy: the original DEM is left intact.
        dem = np.zeros((5, 5))
        add_buildings(dem, [(1, 1, 2, 3)], barrier_height=100.0)
        np.testing.assert_array_equal(dem, np.zeros((5, 5)))

    def test_multiple_footprints(self):
        # Several footprints can be burned in one call; the cell between two
        # corner buildings stays at its original value.
        dem = np.zeros((6, 6))
        out = add_buildings(dem, [(0, 0, 2, 2), (4, 4, 2, 2)], barrier_height=100.0)
        assert np.all(out[0:2, 0:2] == 100.0)
        assert np.all(out[4:6, 4:6] == 100.0)
        assert out[3, 3] == 0.0

    def test_no_footprints_returns_copy_unchanged(self):
        # An empty footprint list returns an equal but distinct array (a copy),
        # never the same object.
        dem = generate_synthetic_dem(seed=0)
        out = add_buildings(dem, [])
        np.testing.assert_array_equal(out, dem)
        assert out is not dem

    def test_default_barrier_is_above_terrain(self):
        # Buildings must sit above any sensible water level (terrain max 80 m),
        # so that flooding (elevation < water_level) never covers them.
        dem = generate_synthetic_dem(seed=0)
        out = add_buildings(dem, [(0, 0, 5, 5)])
        assert out[0:5, 0:5].min() > dem.max()


# ===========================================================================
# FLOOD CALCULATION TESTS
# ===========================================================================

class TestFloodMask:
    """Boolean flooded mask: elevation strictly below the water level."""

    def test_marks_cells_below_water_level(self):
        # Only the two cells below 40 m are flagged as flooded.
        dem = np.array([[10.0, 50.0], [60.0, 20.0]])
        mask = flood_mask(dem, 40.0)
        np.testing.assert_array_equal(mask, [[True, False], [False, True]])

    def test_strict_inequality_excludes_equal_cells(self):
        # Domain spec uses a strict "<": a cell exactly at the water level is
        # NOT flooded, only the one below it is.
        dem = np.array([[40.0, 39.9]])
        mask = flood_mask(dem, 40.0)
        np.testing.assert_array_equal(mask, [[False, True]])

    def test_building_cells_are_not_flooded(self):
        # A building cell (raised to 100 m) stays dry at a 50 m level, while a
        # surrounding 10 m cell floods -> barriers fall out for free.
        dem = add_buildings(np.full((3, 3), 10.0), [(1, 1, 1, 1)])
        mask = flood_mask(dem, 50.0)
        assert mask[1, 1] == False  # noqa: E712 - explicit barrier check
        assert mask[0, 0] == True   # noqa: E712


class TestInundationDepth:
    """Per-cell inundation depth: water_level - elevation where flooded, else 0."""

    def test_depth_is_level_minus_elevation_where_flooded(self):
        # Depth is how far each flooded cell sits below the water surface.
        dem = np.array([[10.0, 30.0]])
        depth = inundation_depth(dem, 40.0)
        np.testing.assert_array_equal(depth, [[30.0, 10.0]])

    def test_depth_is_zero_where_dry(self):
        # Cells above the water level have zero depth, not a negative number.
        dem = np.array([[50.0, 60.0]])
        depth = inundation_depth(dem, 40.0)
        np.testing.assert_array_equal(depth, [[0.0, 0.0]])

    def test_max_depth_equals_level_minus_min_elevation(self):
        # Physical correctness check from the assignment: the deepest point is
        # the lowest cell, so max depth == water_level - min(elevation).
        dem = generate_synthetic_dem(seed=0)
        level = 50.0
        depth = inundation_depth(dem, level)
        assert depth.max() == pytest.approx(level - dem.min())


class TestFloodedPercentage:
    """Flooded area percentage: flooded cells / total cells x 100."""

    def test_all_cells_flooded_is_100(self):
        # Every cell flooded -> 100%.
        mask = np.ones((10, 10), dtype=bool)
        assert flooded_percentage(mask) == 100.0

    def test_no_cells_flooded_is_0(self):
        # No cell flooded -> 0%.
        mask = np.zeros((10, 10), dtype=bool)
        assert flooded_percentage(mask) == 0.0

    def test_half_cells_flooded_is_50(self):
        # Flooding the top half of a 10x10 grid (50 of 100 cells) -> 50%.
        mask = np.zeros((10, 10), dtype=bool)
        mask[:5] = True
        assert flooded_percentage(mask) == 50.0

    def test_percentage_within_bounds_for_real_dem(self):
        # Edge-case validation: the percentage must always stay in [0, 100],
        # even for levels below the minimum or above the maximum elevation.
        dem = generate_synthetic_dem(seed=0)
        for level in (20.0, 30.0, 55.0, 80.0, 90.0):
            pct = flooded_percentage(flood_mask(dem, level))
            assert 0.0 <= pct <= 100.0


# ===========================================================================
# FLOOD MODEL TESTS
# ===========================================================================

class TestSimulateFlood:
    """Bathtub simulation: returns (mask, depth, percentage) together."""

    def test_returns_mask_depth_and_percentage(self):
        # The three outputs have the expected shapes/types.
        dem = generate_synthetic_dem(seed=0)
        mask, depth, pct = simulate_flood(dem, 50.0)
        assert mask.shape == dem.shape
        assert depth.shape == dem.shape
        assert isinstance(pct, float)

    def test_outputs_are_consistent(self):
        # The three outputs agree with each other: depth is positive exactly
        # where the mask is True, and the percentage matches the mask.
        dem = generate_synthetic_dem(seed=0)
        mask, depth, pct = simulate_flood(dem, 50.0)
        np.testing.assert_array_equal(mask, depth > 0)
        assert pct == pytest.approx(flooded_percentage(mask))

    def test_flooded_area_increases_with_water_level(self):
        # Monotonicity check from the assignment: a higher water level can only
        # flood more (or equal) area, never less.
        dem = generate_synthetic_dem(seed=0)
        _, _, low = simulate_flood(dem, 40.0)
        _, _, high = simulate_flood(dem, 60.0)
        assert high > low


class TestFloodRouting:
    """Connected-component flooding (BFS) spreading from a source cell."""

    def test_floods_only_connected_region(self):
        # Three cells are below the water level, but the bottom-right pocket is
        # walled off by high ground, so the flood from the source only reaches
        # the two connected cells, not the isolated one.
        dem = np.array([
            [10.0, 10.0, 10.0],
            [1.0, 1.0, 10.0],
            [10.0, 10.0, 1.0],
        ])
        mask = flood_routing(dem, water_level=5.0, source=(1, 0))
        expected = np.array([
            [False, False, False],
            [True, True, False],
            [False, False, False],
        ])
        np.testing.assert_array_equal(mask, expected)

    def test_source_on_high_ground_floods_nothing(self):
        # If the source itself is above the water level, nothing floods.
        dem = np.array([[10.0, 1.0], [1.0, 1.0]])
        mask = flood_routing(dem, water_level=5.0, source=(0, 0))
        assert not mask.any()

    def test_buildings_block_water_spread(self):
        # A wall of buildings (middle column) separates two low areas, so water
        # starting on the left can never reach the right side.
        dem = add_buildings(np.full((3, 3), 1.0), [(0, 1, 3, 1)])
        mask = flood_routing(dem, water_level=50.0, source=(0, 0))
        assert np.all(mask[:, 0])        # left column floods
        assert not np.any(mask[:, 1])    # building wall stays dry
        assert not np.any(mask[:, 2])    # right side never reached

    def test_routed_mask_is_subset_of_threshold_mask(self):
        # Routing can only flood cells that are below the water level, so its
        # mask is always a subset of the bathtub (threshold) mask.
        dem = generate_synthetic_dem(seed=0)
        level = 50.0
        source = np.unravel_index(np.argmin(dem), dem.shape)
        routed = flood_routing(dem, level, source)
        threshold = flood_mask(dem, level)
        assert np.all(threshold[routed])


# ===========================================================================
# FLOOD VOLUME TESTS
# ===========================================================================

class TestFloodVolume:
    """Flood volume: summed depth x cell area (= mean depth x area x count)."""

    def test_volume_is_sum_of_depth_times_cell_area(self):
        # Volume = (1 + 2 + 3 + 0) * 10 = 60; the dry cell contributes nothing.
        depth = np.array([[1.0, 2.0], [3.0, 0.0]])
        assert flood_volume(depth, cell_area=10.0) == 60.0

    def test_uniform_depth_matches_depth_times_area_times_count(self):
        # The literal "depth x cell area x count" holds when depth is uniform:
        # 5 cells, each 2 m deep, 3 m^2 area -> 2 * 3 * 5.
        depth = np.full((5, 1), 2.0)
        assert flood_volume(depth, cell_area=3.0) == 2.0 * 3.0 * 5

    def test_zero_depth_gives_zero_volume(self):
        # No water anywhere -> zero volume regardless of cell area.
        depth = np.zeros((4, 4))
        assert flood_volume(depth, cell_area=900.0) == 0.0

    def test_default_cell_area_is_one(self):
        # With the default cell area of 1, the volume is just the summed depth.
        depth = np.array([[1.0, 2.0, 3.0]])
        assert flood_volume(depth) == 6.0

    def test_volume_matches_simulate_flood_output(self):
        # End-to-end: feeding simulate_flood's depth array gives the expected
        # depth-sum x area for a 30 m DEM cell (900 m^2).
        dem = generate_synthetic_dem(seed=0)
        _, depth, _ = simulate_flood(dem, 50.0)
        cell_area = 900.0
        assert flood_volume(depth, cell_area) == pytest.approx(depth.sum() * cell_area)


# ===========================================================================
# VISUALISATION TESTS
# ===========================================================================

class TestVisualization:
    """Plotting functions: they must run cleanly and return Figure objects."""

    @pytest.fixture(autouse=True)
    def _close_figures(self):
        # Close every figure after each test so they don't pile up in memory.
        yield
        plt.close("all")

    def test_plot_dem_returns_figure_with_title_and_colorbar(self):
        # Grayscale DEM plot: a titled image plus a colorbar (a second axis).
        dem = generate_synthetic_dem(seed=0)
        fig = plot_dem(dem)
        assert isinstance(fig, Figure)
        assert fig.axes[0].get_title() != ""
        assert len(fig.axes) >= 2  # main image axis + colorbar axis

    def test_plot_flood_extent_returns_figure(self):
        # Terrain with a blue flood overlay; just needs to build and be titled.
        dem = generate_synthetic_dem(seed=0)
        fig = plot_flood_extent(dem, 50.0)
        assert isinstance(fig, Figure)
        assert fig.axes[0].get_title() != ""

    def test_plot_inundation_depth_returns_figure_with_colorbar(self):
        # Depth heatmap with a colorbar (so, again, at least two axes).
        dem = generate_synthetic_dem(seed=0)
        fig = plot_inundation_depth(dem, 50.0)
        assert isinstance(fig, Figure)
        assert len(fig.axes) >= 2
        assert fig.axes[0].get_title() != ""

    def test_comparison_has_one_titled_axis_per_level(self):
        # Side-by-side comparison: one titled subplot for each water level.
        dem = generate_synthetic_dem(seed=0)
        levels = [40.0, 50.0, 60.0]
        fig = plot_water_level_comparison(dem, levels)
        assert isinstance(fig, Figure)
        titled = [ax for ax in fig.axes if ax.get_title() != ""]
        assert len(titled) == len(levels)

    def test_flood_extent_marks_buildings_with_legend(self):
        # Building barriers must be called out in a legend on the flood map.
        dem = add_buildings(generate_synthetic_dem(seed=0), [(10, 10, 8, 12)])
        fig = plot_flood_extent(dem, 50.0)
        legend = fig.axes[0].get_legend()
        assert legend is not None
        labels = [t.get_text() for t in legend.get_texts()]
        assert any("Building" in label for label in labels)

    def test_comparison_has_building_legend(self):
        # The comparison figure also labels the building barriers.
        dem = add_buildings(generate_synthetic_dem(seed=0), [(10, 10, 8, 12)])
        fig = plot_water_level_comparison(dem, [40.0, 50.0])
        texts = [t.get_text() for lg in fig.legends for t in lg.get_texts()]
        for ax in fig.axes:
            lg = ax.get_legend()
            if lg is not None:
                texts += [t.get_text() for t in lg.get_texts()]
        assert any("Building" in t for t in texts)

    def test_flood_curve_returns_labelled_figure(self):
        # Level-vs-percentage curve: titled, both axes labelled, one line whose
        # point count matches the number of water levels plotted.
        dem = generate_synthetic_dem(seed=0)
        levels = [30.0, 40.0, 50.0, 60.0, 70.0]
        fig = plot_flood_curve(dem, levels)
        assert isinstance(fig, Figure)
        ax = fig.axes[0]
        assert ax.get_title() != ""
        assert ax.get_xlabel() != ""
        assert ax.get_ylabel() != ""
        assert len(ax.lines[0].get_xdata()) == len(levels)

    def test_flood_curve_is_monotonic_non_decreasing(self):
        # The plotted percentages must never go down as the water level rises.
        dem = generate_synthetic_dem(seed=0)
        levels = np.linspace(30.0, 80.0, 11)
        fig = plot_flood_curve(dem, levels)
        ydata = fig.axes[0].lines[0].get_ydata()
        assert np.all(np.diff(ydata) >= 0)


# ===========================================================================
# DYNAMIC SIMULATION TESTS
# ===========================================================================

class TestDynamicSimulation:
    """Water-level sweep from 40 m to 50 m and its monotonicity."""

    def test_sweep_runs_inclusively_from_40_to_50(self):
        # The sweep starts at 40, ends at 50 (inclusive), and only rises.
        dem = generate_synthetic_dem(seed=0)
        levels, _ = simulate_dynamic_flood(dem, 40, 50, 1)
        assert levels[0] == 40
        assert levels[-1] == 50
        assert np.all(np.diff(levels) > 0)

    def test_one_percentage_per_level_within_bounds(self):
        # Every level yields one percentage, each in the valid [0, 100] range.
        dem = generate_synthetic_dem(seed=0)
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        assert len(percentages) == len(levels)
        assert np.all((percentages >= 0) & (percentages <= 100))

    def test_percentages_match_direct_computation(self):
        # The swept percentages match a direct mask-based computation per level.
        dem = generate_synthetic_dem(seed=0)
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 2)
        for level, pct in zip(levels, percentages):
            assert pct == pytest.approx(flooded_percentage(flood_mask(dem, level)))

    def test_dynamic_flood_area_is_monotonic(self):
        # On the smooth synthetic terrain the flooded area never shrinks.
        dem = generate_synthetic_dem(seed=0)
        _, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        assert is_monotonic_non_decreasing(percentages)


class TestMonotonicCheck:
    """The non-decreasing helper used to verify the dynamic simulation."""

    def test_increasing_values_are_monotonic(self):
        assert is_monotonic_non_decreasing([0.0, 1.0, 2.5, 2.5, 9.0])

    def test_constant_values_are_monotonic(self):
        # Non-decreasing allows flat plateaus, not just strict increases.
        assert is_monotonic_non_decreasing([3.0, 3.0, 3.0])

    def test_a_dip_is_not_monotonic(self):
        # A single step downward makes the sequence non-monotonic.
        assert not is_monotonic_non_decreasing([0.0, 5.0, 4.9, 6.0])


# ===========================================================================
# ANIMATION TESTS
# ===========================================================================

class TestFloodGif:
    """Animated GIF built from the dynamic-simulation results."""

    @pytest.fixture(autouse=True)
    def _close_figures(self):
        yield
        plt.close("all")

    def test_creates_a_gif_file(self, tmp_path):
        # The saved file exists and starts with the GIF magic bytes.
        dem = generate_synthetic_dem(seed=0)
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        path = tmp_path / "anim.gif"
        create_flood_gif(dem, levels, percentages, path=str(path), fps=2)
        assert path.exists()
        assert path.read_bytes()[:3] == b"GIF"

    def test_one_frame_per_simulation_level(self, tmp_path):
        # Reusing the simulation's levels yields exactly one frame per level.
        from PIL import Image

        dem = generate_synthetic_dem(seed=0)
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        path = tmp_path / "anim.gif"
        create_flood_gif(dem, levels, percentages, path=str(path), fps=2)
        with Image.open(str(path)) as img:
            assert img.n_frames == len(levels)

    def test_fps_sets_frame_duration(self, tmp_path):
        # fps is configurable: 4 fps -> 250 ms per frame in the GIF metadata.
        from PIL import Image

        dem = generate_synthetic_dem(seed=0)
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        path = tmp_path / "anim.gif"
        create_flood_gif(dem, levels, percentages, path=str(path), fps=4)
        with Image.open(str(path)) as img:
            assert img.info["duration"] == pytest.approx(250, abs=1)

    def test_returns_saved_path(self, tmp_path):
        # The function returns the path it wrote to, for convenience.
        dem = generate_synthetic_dem(seed=0)
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        path = tmp_path / "anim.gif"
        result = create_flood_gif(dem, levels, percentages, path=str(path), fps=2)
        assert result == str(path)

    def test_animation_figure_has_building_legend(self):
        # The GIF frames carry the same building-barrier legend as the plots.
        from flood_inundation import _build_flood_figure

        dem = add_buildings(generate_synthetic_dem(seed=0), [(10, 10, 8, 12)])
        levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
        fig, _ = _build_flood_figure(dem, levels, percentages,
                                     annotate=True, barrier_height=100.0)
        legend = fig.axes[0].get_legend()
        assert legend is not None
        labels = [t.get_text() for t in legend.get_texts()]
        assert any("Building" in label for label in labels)
