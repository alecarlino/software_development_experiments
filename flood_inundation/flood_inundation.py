"""Smart Water Lab - Flood Inundation Analysis (DEM-based).

Maps flood inundation over a Digital Elevation Model (DEM): which cells go
underwater at a given water level, how deep, and what fraction of the terrain
floods. Running the module executes, in order:

* Generate a synthetic 100x100 DEM (diagonal slope + Gaussian noise) and burn in
  three building footprints as barriers, then save it to dem_data.npy.
* Save the deliverable figures: flood extent at 40 m and 50 m, and the
  flooded-area curve over the 30-80 m range.
* Dynamic simulation: sweep the water level from 40 m to 50 m and verify the
  flooded area grows monotonically, documenting any anomaly.
* Build an animated GIF of rising water levels from the same sweep.

The flooding model is bathtub inundation (mask, depth, percentage) plus
connected-component flood routing from a source; building cells are raised above
any sensible water level so they act as impermeable barriers. A real DEM can be
loaded from an Esri ASCII Grid (.asc) or NumPy (.npy) file instead.

Outputs: dem_data.npy, flood_extent_40m.png, flood_extent_50m.png,
flood_curve.png and flood_animation.gif in the working directory.
"""

from collections import deque

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import ArtistAnimation, PillowWriter
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch


# ===========================================================================
# DEM GENERATION & LOADING
# ===========================================================================

def generate_synthetic_dem(size=100, low=30.0, high=80.0, seed=None):
    """Generate a synthetic ``size`` x ``size`` DEM with coherent terrain.

    The terrain is a smooth diagonal slope spanning the elevation range plus
    mild Gaussian noise, clamped to ``[low, high]`` (metres). The slope gives
    spatially coherent terrain so that flooding fills the low areas in a
    realistic, contiguous way (pure per-cell noise would not).

    Args:
        size: Side length of the square grid (number of cells).
        low: Minimum elevation in metres.
        high: Maximum elevation in metres.
        seed: Optional seed for reproducible terrain.

    Returns:
        A ``(size, size)`` float64 array of elevations in ``[low, high]``.
    """
    rng = np.random.default_rng(seed)

    # Smooth diagonal slope from `low` (top-left) to `high` (bottom-right).
    axis = np.linspace(0.0, 1.0, size)
    gradient = (axis[:, None] + axis[None, :]) / 2.0
    slope = low + gradient * (high - low)

    # Mild noise relative to the elevation span for local terrain variation.
    noise = rng.normal(0.0, (high - low) * 0.05, size=(size, size))

    dem = slope + noise
    return np.clip(dem, low, high)


def _read_esri_ascii(path):
    """Read an Esri ASCII Grid (.asc) into a 2D float array.

    Parses the leading ``key value`` header lines (ncols, nrows, cellsize,
    NODATA_value, ...) then the elevation grid, mapping NODATA cells to NaN.
    """
    with open(path) as f:
        lines = f.readlines()

    header = {}
    data_start = 0
    for i, line in enumerate(lines):
        parts = line.split()
        if parts and parts[0][0].isalpha():
            header[parts[0].lower()] = parts[1]
        else:
            data_start = i
            break

    grid = np.loadtxt(lines[data_start:], dtype=np.float64)
    nodata = header.get("nodata_value")
    if nodata is not None:
        grid = np.where(grid == float(nodata), np.nan, grid)
    return grid


def load_real_dem(path="dem/dem_data.asc"):
    """Load a real DEM from an Esri ASCII Grid (.asc) or NumPy (.npy) file.

    Real DEM data (e.g. USGS Earth Explorer SRTM or OpenTopography ALOS
    PALSAR) is typically distributed as GeoTIFF. To use it here without a
    GeoTIFF reader, export the raster to Esri ASCII Grid (``.asc``) and place
    it at ``dem/dem_data.asc``; that text format keeps the header metadata
    (cell size, origin, nodata) using only NumPy to read it. A 2D ``.npy``
    array is also accepted.

    Args:
        path: Path to the ``.asc`` or ``.npy`` file
            (default: ``dem/dem_data.asc``).

    Returns:
        The DEM as a 2D float64 array (NODATA cells become NaN).

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the stored DEM is not 2D.
    """
    if path.endswith(".asc"):
        dem = _read_esri_ascii(path)
    else:
        dem = np.load(path)
    if dem.ndim != 2:
        raise ValueError(f"DEM must be a 2D grid, got {dem.ndim} dimensions")
    return dem.astype(np.float64)


# ===========================================================================
# BUILDING BARRIERS
# ===========================================================================

def add_buildings(dem, footprints, barrier_height=100.0):
    """Burn rectangular building footprints into the DEM as flood barriers.

    Each footprint is a ``(row, col, n_rows, n_cols)`` rectangle whose cells
    are raised to ``barrier_height`` (well above the terrain). Because flooding
    is defined as ``elevation < water_level``, those raised cells stay dry at
    any sensible water level, so the buildings act as impermeable barriers.
    Building cells can be recovered later as ``dem >= barrier_height``.

    Args:
        dem: 2D elevation array (not modified).
        footprints: Iterable of ``(row, col, n_rows, n_cols)`` rectangles.
        barrier_height: Elevation in metres assigned to building cells.

    Returns:
        A new DEM array with the footprints raised to ``barrier_height``.
    """
    out = dem.copy()
    for row, col, n_rows, n_cols in footprints:
        out[row:row + n_rows, col:col + n_cols] = barrier_height
    return out


# ===========================================================================
# FLOOD CALCULATIONS
# ===========================================================================

def flood_mask(dem, water_level):
    """Boolean mask of flooded cells: ``True`` where ``elevation < water_level``.

    Buildings (raised to a barrier height) and other high terrain stay ``False``.
    """
    return dem < water_level


def inundation_depth(dem, water_level):
    """Inundation depth per cell: ``water_level - elevation`` where flooded, else 0."""
    return np.where(dem < water_level, water_level - dem, 0.0)


def flooded_percentage(mask):
    """Percentage of cells that are flooded (flooded cells / total cells x 100)."""
    return float(mask.sum()) / mask.size * 100.0


def flood_volume(depth, cell_area=1.0):
    """Total flood volume = sum of inundation depths x cell area.

    Summing the per-cell depths already accounts for the number of flooded
    cells (dry cells contribute 0), so this equals
    ``mean_depth x cell_area x flooded_count``; for a uniform depth it reduces
    to the literal ``depth x cell_area x count``.

    Args:
        depth: Per-cell inundation depth array (e.g. from ``inundation_depth``).
        cell_area: Ground area of one cell in m^2 (e.g. 900 for a 30 m DEM).

    Returns:
        Flood volume in depth-units x area-units (m^3 if depth is metres).
    """
    return float(depth.sum()) * cell_area


# ===========================================================================
# FLOOD MODELS
# ===========================================================================

def simulate_flood(dem, water_level):
    """Bathtub flooding at ``water_level``.

    Floods every cell below the water level, regardless of connectivity.

    Returns:
        Tuple ``(mask, depth, percentage)`` where ``mask`` is the boolean
        flooded mask, ``depth`` the per-cell inundation depth, and
        ``percentage`` the flooded area percentage.
    """
    mask = flood_mask(dem, water_level)
    depth = inundation_depth(dem, water_level)
    percentage = flooded_percentage(mask)
    return mask, depth, percentage


def flood_routing(dem, water_level, source):
    """Connected-component flooding spreading from a source cell.

    Unlike the bathtub model, a cell floods only if it is below ``water_level``
    *and* reachable from ``source`` through other flooded cells, using
    4-connectivity. High terrain and building barriers (cells not below the
    water level) block the spread, so isolated low pockets stay dry.

    Args:
        dem: 2D elevation array.
        water_level: Flood water level in metres.
        source: ``(row, col)`` seed cell where flooding starts.

    Returns:
        Boolean mask of the cells reached by the flood from ``source``.
    """
    floodable = dem < water_level
    mask = np.zeros(dem.shape, dtype=bool)
    rows, cols = dem.shape
    sr, sc = source
    if not floodable[sr, sc]:
        return mask

    mask[sr, sc] = True
    queue = deque([(sr, sc)])
    while queue:
        r, c = queue.popleft()
        for nr, nc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= nr < rows and 0 <= nc < cols and floodable[nr, nc] and not mask[nr, nc]:
                mask[nr, nc] = True
                queue.append((nr, nc))
    return mask


# ===========================================================================
# DYNAMIC SIMULATION
# ===========================================================================

def simulate_dynamic_flood(dem, start=40.0, stop=50.0, step=1.0):
    """Sweep the water level and report the flooded area at each step.

    Loops over water levels from ``start`` to ``stop`` (inclusive) in ``step``
    increments and computes the flooded-area percentage at each one.

    Returns:
        Tuple ``(levels, percentages)`` of 1D arrays, one entry per level.
    """
    levels = np.arange(start, stop + step / 2.0, step)
    percentages = np.array([flooded_percentage(flood_mask(dem, level))
                            for level in levels])
    return levels, percentages


def is_monotonic_non_decreasing(values):
    """True if ``values`` never decrease from one element to the next.

    Flooded area should only grow as the water level rises, so a ``False``
    here flags unexpected behaviour (a non-monotonic dip).
    """
    return bool(np.all(np.diff(values) >= 0))


# ===========================================================================
# VISUALISATION
# ===========================================================================

_FLOOD_BLUE = ListedColormap(["#1f77b4"])  # solid blue for flood overlays
_BUILDING_HEX = "#8c564b"  # brown for building barriers
_BUILDING_BROWN = ListedColormap([_BUILDING_HEX])


def _overlay_buildings(ax, dem, barrier_height):
    """Draw the building barriers (dem >= barrier_height) in a distinct colour."""
    buildings = dem >= barrier_height
    layer = np.ma.masked_where(~buildings, np.ones_like(dem))
    ax.imshow(layer, cmap=_BUILDING_BROWN, vmin=0, vmax=1)


_FLOOD_LEGEND = Patch(facecolor="#1f77b4", alpha=0.5, label="Flooded")
_BUILDING_LEGEND = Patch(facecolor=_BUILDING_HEX, label="Building (barrier)")


def plot_dem(dem, title="Digital Elevation Model"):
    """Show the DEM as a grayscale image with an elevation colorbar."""
    fig, ax = plt.subplots()
    image = ax.imshow(dem, cmap="gray")
    fig.colorbar(image, ax=ax, label="Elevation (m)")
    ax.set_title(title)
    return fig


def plot_flood_extent(dem, water_level, title=None, barrier_height=100.0):
    """Show the terrain in grayscale with the flooded cells as a blue overlay."""
    mask = flood_mask(dem, water_level)
    fig, ax = plt.subplots()
    image = ax.imshow(dem, cmap="gray")
    fig.colorbar(image, ax=ax, label="Elevation (m)")
    # Mask out the dry cells so only the flooded ones get the blue overlay.
    flooded = np.ma.masked_where(~mask, np.ones_like(dem))
    ax.imshow(flooded, cmap=_FLOOD_BLUE, alpha=0.5, vmin=0, vmax=1)
    _overlay_buildings(ax, dem, barrier_height)
    ax.legend(handles=[_FLOOD_LEGEND, _BUILDING_LEGEND],
              loc="upper right", fontsize="small")
    pct = flooded_percentage(mask)
    ax.set_title(title or f"Flood extent at {water_level:g} m ({pct:.1f}%)")
    return fig


def plot_inundation_depth(dem, water_level, title=None):
    """Show the inundation depth as a blue heatmap (dry cells left blank)."""
    depth = inundation_depth(dem, water_level)
    masked = np.ma.masked_where(depth <= 0, depth)
    fig, ax = plt.subplots()
    image = ax.imshow(masked, cmap="Blues")
    fig.colorbar(image, ax=ax, label="Depth (m)")
    ax.set_title(title or f"Inundation depth at {water_level:g} m")
    return fig


def plot_water_level_comparison(dem, water_levels, barrier_height=100.0):
    """Show flood extent side by side for several water levels."""
    fig, axes = plt.subplots(1, len(water_levels),
                             figsize=(4 * len(water_levels), 4))
    axes = np.atleast_1d(axes)
    for ax, level in zip(axes, water_levels):
        mask = flood_mask(dem, level)
        ax.imshow(dem, cmap="gray")
        flooded = np.ma.masked_where(~mask, np.ones_like(dem))
        ax.imshow(flooded, cmap=_FLOOD_BLUE, alpha=0.5, vmin=0, vmax=1)
        _overlay_buildings(ax, dem, barrier_height)
        ax.set_title(f"{level:g} m ({flooded_percentage(mask):.1f}%)")
    fig.suptitle("Flood inundation at different water levels")
    fig.legend(handles=[_FLOOD_LEGEND, _BUILDING_LEGEND],
               loc="lower center", ncol=2)
    return fig


def plot_flood_curve(dem, water_levels):
    """Plot flooded area percentage as a function of water level."""
    percentages = [flooded_percentage(flood_mask(dem, level))
                   for level in water_levels]
    fig, ax = plt.subplots()
    ax.plot(water_levels, percentages, marker="o")
    ax.set_xlabel("Water level (m)")
    ax.set_ylabel("Flooded area (%)")
    ax.set_title("Flooded area vs. water level")
    ax.grid(True)
    return fig


# ===========================================================================
# ANIMATION
# ===========================================================================

def _build_flood_figure(dem, levels, percentages, annotate, barrier_height):
    """Build the figure and per-frame artist lists for the flood animation.

    Returns ``(fig, frames)``; the caller turns ``frames`` into an animation.
    """
    fig, ax = plt.subplots()
    terrain = ax.imshow(dem, cmap="gray")  # static terrain background, shown every frame
    fig.colorbar(terrain, ax=ax, label="Elevation (m)")
    _overlay_buildings(ax, dem, barrier_height)  # static building barriers
    ax.legend(handles=[_FLOOD_LEGEND, _BUILDING_LEGEND],
              loc="upper right", fontsize="small")
    ax.set_title("Rising water levels")

    frames = []
    for i, level in enumerate(levels):
        mask = flood_mask(dem, level)
        flooded = np.ma.masked_where(~mask, np.ones_like(dem))
        overlay = ax.imshow(flooded, cmap=_FLOOD_BLUE, alpha=0.5,
                            vmin=0, vmax=1, animated=True)
        artists = [overlay]
        if annotate:
            pct = percentages[i] if percentages is not None else \
                flooded_percentage(mask)
            label = ax.text(0.02, 0.98, f"{level:g} m - {pct:.1f}%",
                            transform=ax.transAxes, va="top", ha="left",
                            color="white",
                            bbox={"facecolor": "black", "alpha": 0.5})
            artists.append(label)
        frames.append(artists)

    return fig, frames


def create_flood_gif(dem, levels, percentages=None, path="flood_animation.gif",
                     fps=2, annotate=True, barrier_height=100.0):
    """Build an animated GIF of rising water levels and save it to disk.

    Reuses the ``levels`` and ``percentages`` already produced by
    ``simulate_dynamic_flood`` (the percentages are used for the per-frame
    annotation, not recomputed). Each frame is the DEM in grayscale with a blue
    overlay on the cells flooded at that level; the building barriers are drawn
    in brown with a legend that stays on every frame.

    Args:
        dem: 2D elevation array.
        levels: Water levels to animate, one frame each.
        percentages: Flooded-area percentage per level (for annotation); if
            ``None`` and ``annotate`` is set, it is computed per frame.
        path: Output GIF path.
        fps: Frames per second of the animation.
        annotate: Whether to label each frame with its level and percentage.
        barrier_height: Elevation at/above which cells are drawn as buildings.

    Returns:
        The ``path`` the GIF was written to.
    """
    fig, frames = _build_flood_figure(dem, levels, percentages, annotate,
                                      barrier_height)
    animation = ArtistAnimation(fig, frames, interval=1000.0 / fps, blit=False)
    animation.save(path, writer=PillowWriter(fps=fps))
    plt.close(fig)
    return path


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def main():
    """Run the full pipeline: build the DEM, save the figures, sweep, animate."""
    # ------------------------------------------------------------------
    # DEM GENERATION (synthetic terrain + building barriers)
    # ------------------------------------------------------------------
    # Real DEMs live in dem/; the synthetic one is saved here in the root.
    dem = generate_synthetic_dem(seed=0)

    # Burn a few building footprints into the low ground as flood barriers.
    buildings = [(10, 10, 8, 12), (25, 40, 15, 10), (60, 20, 10, 20)]
    dem = add_buildings(dem, buildings)

    np.save("dem_data.npy", dem)
    print(f"Saved dem_data.npy: shape={dem.shape}, "
          f"min={dem.min():.2f}m, max={dem.max():.2f}m, "
          f"buildings={len(buildings)}")

    # ------------------------------------------------------------------
    # DELIVERABLE FIGURES (flood extent at 40 m / 50 m, flooded-area curve)
    # ------------------------------------------------------------------
    plot_flood_extent(dem, 40).savefig("flood_extent_40m.png", dpi=150)
    plot_flood_extent(dem, 50).savefig("flood_extent_50m.png", dpi=150)
    plot_flood_curve(dem, np.arange(30, 81, 1)).savefig("flood_curve.png", dpi=150)
    print("Saved flood_extent_40m.png, flood_extent_50m.png, flood_curve.png")

    # ------------------------------------------------------------------
    # DYNAMIC SIMULATION (sweep 40 m -> 50 m, monotonicity check)
    # ------------------------------------------------------------------
    levels, percentages = simulate_dynamic_flood(dem, 40, 50, 1)
    print("Dynamic simulation (40 m -> 50 m):")
    for level, pct in zip(levels, percentages):
        print(f"  {level:5.1f} m -> {pct:6.2f}%")
    if is_monotonic_non_decreasing(percentages):
        print("  OK: flooded area increases monotonically.")
    else:
        # Should not happen on a smooth DEM; a dip could come from NaN/nodata
        # cells or a step so coarse it skips terrain detail.
        drops = [(levels[i], levels[i + 1])
                 for i in np.where(np.diff(percentages) < 0)[0]]
        print(f"  WARNING: non-monotonic steps detected between {drops}")

    # ------------------------------------------------------------------
    # ANIMATED GIF (rising water levels, reusing the sweep results)
    # ------------------------------------------------------------------
    create_flood_gif(dem, levels, percentages, path="flood_animation.gif", fps=2)
    print("Saved flood_animation.gif")


if __name__ == "__main__":
    main()
