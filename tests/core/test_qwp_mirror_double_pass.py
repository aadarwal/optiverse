import numpy as np

from optiverse.core.models import Polarization
from optiverse.core.raytracing_math import (
    deg2rad,
    transform_polarization_mirror,
    transform_polarization_waveplate,
)


def _equivalent_up_to_global_phase(a: np.ndarray, b: np.ndarray, atol: float = 1e-6) -> bool:
    """Return True if Jones vectors a and b are equal up to a global complex scale."""
    if np.linalg.norm(a) < 1e-12 and np.linalg.norm(b) < 1e-12:
        return True
    # Pick a nonzero component to compute the ratio
    if abs(b[0]) > 1e-12:
        ratio = a[0] / b[0]
    elif abs(b[1]) > 1e-12:
        ratio = a[1] / b[1]
    else:
        return False
    return np.allclose(a, ratio * b, atol=atol)


def _linear_jones(angle_deg: float) -> np.ndarray:
    """Ideal linear polarization Jones vector at angle_deg (from horizontal)."""
    th = deg2rad(angle_deg)
    return np.array([np.cos(th), np.sin(th)], dtype=complex)


def _apply_qwp_mirror_qwp(pol: Polarization, theta_deg: float) -> Polarization:
    """Apply forward QWP(θ), ideal mirror, then backward QWP(θ)."""
    # Forward pass through QWP with +90°
    pol1 = transform_polarization_waveplate(
        pol,
        phase_shift_deg=90.0,
        fast_axis_deg=theta_deg,
        is_forward=True,
    )

    # Ideal mirror at near-normal incidence (s/p fallback picks s=[0,1], p=[-1,0])
    # Convention is fine; only relative phase matters
    pol2 = transform_polarization_mirror(
        pol1, v_in=np.array([1.0, 0.0]), n_hat=np.array([1.0, 0.0])
    )

    # Backward pass through the same QWP (−90° effective)
    pol3 = transform_polarization_waveplate(
        pol2,
        phase_shift_deg=90.0,
        fast_axis_deg=theta_deg,
        is_forward=False,
    )
    return pol3


def test_qwp_mirror_qwp_22_5_degrees_rotates_by_45():
    """
    QWP(22.5°) + mirror + QWP(22.5°) rotates H by 45°.

    A QWP double-pass (with mirror between) acts as an HWP at the same
    axis angle.  An HWP at θ rotates linear polarization by 2θ.
    At θ=22.5°, the rotation is 2×22.5° = 45°, so H → +45° linear.
    """
    pol_in = Polarization.horizontal()
    pol_out = _apply_qwp_mirror_qwp(pol_in, theta_deg=22.5)

    expected_45 = _linear_jones(45.0)
    assert _equivalent_up_to_global_phase(pol_out.jones_vector, expected_45, atol=1e-6)


def test_qwp_mirror_qwp_45_degrees_rotates_by_90():
    pol_in = Polarization.horizontal()
    pol_out = _apply_qwp_mirror_qwp(pol_in, theta_deg=45.0)

    expected = _linear_jones(90.0)
    assert _equivalent_up_to_global_phase(pol_out.jones_vector, expected, atol=1e-6)
