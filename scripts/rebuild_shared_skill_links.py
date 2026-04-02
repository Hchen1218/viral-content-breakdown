#!/usr/bin/env python3
"""Rebuild shared skill entrypoints for Codex and Claude Code."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Roots:
    repo: Path
    codex: Path
    claude: Path
    agents: Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MANIFEST_PATH = REPO_ROOT / "shared-skills.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild shared skill symlinks for Codex and Claude Code."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned changes without writing to disk.",
    )
    return parser.parse_args()


def load_manifest() -> tuple[Roots, list[str], list[str], list[str]]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    roots = Roots(
        repo=Path(data["roots"]["repo"]).expanduser().resolve(),
        codex=Path(data["roots"]["codex"]).expanduser(),
        claude=Path(data["roots"]["claude"]).expanduser(),
        agents=Path(data["roots"]["agents"]).expanduser(),
    )
    if roots.repo != REPO_ROOT:
        raise RuntimeError(
            f"Manifest repo root {roots.repo} does not match actual repo {REPO_ROOT}"
        )
    repo_managed = list(data["repoManaged"])
    external_shared = list(data["externalShared"])
    agent_compat = list(data.get("compatibilityLinks", {}).get("agents", []))
    return roots, repo_managed, external_shared, agent_compat


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
        return link_path.resolve() == target_path.resolve()
    except FileNotFoundError:
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


def main() -> int:
    args = parse_args()
    roots, repo_managed, external_shared, agent_compat = load_manifest()
    actions: list[str] = []

    pending_backups = False
    for skill_name in repo_managed:
        codex_entry = roots.codex / skill_name
        claude_entry = roots.claude / skill_name
        repo_entry = roots.repo / skill_name
        if not symlink_matches(codex_entry, repo_entry) and (
            codex_entry.exists() or codex_entry.is_symlink()
        ):
            pending_backups = True
        if not symlink_matches(claude_entry, repo_entry) and (
            claude_entry.exists() or claude_entry.is_symlink()
        ):
            pending_backups = True

    for skill_name in agent_compat:
        compat_entry = roots.agents / skill_name
        repo_entry = roots.repo / skill_name
        if not symlink_matches(compat_entry, repo_entry) and (
            compat_entry.exists() or compat_entry.is_symlink()
        ):
            pending_backups = True

    backup_root = compute_backup_root(args.dry_run, pending_backups)

    for skill_name in repo_managed:
        repo_entry = roots.repo / skill_name
        replace_with_symlink(
            roots.codex / skill_name,
            repo_entry,
            "codex",
            backup_root,
            args.dry_run,
            actions,
        )
        replace_with_symlink(
            roots.claude / skill_name,
            repo_entry,
            "claude",
            backup_root,
            args.dry_run,
            actions,
        )

    for skill_name in external_shared:
        codex_entry = roots.codex / skill_name
        if not (codex_entry.exists() or codex_entry.is_symlink()):
            raise FileNotFoundError(
                f"Codex entrypoint missing for external skill: {codex_entry}"
            )
        replace_with_symlink(
            roots.claude / skill_name,
            codex_entry.resolve(),
            "claude",
            backup_root,
            args.dry_run,
            actions,
        )

    for skill_name in agent_compat:
        replace_with_symlink(
            roots.agents / skill_name,
            roots.repo / skill_name,
            "agents",
            backup_root,
            args.dry_run,
            actions,
        )

    print(f"Manifest: {MANIFEST_PATH}")
    if pending_backups:
        print(f"Backup root: {backup_root}")
    else:
        print("Backup root: not needed")

    for action in actions:
        print(action)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
