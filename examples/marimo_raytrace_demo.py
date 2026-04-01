import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def intro():
    import marimo as mo

    mo.md(
        """
        # Optiverse Ray Optics Demo

        Interactive 2D ray tracing using the
        [Optiverse](https://github.com/QPG-MIT/optiverse) engine.

        **What you can do:**
        - Adjust lens focal length and watch rays converge / diverge
        - Change the number of rays to see beam structure
        - See reflection off a flat mirror
        """
    )
    return (mo,)


@app.cell
def controls(mo):
    focal_length = mo.ui.slider(
        start=50, stop=300, step=10, value=100, label="Focal length (mm)"
    )
    n_rays = mo.ui.slider(
        start=3, stop=15, step=2, value=9, label="Number of rays"
    )
    beam_size = mo.ui.slider(
        start=5, stop=40, step=5, value=20, label="Beam size (mm)"
    )

    mo.md(
        f"""
        ## Optical Setup

        {focal_length}
        {n_rays}
        {beam_size}
        """
    )
    return (beam_size, focal_length, n_rays)


@app.cell
def trace_and_plot(mo, focal_length, n_rays, beam_size):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from optiverse.raytracing.elements.lens import LensElement
    from optiverse.raytracing.elements.mirror import MirrorElement
    from optiverse.raytracing.engine import trace_rays_polymorphic
    from optiverse.core.models import SourceParams

    # ---- Build optical elements ----
    lens_half = 30.0  # half-height of lens element (mm)
    lens = LensElement(
        p1=np.array([0.0, -lens_half]),
        p2=np.array([0.0, lens_half]),
        efl_mm=float(focal_length.value),
    )

    mirror_half = 30.0
    mirror = MirrorElement(
        p1=np.array([250.0, -mirror_half]),
        p2=np.array([250.0, mirror_half]),
        reflectivity=1.0,
    )

    elements = [lens, mirror]

    # ---- Light source ----
    source = SourceParams(
        x_mm=-200.0,
        y_mm=0.0,
        angle_deg=0.0,
        size_mm=float(beam_size.value),
        n_rays=int(n_rays.value),
        ray_length_mm=800.0,
        spread_deg=0.0,
        color_hex="#DC143C",
        wavelength_nm=633.0,
    )

    # ---- Trace ----
    paths = trace_rays_polymorphic(elements, [source], parallel=False)

    # ---- Plot ----
    fig, ax = plt.subplots(figsize=(10, 5))

    # Draw elements
    ax.plot([0, 0], [-lens_half, lens_half], "b-", linewidth=3,
            label=f"Lens (f={focal_length.value} mm)")
    ax.plot([250, 250], [-mirror_half, mirror_half], "k-", linewidth=4,
            label="Mirror")

    # Draw rays
    for path in paths:
        xs = [float(p[0]) for p in path.points]
        ys = [float(p[1]) for p in path.points]
        r, g, b, a = path.rgba
        ax.plot(xs, ys, color=(r / 255, g / 255, b / 255, a / 255),
                linewidth=0.8)

    # Source marker
    ax.plot(-200, 0, "r*", markersize=12, label="Source")

    # Focal point marker
    ax.axvline(x=float(focal_length.value), color="blue", linestyle=":",
               alpha=0.4, label=f"Focal plane (x={focal_length.value})")

    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title("2D Ray Trace: Lens + Mirror")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    mo.mpl.interactive(fig)
    return (paths,)


@app.cell
def summary(mo, paths):
    n_paths = len(paths)
    total_points = sum(len(p.points) for p in paths)
    mo.md(
        f"""
        ## Trace Summary

        | Metric | Value |
        |--------|-------|
        | Ray paths | {n_paths} |
        | Total vertices | {total_points} |
        | Wavelength | 633 nm (HeNe) |
        """
    )
    return


if __name__ == "__main__":
    app.run()
