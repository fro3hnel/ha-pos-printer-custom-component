#!/usr/bin/env python3
"""Automate local release preparation for the POS printer project."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
BRIDGE_VERSION_PATTERN = re.compile(r'^(BRIDGE_VERSION = ")([^"]+)(")$', re.MULTILINE)
RELEASE_COMMIT_TEMPLATE = "Release {version}"
RELEASE_TITLE_TEMPLATE = "Release v{version}"
DEFAULT_OUTPUT_DIR = Path("dist") / "releases"


class ReleaseError(RuntimeError):
    """Raised when release preparation cannot continue safely."""


@dataclass(frozen=True)
class ReleasePaths:
    """Resolved paths used by the release workflow."""

    repo_root: Path
    manifest_path: Path
    bridge_version_path: Path
    integration_dir: Path
    blueprints_dir: Path
    readme_path: Path
    hacs_path: Path
    license_path: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "ReleasePaths":
        """Build release paths from the repository root."""
        return cls(
            repo_root=repo_root,
            manifest_path=repo_root / "custom_components" / "pos_printer" / "manifest.json",
            bridge_version_path=repo_root / "bridge" / "bridge_version.py",
            integration_dir=repo_root / "custom_components" / "pos_printer",
            blueprints_dir=repo_root / "blueprints" / "automation" / "pos_printer",
            readme_path=repo_root / "README.md",
            hacs_path=repo_root / "hacs.json",
            license_path=repo_root / "LICENSE",
        )

    @property
    def version_files(self) -> tuple[Path, Path]:
        """Files that must carry the release version."""
        return (self.manifest_path, self.bridge_version_path)

    @property
    def release_bundle_sources(self) -> tuple[Path, ...]:
        """Files and directories included in the HA release archive."""
        return (
            self.integration_dir,
            self.blueprints_dir,
            self.readme_path,
            self.hacs_path,
            self.license_path,
        )


@dataclass(frozen=True)
class ReleaseArtifacts:
    """Generated release outputs."""

    version: str
    previous_version: str
    previous_tag: str | None
    release_dir: Path
    archive_path: Path
    notes_path: Path

    @property
    def tag_name(self) -> str:
        """Tag name used for bridge self-updates."""
        return self.version

    @property
    def release_title(self) -> str:
        """Human-readable release title."""
        return RELEASE_TITLE_TEMPLATE.format(version=self.version)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the next local release by bumping versions, running tests, "
            "building the Home Assistant archive, and generating release notes."
        )
    )
    version_group = parser.add_mutually_exclusive_group(required=True)
    version_group.add_argument(
        "--version",
        help="Explicit semantic version to release, for example 0.2.1.",
    )
    version_group.add_argument(
        "--bump",
        choices=("patch", "minor", "major"),
        help="Calculate the next semantic version from the current one.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the current project root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where release artifacts will be written.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip the mandatory pytest run.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow running with local uncommitted changes.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Create a release commit after preparing the files.",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Create the git tag matching the released bridge version.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the workflow and print the planned actions without changing files.",
    )
    args = parser.parse_args(argv)
    if args.tag and not args.commit:
        parser.error("--tag requires --commit.")
    return args


def parse_version(value: str) -> tuple[int, int, int]:
    """Parse a semantic version into numeric parts."""
    match = SEMVER_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ReleaseError(
            f"Invalid version '{value}'. Expected semantic version X.Y.Z with numeric parts."
        )
    return tuple(int(part) for part in match.groups())


def format_version(parts: tuple[int, int, int]) -> str:
    """Format a semantic version tuple back to a string."""
    return ".".join(str(part) for part in parts)


def bump_version(current_version: str, part: str) -> str:
    """Calculate the next semantic version."""
    major, minor, patch = parse_version(current_version)
    if part == "patch":
        patch += 1
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ReleaseError(f"Unsupported bump type '{part}'.")
    return format_version((major, minor, patch))


def ensure_version_order(current_version: str, target_version: str) -> None:
    """Reject releases that do not advance the version."""
    if parse_version(target_version) <= parse_version(current_version):
        raise ReleaseError(
            f"Target version {target_version} must be greater than current version {current_version}."
        )


def read_manifest_version(path: Path) -> str:
    """Read the integration version from manifest.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str):
        raise ReleaseError(f"Missing string version in {path}.")
    parse_version(version)
    return version


def write_manifest_version(path: Path, version: str) -> None:
    """Write the integration version to manifest.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_bridge_version(path: Path) -> str:
    """Read the bridge version constant."""
    content = path.read_text(encoding="utf-8")
    match = BRIDGE_VERSION_PATTERN.search(content)
    if match is None:
        raise ReleaseError(f"Could not find BRIDGE_VERSION in {path}.")
    version = match.group(2)
    parse_version(version)
    return version


def write_bridge_version(path: Path, version: str) -> None:
    """Update the bridge version constant."""
    content = path.read_text(encoding="utf-8")
    updated_content, replacements = BRIDGE_VERSION_PATTERN.subn(
        lambda match: f'{match.group(1)}{version}{match.group(3)}',
        content,
        count=1,
    )
    if replacements != 1:
        raise ReleaseError(f"Could not update BRIDGE_VERSION in {path}.")
    path.write_text(updated_content, encoding="utf-8")


def read_current_version(paths: ReleasePaths) -> str:
    """Ensure all authoritative version files are aligned."""
    manifest_version = read_manifest_version(paths.manifest_path)
    bridge_version = read_bridge_version(paths.bridge_version_path)
    versions = {
        str(paths.manifest_path.relative_to(paths.repo_root)): manifest_version,
        str(paths.bridge_version_path.relative_to(paths.repo_root)): bridge_version,
    }
    if len(set(versions.values())) != 1:
        details = ", ".join(f"{name}={value}" for name, value in versions.items())
        raise ReleaseError(f"Version mismatch detected: {details}")
    return manifest_version


def update_version_files(paths: ReleasePaths, version: str) -> list[Path]:
    """Update all release-controlled version files."""
    parse_version(version)
    write_manifest_version(paths.manifest_path, version)
    write_bridge_version(paths.bridge_version_path, version)
    return list(paths.version_files)


def iter_release_bundle_files(paths: ReleasePaths) -> Iterable[Path]:
    """Yield files that should end up in the Home Assistant release archive."""
    for source in paths.release_bundle_sources:
        if not source.exists():
            continue
        if source.is_file():
            yield source
            continue
        for candidate in sorted(source.rglob("*")):
            if candidate.is_file() and "__pycache__" not in candidate.parts:
                yield candidate


def build_release_archive(paths: ReleasePaths, release_dir: Path, version: str) -> Path:
    """Build the Home Assistant release zip archive."""
    release_dir.mkdir(parents=True, exist_ok=True)
    archive_path = release_dir / f"pos_printer-v{version}.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in iter_release_bundle_files(paths):
            archive.write(file_path, file_path.relative_to(paths.repo_root))
    return archive_path


def build_release_notes(version: str, previous_tag: str | None, subjects: Sequence[str]) -> str:
    """Render markdown release notes."""
    if previous_tag:
        headline = f"Changes since `{previous_tag}`"
    else:
        headline = "Changes since repository start"

    lines = [f"# {RELEASE_TITLE_TEMPLATE.format(version=version)}", "", headline, ""]
    if subjects:
        lines.extend(f"- {subject}" for subject in subjects)
    else:
        lines.append("- No commits found in the selected range.")
    lines.extend(
        [
            "",
            "## Publish checklist",
            "",
            f"- Create or verify git tag `{version}`.",
            f"- Upload `pos_printer-v{version}.zip` to the GitHub release if you want a manual install asset.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_command(
    command: Sequence[str],
    cwd: Path,
    *,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and raise a friendly error on failure."""
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=capture_output,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown command failure"
        raise ReleaseError(f"Command failed ({' '.join(command)}): {message}")
    return result


def require_clean_worktree(repo_root: Path) -> None:
    """Ensure the release starts from a clean git worktree."""
    result = run_command(
        ("git", "status", "--short"),
        cwd=repo_root,
        capture_output=True,
    )
    if result.stdout.strip():
        raise ReleaseError(
            "Working tree is not clean. Commit or stash your changes, or rerun with --allow-dirty."
        )


def tag_exists(repo_root: Path, tag_name: str) -> bool:
    """Check whether a git tag already exists."""
    result = run_command(
        ("git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag_name}"),
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def find_latest_tag(repo_root: Path) -> str | None:
    """Return the latest reachable tag, if any."""
    result = run_command(
        ("git", "describe", "--tags", "--abbrev=0"),
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    tag = result.stdout.strip()
    return tag or None


def collect_release_subjects(repo_root: Path, previous_tag: str | None) -> list[str]:
    """Collect commit subjects for release notes."""
    command = ["git", "log", "--first-parent", "--reverse", "--pretty=format:%s"]
    if previous_tag:
        command.append(f"{previous_tag}..HEAD")
    else:
        command.append("HEAD")
    result = run_command(command, cwd=repo_root, capture_output=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def find_test_python(repo_root: Path) -> Path:
    """Prefer the repository virtualenv for test execution when available."""
    candidates = (
        repo_root / ".venv" / "bin" / "python",
        repo_root / ".venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def run_pytest(repo_root: Path) -> None:
    """Execute the repository test suite."""
    python_executable = find_test_python(repo_root)
    run_command((str(python_executable), "-m", "pytest"), cwd=repo_root)


def git_add(repo_root: Path, files: Sequence[Path]) -> None:
    """Stage specific files for a release commit."""
    relative_files = [str(file_path.relative_to(repo_root)) for file_path in files]
    run_command(("git", "add", *relative_files), cwd=repo_root)


def git_commit(repo_root: Path, version: str) -> None:
    """Create the release commit."""
    run_command(
        ("git", "commit", "-m", RELEASE_COMMIT_TEMPLATE.format(version=version)),
        cwd=repo_root,
    )


def git_tag(repo_root: Path, version: str) -> None:
    """Create the release tag expected by bridge self-updates."""
    run_command(
        ("git", "tag", "-a", version, "-m", RELEASE_TITLE_TEMPLATE.format(version=version)),
        cwd=repo_root,
    )


def prepare_release(args: argparse.Namespace) -> ReleaseArtifacts:
    """Execute the local release preparation workflow."""
    repo_root = args.repo_root.resolve()
    paths = ReleasePaths.from_repo_root(repo_root)

    if not args.allow_dirty:
        require_clean_worktree(repo_root)

    current_version = read_current_version(paths)
    target_version = args.version or bump_version(current_version, args.bump)
    parse_version(target_version)
    ensure_version_order(current_version, target_version)

    if tag_exists(repo_root, target_version):
        raise ReleaseError(
            f"Git tag {target_version} already exists. The bridge updater expects a unique tag per release."
        )

    previous_tag = find_latest_tag(repo_root)
    subjects = collect_release_subjects(repo_root, previous_tag)

    release_dir = (repo_root / args.output_dir / target_version).resolve()
    archive_path = release_dir / f"pos_printer-v{target_version}.zip"
    notes_path = release_dir / "RELEASE_NOTES.md"

    if args.dry_run:
        print(f"Dry run for {target_version}")
        print(f"Current version: {current_version}")
        print(f"Previous tag: {previous_tag or 'none'}")
        print(f"Would update: {paths.manifest_path.relative_to(repo_root)}")
        print(f"Would update: {paths.bridge_version_path.relative_to(repo_root)}")
        if args.skip_tests:
            print("Would skip: pytest")
        else:
            print("Would run: pytest")
        print(f"Would create: {archive_path.relative_to(repo_root)}")
        print(f"Would create: {notes_path.relative_to(repo_root)}")
        if args.commit:
            print(f"Would commit: {RELEASE_COMMIT_TEMPLATE.format(version=target_version)}")
        if args.tag:
            print(f"Would tag: {target_version}")
        return ReleaseArtifacts(
            version=target_version,
            previous_version=current_version,
            previous_tag=previous_tag,
            release_dir=release_dir,
            archive_path=archive_path,
            notes_path=notes_path,
        )

    update_version_files(paths, target_version)

    if not args.skip_tests:
        run_pytest(repo_root)

    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)

    archive_path = build_release_archive(paths, release_dir, target_version)
    notes_content = build_release_notes(target_version, previous_tag, subjects)
    notes_path.write_text(notes_content, encoding="utf-8")

    if args.commit:
        git_add(repo_root, paths.version_files)
        git_commit(repo_root, target_version)
    if args.tag:
        git_tag(repo_root, target_version)

    return ReleaseArtifacts(
        version=target_version,
        previous_version=current_version,
        previous_tag=previous_tag,
        release_dir=release_dir,
        archive_path=archive_path,
        notes_path=notes_path,
    )


def print_summary(artifacts: ReleaseArtifacts, *, dry_run: bool) -> None:
    """Print a concise operator summary."""
    title = "Planned release" if dry_run else "Prepared release"
    print(f"{title}: {artifacts.release_title}")
    print(f"Version tag: {artifacts.tag_name}")
    print(f"Artifacts: {artifacts.release_dir}")
    print(f"Archive: {artifacts.archive_path}")
    print(f"Notes: {artifacts.notes_path}")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    try:
        artifacts = prepare_release(args)
    except ReleaseError as err:
        print(f"Release failed: {err}", file=sys.stderr)
        return 1

    print_summary(artifacts, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
