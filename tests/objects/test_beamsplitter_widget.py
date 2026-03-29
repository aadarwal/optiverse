
from tests.helpers import safe_wait_exposed


def test_beamsplitter_placement_infrastructure(qtbot):
    """Verify beamsplitter placement goes through tool controller."""
    from optiverse.ui.views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    safe_wait_exposed(qtbot, w)

    assert hasattr(w, "tool_controller")
    assert hasattr(w.tool_controller, "toggle_placement")
