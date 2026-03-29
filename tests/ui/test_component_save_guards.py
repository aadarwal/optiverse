"""Tests for component editor save guards (name uniqueness, builtin protection)."""

from __future__ import annotations

import pytest

try:
    from PyQt6 import QtGui, QtWidgets

    HAVE_PYQT6 = True
except ImportError:
    HAVE_PYQT6 = False

pytestmark = pytest.mark.skipif(not HAVE_PYQT6, reason="PyQt6 not available")


@pytest.fixture()
def editor(qtbot, tmp_path):
    """Create a ComponentEditor backed by a temporary library directory."""
    from optiverse.services.storage_service import StorageService
    from optiverse.ui.views.component_editor_dialog import ComponentEditor

    storage = StorageService(library_path=str(tmp_path))
    ed = ComponentEditor(storage=storage)
    qtbot.addWidget(ed)
    return ed


def _set_dummy_image(editor):
    """Load a minimal image so the editor considers the component valid."""
    img = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
    img.fill(0)
    editor.canvas.set_pixmap(QtGui.QPixmap.fromImage(img))
    editor.object_height_mm.setValue(25.4)


# ---------- Tracking context ----------


class TestTrackingContext:
    def test_new_component_has_no_tracking(self, editor):
        assert editor._original_name is None
        assert editor._component_source is None

    def test_load_from_dict_sets_tracking(self, editor):
        data = {
            "name": "My Lens",
            "object_height_mm": 25.4,
            "interfaces": [],
            "_source": "user",
        }
        editor._load_from_dict(data)
        assert editor._original_name == "My Lens"
        assert editor._component_source == "user"

    def test_load_builtin_sets_source(self, editor):
        data = {
            "name": "Standard Lens 1in",
            "object_height_mm": 25.4,
            "interfaces": [],
            "_source": "builtin",
        }
        editor._load_from_dict(data)
        assert editor._original_name == "Standard Lens 1in"
        assert editor._component_source == "builtin"

    def test_new_component_resets_tracking(self, editor):
        editor._load_from_dict(
            {"name": "Foo", "object_height_mm": 10, "interfaces": [], "_source": "user"}
        )
        editor._new_component()
        assert editor._original_name is None
        assert editor._component_source is None


# ---------- Builtin guard ----------


class TestBuiltinGuard:
    def test_builtin_component_save_blocked_and_prompts(self, editor, monkeypatch):
        """Saving a builtin component must prompt for a new name."""
        _set_dummy_image(editor)
        editor._load_from_dict(
            {
                "name": "Standard Lens 1in",
                "object_height_mm": 25.4,
                "interfaces": [],
                "_source": "builtin",
            }
        )

        # Stub the helpers so we control what names exist
        monkeypatch.setattr(
            editor, "_get_builtin_names", lambda: {"Standard Lens 1in", "Standard Mirror 1in"}
        )
        monkeypatch.setattr(
            editor,
            "_get_all_component_names",
            lambda: {"Standard Lens 1in", "Standard Mirror 1in"},
        )

        # Track dialogs shown
        info_shown = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "information",
            lambda *args, **kw: info_shown.append(args),
        )

        # Simulate user entering a new unique name
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getText",
            lambda *a, **kw: ("My Custom Lens", True),
        )

        result = editor.save_component()

        assert result is True
        assert len(info_shown) >= 1  # the "Standard Component" info dialog
        assert editor.name_edit.text() == "My Custom Lens"
        assert editor._original_name == "My Custom Lens"
        assert editor._component_source == "user"

    def test_builtin_save_cancelled_when_user_cancels_name(self, editor, monkeypatch):
        """If the user cancels the name prompt, save should abort."""
        _set_dummy_image(editor)
        editor._load_from_dict(
            {
                "name": "Standard Lens 1in",
                "object_height_mm": 25.4,
                "interfaces": [],
                "_source": "builtin",
            }
        )

        monkeypatch.setattr(
            editor, "_get_builtin_names", lambda: {"Standard Lens 1in"}
        )
        monkeypatch.setattr(
            editor, "_get_all_component_names", lambda: {"Standard Lens 1in"}
        )
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "information", lambda *a, **kw: None
        )
        # User cancels the name dialog
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("", False)
        )

        result = editor.save_component()
        assert result is False

    def test_user_component_with_builtin_name_is_blocked(self, editor, monkeypatch):
        """Even a user-source component whose name matches a builtin is blocked."""
        _set_dummy_image(editor)
        editor.name_edit.setText("Standard Mirror 1in")
        editor._original_name = None
        editor._component_source = None

        monkeypatch.setattr(
            editor, "_get_builtin_names", lambda: {"Standard Mirror 1in"}
        )
        monkeypatch.setattr(
            editor, "_get_all_component_names", lambda: {"Standard Mirror 1in"}
        )
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "information", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("", False)
        )

        result = editor.save_component()
        assert result is False


# ---------- User replace / copy guard ----------


class TestUserReplaceOrCopy:
    def test_replace_existing_component(self, editor, monkeypatch):
        """Choosing 'Replace' overwrites the same component."""
        _set_dummy_image(editor)
        editor.name_edit.setText("My Lens")
        editor._original_name = "My Lens"
        editor._component_source = "user"

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: {"My Lens"})

        # Simulate clicking "Replace" button
        def fake_exec(self_msg):
            for btn in self_msg.buttons():
                if btn.text() == "Replace":
                    self_msg.clickedButton = lambda _btn=btn: _btn
                    return
            raise AssertionError("Replace button not found")

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)

        result = editor.save_component()
        assert result is True
        assert editor._original_name == "My Lens"

    def test_save_as_copy_prompts_for_name(self, editor, monkeypatch):
        """Choosing 'Save as Copy' prompts for a new unique name."""
        _set_dummy_image(editor)
        editor.name_edit.setText("My Lens")
        editor._original_name = "My Lens"
        editor._component_source = "user"

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: {"My Lens"})

        # Simulate clicking "Save as Copy" button
        def fake_exec(self_msg):
            for btn in self_msg.buttons():
                if btn.text() == "Save as Copy":
                    self_msg.clickedButton = lambda _btn=btn: _btn
                    return
            raise AssertionError("Save as Copy button not found")

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)

        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("My Lens (Copy)", True)
        )

        result = editor.save_component()
        assert result is True
        assert editor.name_edit.text() == "My Lens (Copy)"
        assert editor._original_name == "My Lens (Copy)"

    def test_cancel_replace_dialog_aborts(self, editor, monkeypatch):
        """Cancelling the replace/copy dialog aborts the save."""
        _set_dummy_image(editor)
        editor.name_edit.setText("My Lens")
        editor._original_name = "My Lens"
        editor._component_source = "user"

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: {"My Lens"})

        # Simulate clicking Cancel
        def fake_exec(self_msg):
            for btn in self_msg.buttons():
                if self_msg.buttonRole(btn) == QtWidgets.QMessageBox.ButtonRole.RejectRole:
                    self_msg.clickedButton = lambda _btn=btn: _btn
                    return
            raise AssertionError("Cancel button not found")

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)

        result = editor.save_component()
        assert result is False


# ---------- Name uniqueness guard ----------


class TestNameUniqueness:
    def test_new_component_with_duplicate_name_blocked(self, editor, monkeypatch):
        """New component whose name collides with existing is blocked."""
        _set_dummy_image(editor)
        editor.name_edit.setText("Existing Lens")
        editor._original_name = None
        editor._component_source = None

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: {"Existing Lens"})

        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **kw: None)
        # User cancels the name prompt
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("", False)
        )

        result = editor.save_component()
        assert result is False

    def test_renamed_component_with_unique_name_saves(self, editor, monkeypatch):
        """User renames a component to a unique name — should save directly."""
        _set_dummy_image(editor)
        editor.name_edit.setText("Brand New Name")
        editor._original_name = "Old Name"
        editor._component_source = "user"

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: {"Old Name"})

        result = editor.save_component()
        assert result is True
        assert editor._original_name == "Brand New Name"
        assert editor._component_source == "user"

    def test_new_component_with_unique_name_saves(self, editor, monkeypatch):
        """Brand new component with a unique name saves without prompts."""
        _set_dummy_image(editor)
        editor.name_edit.setText("Unique Component")
        editor._original_name = None
        editor._component_source = None

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: set())

        result = editor.save_component()
        assert result is True
        assert editor._original_name == "Unique Component"
        assert editor._component_source == "user"

    def test_renamed_component_colliding_with_existing_prompts(self, editor, monkeypatch):
        """User renames component to a name that already exists — prompted for new name."""
        _set_dummy_image(editor)
        editor.name_edit.setText("Taken Name")
        editor._original_name = "Old Name"
        editor._component_source = "user"

        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        monkeypatch.setattr(editor, "_get_all_component_names", lambda: {"Taken Name", "Old Name"})

        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("Fresh Name", True)
        )

        result = editor.save_component()
        assert result is True
        assert editor.name_edit.text() == "Fresh Name"
        assert editor._original_name == "Fresh Name"


# ---------- _prompt_for_unique_name ----------


class TestPromptForUniqueName:
    def test_accepts_unique_name(self, editor, monkeypatch):
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("Good Name", True)
        )
        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        result = editor._prompt_for_unique_name("Suggestion", {"Existing"})
        assert result == "Good Name"

    def test_returns_none_on_cancel(self, editor, monkeypatch):
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("", False)
        )
        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        result = editor._prompt_for_unique_name("Suggestion", {"Existing"})
        assert result is None

    def test_rejects_duplicate_then_accepts(self, editor, monkeypatch):
        """First attempt returns duplicate, second returns unique."""
        call_count = [0]

        def fake_get_text(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("Existing", True)  # duplicate
            return ("Unique", True)

        monkeypatch.setattr(QtWidgets.QInputDialog, "getText", fake_get_text)
        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())

        result = editor._prompt_for_unique_name("Suggestion", {"Existing"})
        assert result == "Unique"
        assert call_count[0] == 2

    def test_allow_name_bypasses_duplicate_check(self, editor, monkeypatch):
        monkeypatch.setattr(
            QtWidgets.QInputDialog, "getText", lambda *a, **kw: ("Existing", True)
        )
        monkeypatch.setattr(editor, "_get_builtin_names", lambda: set())
        result = editor._prompt_for_unique_name("Suggestion", {"Existing"}, allow_name="Existing")
        assert result == "Existing"

    def test_rejects_builtin_name(self, editor, monkeypatch):
        """Names matching builtin components are rejected even if not in all_names."""
        call_count = [0]

        def fake_get_text(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return ("Standard Lens 1in", True)
            return ("My Custom Lens", True)

        monkeypatch.setattr(QtWidgets.QInputDialog, "getText", fake_get_text)
        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(editor, "_get_builtin_names", lambda: {"Standard Lens 1in"})

        result = editor._prompt_for_unique_name("Suggestion", set())
        assert result == "My Custom Lens"
        assert call_count[0] == 2
