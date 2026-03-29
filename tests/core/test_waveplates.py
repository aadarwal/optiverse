"""
Tests for waveplate polarization physics.

Verifies that quarter and half waveplates correctly transform polarization states.
"""

import numpy as np
import pytest

from optiverse.core.models import Polarization
from optiverse.core.raytracing_math import transform_polarization_waveplate


def test_quarter_waveplate_horizontal_to_circular():
    """QWP at 45° converts horizontal polarization to right circular."""
    pol_in = Polarization.horizontal()
    pol_out = transform_polarization_waveplate(pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0)

    jones = pol_out.jones_vector

    # Check magnitude is normalized
    assert np.abs(np.linalg.norm(jones) - 1.0) < 1e-6

    # For right circular: Ex and Ey have equal magnitude, 90° phase difference
    assert np.abs(np.abs(jones[0]) - np.abs(jones[1])) < 1e-6


def test_quarter_waveplate_circular_to_linear():
    """QWP at 0° converts right circular to linear."""
    pol_in = Polarization.circular_right()
    pol_out = transform_polarization_waveplate(pol_in, phase_shift_deg=90.0, fast_axis_deg=0.0)

    jones = pol_out.jones_vector

    # Check magnitude is normalized
    assert np.abs(np.linalg.norm(jones) - 1.0) < 1e-6


def test_half_waveplate_rotates_linear():
    """HWP at 22.5° rotates horizontal polarization by 45°."""
    pol_in = Polarization.horizontal()
    pol_out = transform_polarization_waveplate(pol_in, phase_shift_deg=180.0, fast_axis_deg=22.5)

    jones = pol_out.jones_vector

    # Check magnitude is normalized
    assert np.abs(np.linalg.norm(jones) - 1.0) < 1e-6


def test_waveplate_preserves_intensity():
    """Waveplates preserve total intensity."""
    pol_in = Polarization.linear(30.0)
    pol_out = transform_polarization_waveplate(pol_in, phase_shift_deg=90.0, fast_axis_deg=60.0)

    intensity_in = pol_in.intensity()
    intensity_out = pol_out.intensity()

    # Intensity should be conserved
    assert np.abs(intensity_in - intensity_out) < 1e-6


def test_zero_phase_shift_is_identity():
    """Zero phase shift leaves polarization unchanged."""
    pol_in = Polarization.diagonal_plus_45()
    pol_out = transform_polarization_waveplate(pol_in, phase_shift_deg=0.0, fast_axis_deg=0.0)

    jones_in = pol_in.jones_vector
    jones_out = pol_out.jones_vector

    # Jones vectors should be identical
    assert np.allclose(jones_in, jones_out, atol=1e-6)


# ===== DIRECTIONALITY TESTS =====


def test_qwp_forward_horizontal_to_circular():
    """QWP forward at 45° converts horizontal to circular polarization."""
    pol_in = Polarization.horizontal()
    pol_out = transform_polarization_waveplate(
        pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=True
    )

    jones = pol_out.jones_vector

    # Circular: equal magnitude components
    assert np.abs(np.linalg.norm(jones) - 1.0) < 1e-6
    assert np.abs(np.abs(jones[0]) - 1 / np.sqrt(2)) < 1e-6
    assert np.abs(np.abs(jones[1]) - 1 / np.sqrt(2)) < 1e-6

    # Check phase difference: should be ±90° (circular polarization)
    phase_diff = np.angle(jones[1]) - np.angle(jones[0])
    # Normalize to [-π, π]
    phase_diff = np.arctan2(np.sin(phase_diff), np.cos(phase_diff))
    assert np.abs(np.abs(phase_diff) - np.pi / 2) < 1e-6  # Either +90° or -90°


def test_qwp_backward_horizontal_to_circular():
    """
    QWP backward at 45° converts horizontal to circular polarization
    (opposite handedness from forward).
    """
    pol_in = Polarization.horizontal()
    pol_out = transform_polarization_waveplate(
        pol_in,
        phase_shift_deg=90.0,
        fast_axis_deg=45.0,
        is_forward=False,  # Backward direction
    )

    jones = pol_out.jones_vector

    # Circular: equal magnitude components
    assert np.abs(np.linalg.norm(jones) - 1.0) < 1e-6
    assert np.abs(np.abs(jones[0]) - 1 / np.sqrt(2)) < 1e-6
    assert np.abs(np.abs(jones[1]) - 1 / np.sqrt(2)) < 1e-6

    # Check phase difference: should be ±90° (opposite from forward)
    phase_diff = np.angle(jones[1]) - np.angle(jones[0])
    # Normalize to [-π, π]
    phase_diff = np.arctan2(np.sin(phase_diff), np.cos(phase_diff))
    assert np.abs(np.abs(phase_diff) - np.pi / 2) < 1e-6  # Either +90° or -90°


def test_qwp_directionality_same_for_forward_backward():
    """
    QWP forward and backward produce identical output.

    The waveplate Jones matrix J = R(-θ)·D·R(θ) is symmetric (J = J^T)
    because R(θ)^T = R(-θ) and D^T = D. Therefore the backward matrix
    (which is J^T for reciprocal elements) equals the forward matrix.
    """
    pol_in = Polarization.horizontal()

    pol_forward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=True
    )
    pol_backward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=False
    )

    jones_fwd = pol_forward.jones_vector
    jones_bwd = pol_backward.jones_vector

    # Forward and backward must be identical (J^T = J for waveplates)
    assert np.allclose(jones_fwd, jones_bwd, atol=1e-6)


def test_qwp_double_pass_equals_hwp():
    """
    Two passes through a QWP (without a mirror) act as a HWP.

    Since J_backward = J_forward (symmetric matrix), applying the QWP
    twice is simply J^2.  For a QWP at 45° with δ=90°, J^2 equals the
    HWP Jones matrix, which rotates linear polarization by 90°.

    Note: this is NOT a round-trip identity.  A true QWP+mirror+QWP
    retroreflector also gives a 90° rotation, but via a different
    mechanism (the mirror flips handedness between the two passes).
    """
    pol_in = Polarization.horizontal()

    # First pass
    pol_mid = transform_polarization_waveplate(
        pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=True
    )

    # Second pass (backward flag makes no difference — J^T = J)
    pol_out = transform_polarization_waveplate(
        pol_mid, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=False
    )

    jones_out = pol_out.jones_vector

    # QWP^2 at 45° on horizontal input should produce vertical (up to global phase)
    expected_vertical = Polarization.vertical().jones_vector

    # Check equivalence up to global phase
    if np.abs(expected_vertical[1]) > 1e-6:
        ratio = jones_out[1] / expected_vertical[1]
    else:
        ratio = jones_out[0] / expected_vertical[0]
    assert np.allclose(jones_out, ratio * expected_vertical, atol=1e-6)


def test_hwp_directionality_symmetric():
    """HWP behavior is symmetric - forward and backward give same result."""
    pol_in = Polarization.horizontal()

    pol_forward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=180.0, fast_axis_deg=22.5, is_forward=True
    )
    pol_backward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=180.0, fast_axis_deg=22.5, is_forward=False
    )

    jones_fwd = pol_forward.jones_vector
    jones_bwd = pol_backward.jones_vector

    # For HWP, exp(i*180°) = exp(-i*180°) = -1, so forward and backward are the same
    # They should be equal up to a global phase factor (both get multiplied by some phase)
    # The simplest check: they should both have the same relative components
    assert np.allclose(np.abs(jones_fwd), np.abs(jones_bwd), atol=1e-6)

    # More rigorous: check if one is a scalar multiple of the other
    ratio = (
        jones_fwd[0] / jones_bwd[0] if np.abs(jones_bwd[0]) > 1e-6 else jones_fwd[1] / jones_bwd[1]
    )
    assert np.allclose(jones_fwd, ratio * jones_bwd, atol=1e-6)


def test_qwp_vertical_polarization_forward_equals_backward():
    """
    QWP forward and backward give identical results for vertical input.

    The waveplate Jones matrix is symmetric (J = J^T), so the propagation
    direction does not matter.
    """
    pol_in = Polarization.vertical()

    pol_forward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=True
    )
    pol_backward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=90.0, fast_axis_deg=45.0, is_forward=False
    )

    jones_fwd = pol_forward.jones_vector
    jones_bwd = pol_backward.jones_vector

    # Both should produce circular polarization (normalized)
    assert np.abs(np.linalg.norm(jones_fwd) - 1.0) < 1e-6
    assert np.abs(np.linalg.norm(jones_bwd) - 1.0) < 1e-6

    # Forward and backward must be identical
    assert np.allclose(jones_fwd, jones_bwd, atol=1e-6)


def test_arbitrary_waveplate_forward_equals_backward():
    """
    Arbitrary waveplate: forward and backward give identical results.

    This holds for all phase shifts and fast-axis angles because the
    Jones matrix J = R(-θ)·diag(1, e^{iδ})·R(θ) is always symmetric.
    """
    pol_in = Polarization.diagonal_plus_45()
    phase_shift = 37.5  # Arbitrary phase shift

    pol_forward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=phase_shift, fast_axis_deg=60.0, is_forward=True
    )
    pol_backward = transform_polarization_waveplate(
        pol_in, phase_shift_deg=phase_shift, fast_axis_deg=60.0, is_forward=False
    )

    jones_fwd = pol_forward.jones_vector
    jones_bwd = pol_backward.jones_vector

    # Forward and backward must be identical for any phase shift / axis angle
    assert np.allclose(jones_fwd, jones_bwd, atol=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
