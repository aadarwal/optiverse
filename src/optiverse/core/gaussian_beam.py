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


def rayleigh_range(w0_mm: float, wavelength_nm: float) -> float:
    """Compute the Rayleigh range z_R = pi * w0^2 / lambda."""
    wavelength_mm = wavelength_nm * 1e-6
    return math.pi * w0_mm**2 / wavelength_mm


def rayleigh_range_from_q(q: complex, wavelength_nm: float) -> float:
    """
    Local Rayleigh range from current q: z_R = pi * w^2 / lambda = -1 / Im(1/q).

    Used to choose free-space subsampling step size.
    """
    inv_q = 1.0 / q
    im = inv_q.imag
    if im >= -1e-30:
        return rayleigh_range(0.1, wavelength_nm)
    return -1.0 / im


def propagate_free_space(q: complex, distance_mm: float) -> complex:
    """
    Propagate q through free space by distance d.

    ABCD matrix: [[1, d], [0, 1]]  =>  q' = q + d
    """
    return q + distance_mm


def apply_abcd(q: complex, A: float, B: float, C: float, D: float) -> complex:
    """
    Apply a 2x2 ABCD ray transfer matrix to the complex beam parameter.

        q' = (A*q + B) / (C*q + D)

    All distances are in mm; A, B, C, D must be dimensionally consistent with q in mm.
    """
    denom = C * q + D
    if abs(denom) < 1e-30:
        return q
    return (A * q + B) / denom


def clip_gaussian_circular_aperture(beam_radius_mm: float, aperture_radius_mm: float) -> float:
    """
    Fraction of power for a rotationally symmetric Gaussian beam through a hard circular aperture.

    Intensity I(r) ∝ exp(-2 r² / w²) with w the 1/e² radius. Transmitted power fraction inside
    radius a is 1 - exp(-2 a² / w²).

    Args:
        beam_radius_mm: 1/e² half-width w of the beam (mm)
        aperture_radius_mm: Clear aperture radius (mm), not diameter

    Returns:
        Fraction in (0, 1], or 1.0 if clipping does not apply.
    """
    if beam_radius_mm <= 1e-15 or aperture_radius_mm <= 0.0:
        return 1.0
    w = beam_radius_mm
    a = aperture_radius_mm
    arg = 2.0 * (a / w) ** 2
    if arg > 80.0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - math.exp(-arg)))


def q_rescale_radius_preserve_curvature(
    q: complex, w_new_mm: float, wavelength_nm: float
) -> complex:
    """
    Adjust q so the 1/e^2 radius becomes w_new while keeping Re(1/q) (curvature) fixed.

    With 1/q = 1/R - i*lambda/(pi*w^2), replace Im(1/q) for the new waist w_new.
    """
    if w_new_mm <= 1e-15:
        return q
    wavelength_mm = wavelength_nm * 1e-6
    inv_q = 1.0 / q
    im_new = -wavelength_mm / (math.pi * w_new_mm * w_new_mm)
    return 1.0 / complex(inv_q.real, im_new)

