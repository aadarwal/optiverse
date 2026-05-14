import numpy as np

from optiverse.agentic.catalog import load_builtin_catalog
from optiverse.agentic.compiler import compile_elements, placed_interface, rotate_translate
from optiverse.agentic.schema import Placement, demo_goal_spec
from optiverse.raytracing.engine import trace_rays_polymorphic


def test_rotate_translate_uses_optiverse_user_angle_convention():
    placement = Placement(label="P", catalog_id="lens_standard_1in", x_mm=10, y_mm=20, angle_deg=90)

    x, y = rotate_translate(1, 0, placement)

    assert np.allclose([x, y], [10, 19])


def test_placed_interface_applies_interface_overrides_and_position():
    catalog = load_builtin_catalog()
    placement = Placement(
        label="HWP1",
        catalog_id="waveplate_hwp",
        x_mm=60,
        y_mm=0,
        interface_overrides={0: {"fast_axis_deg": 22.5}},
    )
    iface_data = catalog["waveplate_hwp"]["interfaces"][0].copy()
    iface_data.update(placement.normalized_overrides()[0])

    iface = placed_interface(iface_data, placement)

    assert iface.fast_axis_deg == 22.5
    assert np.allclose([iface.x1_mm, iface.x2_mm], [60, 60])


def test_compile_demo_elements_traces_two_split_paths():
    catalog = load_builtin_catalog()
    goal = demo_goal_spec()

    elements = compile_elements(catalog, goal.placements)
    paths = trace_rays_polymorphic(elements, [goal.source.to_source_params()], parallel=False)

    assert len(elements) == 2
    assert len(paths) == 2
