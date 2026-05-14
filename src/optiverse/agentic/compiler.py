"""Compile explicit component placements into raytracing elements."""

from __future__ import annotations

import copy
import math
from typing import Any

from optiverse.core.interface_definition import InterfaceDefinition
from optiverse.integration import create_polymorphic_element
from optiverse.integration.adapter import convert_legacy_interface_to_optical

from .catalog import Catalog
from .schema import Placement


def rotate_translate(x: float, y: float, placement: Placement) -> tuple[float, float]:
    """Apply Optiverse's user angle convention to local component coordinates."""
    theta = -math.radians(placement.angle_deg)
    c = math.cos(theta)
    s = math.sin(theta)
    return (
        placement.x_mm + c * x - s * y,
        placement.y_mm + s * x + c * y,
    )


def placed_interface(iface_data: dict[str, Any], placement: Placement) -> InterfaceDefinition:
    """Convert a component-local interface definition to scene coordinates."""
    iface = InterfaceDefinition.from_dict(copy.deepcopy(iface_data))
    x1, y1 = rotate_translate(float(iface.x1_mm), float(iface.y1_mm), placement)
    x2, y2 = rotate_translate(float(iface.x2_mm), float(iface.y2_mm), placement)
    iface.x1_mm = x1
    iface.y1_mm = y1
    iface.x2_mm = x2
    iface.y2_mm = y2
    return iface


def interfaces_for_placement(catalog: Catalog, placement: Placement) -> list[dict[str, Any]]:
    """Return component interface dictionaries after placement overrides."""
    component = catalog[placement.catalog_id]
    interfaces = copy.deepcopy(component.get("interfaces", []) or [])
    for index, overrides in placement.normalized_overrides().items():
        interfaces[index].update(overrides)
    return interfaces


def compile_elements(catalog: Catalog, placements: list[Placement]) -> list[Any]:
    """Compile selected catalog components into polymorphic raytracing elements."""
    elements = []
    for placement in placements:
        for iface_data in interfaces_for_placement(catalog, placement):
            scene_iface = placed_interface(iface_data, placement)
            optical_iface = convert_legacy_interface_to_optical(scene_iface)
            elements.append(create_polymorphic_element(optical_iface))
    return elements
