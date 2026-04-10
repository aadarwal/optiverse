"""Tests for @component/ path resolution."""

from __future__ import annotations

from pathlib import Path

from optiverse.platform.paths import get_builtin_library_root, resolve_component_path


def test_resolve_component_path_prefers_user_library_over_builtin(tmp_path: Path) -> None:
    """When the same component name exists in a user library and built-in, user wins."""
    user_lib = tmp_path / "my_lab_library"
    user_beam = user_lib / "beam_block" / "images"
    user_beam.mkdir(parents=True)
    marker = user_beam / "beam_block.png"
    marker.write_text("user copy", encoding="utf-8")

    builtin_root = get_builtin_library_root()
    # Discovery order often lists built-in first; resolution must still prefer the user copy.
    roots = [builtin_root, user_lib]

    resolved = resolve_component_path("@component/beam_block/images/beam_block.png", roots)
    assert resolved is not None
    assert Path(resolved).resolve() == marker.resolve()
