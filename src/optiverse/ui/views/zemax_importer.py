"""
Zemax file import functionality for the Component Editor.

Extracts Zemax import logic from component_editor_dialog.py for better modularity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6 import QtCore, QtWidgets

if TYPE_CHECKING:
    from ...core.models import ComponentRecord


class ZemaxImporter:
    """
    Handles importing Zemax ZMX files into the component editor.

    This class encapsulates all Zemax-related import logic, making
    the component editor cleaner and more focused.
    """

    def __init__(self, parent_widget: QtWidgets.QWidget):
        """
        Initialize the Zemax importer.

        Args:
            parent_widget: Parent widget for dialogs
        """
        self.parent = parent_widget

    def import_file(self) -> ComponentRecord | None:
        """
        Show file dialog and import a Zemax ZMX file.

        Returns:
            ComponentRecord if successful, None otherwise
        """
        from ...services.glass_catalog import GlassCatalog
        from ...services.zemax_converter import ZemaxToInterfaceConverter
        from ...services.zemax_parser import ZemaxParser

        dlg = QtWidgets.QFileDialog(self.parent, "Import Zemax File", "")
        dlg.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        dlg.setNameFilter("Zemax Files (*.zmx *.ZMX);;All Files (*.*)")
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        files = dlg.selectedFiles()
        filepath = files[0] if files else ""

        if not filepath:
            return None

        try:
            # Parse Zemax file
            parser = ZemaxParser()
            zemax_data = parser.parse(filepath)

            if not zemax_data:
                QtWidgets.QMessageBox.critical(
                    self.parent,
                    "Import Error",
                    "Failed to parse Zemax file. "
                    "The file may be corrupted or in an unsupported format.",
                )
                return None

            # Convert to interfaces
            catalog = GlassCatalog()
            converter = ZemaxToInterfaceConverter(catalog)
            component = converter.convert(zemax_data)

            # Show success message
            self._show_success_message(component)

            return component

        except Exception as e:
            import traceback

            error_details = traceback.format_exc()
            QtWidgets.QMessageBox.critical(
                self.parent,
                "Import Error",
                f"Error importing Zemax file:\n\n{str(e)}\n\nDetails:\n{error_details}",
            )
            return None

    def _show_success_message(self, component: ComponentRecord) -> None:
        """Show success message with import summary."""
        num_interfaces = len(component.interfaces) if component.interfaces else 0

        # Determine component type from interfaces
        if num_interfaces > 1:
            component_type = f"Multi-element ({num_interfaces} interfaces)"
        elif num_interfaces == 1 and component.interfaces:
            element_type = component.interfaces[0].element_type.replace("_", " ").title()
            component_type = element_type
        else:
            component_type = "Unknown"

        msg = f"Successfully imported {num_interfaces} interface(s) from Zemax file:\n\n"
        msg += f"Name: {component.name}\n"
        msg += f"Type: {component_type}\n"
        msg += f"Aperture: {component.object_height_mm:.2f} mm\n\n"

        if component.interfaces:
            msg += "Interfaces:\n"
            for i, iface in enumerate(component.interfaces[:5]):  # Show first 5
                curv_str = f" [R={iface.radius_of_curvature_mm:.1f}mm]" if iface.is_curved else ""
                msg += f"  {i + 1}. {iface.name}{curv_str}\n"
            if num_interfaces > 5:
                msg += f"  ... and {num_interfaces - 5} more\n"

            msg += "\n"
            msg += "💡 TIP: Load an image (File → Open Image) to visualize\n"
            msg += "    the interfaces on the canvas. The interfaces are listed\n"
            msg += "    in the panel on the right.\n"
            msg += "\n"
            msg += "👉 Expand each interface in the list to see:\n"
            msg += "   • Refractive indices (n₁, n₂)\n"
            msg += "   • Curvature (is_curved, radius_of_curvature_mm)\n"
            msg += "   • Position and geometry\n"

        QtWidgets.QMessageBox.information(self.parent, "Import Successful", msg)
