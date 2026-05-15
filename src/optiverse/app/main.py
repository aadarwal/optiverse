"""
Optiverse Application Entry Point.

This module provides the main() function that bootstraps the Qt application.
Theme management is delegated to ui.theme_manager.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

# Module logger
_logger = logging.getLogger(__name__)


def _configure_opengl() -> None:
    """Configure OpenGL surface format before QApplication creation."""
    try:
        fmt = QtGui.QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)  # 4x MSAA for antialiasing
        fmt.setVersion(2, 1)  # OpenGL 2.1 for macOS compatibility
        fmt.setProfile(QtGui.QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setAlphaBufferSize(8)  # Enable alpha channel for transparency
        QtGui.QSurfaceFormat.setDefaultFormat(fmt)
        _logger.info("OpenGL surface format configured: 4x MSAA, OpenGL 2.1")
    except Exception as e:
        _logger.warning("Failed to configure OpenGL format: %s", e)


def _configure_macos_app_name() -> str:
    """
    Configure macOS app name in menu bar.

    Returns the original argv[0] to restore after QApplication creation.
    """
    original_argv0 = sys.argv[0]
    sys.argv[0] = "Optiverse"

    # Use pyobjc to set process name (macOS only)
    try:
        from Foundation import NSProcessInfo

        processInfo = NSProcessInfo.processInfo()
        processInfo.setProcessName_("Optiverse")
        _logger.info("macOS process name set to 'Optiverse' via pyobjc")
    except ImportError:
        _logger.debug("pyobjc not available - app name in menu bar may show as 'Python'")
    except Exception as e:
        _logger.warning("Failed to set macOS process name: %s", e)

    return original_argv0


def _configure_macos_activation() -> None:
    """Configure macOS NSApp activation after QApplication creation."""
    try:
        from AppKit import NSRunningApplication

        NSRunningApplication.currentApplication().activateWithOptions_(1 << 1)
        _logger.info("macOS NSApp activation configured")
    except Exception as e:
        _logger.debug("Failed to configure NSApp: %s", e)


def _extract_initial_scene_path(argv: Sequence[str]) -> tuple[list[str], Path | None]:
    """Split a positional scene path from Qt/application arguments."""
    qt_argv = [argv[0]]
    initial_scene_path: Path | None = None
    for arg in argv[1:]:
        if initial_scene_path is None and not arg.startswith("-") and arg.endswith(".json"):
            initial_scene_path = Path(arg)
        else:
            qt_argv.append(arg)
    return qt_argv, initial_scene_path


def main(argv: Sequence[str] | None = None) -> int:
    """
    Application entry point.

    Bootstraps the Qt application, configures platform-specific settings,
    and launches the main window.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    raw_argv = list(sys.argv if argv is None else argv)
    qt_argv, initial_scene_path = _extract_initial_scene_path(raw_argv)

    # Install stderr filter to suppress harmless macOS warnings (TSM errors)
    from ..platform.macos import install_macos_stderr_filter

    install_macos_stderr_filter()

    # Configure basic logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    # Install global error handler FIRST (before any Qt code)
    from ..services.error_handler import get_error_handler, install_qt_message_handler

    error_handler = get_error_handler()
    _logger.info("Global error handler installed")

    # Increase Qt's image allocation limit for large SVG cache files
    # Default is 256MB, we set to 1GB to allow high-resolution cached PNGs
    os.environ["QT_IMAGEIO_MAXALLOC"] = "1024"  # In MB

    # Configure OpenGL before QApplication
    _configure_opengl()

    # Configure macOS app name before QApplication
    original_argv0 = _configure_macos_app_name()

    # Create QApplication (Qt6 enables high DPI by default)
    app = QtWidgets.QApplication(qt_argv)

    # Force period as decimal separator program-wide (regardless of system locale)
    QtCore.QLocale.setDefault(QtCore.QLocale.c())

    # Install Qt message handler
    install_qt_message_handler()
    _logger.info("Qt message handler installed")

    # Restore original argv[0]
    sys.argv[0] = original_argv0

    # Configure Qt application metadata
    app.setApplicationName("Optiverse")
    app.setApplicationDisplayName("Optiverse")
    app.setOrganizationName("Optiverse")
    app.setOrganizationDomain("optiverse.app")

    # Configure macOS activation
    _configure_macos_activation()

    # Set application icon
    icon_path = Path(__file__).parent.parent / "ui" / "icons" / "optiverse.png"
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))

    # Apply initial theme based on system preference
    from ..ui.theme_manager import apply_theme, detect_system_dark_mode

    system_dark_mode = detect_system_dark_mode()
    apply_theme(system_dark_mode)

    # Create and show main window
    from ..ui.views.main_window import MainWindow

    try:
        window = MainWindow()
        window.show()
        if initial_scene_path is not None:
            scene_path = initial_scene_path.resolve()

            def load_initial_scene() -> None:
                if not window.open_recent_file(str(scene_path)):
                    _logger.warning("Failed to open initial scene: %s", scene_path)

            QtCore.QTimer.singleShot(0, load_initial_scene)
    except Exception as e:
        error_handler.handle_error(e, "during application startup")
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
