"""Tests for the local release automation script."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.release import (
    ReleaseError,
    ReleasePaths,
    build_release_archive,
    build_release_notes,
    bump_version,
    read_current_version,
    update_version_files,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_repo_fixture(tmp_path: Path) -> ReleasePaths:
    _write(
        tmp_path / "custom_components" / "pos_printer" / "manifest.json",
        json.dumps({"domain": "pos_printer", "version": "0.2.0"}, indent=2) + "\n",
    )
    _write(tmp_path / "bridge" / "bridge_version.py", 'BRIDGE_VERSION = "0.2.0"\n')
    _write(tmp_path / "custom_components" / "pos_printer" / "__init__.py", '"""init"""\n')
    _write(tmp_path / "blueprints" / "automation" / "pos_printer" / "sample.yaml", "id: 1\n")
    _write(tmp_path / "README.md", "# POS-Printer Bridge\n")
    _write(tmp_path / "hacs.json", "{}\n")
    _write(tmp_path / "LICENSE", "MIT\n")
    return ReleasePaths.from_repo_root(tmp_path)


def test_bump_version_supports_all_levels() -> None:
    assert bump_version("0.2.0", "patch") == "0.2.1"
    assert bump_version("0.2.0", "minor") == "0.3.0"
    assert bump_version("0.2.0", "major") == "1.0.0"


def test_read_current_version_rejects_mismatch(tmp_path: Path) -> None:
    paths = _create_repo_fixture(tmp_path)
    paths.bridge_version_path.write_text('BRIDGE_VERSION = "0.3.0"\n', encoding="utf-8")

    with pytest.raises(ReleaseError, match="Version mismatch"):
        read_current_version(paths)


def test_update_version_files_and_build_archive(tmp_path: Path) -> None:
    paths = _create_repo_fixture(tmp_path)

    updated_files = update_version_files(paths, "0.2.1")
    assert updated_files == [paths.manifest_path, paths.bridge_version_path]
    assert read_current_version(paths) == "0.2.1"

    release_dir = tmp_path / "dist" / "releases" / "0.2.1"
    archive_path = build_release_archive(paths, release_dir, "0.2.1")

    assert archive_path.exists()
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())

    assert "custom_components/pos_printer/__init__.py" in names
    assert "blueprints/automation/pos_printer/sample.yaml" in names
    assert "README.md" in names
    assert "hacs.json" in names


def test_build_release_notes_mentions_publish_steps() -> None:
    notes = build_release_notes("0.2.1", "0.2.0", ["Add release automation"])

    assert "# Release v0.2.1" in notes
    assert "Changes since `0.2.0`" in notes
    assert "- Add release automation" in notes
    assert "Create or verify git tag `0.2.1`." in notes
