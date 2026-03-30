"""
Simplified raytracing engine using polymorphic elements.

This replaces the complex 358-line _trace_single_ray_worker function
with a clean, extensible 50-line implementation.

Features:
- Polymorphic element dispatch (no string-based type checking)
- Parallel processing support with ThreadPoolExecutor + Numba
- Clean, extensible architecture ready for BVH acceleration
"""

import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..core.color_utils import qcolor_from_hex
from ..core.gaussian_beam import (
    beam_radius_from_q,
    clip_gaussian_circular_aperture,
    propagate_free_space,
    q_from_waist,
    q_rescale_radius_preserve_curvature,
    rayleigh_range_from_q,
)
from ..core.models import SourceParams
from ..core.raytracing_math import NUMBA_AVAILABLE, deg2rad, ray_hit_element
from .elements.base import IOpticalElement, RayIntersection
from .ray import Ray, RayPath

_logger = logging.getLogger(__name__)

_GAUSSIAN_SUBSAMPLE_MAX = 200
_GAUSSIAN_ADAPT_REL_DW = 0.06  # extra subdivisions when |Δw|/max(w) exceeds this per segment


def _effective_half_aperture_mm(element: IOpticalElement, segment_length_mm: float) -> float:
    """Half-width for Gaussian clipping: segment half-length, optionally capped by clear aperture.

    The painted interface line spans the full segment; when the mount is larger than the
    clear optic, set ``clear_aperture_mm`` on the lens so trace clipping matches the glass.
    """
    half = 0.5 * float(segment_length_mm)
    iface = getattr(element, "interface", None)
    if iface is None:
        return half
    props = getattr(iface, "properties", None)
    if props is None:
        return half
    ca = float(getattr(props, "clear_aperture_mm", 0.0) or 0.0)
    if ca > 1e-12:
        return min(half, 0.5 * ca)
    return half


def _insert_gaussian_free_space_samples(
    ray: Ray,
    q_start: complex,
    distance_mm: float,
    end_point: np.ndarray,
    wavelength_nm: float,
) -> complex:
    """
    Append intermediate path vertices so the beam envelope follows hyperbolic w(z).

    Geometry follows the chord from the last path vertex to end_point; q advances
    along the optical path length ``distance_mm`` (chief-ray drift).
    """
    if distance_mm <= 1e-12:
        return q_start

    p0 = np.asarray(ray.path_points[-1], dtype=float)
    p_end = np.asarray(end_point, dtype=float)
    seg = p_end - p0

    wl = wavelength_nm
    q_final = propagate_free_space(q_start, distance_mm)
    w0 = beam_radius_from_q(q_start, wl)
    w1 = beam_radius_from_q(q_final, wl)

    z_R = rayleigh_range_from_q(q_start, wl)

    # When the beam waist falls inside this free-space segment, both endpoint
    # radii can be large while the beam focuses to a tiny waist in between.
    # The endpoint-only heuristics (z_R at start, dw between endpoints) miss
    # this completely, resulting in n≈1 and no visible focus.  Detect this
    # case and use the waist's Rayleigh range / radius for proper sampling.
    re_q0 = q_start.real
    z_waist = -re_q0
    if 0 < z_waist < distance_mm:
        z_R_waist = max(q_start.imag, 1e-12)
        z_R = min(z_R, z_R_waist)
        w_min = beam_radius_from_q(1j * q_start.imag, wl)
        dw = max(abs(w1 - w0), abs(w0 - w_min), abs(w1 - w_min))
    else:
        dw = abs(w1 - w0)

    step = min(distance_mm, max(5.0, z_R / 4.0))
    n = max(1, int(math.ceil(distance_mm / step)))

    w_ref = max(w0, w1, 1e-9)
    rel_dw = dw / w_ref
    if rel_dw > _GAUSSIAN_ADAPT_REL_DW:
        n = max(n, int(math.ceil(6.0 * rel_dw * max(8.0, distance_mm / max(step, 1e-6)))))
    if dw > 1e-12:
        n = max(n, int(math.ceil((dw / max(distance_mm, 1e-9)) * 80.0)))

    n = min(max(n, 1), _GAUSSIAN_SUBSAMPLE_MAX)

    for k in range(1, n):
        frac = k / n
        pt = p0 + seg * frac
        qk = propagate_free_space(q_start, frac * distance_mm)
        ray.path_points.append(pt.copy())
        ray.path_polarizations.append(ray.polarization)
        ray.path_intensities.append(ray.intensity)
        ray.path_beam_radii.append(beam_radius_from_q(qk, wl))

    return q_final


def trace_rays_polymorphic(
    elements: list[IOpticalElement],
    sources: list[SourceParams],
    max_events: int = 80,
    epsilon: float = 1e-3,
    min_intensity: float = 0.02,
    parallel: bool | None = None,
    parallel_threshold: int = 20,
) -> list[RayPath]:
    """
    Trace rays from sources through optical elements using polymorphism.

    This is the new, simplified raytracing engine that uses polymorphism
    instead of string-based type checking.

    Performance optimizations:
    - Uses Numba JIT compilation for geometry calculations (2-3x speedup)
    - Uses ThreadPoolExecutor for parallel ray tracing (2-4x speedup on multi-core CPUs)
    - Combined: 4-8x speedup on typical workloads

    Args:
        elements: List of optical elements implementing IOpticalElement
        sources: List of light sources (SourceParams objects)
        max_events: Maximum interactions per ray
        epsilon: Small distance to advance ray after interaction (prevents re-intersection)
        min_intensity: Minimum intensity threshold to continue tracing
        parallel: If True, use parallel processing. If None (default), automatically
                 enable only when Numba is available (required for GIL release).
                 If False, always use sequential processing.
        parallel_threshold: Minimum number of total rays to use parallelization.
                          Default is 20. Set to 1 to always parallelize.

    Returns:
        List of ray paths for visualization

    Complexity:
        - Before: O(6n) per ray (6 separate loops for pre-filtering)
        - After: O(n) per ray (single loop with polymorphism)
        - With BVH (Phase 4): O(log n) per ray

    Note:
        Parallel processing REQUIRES Numba to be effective. Without Numba, the Python
        GIL prevents true parallelism and threading overhead makes it slower.
    """
    # Auto-detect: only enable parallel if Numba is available
    if parallel is None:
        parallel = NUMBA_AVAILABLE
    if not NUMBA_AVAILABLE and parallel:
        _logger.debug("Parallel processing disabled (Numba not available)")
        parallel = False

    # Build ray job list with source index for linking rays to sources
    ray_jobs: list[tuple[Ray, list[IOpticalElement], int, float, float, SourceParams, int]] = []
    for source_index, source in enumerate(sources):
        initial_rays = _generate_rays_from_source(source)
        for ray in initial_rays:
            ray_jobs.append(
                (ray, elements, max_events, epsilon, min_intensity, source, source_index)
            )

    # Decide whether to use parallel processing
    total_rays = len(ray_jobs)
    use_parallel = parallel and total_rays >= parallel_threshold

    if use_parallel:
        # Use parallel processing with threading
        # Threading works well here because:
        # 1. Numba JIT-compiled functions release the GIL
        # 2. NumPy operations release the GIL
        # 3. Much lower overhead than multiprocessing
        try:
            num_workers = os.cpu_count() or 4

            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                results = executor.map(_trace_single_ray_worker, ray_jobs)

            # Flatten results
            paths: list[RayPath] = []
            for ray_paths in results:
                paths.extend(ray_paths)

            return paths
        except Exception as e:
            # If parallel processing fails, fall back to sequential
            _logger.warning(
                "Parallel raytracing failed (%s), falling back to sequential processing", e
            )
            use_parallel = False

    # Sequential processing (fallback or when parallel disabled)
    paths = []
    for job in ray_jobs:
        ray_paths = _trace_single_ray_worker(job)
        paths.extend(ray_paths)

    return paths


def _trace_single_ray_worker(
    args: tuple[Ray, list[IOpticalElement], int, float, float, SourceParams, int],
) -> list[RayPath]:
    """
    Worker function for parallel ray tracing. Must be at module level for ThreadPoolExecutor.

    Args:
        args: Tuple containing (ray, elements, max_events, epsilon, min_intensity,
              source, source_index)

    Returns:
        List of RayPath objects generated by tracing this single ray
    """
    ray, elements, max_events, epsilon, min_intensity, source, source_index = args
    return _trace_single_ray(
        ray, elements, max_events, epsilon, min_intensity, source, source_index
    )


def _generate_rays_from_source(source: SourceParams) -> list[Ray]:
    """
    Generate initial rays from a source configuration.

    Args:
        source: SourceParams object

    Returns:
        List of Ray objects
    """
    base = -deg2rad(source.angle_deg)  # Convert user (CW) to math (CCW) convention
    spread = deg2rad(source.spread_deg)

    is_gaussian = source.source_type == "gaussian"

    # Gaussian beams emit a single ray on the optical axis — the beam
    # envelope replaces the concept of multiple discrete rays.
    if is_gaussian:
        y_offsets = [0.0]
        angles = [base]
    else:
        if source.n_rays <= 1 or source.size_mm == 0:
            y_offsets = [0.0]
        else:
            y_offsets = list(
                np.linspace(-source.size_mm / 2, source.size_mm / 2, source.n_rays)
            )

        if spread == 0 or source.n_rays <= 1:
            angles = [base] * len(y_offsets)
        else:
            fan = np.linspace(-spread, +spread, len(y_offsets))
            angles = [base + a for a in fan]

    # Get initial polarization
    initial_polarization = source.get_polarization()

    # Get color from source
    src_col = qcolor_from_hex(source.color_hex)
    base_rgb = (src_col.red(), src_col.green(), src_col.blue())

    # Gaussian beam q-parameter (None for geometric rays)
    initial_q: complex | None = None
    initial_beam_radius = 0.0
    if is_gaussian and source.beam_waist_mm > 0:
        initial_q = q_from_waist(source.beam_waist_mm, source.wavelength_nm)
        initial_beam_radius = source.beam_waist_mm

    # Create rays
    rays = []
    for i, y_offset in enumerate(y_offsets):
        angle = angles[i]
        direction = np.array([math.cos(angle), math.sin(angle)], dtype=float)
        perpendicular = np.array([-math.sin(angle), math.cos(angle)], dtype=float)
        position = np.array([source.x_mm, source.y_mm], dtype=float) + y_offset * perpendicular

        ray = Ray(
            position=position,
            direction=direction,
            remaining_length=source.ray_length_mm,
            polarization=initial_polarization,
            wavelength_nm=source.wavelength_nm,
            base_rgb=base_rgb,
            intensity=1.0,
            events=0,
            path_points=[position.copy()],
            path_polarizations=[initial_polarization],
            path_intensities=[1.0],
            q_parameter=initial_q,
            path_beam_radii=[initial_beam_radius] if initial_q is not None else [],
        )
        rays.append(ray)

    return rays


def _trace_single_ray(
    ray: Ray,
    elements: list[IOpticalElement],
    max_events: int,
    epsilon: float,
    min_intensity: float,
    source: SourceParams,
    source_index: int = 0,
) -> list[RayPath]:
    """
    Trace a single ray through elements.

    This is the core of the new architecture - clean and simple!
    No string-based dispatch, no pre-filtering, just pure polymorphism.

    Args:
        ray: Initial ray state
        elements: List of optical elements
        max_events: Maximum interactions
        epsilon: Small distance to advance after interaction
        min_intensity: Minimum intensity to continue
        source: Source parameters (for color/wavelength info)
        source_index: Index of the source for linking rays to z-order

    Returns:
        List of RayPath objects (can be multiple due to beamsplitters)
    """
    paths = []
    base_rgb = ray.base_rgb

    # Stack for ray processing (enables beam splitting)
    # Each stack item is a Ray object
    stack = [ray]
    last_element_for_ray: dict[int, IOpticalElement] = (
        {}
    )  # Track last interacted element to prevent re-intersection (keyed by ray id)

    while stack:
        current_ray = stack.pop()

        # Check termination conditions
        if (
            current_ray.events >= max_events
            or current_ray.intensity < min_intensity
            or current_ray.remaining_length <= 0
        ):
            # Finalize this path
            if len(current_ray.path_points) >= 2:
                alpha = int(255 * max(0.0, min(1.0, current_ray.intensity)))
                paths.append(
                    RayPath(
                        points=current_ray.path_points,
                        rgba=(base_rgb[0], base_rgb[1], base_rgb[2], alpha),
                        polarization=current_ray.polarization,
                        wavelength_nm=current_ray.wavelength_nm,
                        source_index=source_index,
                        polarizations=current_ray.path_polarizations,
                        intensities=current_ray.path_intensities,
                        beam_radii=current_ray.path_beam_radii,
                    )
                )
            continue

        # Find nearest intersection
        # TODO Phase 4: Replace with BVH spatial index for O(log n)
        nearest_element: IOpticalElement | None = None
        nearest_distance = float("inf")
        nearest_intersection: RayIntersection | None = None
        last_elem = last_element_for_ray.get(id(current_ray))

        for element in elements:
            # Skip the last element this ray interacted with
            if element is last_elem:
                continue

            # Get geometry (may be LineSegment or CurvedSegment)
            geometry = getattr(element, "_geometry", None)

            if geometry is not None:
                # NEW: Support for curved surfaces!
                is_curved = getattr(geometry, "is_curved", False)

                if is_curved:
                    # Use curved intersection for curved surfaces
                    from ..core.raytracing_math import (
                        ray_hit_curved_element,
                    )

                    result = ray_hit_curved_element(
                        current_ray.position,
                        current_ray.direction,
                        geometry.get_center(),
                        geometry.get_radius(),
                        geometry.p1,
                        geometry.p2,
                    )
                else:
                    # Use flat intersection for flat surfaces
                    result = ray_hit_element(
                        current_ray.position, current_ray.direction, geometry.p1, geometry.p2
                    )
            else:
                # Fallback for elements without _geometry attribute (legacy)
                p1, p2 = element.get_geometry()
                result = ray_hit_element(current_ray.position, current_ray.direction, p1, p2)

            if result is not None:
                t, hit_point, tangent, normal, center, length = result
                distance = t

                # Check if within remaining ray length
                if distance * np.linalg.norm(current_ray.direction) > current_ray.remaining_length:
                    continue

                if (
                    distance < nearest_distance and distance > epsilon
                ):  # epsilon prevents immediate re-intersection
                    nearest_distance = distance
                    nearest_element = element
                    # Get the optical interface from the element
                    # Assuming elements have an 'interface' attribute from Phase 2
                    nearest_intersection = RayIntersection(
                        distance=distance,
                        point=hit_point,
                        tangent=tangent,
                        normal=normal,
                        center=center,
                        length=length,
                        interface=getattr(element, "interface", None),
                    )

        # No intersection - ray escapes
        if nearest_element is None:
            # Extend ray to remaining length
            final_point = (
                current_ray.position + current_ray.direction * current_ray.remaining_length
            )
            if current_ray.q_parameter is not None:
                q_start = current_ray.q_parameter
                q_final = _insert_gaussian_free_space_samples(
                    current_ray,
                    q_start,
                    current_ray.remaining_length,
                    final_point,
                    current_ray.wavelength_nm,
                )
                current_ray.q_parameter = q_final
            current_ray.path_points.append(final_point)
            current_ray.path_polarizations.append(current_ray.polarization)
            current_ray.path_intensities.append(current_ray.intensity)

            if current_ray.q_parameter is not None:
                current_ray.path_beam_radii.append(
                    beam_radius_from_q(current_ray.q_parameter, current_ray.wavelength_nm)
                )

            alpha = int(255 * max(0.0, min(1.0, current_ray.intensity)))
            paths.append(
                RayPath(
                    points=current_ray.path_points,
                    rgba=(base_rgb[0], base_rgb[1], base_rgb[2], alpha),
                    polarization=current_ray.polarization,
                    wavelength_nm=current_ray.wavelength_nm,
                    source_index=source_index,
                    polarizations=current_ray.path_polarizations,
                    intensities=current_ray.path_intensities,
                    beam_radii=current_ray.path_beam_radii,
                )
            )
            continue

        # Add intersection point to path before interaction
        if nearest_intersection is None:
            continue
        hit_pt = nearest_intersection.point
        half_aperture = _effective_half_aperture_mm(
            nearest_element, float(nearest_intersection.length)
        )

        # Propagate q along drift, subsample envelope, then record hit vertex
        if current_ray.q_parameter is not None:
            q_start = current_ray.q_parameter
            q_at_surface = _insert_gaussian_free_space_samples(
                current_ray,
                q_start,
                nearest_distance,
                hit_pt,
                current_ray.wavelength_nm,
            )
            current_ray.path_points.append(hit_pt.copy())
            current_ray.path_polarizations.append(current_ray.polarization)

            w = beam_radius_from_q(q_at_surface, current_ray.wavelength_nm)
            trans_frac = clip_gaussian_circular_aperture(w, half_aperture)
            current_ray.intensity *= trans_frac
            current_ray.path_intensities.append(current_ray.intensity)

            w_vis = min(w, half_aperture) if half_aperture > 1e-12 else w
            current_ray.path_beam_radii.append(w_vis)

            q_for_transform = q_at_surface
            if half_aperture > 1e-12 and w > half_aperture + 1e-9:
                q_for_transform = q_rescale_radius_preserve_curvature(
                    q_at_surface, half_aperture, current_ray.wavelength_nm
                )

            current_ray.q_parameter = nearest_element.transform_q(
                q_for_transform,
                current_ray,
                nearest_intersection.normal,
                hit_point=hit_pt,
                tangent=nearest_intersection.tangent,
            )
            w_out = beam_radius_from_q(current_ray.q_parameter, current_ray.wavelength_nm)
            w_draw = min(w_out, half_aperture) if half_aperture > 1e-12 else w_out
            current_ray.path_beam_radii[-1] = w_draw
        else:
            current_ray.path_points.append(hit_pt.copy())
            current_ray.path_polarizations.append(current_ray.polarization)
            current_ray.path_intensities.append(current_ray.intensity)

        # Interact with element - POLYMORPHIC DISPATCH!
        output_rays = nearest_element.interact(
            current_ray,
            nearest_intersection.point,
            nearest_intersection.normal,
            nearest_intersection.tangent,
        )

        # Handle absorption case (empty output_rays)
        if not output_rays:
            alpha = int(255 * max(0.0, min(1.0, current_ray.intensity)))
            paths.append(
                RayPath(
                    points=current_ray.path_points,
                    rgba=(base_rgb[0], base_rgb[1], base_rgb[2], alpha),
                    polarization=current_ray.polarization,
                    wavelength_nm=current_ray.wavelength_nm,
                    source_index=source_index,
                    polarizations=current_ray.path_polarizations,
                    intensities=current_ray.path_intensities,
                    beam_radii=current_ray.path_beam_radii,
                )
            )
            continue

        # Track last element and propagate engine-specific fields to output rays
        for out_ray in output_rays:
            ray_id = id(out_ray)
            last_element_for_ray[ray_id] = nearest_element

            # Propagate engine-specific fields that interact() doesn't know about
            if not hasattr(out_ray, "base_rgb") or out_ray.base_rgb is None:
                out_ray.base_rgb = base_rgb
            out_ray.remaining_length = current_ray.remaining_length - nearest_distance
            if not hasattr(out_ray, "path_points") or len(out_ray.path_points) == 0:
                out_ray.path_points = current_ray.path_points.copy()
            if len(out_ray.path_polarizations) == 0:
                out_ray.path_polarizations = current_ray.path_polarizations.copy()
            if len(out_ray.path_intensities) == 0:
                out_ray.path_intensities = current_ray.path_intensities.copy()
            # Update last entries to post-interaction state
            if len(out_ray.path_polarizations) > 0:
                out_ray.path_polarizations[-1] = out_ray.polarization
            if len(out_ray.path_intensities) > 0:
                out_ray.path_intensities[-1] = out_ray.intensity

            # Propagate Gaussian beam q-parameter to child rays
            if current_ray.q_parameter is not None:
                if out_ray.q_parameter is None:
                    out_ray.q_parameter = current_ray.q_parameter
                if len(out_ray.path_beam_radii) == 0:
                    out_ray.path_beam_radii = current_ray.path_beam_radii.copy()

        # Add output rays to stack for processing
        stack.extend(output_rays)

    return paths


# Convenience alias for the main function
trace_rays = trace_rays_polymorphic
