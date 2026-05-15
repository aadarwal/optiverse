import numpy as np

from optiverse.agentic.catalog import load_builtin_catalog
from optiverse.agentic.compiler import interfaces_for_placement, placed_interface
from optiverse.agentic.layout_compiler import (
    placement_from_planner_data,
    placements_from_planner_data,
)


def _interface_midpoint(catalog, placement):
    iface = placed_interface(interfaces_for_placement(catalog, placement)[0], placement)
    return np.array(
        [
            0.5 * (float(iface.x1_mm) + float(iface.x2_mm)),
            0.5 * (float(iface.y1_mm) + float(iface.y2_mm)),
        ]
    )


def test_origin_placement_form_is_preserved():
    catalog = load_builtin_catalog()
    placement = placement_from_planner_data(
        catalog,
        {
            "label": "L1",
            "catalog_id": "lens_standard_1in",
            "x_mm": 100.0,
            "y_mm": 0.0,
        },
    )

    assert placement.x_mm == 100.0
    assert placement.y_mm == 0.0


def test_interface_anchor_translates_to_optiverse_origin():
    catalog = load_builtin_catalog()
    placement = placement_from_planner_data(
        catalog,
        {
            "label": "M1",
            "catalog_id": "mirror_standard_1in",
            "angle_deg": 45.0,
            "anchor": {
                "kind": "interface_midpoint",
                "interface_index": 0,
                "x_mm": 50.0,
                "y_mm": 0.0,
            },
        },
    )

    assert np.allclose(_interface_midpoint(catalog, placement), [50.0, 0.0])


def test_focal_length_spacing_places_second_relay_lens():
    catalog = load_builtin_catalog()
    placements = placements_from_planner_data(
        catalog,
        [
            {
                "label": "L1",
                "catalog_id": "lens_standard_1in",
                "anchor": {
                    "kind": "interface_midpoint",
                    "x_mm": 100.0,
                    "y_mm": 0.0,
                },
            },
            {
                "label": "L2",
                "catalog_id": "lens_standard_1in",
                "anchor": {
                    "kind": "interface_midpoint",
                    "relative_to": "L1",
                    "spacing": "f1_plus_f2",
                    "axis": "x",
                },
            },
        ],
    )

    assert np.allclose(_interface_midpoint(catalog, placements[0]), [100.0, 0.0])
    assert np.allclose(_interface_midpoint(catalog, placements[1]), [300.0, 0.0])
