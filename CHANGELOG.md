# Changelog

All notable changes to Optiverse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

