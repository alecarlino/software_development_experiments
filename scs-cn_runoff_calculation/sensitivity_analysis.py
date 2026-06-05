"""Sensitivity analysis and visualisation for the SCS-CN module.

Builds four plots from the functions in ``scscn_runoff``:

1. SCS-CN runoff Q vs rainfall P for several curve numbers, saved as
   ``runoff_comparison.png``.
2. SCS-CN runoff Q vs curve number CN at a fixed rainfall depth.
3. SCS-CN vs the Rational method on a shared rainfall axis (both as depth).
4. An interactive SCS-CN plot with sliders for P and CN.

Run as ``python sensitivity_analysis.py`` to generate all four and open them
in Matplotlib windows.
"""

from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.widgets import Slider

from scscn_runoff import calculate_runoff, rational_runoff


# ===========================================================================
# PLOTS
# ===========================================================================

def plot_cn_comparison(
    cn_values: Sequence[int] = (60, 70, 80, 90, 95, 100),
    p_max: float = 200.0,
    n_points: int = 200,
    save_path: str = "runoff_comparison.png",
) -> Figure:
    """Plot SCS-CN runoff Q vs rainfall P for several curve numbers.

    Draws one line per CN in ``cn_values`` over ``n_points`` rainfall samples
    in [0, ``p_max``], writes the figure to ``save_path`` and returns it. This
    is the project's required ``runoff_comparison.png`` deliverable.
    """
    # Sample rainfall uniformly over [0, p_max].
    P = np.linspace(0, p_max, n_points)

    fig, ax = plt.subplots(figsize=(8, 5))
    # One line per CN; calculate_runoff is scalar, so we map it over P.
    for cn in cn_values:
        Q = [calculate_runoff(p, cn) for p in P]
        ax.plot(P, Q, label=f"CN = {cn}")

    ax.set_xlabel("Rainfall P (mm)")
    ax.set_ylabel("Runoff Q (mm)")
    ax.set_title("SCS-CN runoff vs rainfall for several curve numbers")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    return fig


def plot_cn_vs_q_at_fixed_p(
    p_fixed: float = 50.0,
    cn_values: Sequence[int] = (60, 70, 80, 90, 95, 100),
    save_path: str | None = None,
) -> Figure:
    """Plot SCS-CN runoff Q against CN at a fixed rainfall depth ``p_fixed``.

    Evaluates Q at each CN in ``cn_values`` and draws the single sensitivity
    line. Writes the figure to ``save_path`` when given, and returns it.
    """
    # Evaluate Q at the fixed P for each CN; produces a single Q-vs-CN line.
    Q = [calculate_runoff(p_fixed, cn) for cn in cn_values]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(cn_values, Q, marker="o")
    ax.set_xlabel("Curve Number CN")
    ax.set_ylabel("Runoff Q (mm)")
    ax.set_title(f"SCS-CN sensitivity: Q vs CN at P = {p_fixed:.0f} mm")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=150)
    return fig


def plot_methods_comparison(
    pairs: Sequence[tuple[int, float]] = ((60, 0.3), (75, 0.5), (90, 0.7)),
    p_max: float = 200.0,
    n_points: int = 200,
    save_path: str | None = None,
) -> Figure:
    """Compare SCS-CN and Rational runoff depth on a shared rainfall axis.

    Each ``(CN, C)`` pair in ``pairs`` draws an SCS-CN curve (solid) and a
    Rational curve (dashed) in matching colours, over ``n_points`` samples in
    [0, ``p_max``]. Duration is fixed at 1 h so the Rational depth collapses to
    ``C * P``. Writes the figure to ``save_path`` when given, and returns it.
    """
    # Fix duration = 1 h so total rainfall (mm) equals intensity (mm/h);
    # the Rational depth then collapses to C * P (linear in rainfall).
    duration = 1.0
    P = np.linspace(0, p_max, n_points)

    fig, ax = plt.subplots(figsize=(8, 5))
    for cn, C in pairs:
        # SCS-CN depth: nonlinear in P, drawn solid.
        Q_scscn = [calculate_runoff(p, cn) for p in P]
        line, = ax.plot(P, Q_scscn, label=f"SCS-CN (CN={cn})")
        # Rational depth: linear in P, drawn dashed in the matching color
        # so each (CN, C) pair is visually grouped. Treat P as intensity
        # (mm/h) since duration = 1 h makes the two numerically identical.
        Q_rational = [rational_runoff(C, p, duration) for p in P]
        ax.plot(
            P,
            Q_rational,
            linestyle="--",
            color=line.get_color(),
            label=f"Rational (C={C})",
        )

    ax.set_xlabel("Rainfall P (mm)")
    ax.set_ylabel("Runoff depth Q (mm)")
    ax.set_title("SCS-CN vs Rational method (depth, same total rainfall)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    if save_path is not None:
        fig.savefig(save_path, dpi=150)
    return fig


def plot_interactive(
    p_init: float = 50.0,
    cn_init: float = 75.0,
    p_max: float = 200.0,
    n_points: int = 200,
) -> Figure:
    """Build an interactive SCS-CN plot with P and CN sliders.

    Draws Q(P) at ``cn_init`` with a red marker at ``p_init``, plus two sliders
    that recompute the curve and marker on every change. The slider widgets are
    attached as ``fig._sliders`` so they stay alive after the function returns.
    Returns the figure.
    """
    # Static sample of P; the Q values are recomputed on every slider change.
    P = np.linspace(0, p_max, n_points)

    fig, ax = plt.subplots(figsize=(8, 6))
    # Leave space at the bottom for the two slider rows.
    fig.subplots_adjust(bottom=0.25)

    # Initial curve Q(P) at cn_init and a red marker at the (P, Q) of p_init.
    Q = [calculate_runoff(p, cn_init) for p in P]
    line, = ax.plot(P, Q, label=f"CN = {cn_init:.0f}")
    marker, = ax.plot(
        [p_init], [calculate_runoff(p_init, cn_init)], "ro", markersize=8
    )

    ax.set_xlim(0, p_max)
    ax.set_ylim(0, p_max)
    ax.set_xlabel("Rainfall P (mm)")
    ax.set_ylabel("Runoff Q (mm)")
    ax.set_title("Interactive SCS-CN runoff")
    ax.grid(True, alpha=0.3)
    legend = ax.legend(loc="upper left")

    # Two horizontal slider axes below the main plot.
    ax_p = fig.add_axes([0.15, 0.10, 0.7, 0.03])
    ax_cn = fig.add_axes([0.15, 0.05, 0.7, 0.03])
    slider_p = Slider(ax_p, "P (mm)", 0.0, p_max, valinit=p_init)
    slider_cn = Slider(ax_cn, "CN", 0.0, 100.0, valinit=cn_init)

    def update(_val: float) -> None:
        # Pull the current slider values, recompute the curve and marker.
        cn = slider_cn.val
        p = slider_p.val
        line.set_ydata([calculate_runoff(pp, cn) for pp in P])
        marker.set_data([p], [calculate_runoff(p, cn)])
        legend.get_texts()[0].set_text(f"CN = {cn:.0f}")
        fig.canvas.draw_idle()

    slider_p.on_changed(update)
    slider_cn.on_changed(update)

    # Keep the slider widgets reachable so they don't get garbage-collected.
    fig._sliders = (slider_p, slider_cn)
    return fig


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def main() -> None:
    """Generate all four plots and open them in Matplotlib windows."""
    plot_cn_comparison()
    plot_cn_vs_q_at_fixed_p()
    plot_methods_comparison()
    plot_interactive()
    plt.show()


if __name__ == "__main__":
    main()
