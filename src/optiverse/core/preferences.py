"""
Mutable runtime preferences, loaded from SettingsService on startup
and updated when the user changes Preferences.

Consumers import this *module* and read its attributes directly::

    from ...core import preferences
    snap_size = preferences.grid_snap_size_mm

MainWindow is responsible for calling :func:`load_from_settings` to
sync these values with the persisted QSettings store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.settings_service import SettingsService

# ── General ──────────────────────────────────────────────────────────

autosave_enabled: bool = True
autosave_interval_ms: int = 1000
max_recent_files: int = 10

# ── Appearance ───────────────────────────────────────────────────────

show_scale_bar: bool = True

# ── Canvas & Editing ─────────────────────────────────────────────────

grid_snap_size_mm: float = 1.0
magnetic_snap_tolerance_px: float = 10.0
rotation_snap_angle_deg: float = 45.0
wheel_rotation_deg_per_step: float = 2.0
max_raytracing_events: int = 80
clone_offset_x_mm: float = 20.0
clone_offset_y_mm: float = 20.0
nudge_small_mm: float = 0.1
nudge_large_mm: float = 1.0

# ── Export Defaults ──────────────────────────────────────────────────

default_png_scale: float = 4.0
default_pdf_dpi: int = 300
export_margin_mm: int = 20


def load_from_settings(s: SettingsService) -> None:
    """Sync all module-level attributes from *s*."""
    import optiverse.core.preferences as _self

    _self.autosave_enabled = s.get_value("general/autosave_enabled", True, bool)
    _self.autosave_interval_ms = s.get_value("general/autosave_interval_ms", 1000, int)
    _self.max_recent_files = s.get_value("general/max_recent_files", 10, int)

    _self.show_scale_bar = s.get_value("appearance/show_scale_bar", True, bool)

    _self.grid_snap_size_mm = s.get_value("canvas/grid_snap_size_mm", 1.0, float)
    _self.magnetic_snap_tolerance_px = s.get_value(
        "canvas/magnetic_snap_tolerance_px", 10.0, float
    )
    _self.rotation_snap_angle_deg = s.get_value(
        "canvas/rotation_snap_angle_deg", 45.0, float
    )
    _self.wheel_rotation_deg_per_step = s.get_value(
        "canvas/wheel_rotation_deg_per_step", 2.0, float
    )
    _self.max_raytracing_events = s.get_value("canvas/max_raytracing_events", 80, int)
    _self.clone_offset_x_mm = s.get_value("canvas/clone_offset_x_mm", 20.0, float)
    _self.clone_offset_y_mm = s.get_value("canvas/clone_offset_y_mm", 20.0, float)
    _self.nudge_small_mm = s.get_value("canvas/nudge_small_mm", 0.1, float)
    _self.nudge_large_mm = s.get_value("canvas/nudge_large_mm", 1.0, float)

    _self.default_png_scale = s.get_value("export/default_png_scale", 4.0, float)
    _self.default_pdf_dpi = s.get_value("export/default_pdf_dpi", 300, int)
    _self.export_margin_mm = s.get_value("export/export_margin_mm", 20, int)
