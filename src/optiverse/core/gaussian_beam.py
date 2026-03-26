"""
Gaussian beam propagation using the complex beam parameter (q-parameter).

The q-parameter encodes both beam waist and wavefront curvature:
    1/q = 1/R - i * lambda / (pi * w^2)

where R is the wavefront radius of curvature and w is the 1/e^2 beam radius.

At the beam waist (z=0): q = i * z_R, where z_R = pi * w0^2 / lambda
is the Rayleigh range.

Propagation through any paraxial element with ABCD ray transfer matrix:
    q' = (A*q + B) / (C*q + D)
"""

from __future__ import annotations

import math


def q_from_waist(w0_mm: float, wavelength_nm: float) -> complex:
    """
    Create initial q-parameter at the beam waist.

    At the waist, the wavefront is flat (R -> inf), so q = i * z_R.

    Args:
        w0_mm: Beam waist radius (1/e^2) in mm
        wavelength_nm: Wavelength in nanometers

    Returns:
        Complex beam parameter q (in mm)
    """
    wavelength_mm = wavelength_nm * 1e-6
    z_R = math.pi * w0_mm**2 / wavelength_mm
    return 1j * z_R


def beam_radius_from_q(q: complex, wavelength_nm: float) -> float:
    """
    Extract beam radius w(z) from the q-parameter.

    From 1/q = 1/R - i*lambda/(pi*w^2), the beam radius is:
        w = sqrt(-lambda / (pi * Im(1/q)))

    Args:
        q: Complex beam parameter (in mm)
        wavelength_nm: Wavelength in nanometers

    Returns:
        Beam radius (1/e^2) in mm
    """
    wavelength_mm = wavelength_nm * 1e-6
    inv_q = 1.0 / q
    im_inv_q = inv_q.imag
    if im_inv_q >= 0:
        return 0.0
    w_sq = -wavelength_mm / (math.pi * im_inv_q)
    if w_sq <= 0:
        return 0.0
    return math.sqrt(w_sq)


def wavefront_radius_from_q(q: complex) -> float:
    """
    Extract wavefront radius of curvature R(z) from the q-parameter.

    From 1/q = 1/R - i*lambda/(pi*w^2), the radius of curvature is:
        R = 1 / Re(1/q)

    Returns float('inf') at the waist (flat wavefront).

    Args:
        q: Complex beam parameter (in mm)

    Returns:
        Radius of curvature in mm (positive = diverging, negative = converging)
    """
    re_inv_q = (1.0 / q).real
    if abs(re_inv_q) < 1e-15:
        return float("inf")
    return 1.0 / re_inv_q


def rayleigh_range(w0_mm: float, wavelength_nm: float) -> float:
    """Compute the Rayleigh range z_R = pi * w0^2 / lambda."""
    wavelength_mm = wavelength_nm * 1e-6
    return math.pi * w0_mm**2 / wavelength_mm


def propagate_free_space(q: complex, distance_mm: float) -> complex:
    """
    Propagate q through free space by distance d.

    ABCD matrix: [[1, d], [0, 1]]  =>  q' = q + d
    """
    return q + distance_mm


def transform_thin_lens(q: complex, focal_length_mm: float) -> complex:
    """
    Transform q through an ideal thin lens.

    ABCD matrix: [[1, 0], [-1/f, 1]]  =>  1/q' = 1/q - 1/f
    """
    if abs(focal_length_mm) < 1e-12:
        return q
    inv_q_new = 1.0 / q - 1.0 / focal_length_mm
    return 1.0 / inv_q_new


def transform_flat_refraction(q: complex, n1: float, n2: float) -> complex:
    """
    Transform q through a flat refractive interface.

    The beam spot size w is continuous across a flat interface. We adjust
    the wavefront curvature (Re(1/q)) by n1/n2 while preserving the beam
    radius (Im(1/q) unchanged). This ensures beam_radius_from_q returns
    the correct physical beam size using the vacuum wavelength throughout.
    """
    if abs(n1) < 1e-12 or abs(n2) < 1e-12:
        return q
    inv_q = 1.0 / q
    inv_q_new = complex(inv_q.real * n1 / n2, inv_q.imag)
    return 1.0 / inv_q_new


def transform_curved_refraction(
    q: complex, n1: float, n2: float, radius_mm: float
) -> complex:
    """
    Transform q through a curved refractive interface.

    Uses the focusing power of the curved surface (equivalent to a thin
    lens with f = R*n2/(n2-n1)) applied to the vacuum-equivalent q,
    preserving the beam radius convention used by beam_radius_from_q.
    """
    if abs(radius_mm) < 1e-12:
        return transform_flat_refraction(q, n1, n2)
    # Equivalent focal length of the curved refractive surface
    dn = n2 - n1
    if abs(dn) < 1e-12:
        return q
    f_eq = radius_mm * n2 / dn
    # Apply thin-lens-like transform for the focusing, then flat refraction
    # for the medium change
    q = transform_thin_lens(q, f_eq)
    return transform_flat_refraction(q, n1, n2)


def transform_flat_mirror(q: complex) -> complex:
    """
    Transform q at a flat mirror (identity for beam parameters).

    ABCD matrix: [[1, 0], [0, 1]]  =>  q' = q
    """
    return q


def transform_curved_mirror(q: complex, radius_mm: float) -> complex:
    """
    Transform q at a curved mirror with radius of curvature R.

    ABCD matrix: [[1, 0], [-2/R, 1]]
    Equivalent to a thin lens with f = R/2.
    """
    if abs(radius_mm) < 1e-12:
        return q
    return transform_thin_lens(q, radius_mm / 2.0)


def _transform_abcd(q: complex, A: float, B: float, C: float, D: float) -> complex:
    """
    General ABCD matrix transformation: q' = (A*q + B) / (C*q + D).
    """
    numerator = A * q + B
    denominator = C * q + D
    if abs(denominator) < 1e-30:
        return q
    return numerator / denominator
