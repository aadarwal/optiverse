"""
Collaboration Manager - Bridge between UI and network layer.

Manages item synchronization, command broadcasting, and state reconciliation
for real-time collaborative editing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.log_categories import LogCategory
from ..core.protocols import Editable, HasShape, Lockable, Serializable
from ..objects.type_registry import TypeRegistry
from .collaboration_service import CollaborationService
from .log_service import get_log_service

if TYPE_CHECKING:
    from ..ui.views.main_window import MainWindow


class CollaborationManager(QObject):
    """
    Manages collaboration state and coordinates between UI and network.

    Responsibilities:
    - Track local vs remote changes
    - Broadcast local changes to other users
    - Apply remote changes to local scene
    - Handle conflicts and synchronization
    - Manage session roles (host/client)
    - Handle initial state sync and reconnection
    """

    # Signals
    remote_item_added = pyqtSignal(str, dict)  # item_type, data
    remote_item_moved = pyqtSignal(str, dict)  # item_uuid, data
    remote_item_removed = pyqtSignal(str)  # item_uuid
    remote_item_updated = pyqtSignal(str, dict)  # item_uuid, data
    status_changed = pyqtSignal(str)  # status message

    def __init__(self, main_window: MainWindow, parent: QObject | None = None):
        super().__init__(parent)
        self.main_window = main_window
        self.collaboration_service = CollaborationService(self)
        self.enabled = False
        self._suppress_broadcast = False  # Flag to prevent re-broadcasting remote changes

        # Get log service
        self.log = get_log_service()

        # Track items by UUID
        self.item_uuid_map: dict[str, Any] = {}  # uuid -> item object

        # Session management
        self.role: str | None = None  # "host" or "client"
        self.session_id: str | None = None
        self.session_version: int = 0  # Version counter for state tracking
        self.initial_sync_complete: bool = False  # Flag for initial sync

        # Reconnection handling
        self.needs_resync: bool = False  # Flag to trigger resync on reconnect
        self.last_known_state: dict[str, Any] | None = None  # Cached state
        self.pending_changes: list[dict[str, Any]] = []  # Changes made while offline

        # Connect signals
        self.collaboration_service.connected.connect(self._on_connected)
        self.collaboration_service.disconnected.connect(self._on_disconnected)
        self.collaboration_service.command_received.connect(self._on_command_received)
        self.collaboration_service.sync_state_received.connect(self._on_sync_state_received)
        self.collaboration_service.user_joined.connect(self._on_user_joined)
        self.collaboration_service.user_left.connect(self._on_user_left)
        self.collaboration_service.error_occurred.connect(self._on_error)
        self.collaboration_service.connection_acknowledged.connect(self._on_connection_acknowledged)

    def create_session(
        self, session_id: str, user_id: str, use_current_canvas: bool = True
    ) -> None:
        """
        Create a new session as host.

        Args:
            session_id: Session ID to create
            user_id: Your user ID/name
            use_current_canvas: If True, share current canvas state;
                if False, start with empty canvas
        """
        self.role = "host"
        self.session_id = session_id
        self.session_version = 0
        self.initial_sync_complete = True  # Host starts with sync complete

        if not use_current_canvas:
            # Clear the canvas for empty session
            if self.main_window.scene:
                self.main_window.scene.clear()
            self.item_uuid_map.clear()
        else:
            # Rebuild UUID map from current canvas
            self.rebuild_uuid_map()

        # Cache initial state
        self.last_known_state = self.get_session_state()

        self.log.info(
            f"Created session '{session_id}' as host (current_canvas={use_current_canvas})",
            LogCategory.COLLABORATION,
        )

    def join_session(self, server_url: str, session_id: str, user_id: str) -> None:
        """
        Join an existing session as client.

        Args:
            server_url: WebSocket server URL (e.g., ws://localhost:8765)
            session_id: Session ID to join
            user_id: Your user ID/name
        """
        self.role = "client"
        self.session_id = session_id
        self.initial_sync_complete = False  # Client needs initial sync

        # Clear canvas before joining
        if self.main_window.scene:
            self.main_window.scene.clear()
        self.item_uuid_map.clear()

        # Connect to session
        self.connect_to_session(server_url, session_id, user_id)

        self.log.info(f"Joining session '{session_id}' as client", LogCategory.COLLABORATION)

    def connect_to_session(self, server_url: str, session_id: str, user_id: str) -> None:
        """
        Connect to a collaboration session.

        Args:
            server_url: WebSocket server URL (e.g., ws://localhost:8765)
            session_id: Session ID to join
            user_id: Your user ID/name
        """
        self.session_id = session_id
        self.collaboration_service.set_server_url(server_url)
        self.collaboration_service.connect_to_session(session_id, user_id)
        self.status_changed.emit(f"Connecting to {server_url}...")

    def disconnect(self) -> None:
        """Disconnect from current session."""
        self.collaboration_service.disconnect_from_session()
        self.enabled = False
        self.item_uuid_map.clear()

    def is_connected(self) -> bool:
        """Check if connected to a collaboration session."""
        return self.collaboration_service.is_connected()

    def rebuild_uuid_map(self) -> None:
        """Rebuild the UUID map from current scene items."""
        self.item_uuid_map.clear()
        if not self.main_window.scene:
            return

        for item in self.main_window.scene.items():
            if isinstance(item, Serializable):
                self.item_uuid_map[item.item_uuid] = item

    def broadcast_add_item(self, item: Serializable) -> None:
        """
        Broadcast that an item was added locally.

        Args:
            item: The item that was added (must be Serializable)
        """
        if not self.enabled or self._suppress_broadcast:
            return

        # Suppress during initial sync
        if not self.initial_sync_complete:
            return

        if not isinstance(item, Serializable):
            return

        item_type = self._get_item_type(item)
        if not item_type:
            return

        # Add to UUID map
        self.item_uuid_map[item.item_uuid] = item

        # Increment version
        self._increment_version()

        # Log the broadcast (all QGraphicsItems have x/y)
        if hasattr(item, "x") and hasattr(item, "y") and callable(item.x) and callable(item.y):
            pos = (item.x(), item.y())
        else:
            pos = (0.0, 0.0)
        self.log.info(
            f"Broadcasting ADD: {item_type} at ({pos[0]:.0f}, {pos[1]:.0f})",
            LogCategory.COLLABORATION,
        )

        # Broadcast to other users
        data = item.to_dict()
        # Ensure UUID is in the data for remote recreation
        data["item_uuid"] = item.item_uuid
        self.collaboration_service.send_command(
            action="add_item", item_type=item_type, item_id=item.item_uuid, data=data
        )

    def broadcast_move_item(self, item: Serializable) -> None:
        """
        Broadcast that an item was moved locally.

        Args:
            item: The item that was moved (must be Serializable)
        """
        if not self.enabled or self._suppress_broadcast:
            return

        if not isinstance(item, Serializable):
            return

        item_type = self._get_item_type(item)
        if not item_type:
            return

        # Log the broadcast (all QGraphicsItems have x/y/rotation)
        if hasattr(item, "x") and hasattr(item, "y") and callable(item.x) and callable(item.y):
            pos = (item.x(), item.y())
        else:
            pos = (0.0, 0.0)
        if hasattr(item, "rotation") and callable(item.rotation):
            rot = item.rotation()
        else:
            rot = 0.0
        self.log.debug(
            f"Broadcasting MOVE: {item_type} to ({pos[0]:.0f}, {pos[1]:.0f}) rot={rot:.0f} deg",
            LogCategory.COLLABORATION,
        )

        data = item.to_dict()
        data["item_uuid"] = item.item_uuid
        self.collaboration_service.send_command(
            action="move_item", item_type=item_type, item_id=item.item_uuid, data=data
        )

    def broadcast_remove_item(self, item: Serializable) -> None:
        """
        Broadcast that an item was removed locally.

        Args:
            item: The item that was removed (must be Serializable)
        """
        if not self.enabled or self._suppress_broadcast:
            return

        if not isinstance(item, Serializable):
            return

        item_type = self._get_item_type(item)
        if not item_type:
            return

        # Remove from UUID map
        if item.item_uuid in self.item_uuid_map:
            del self.item_uuid_map[item.item_uuid]

        # Log the broadcast
        self.log.info(f"Broadcasting REMOVE: {item_type}", LogCategory.COLLABORATION)

        self.collaboration_service.send_command(
            action="remove_item", item_type=item_type, item_id=item.item_uuid, data={}
        )

    def broadcast_update_item(self, item: Serializable) -> None:
        """
        Broadcast that an item was updated locally.

        Args:
            item: The item that was updated (must be Serializable)
        """
        if not self.enabled or self._suppress_broadcast:
            return

        if not isinstance(item, Serializable):
            return

        item_type = self._get_item_type(item)
        if not item_type:
            return

        # Log the broadcast
        self.log.info(f"Broadcasting UPDATE: {item_type}", LogCategory.COLLABORATION)

        data = item.to_dict()
        data["item_uuid"] = item.item_uuid
        self.collaboration_service.send_command(
            action="update_item", item_type=item_type, item_id=item.item_uuid, data=data
        )

    def _get_item_type(self, item: Serializable) -> str | None:
        """Get the type string for an item using centralized TypeRegistry."""
        return TypeRegistry.get_type_for_item(item)

    def _on_connected(self) -> None:
        """Handle successful connection."""
        from datetime import datetime

        self.status_changed.emit("Connected!")

        # If reconnecting, request sync
        if self.needs_resync and self.role == "client":
            self.log.info("Reconnected - requesting state sync", LogCategory.COLLABORATION)
            # Send sync request with local version
            self.collaboration_service.send_message(
                {
                    "type": "sync:request",
                    "local_version": self.session_version,
                    "timestamp": datetime.now().isoformat(),
                }
            )

    def _on_disconnected(self) -> None:
        """Handle disconnection."""
        # Cache current state before clearing
        if self.item_uuid_map:
            self.last_known_state = self.get_session_state()

        self.enabled = False
        self.needs_resync = True  # Flag for reconnection
        # Don't clear item_uuid_map yet - keep it for reconnection comparison
        self.status_changed.emit("Disconnected")

    def _on_connection_acknowledged(self, data: dict[str, Any]) -> None:
        """Handle connection acknowledgment with user list."""
        self.enabled = True
        users = data.get("users", [])
        user_count = len(users)
        self.status_changed.emit(f"Connected ({user_count} users)")

        if self.role == "host":
            # Host is the source of truth — upload current canvas to server
            self.rebuild_uuid_map()
            state = self.get_session_state()
            item_count = len(state.get("items", []))
            self.log.info(
                f"Uploading host state to server ({item_count} items)",
                LogCategory.COLLABORATION,
            )
            self.status_changed.emit(f"Uploading {item_count} items to server...")
            self.collaboration_service.send_message(
                {
                    "type": "sync:full_state",
                    "state": state,
                }
            )
            self.status_changed.emit(f"Connected ({user_count} users) — {item_count} items shared")
        else:
            # Client needs to receive state from host/server
            self.status_changed.emit("Requesting state from host...")
            self.collaboration_service.request_sync()
            self.rebuild_uuid_map()

    def _on_command_received(self, message: dict[str, Any]) -> None:
        """
        Handle incoming command from another user.

        Args:
            message: Command message from server
        """
        if not self.enabled:
            return

        command = message.get("command", {})
        action = command.get("action")
        item_type = command.get("item_type")
        item_id = command.get("item_id")
        data = command.get("data", {})

        self.log.debug(
            f"Processing remote command: {action} {item_type} {item_id}", LogCategory.COLLABORATION
        )

        # Suppress broadcasting while applying remote changes
        self._suppress_broadcast = True
        try:
            if action == "add_item":
                self._apply_add_item(item_type, data)
            elif action == "move_item":
                self._apply_move_item(item_id, data)
            elif action == "remove_item":
                self._apply_remove_item(item_id)
            elif action == "update_item":
                self._apply_update_item(item_id, data)
        finally:
            self._suppress_broadcast = False

        # Retrace and refresh layer panel after applying remote command
        if self.main_window.autotrace:
            self.main_window.retrace()
        self.main_window._refresh_layer_panel()

    def _apply_add_item(self, item_type: str, data: dict[str, Any]) -> None:
        """Apply remote add item command.

        Adds item to scene, layer state, and UUID map. Connects signals.
        Does NOT retrace or refresh the layer panel — callers handle that
        so batch operations (sync) can defer to the end.
        """
        # Create item from remote data
        item = self._create_item_from_remote(item_type, data)
        if item:
            # Log the remote add
            pos = (data.get("x_mm", 0), data.get("y_mm", 0))
            self.log.info(
                f"Received ADD: {item_type} at ({pos[0]:.0f}, {pos[1]:.0f})",
                LogCategory.COLLABORATION,
            )

            # Add to scene
            self.main_window.scene.addItem(item)
            # Register in layer state so item appears in the layers panel
            if hasattr(self.main_window, "layer_state") and hasattr(item, "item_uuid"):
                self.main_window.layer_state.add_item(
                    item.item_uuid, None, index=0, emit=False
                )
            # Add to UUID map
            self.item_uuid_map[item.item_uuid] = item
            # Connect item signals (edited, commandCreated, requestDelete)
            # but skip the per-item layer panel refresh — caller will do it
            self._connect_item_signals_no_refresh(item)
        else:
            self.log.error(f"ADD failed: couldn't create {item_type}", LogCategory.COLLABORATION)

        self.remote_item_added.emit(item_type, data)

    def _connect_item_signals_no_refresh(self, item) -> None:
        """Connect item signals without triggering a layer panel refresh.

        Same as MainWindow._connect_item_signals but skips the
        _refresh_layer_panel() call to avoid N refreshes during batch sync.
        """
        from functools import partial

        from ..core.protocols import Editable
        from ..objects import BaseObj
        from ..objects.annotations import RulerItem

        if isinstance(item, Editable):
            item.edited.connect(self.main_window._maybe_retrace)  # type: ignore[attr-defined]
            item.edited.connect(  # type: ignore[attr-defined]
                partial(self.main_window.collaboration_manager.broadcast_update_item, item)
            )

        if isinstance(item, BaseObj):
            item.commandCreated.connect(self.main_window.undo_stack.push)
            item.requestDelete.connect(self.main_window._handle_item_delete)
        elif isinstance(item, RulerItem):
            item.commandCreated.connect(self.main_window.undo_stack.push)

    def _create_item_from_remote(self, item_type: str, data: dict[str, Any]):
        """Create an optical component from remote data.

        Uses deserialize_item() for registered types (component, source) which
        properly reconstructs params, image paths, and interfaces.
        Annotation types (ruler, text) are handled separately since they
        don't use the type registry.
        """
        try:
            from ..objects.annotations import RulerItem, TextNoteItem
            from ..objects.type_registry import deserialize_item

            # Extract UUID from data
            item_uuid = data.get("uuid") or data.get("item_uuid")

            # Make a working copy to avoid mutating input
            data_copy = data.copy()

            # Handle annotation types separately (not in type registry)
            if item_type == "ruler":
                data_copy.pop("uuid", None)
                data_copy.pop("item_uuid", None)
                data_copy.pop("item_type", None)
                data_copy.pop("_type", None)
                ruler_item = RulerItem()
                if item_uuid:
                    ruler_item.item_uuid = item_uuid
                ruler_item.from_dict(data_copy)
                return ruler_item

            if item_type == "text":
                data_copy.pop("uuid", None)
                data_copy.pop("item_uuid", None)
                data_copy.pop("item_type", None)
                data_copy.pop("_type", None)
                text_item = TextNoteItem()
                if item_uuid:
                    text_item.item_uuid = item_uuid
                text_item.from_dict(data_copy)
                return text_item

            # For all registered types (component, source, etc.),
            # use deserialize_item which properly reconstructs params,
            # image paths, and interfaces.
            # Ensure _type is present for registry lookup
            if "_type" not in data_copy:
                data_copy["_type"] = item_type

            # Set item_uuid for deserialize_item to pick up
            if item_uuid:
                data_copy["item_uuid"] = item_uuid

            # Remove collaboration-specific fields not expected by deserialize_item
            data_copy.pop("uuid", None)  # deserialize_item uses item_uuid
            data_copy.pop("item_type", None)  # deserialize_item uses _type

            roots = None
            if hasattr(self.main_window, "library_service"):
                roots = self.main_window.library_service.get_all_roots()
            item = deserialize_item(data_copy, library_roots=roots)
            if item is None:
                self.log.error(
                    f"deserialize_item returned None for type '{item_type}'",
                    LogCategory.COLLABORATION,
                )
            return item

        except Exception as e:
            self.log.error(f"Error creating remote item: {e}", LogCategory.COLLABORATION)
            import traceback

            self.log.error(traceback.format_exc(), LogCategory.COLLABORATION)
            return None

    def _apply_move_item(self, item_uuid: str, data: dict[str, Any]) -> None:
        """Apply remote move item command."""
        if item_uuid in self.item_uuid_map:
            from ..core.raytracing_math import user_angle_to_qt

            item = self.item_uuid_map[item_uuid]
            pos = (data.get("x_mm", 0), data.get("y_mm", 0))
            rot = data.get("angle_deg", 0)
            self.log.debug(
                f"Received MOVE: to ({pos[0]:.0f}, {pos[1]:.0f}) rot={rot:.0f} deg",
                LogCategory.COLLABORATION,
            )

            # All items in uuid_map are QGraphicsItems with setPos/setRotation
            if "x_mm" in data and "y_mm" in data:
                item.setPos(data["x_mm"], data["y_mm"])
            if "angle_deg" in data:
                # angle_deg is stored in user convention (CW), convert to Qt (CCW)
                item.setRotation(user_angle_to_qt(data["angle_deg"]))
        else:
            # Item not found, might need to add it
            self.log.warning(
                f"MOVE failed: item {item_uuid[:8]} not found", LogCategory.COLLABORATION
            )
            self.remote_item_moved.emit(item_uuid, data)

    def _apply_remove_item(self, item_uuid: str) -> None:
        """Apply remote remove item command."""
        if item_uuid in self.item_uuid_map:
            item = self.item_uuid_map[item_uuid]
            item_type = self._get_item_type(item)
            self.log.info(f"Received REMOVE: {item_type}", LogCategory.COLLABORATION)

            if self.main_window.scene:
                self.main_window.scene.removeItem(item)
            # Remove from layer state
            if hasattr(self.main_window, "layer_state"):
                self.main_window.layer_state.remove_item(item_uuid, emit=False)
            del self.item_uuid_map[item_uuid]
        else:
            self.log.warning(
                f"REMOVE failed: item {item_uuid[:8]} not found", LogCategory.COLLABORATION
            )
        self.remote_item_removed.emit(item_uuid)

    def _apply_update_item(self, item_uuid: str, data: dict[str, Any]) -> None:
        """Apply remote update item command."""
        if item_uuid in self.item_uuid_map:
            item = self.item_uuid_map[item_uuid]
            item_type = self._get_item_type(item)
            self.log.info(f"Received UPDATE: {item_type}", LogCategory.COLLABORATION)

            # For BaseObj items, use deserialize_item to update
            from ..objects import BaseObj
            from ..objects.type_registry import deserialize_item

            if isinstance(item, BaseObj):
                # Recreate item from updated data using deserialize_item
                data_copy = data.copy()
                if "_type" not in data_copy:
                    data_copy["_type"] = item_type
                roots = None
                if hasattr(self.main_window, "library_service"):
                    roots = self.main_window.library_service.get_all_roots()
                updated_item = deserialize_item(data_copy, library_roots=roots)
                if updated_item:
                    # Copy state to existing item
                    if hasattr(item, "params") and hasattr(updated_item, "params"):
                        item.params = updated_item.params  # type: ignore[attr-defined]
                    item.setPos(updated_item.pos())
                    item.setRotation(updated_item.rotation())
                    item.setZValue(updated_item.zValue())
                    if isinstance(updated_item, Lockable):
                        item.set_locked(updated_item.is_locked())
                    # Trigger update
                    if isinstance(item, HasShape):
                        item._update_geom()
                    if isinstance(item, Editable):
                        item.update()
            elif callable(getattr(item, "from_dict", None)):
                # Annotation items use their own from_dict method
                data_copy = data.copy()
                data_copy.pop("uuid", None)
                data_copy.pop("item_uuid", None)
                data_copy.pop("item_type", None)
                item.from_dict(data_copy)
        else:
            self.log.warning(
                f"UPDATE failed: item {item_uuid[:8]} not found", LogCategory.COLLABORATION
            )
        self.remote_item_updated.emit(item_uuid, data)

    def _on_sync_state_received(self, message: dict[str, Any]) -> None:
        """Handle full state synchronization from server."""
        state = message.get("state")
        if not state:
            return

        self.log.info("Received full state sync", LogCategory.COLLABORATION)

        # Host is the source of truth — ignore incoming state syncs
        # (these are echoes of our own upload or stale server state)
        if self.role == "host":
            self.log.info(
                "Ignoring state sync (we are the host)", LogCategory.COLLABORATION
            )
            return

        # Check for version conflict
        conflict_resolution = message.get("conflict_resolution", "host_wins")
        has_conflict = self._detect_version_conflict(state)

        if has_conflict and self.role == "client":
            self.log.warning(
                f"Version conflict detected: local={self.session_version}, "
                f"remote={state.get('version', 0)}",
                LogCategory.COLLABORATION,
            )
            self.log.info(
                f"Resolving with strategy: {conflict_resolution}", LogCategory.COLLABORATION
            )

        # Clear scene and layer state before applying state
        if self.main_window.scene:
            for item in list(self.main_window.scene.items()):
                self.main_window.scene.removeItem(item)
        if hasattr(self.main_window, "layer_state"):
            self.main_window.layer_state.clear()

        self.item_uuid_map.clear()

        # Suppress broadcast while applying state
        self._suppress_broadcast = True
        try:
            # Apply all items from state (no per-item retrace or layer refresh)
            items = state.get("items", [])
            total = len(items)
            self.log.info(f"Applying {total} items from state sync", LogCategory.COLLABORATION)
            self.status_changed.emit(f"Syncing: 0/{total} items...")

            succeeded = 0
            failed = 0
            for i, item_data in enumerate(items):
                item_type = item_data.get("item_type")
                if item_type:
                    self._apply_add_item(item_type, item_data)
                    succeeded += 1
                else:
                    failed += 1
                    self.log.warning(
                        f"Skipped item {i}: no item_type", LogCategory.COLLABORATION
                    )
                # Update progress every few items
                if (i + 1) % 5 == 0 or (i + 1) == total:
                    self.status_changed.emit(f"Syncing: {i + 1}/{total} items...")

            # Update version
            self.session_version = state.get("version", 0)
            self.last_known_state = state
            self.initial_sync_complete = True
            self.needs_resync = False

            # Emit layer state change once (triggers layer panel rebuild)
            if hasattr(self.main_window, "layer_state"):
                self.main_window.layer_state.changed.emit()

            # Single retrace for entire scene
            if self.main_window.autotrace:
                self.main_window.retrace()

            # Refresh layer panel once
            self.main_window._refresh_layer_panel()

            # Show completion status
            status = f"Sync complete: {succeeded} items"
            if failed:
                status += f" ({failed} failed)"
            self.status_changed.emit(status)

            self.log.info(
                f"State sync complete - version {self.session_version}", LogCategory.COLLABORATION
            )
        finally:
            self._suppress_broadcast = False

    def _on_user_joined(self, user_id: str) -> None:
        """Handle user joined notification."""
        self.log.info(f"User joined: {user_id}", LogCategory.COLLABORATION)
        self.status_changed.emit(f"{user_id} joined")

        # If we're the host, send full state to new client
        if self.role == "host":
            self.rebuild_uuid_map()
            state = self.get_session_state()
            item_count = len(state.get("items", []))
            self.log.info(
                f"Sending {item_count} items to new client: {user_id}",
                LogCategory.COLLABORATION,
            )
            self.status_changed.emit(f"Sending {item_count} items to {user_id}...")
            self.collaboration_service.send_message(
                {
                    "type": "sync:full_state",
                    "state": state,
                    "target_user": user_id,  # Optional: target specific user
                }
            )
            self.status_changed.emit(f"{user_id} joined — {item_count} items sent")

    def _on_user_left(self, user_id: str) -> None:
        """Handle user left notification."""
        self.log.info(f"👤 User left: {user_id}", LogCategory.COLLABORATION)
        self.status_changed.emit(f"{user_id} left")

    def _on_error(self, error: str) -> None:
        """Handle collaboration error."""
        self.status_changed.emit(f"Error: {error}")

    def get_session_state(self) -> dict[str, Any]:
        """
        Get complete session state including all items.

        Returns:
            Dictionary containing complete canvas state with version
        """
        items = []
        for item_uuid, item in self.item_uuid_map.items():
            if isinstance(item, Serializable):
                item_data = item.to_dict()
                item_data["uuid"] = item_uuid
                item_data["item_type"] = self._get_item_type(item)
                items.append(item_data)

        from datetime import datetime

        state = {
            "items": items,
            "version": self.session_version,
            "timestamp": datetime.now().isoformat(),
        }

        return state

    def _increment_version(self) -> None:
        """Increment session version counter."""
        self.session_version += 1
        self.last_known_state = self.get_session_state()

    def _detect_version_conflict(self, remote_state: dict[str, Any]) -> bool:
        """
        Detect if remote state version conflicts with local version.

        Args:
            remote_state: Remote state dictionary with version

        Returns:
            True if versions conflict, False otherwise
        """
        remote_version = remote_state.get("version", 0)
        return bool(remote_version != self.session_version)
