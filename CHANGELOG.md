# Changelog

All notable changes to Optiverse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

