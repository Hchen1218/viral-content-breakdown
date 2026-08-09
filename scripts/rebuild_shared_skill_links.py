#!/usr/bin/env python3
"""Rebuild Codex, Claude, and agents skill entrypoints from one manifest."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Roots:
    repo: Path
    skillhub: Path
    codex: Path
    claude: Path
    agents: Path
    external: Path

    def get(self, key: str) -> Path:
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(f"Unknown root key: {key}") from exc

    def keys(self) -> tuple[str, ...]:
        return ("repo", "skillhub", "codex", "claude", "agents", "external")


@dataclass(frozen=True)
class Manifest:
    roots: Roots
    source_of_truth: dict[str, list[str]]
    runtime_links: dict[str, dict[str, list[str]]]
    direct_entries: dict[str, list[str]]
    runtime_target_overrides: dict[str, dict[str, Path]]
    preserved_entries: dict[str, list[str]]


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MANIFEST_PATH = REPO_ROOT / "shared-skills.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild shared skill symlinks for Codex, Claude, and agents."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned changes without writing to disk.",
    )
    return parser.parse_args()


def unique_ordered(items: list[str], label: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    duplicates: list[str] = []
    for item in items:
        if item in seen:
            duplicates.append(item)
            continue
        seen.add(item)
        result.append(item)
    if duplicates:
        joined = ", ".join(sorted(set(duplicates)))
        raise RuntimeError(f"Duplicate entries in {label}: {joined}")
    return result


def load_manifest() -> Manifest:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    roots = Roots(
        repo=Path(data["roots"]["repo"]).expanduser().resolve(),
        skillhub=Path(data["roots"]["skillhub"]).expanduser().resolve(),
        codex=Path(data["roots"]["codex"]).expanduser(),
        claude=Path(data["roots"]["claude"]).expanduser(),
        agents=Path(data["roots"]["agents"]).expanduser(),
        external=Path(data["roots"].get("external", REPO_ROOT)).expanduser().resolve(),
    )
    if roots.repo != REPO_ROOT:
        raise RuntimeError(
            f"Manifest repo root {roots.repo} does not match actual repo {REPO_ROOT}"
        )

    source_of_truth = {
        root_key: unique_ordered(skills, f"sourceOfTruth.{root_key}")
        for root_key, skills in data["sourceOfTruth"].items()
    }
    runtime_links = {
        runtime_key: {
            source_key: unique_ordered(
                skills, f"runtimeLinks.{runtime_key}.{source_key}"
            )
            for source_key, skills in source_map.items()
        }
        for runtime_key, source_map in data["runtimeLinks"].items()
    }
    direct_entries = {
        runtime_key: unique_ordered(
            skills, f"directEntries.{runtime_key}"
        )
        for runtime_key, skills in data.get("directEntries", {}).items()
    }
    runtime_target_overrides = {
        runtime_key: {
            skill_name: Path(target_path).expanduser().resolve()
            for skill_name, target_path in override_map.items()
        }
        for runtime_key, override_map in data.get("runtimeTargetOverrides", {}).items()
    }
    preserved_entries = {
        root_key: unique_ordered(entries, f"preservedEntries.{root_key}")
        for root_key, entries in data.get("preservedEntries", {}).items()
    }
    return Manifest(
        roots=roots,
        source_of_truth=source_of_truth,
        runtime_links=runtime_links,
        direct_entries=direct_entries,
        runtime_target_overrides=runtime_target_overrides,
        preserved_entries=preserved_entries,
    )


def ensure_dir(path: Path, dry_run: bool, actions: list[str]) -> None:
    if path.exists():
        return
    actions.append(f"mkdir {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def backup_existing(
    path: Path,
    bucket: str,
    backup_root: Path,
    dry_run: bool,
    actions: list[str],
) -> None:
    if not (path.exists() or path.is_symlink()):
        return

    destination = backup_root / bucket / path.name
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"Backup destination already exists: {destination}")

    actions.append(f"backup {path} -> {destination}")
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))


def symlink_matches(link_path: Path, target_path: Path) -> bool:
    if not link_path.is_symlink():
        return False
    try:
        declared_target = Path(
            os.path.abspath(os.path.join(str(link_path.parent), os.readlink(link_path)))
        )
        return declared_target == Path(os.path.abspath(str(target_path)))
    except (FileNotFoundError, OSError):
        return False


def replace_with_symlink(
    link_path: Path,
    target_path: Path,
    bucket: str,
    backup_root: Path,
    dry_run: bool,
    actions: list[str],
) -> None:
    target_path = target_path.expanduser().resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Target does not exist: {target_path}")

    ensure_dir(link_path.parent, dry_run, actions)

    if symlink_matches(link_path, target_path):
        actions.append(f"keep {link_path} -> {target_path}")
        return

    if link_path.exists() or link_path.is_symlink():
        backup_existing(link_path, bucket, backup_root, dry_run, actions)

    actions.append(f"link {link_path} -> {target_path}")
    if not dry_run:
        link_path.symlink_to(target_path, target_is_directory=True)


def compute_backup_root(dry_run: bool, needed: bool) -> Path:
    base_root = Path.home() / ".codex" / ".shared-skill-backups"
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if dry_run or not needed:
        return base_root / stamp
    target = base_root / stamp
    target.mkdir(parents=True, exist_ok=False)
    return target


def existing_entry_names(root_path: Path) -> set[str]:
    if not root_path.exists():
        return set()
    return {
        child.name
        for child in root_path.iterdir()
        if child.is_dir() or child.is_symlink()
    }


def validate_manifest(manifest: Manifest) -> dict[str, str]:
    authoritative_source: dict[str, str] = {}
    known_root_keys = set(manifest.roots.keys())

    for source_key, skills in manifest.source_of_truth.items():
        if source_key not in known_root_keys:
            raise RuntimeError(f"Unknown sourceOfTruth root: {source_key}")
        source_root = manifest.roots.get(source_key)
        for skill_name in skills:
            previous = authoritative_source.get(skill_name)
            if previous and previous != source_key:
                raise RuntimeError(
                    f"Skill {skill_name} has conflicting authorities: "
                    f"{previous} and {source_key}"
                )
            authoritative_source[skill_name] = source_key
            source_path = source_root / skill_name
            if not source_path.exists():
                raise FileNotFoundError(
                    f"Authoritative skill missing from {source_key}: {source_path}"
                )

    for runtime_key, source_map in manifest.runtime_links.items():
        if runtime_key not in known_root_keys:
            raise RuntimeError(f"Unknown runtimeLinks root: {runtime_key}")
        seen_in_runtime: set[str] = set()
        direct = set(manifest.direct_entries.get(runtime_key, []))
        for source_key, skills in source_map.items():
            if source_key not in known_root_keys:
                raise RuntimeError(
                    f"Unknown runtimeLinks source {source_key} for {runtime_key}"
                )
            for skill_name in skills:
                if skill_name in direct:
                    raise RuntimeError(
                        f"Skill {skill_name} is both a direct entry and a runtime link "
                        f"in {runtime_key}"
                    )
                if skill_name in seen_in_runtime:
                    raise RuntimeError(
                        f"Duplicate runtime entry {skill_name} in {runtime_key}"
                    )
                seen_in_runtime.add(skill_name)
                authority = authoritative_source.get(skill_name)
                if authority is None:
                    raise RuntimeError(
                        f"Skill {skill_name} is routed into {runtime_key} "
                        "but has no sourceOfTruth entry"
                    )
                if authority != source_key:
                    raise RuntimeError(
                        f"Skill {skill_name} is routed from {source_key} into "
                        f"{runtime_key}, but authority is {authority}"
                    )

    for runtime_key, skills in manifest.direct_entries.items():
        if runtime_key not in known_root_keys:
            raise RuntimeError(f"Unknown directEntries root: {runtime_key}")
        runtime_root = manifest.roots.get(runtime_key)
        for skill_name in skills:
            authority = authoritative_source.get(skill_name)
            if authority != runtime_key:
                raise RuntimeError(
                    f"Direct entry {runtime_key}.{skill_name} must be authoritative "
                    f"from {runtime_key}, got {authority}"
                )
            direct_path = runtime_root / skill_name
            if not direct_path.exists():
                raise FileNotFoundError(
                    f"Direct skill missing from {runtime_key}: {direct_path}"
                )
            if direct_path.is_symlink() or not direct_path.is_dir():
                raise RuntimeError(
                    f"Direct skill must be a real directory: {direct_path}"
                )

    for runtime_key, override_map in manifest.runtime_target_overrides.items():
        if runtime_key not in known_root_keys:
            raise RuntimeError(f"Unknown runtimeTargetOverrides root: {runtime_key}")
        declared = desired_entries_for_runtime(
            runtime_key, manifest.runtime_links.get(runtime_key, {})
        )
        for skill_name, target_path in override_map.items():
            if skill_name not in declared:
                raise RuntimeError(
                    f"runtimeTargetOverrides.{runtime_key}.{skill_name} has no "
                    "matching runtimeLinks entry"
                )
            if not target_path.exists():
                raise FileNotFoundError(
                    f"Override target does not exist for {runtime_key}.{skill_name}: "
                    f"{target_path}"
                )

    return authoritative_source


def desired_entries_for_runtime(
    runtime_key: str,
    runtime_sources: dict[str, list[str]],
    direct_entries: list[str] | None = None,
) -> set[str]:
    desired: set[str] = set()
    for skills in runtime_sources.values():
        desired.update(skills)
    desired.update(direct_entries or [])
    return desired


def collect_unmanaged_entries(manifest: Manifest) -> dict[str, list[str]]:
    unmanaged: dict[str, list[str]] = {}
    for runtime_key, source_map in manifest.runtime_links.items():
        runtime_root = manifest.roots.get(runtime_key)
        current = existing_entry_names(runtime_root)
        desired = desired_entries_for_runtime(
            runtime_key, source_map, manifest.direct_entries.get(runtime_key, [])
        )
        preserved = set(manifest.preserved_entries.get(runtime_key, []))
        leftovers = sorted(current - desired - preserved)
        if leftovers:
            unmanaged[runtime_key] = leftovers
    return unmanaged


def has_pending_backups(manifest: Manifest) -> bool:
    for runtime_key, source_map in manifest.runtime_links.items():
        runtime_root = manifest.roots.get(runtime_key)
        overrides = manifest.runtime_target_overrides.get(runtime_key, {})
        for source_key, skills in source_map.items():
            source_root = manifest.roots.get(source_key)
            for skill_name in skills:
                link_path = runtime_root / skill_name
                target_path = overrides.get(skill_name, source_root / skill_name)
                if not symlink_matches(link_path, target_path) and (
                    link_path.exists() or link_path.is_symlink()
                ):
                    return True
    return False


def rebuild_links(
    manifest: Manifest, backup_root: Path, dry_run: bool, actions: list[str]
) -> None:
    for runtime_key, source_map in manifest.runtime_links.items():
        runtime_root = manifest.roots.get(runtime_key)
        overrides = manifest.runtime_target_overrides.get(runtime_key, {})
        for source_key, skills in source_map.items():
            source_root = manifest.roots.get(source_key)
            for skill_name in skills:
                replace_with_symlink(
                    runtime_root / skill_name,
                    overrides.get(skill_name, source_root / skill_name),
                    runtime_key,
                    backup_root,
                    dry_run,
                    actions,
                )


def main() -> int:
    args = parse_args()
    manifest = load_manifest()
    validate_manifest(manifest)
    unmanaged = collect_unmanaged_entries(manifest)

    actions: list[str] = []
    pending_backups = has_pending_backups(manifest)
    backup_root = compute_backup_root(args.dry_run, pending_backups)
    rebuild_links(manifest, backup_root, args.dry_run, actions)

    print(f"Manifest: {MANIFEST_PATH}")
    if pending_backups:
        print(f"Backup root: {backup_root}")
    else:
        print("Backup root: not needed")

    if unmanaged:
        print("Unmanaged entries:")
        for runtime_key, entries in unmanaged.items():
            joined = ", ".join(entries)
            print(f"- {runtime_key}: {joined}")
    else:
        print("Unmanaged entries: none")

    for action in actions:
        print(action)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
