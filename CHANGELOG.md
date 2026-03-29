# Changelog

All notable changes to Optiverse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.3] - 2026-03-28

### Added

- **Update Canvas Instances**: Component Editor toolbar action **Update Canvas Instances…** — after confirmation, updates every placed component on the main canvas that matches the current component name (single batch undo; pose and lock preserved)
- **Gaussian Beams**: Gaussian beam propagation support for sources and optical elements

### Fixed

- **External Component Storing**: Centralized library management via new `LibraryService` — fixes settings-configured library paths being silently ignored by the dock, scene loading, and collaboration. Components from all configured libraries now appear correctly everywhere.
  - **Library enable/disable**: Libraries can be toggled on/off in Preferences without removing them (ideal for switching between project contexts)
  - **Save To selector**: Component Editor lets you choose which library to save into
  - **Link vs Copy import**: Importing a library folder now offers "Link" (register the path, ideal for git repos) or "Copy" (legacy behavior)
  - **Missing component report**: Scene loading warns when components cannot be resolved, with guidance to configure library paths
  - **Preferences overhaul**: Library page uses a table with Name, Path, Components, Status columns and enable/disable checkboxes
  - **Open Library Folder submenu**: Tools menu lists all known libraries for quick access

## [0.3.2] - 2026-03-26

### Added

- **Placed components on canvas**: context menu **Edit in Component Editor…** (save updates library and instance, undoable) and **Apply Properties to All…** (choose scope and fields, single batch undo)
- **Layer panel context menu**: **Edit…**, **Edit in Component Editor…** for items, and **Z-Order** submenu (bring forward/back, to front/back)
- **Save guards** when saving from the Component Editor to reduce accidental silent duplication
- **Undo commands** for operations that were previously missing from the stack: layer rename; visibility and lock toggles; z-order changes; inline text note edits; rectangle property edits from the editor dialog

### Changed

- **Hover and hitboxes**: Clearer hover feedback and more forgiving hit targets for sources, component sprites, rectangle annotations, and shared base item behavior
- **Developer layout**: Build and icon scripts live under `tools/`; generated `.icns` / `.ico` go to `tools/generated_icons/`; Ruff and Mypy settings consolidated in `pyproject.toml`

### Fixed

- **Undo/redo consistency**: Layer model changes, z-order from multiple UI paths, annotation deletes, path measure wiring on load, component editor save baseline, and related cases no longer leave Ctrl+Z targeting the wrong action
- **Group rotation undo**: Restores rotations for ruler and angle measure items included in the group
- **Drag + autosave**: Undo merge during moves emits `commandPushed` so the autosave debounce resets correctly
- **Collaboration**: Starting the local server from the dialog raises `OSError` on failure so errors surface properly
- **Rotation tracking**: Missing `AngleMeasureItem` import in rotation startup
- **Raytracing engine**: Removed dead parallel-detection branch (condition was never true)
- **Documentation site**: GitHub Pages header shows the home button label again

### Removed

- Tracked `optiverse.iconset/` PNGs (icons are generated locally); root `resources/` placeholder directory
- Obsolete `tools/` helpers (`compile_ui.py`, `compile_rc.py`, old lint/WebSocket test scripts); duplicate `.ruff.toml` and `mypy.ini` (see `pyproject.toml`)
- Unused `StorageService.ensure_standard_components` and other dead code paths cleaned up for the release

## [0.3.1] - 2026-03-25

### Added

- **Linear Polarizer Element**: Full raytracing support with Malus's Law, finite extinction ratio, Jones vector decomposition, and drag-and-drop library component
- **Faraday Rotator Element**: Non-reciprocal polarization rotation via magneto-optic effect for optical isolator designs; includes library component
- **Per-Segment Intensity Tracking**: Ray segments before lossy elements render at full brightness while downstream segments render dimmer (both software and OpenGL renderers)
- **Per-Segment Polarization Tracking**: Inspect tool now shows correct polarization state at each point along the ray
- **Library Search/Filter Bar**: Filter components in the library tree by name
- **Smart Spinboxes**: Replace plain spinboxes with SmartDoubleSpinBox/SmartSpinBox across source, rectangle, and component editors

### Changed

- **Source Editor Live Editing**: All parameters now apply live instead of only on OK click
- **Lens Physics**: Use ideal non-paraxial deflection formula (arctan) instead of paraxial approximation, eliminating spurious aberration at large impact parameters
- **Unified Item Drag Handling**: Single code path for all non-Ctrl left-button drags, eliminating competition between Qt's built-in drag and custom handler
- **Polarizer Properties Panel**: Only shows properties relevant to the selected polarizer subtype (waveplate, linear polarizer, Faraday rotator)
- **Undo Merge Window**: 0.5s merge window for MoveItemCommand to reduce undo stack noise

### Fixed

- Fix wavelength editing not persisting when source editor is in "Custom Color" mode
- Fix collaboration crash when syncing RulerItem/TextNoteItem (only BaseObj subclasses have 'edited' signal)
- Fix host state transfer: host now uploads canvas to server on connect instead of requesting empty state
- Fix collaboration server leaking commands across sessions (connections now scoped per session)
- Fix multi-selection drag: clicking an already-selected item preserves current selection
- Fix rubber band selection appearing during item drag
- Fix waveplate backward propagation: use transpose (not conjugate) for Jones matrix
- Fix mirror polarization: use r_s = r_p = -1 (Born & Wolf convention) to prevent spurious phase at normal incidence
- Fix context menu delete to emit requestDelete signal for proper undo integration and automatic retrace
- Fix signal reconnection on file load for optical items, text notes, and rectangles
- Fix layer panel orphan items and ghost node deletion
- Fix lock state sync between BaseObj and LayerNode
- Fix component editor endpoint dragging to find closest endpoint globally

## [0.3.0] - 2025-12-20

### Added

- **Layer Widget System Overhaul**: Complete rewrite using Qt Model/View/Delegate pattern
  - `LayerTreeState` as single source of truth for hierarchy and z-order
  - `LayerNode` dataclass for tree nodes (groups and items)
  - `LayerItemModel` with full drag-and-drop support
  - `LayerItemDelegate` for custom icon painting (visibility, lock, folder icons)
  - `KeyboardLayerTreeView` with Delete/Backspace key handling
  - `LayerZOrderApplier` for automatic z-value synchronization
- **Group Management**: Full support for creating, deleting, and nesting groups
  - Photoshop-style effective visibility (inherit from parent chain)
  - Effective lock state (locked if self or any ancestor is locked)
  - Drag-and-drop reordering within and between groups
- **Undo/Redo for Layer Operations**
  - `CreateGroupCommand` for grouping items
  - `DeleteGroupCommand` for ungrouping/deleting groups
  - `MoveNodeCommand` for z-order and hierarchy changes
  - `BatchCommand` for combining multiple operations
- **Parallel Raytracing**: Multi-threaded ray tracing for 2-4x speedup on multi-core CPUs
- **Debounced UI Updates**: Smart refresh timers (50-100ms) to prevent UI flicker during rapid changes

### Changed

- **Drag System Architecture**: Refactored to work with Qt patterns instead of against them
- **Z-Order Management**: Now derived from layer tree traversal order, no longer stored directly on items
- **Item Visibility**: Controlled through layer panel with effective state inheritance

### Fixed

- Fixed z-order signaling issues causing items to appear in wrong order
- Fixed double-click bug in layer panel
- Fixed bug when loading files with layer state
- Fixed source visibility not updating correctly
- Fixed renaming items/groups in layer panel
- Fixed save/load problems with layer hierarchy
- Fixed closing errors and removed debug print statements
- Fixed beam block component behavior
- Increased hitbox size for easier selection

### Removed

- Legacy raytracing implementation (replaced by parallel processing engine)

## [0.2.x] - Previous Releases

Prior versions did not maintain a changelog. See git history for details.

