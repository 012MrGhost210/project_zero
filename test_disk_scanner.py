"""Smoke tests for read-only disk scanner."""

from __future__ import annotations

from pathlib import Path

from disk_scanner import human_size, resolve_existing_dir, scan_directory, volume_info


def test_human_size():
    assert human_size(0) == "0 B"
    assert human_size(1024).endswith("KB")
    assert "MB" in human_size(5 * 1024 * 1024)


def test_scan_tmp_tree(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "big.bin").write_bytes(b"x" * 4096)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "small.txt").write_text("hi")
    (tmp_path / "root.txt").write_bytes(b"y" * 100)

    result = scan_directory(tmp_path, top_n=10)
    assert result.total_bytes == 4096 + 2 + 100
    assert result.entries_seen == 3
    assert result.files[0].size_bytes == 4096
    assert any(f.path.endswith(str(Path("a"))) or f.path.endswith("/a") for f in result.folders)

    # Scanner must not create extra files under target.
    before = {p.name for p in tmp_path.rglob("*")}
    scan_directory(tmp_path, top_n=5)
    after = {p.name for p in tmp_path.rglob("*")}
    assert before == after


def test_resolve_and_volume(tmp_path: Path):
    p = resolve_existing_dir(str(tmp_path))
    assert p.is_dir()
    vol = volume_info(p)
    assert vol is not None
    assert vol.total_bytes > 0
    assert vol.available_bytes >= 0


def test_invalid_path():
    try:
        resolve_existing_dir("/nonexistent/path/xyz-disk-monitor")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
