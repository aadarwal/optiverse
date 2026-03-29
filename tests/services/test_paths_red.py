import os


def test_platform_paths_exposes_core_dirs(tmp_path, monkeypatch):
    # Force HOME to tmp so paths resolve under it for the test
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows

    from optiverse.platform.paths import assets_dir, get_user_library_root, library_root_dir

    root = library_root_dir()
    assets = assets_dir()
    lib_root = get_user_library_root()

    assert os.path.isdir(root)
    assert os.path.isdir(assets)
    assert lib_root.parent == lib_root.parent  # Path object is valid
