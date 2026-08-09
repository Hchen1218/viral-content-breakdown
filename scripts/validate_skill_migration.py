#!/usr/bin/env python3
"""Snapshot, verify, and adversarially test the SkillHub-to-Codex migration."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "shared-skills.json"
EXTERNAL_SKILL = "creator-platform-ingest"
FORBIDDEN_SOURCE_MARKERS = (".skillhub", ".skillshub")
PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])((?:\.\.?/|references/|scripts/|internal/)[^\s`\"'<>]+)"
)
TRAILING_PATH_PUNCTUATION = ",.;:)]}>"
FENCED_BLOCK = re.compile(r"```.*?```", flags=re.DOTALL)


class ValidationError(RuntimeError):
    """Raised when the migration violates an invariant."""


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read JSON: {path}: {exc}") from exc


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def resolve_roots(manifest: dict) -> dict[str, Path]:
    values = manifest.get("roots", {})
    required = ("repo", "skillhub", "codex", "claude", "agents")
    missing = [name for name in required if name not in values]
    if missing:
        raise ValidationError(f"Manifest is missing roots: {', '.join(missing)}")
    roots = {name: Path(values[name]).expanduser().resolve() for name in values}
    return roots


def iter_entries(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {
        child.name
        for child in root.iterdir()
        if child.is_dir() or child.is_symlink()
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_state(root: Path) -> dict:
    """Return a deterministic file, directory, and link inventory."""
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise ValidationError(f"Expected a real directory: {root}")

    files: dict[str, str] = {}
    directories: list[str] = []
    links: dict[str, str] = {}

    def visit(path: Path, relative: str = "") -> None:
        with os.scandir(path) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                child_relative = f"{relative}/{entry.name}".lstrip("/")
                child = Path(entry.path)
                if entry.is_symlink():
                    links[child_relative] = os.readlink(child)
                elif entry.is_dir(follow_symlinks=False):
                    directories.append(child_relative)
                    visit(child, child_relative)
                elif entry.is_file(follow_symlinks=False):
                    files[child_relative] = sha256_file(child)
                else:
                    raise ValidationError(f"Unsupported filesystem entry: {child}")

    visit(root)
    return {
        "directories": sorted(directories),
        "files": dict(sorted(files.items())),
        "links": dict(sorted(links.items())),
    }


def assert_equal(label: str, expected: object, actual: object) -> None:
    if expected != actual:
        raise ValidationError(f"{label} mismatch")


def source_skill_names(manifest: dict) -> list[str]:
    names = manifest.get("sourceOfTruth", {}).get("skillhub", [])
    if EXTERNAL_SKILL not in names:
        raise ValidationError(
            f"Pre-migration manifest must register {EXTERNAL_SKILL} under skillhub"
        )
    migrated = [name for name in names if name != EXTERNAL_SKILL]
    if not migrated:
        raise ValidationError("No SkillHub-owned skills found to migrate")
    if len(set(migrated)) != len(migrated):
        raise ValidationError("Duplicate SkillHub migration entries")
    return migrated


def snapshot_migration(manifest_path: Path, output_path: Path) -> None:
    manifest = load_json(manifest_path)
    roots = resolve_roots(manifest)
    skillhub = roots["skillhub"]
    codex = roots["codex"]
    migrated = source_skill_names(manifest)
    registered = set(manifest.get("sourceOfTruth", {}).get("skillhub", []))
    actual_skillhub = iter_entries(skillhub)
    if actual_skillhub != registered:
        raise ValidationError(
            "SkillHub filesystem does not exactly match sourceOfTruth.skillhub"
        )

    sources: dict[str, dict] = {}
    for name in migrated:
        path = skillhub / name
        if not path.is_dir() or path.is_symlink():
            raise ValidationError(f"SkillHub source is not a real directory: {path}")
        if not (path / "SKILL.md").is_file():
            raise ValidationError(f"Skill has no SKILL.md: {path}")
        sources[name] = tree_state(path)

    external_link = skillhub / EXTERNAL_SKILL
    if not external_link.is_symlink():
        raise ValidationError(f"External Skill is not a symlink: {external_link}")
    external_target = external_link.resolve()
    if not external_target.is_dir() or not (external_target / "SKILL.md").is_file():
        raise ValidationError(f"External Skill target is invalid: {external_target}")

    protected_paths = [codex / ".system", codex / "codex-primary-runtime"]
    for name in manifest.get("sourceOfTruth", {}).get("repo", []):
        protected_paths.append(roots["repo"] / name)
    protected: dict[str, dict] = {}
    for path in protected_paths:
        if path.exists() and path.is_dir() and not path.is_symlink():
            protected[str(path)] = tree_state(path)

    snapshot = {
        "version": 1,
        "migrated": migrated,
        "sources": sources,
        "external": {
            "name": EXTERNAL_SKILL,
            "target": str(external_target),
            "tree": tree_state(external_target),
        },
        "protected": protected,
    }
    write_json(output_path, snapshot)
    print(f"snapshot=ok migrated={len(migrated)} output={output_path}")


def runtime_target(roots: dict[str, Path], manifest: dict, runtime: str, source: str, name: str) -> Path:
    override = (
        manifest.get("runtimeTargetOverrides", {})
        .get(runtime, {})
        .get(name)
    )
    if override:
        return Path(override).expanduser().resolve()
    if source not in roots:
        raise ValidationError(f"Unknown source root {source} for {runtime}.{name}")
    return roots[source] / name


def declared_symlink_target(link: Path) -> Path:
    """Resolve a link's declared path without following another symlink."""
    return Path(os.path.abspath(os.path.join(str(link.parent), os.readlink(link))))


def check_runtime_links(manifest: dict, roots: dict[str, Path], migrated: set[str]) -> None:
    runtime_links = manifest.get("runtimeLinks", {})
    for runtime, source_map in runtime_links.items():
        if runtime not in roots:
            raise ValidationError(f"Unknown runtime root: {runtime}")
        seen: set[str] = set()
        for source, names in source_map.items():
            for name in names:
                if name in seen:
                    raise ValidationError(f"Duplicate runtime entry: {runtime}.{name}")
                seen.add(name)
                link = roots[runtime] / name
                target = runtime_target(roots, manifest, runtime, source, name)
                if not link.is_symlink():
                    raise ValidationError(f"Runtime entry is not a symlink: {link}")
                if declared_symlink_target(link) != Path(os.path.abspath(str(target))):
                    raise ValidationError(
                        f"Runtime link target mismatch: {link} -> "
                        f"{declared_symlink_target(link)} "
                        f"expected {target.resolve()}"
                    )

        if runtime in ("claude", "agents"):
            codex_names = set(source_map.get("codex", []))
            if codex_names != migrated:
                raise ValidationError(f"{runtime} does not link exactly all migrated Skills")


def check_direct_entries(manifest: dict, roots: dict[str, Path], migrated: set[str]) -> None:
    direct = manifest.get("directEntries", {}).get("codex", [])
    if set(direct) != migrated or len(direct) != len(migrated):
        raise ValidationError("directEntries.codex does not exactly match migrated Skills")
    for name in direct:
        path = roots["codex"] / name
        if not path.is_dir() or path.is_symlink():
            raise ValidationError(f"Codex direct entry is not a real directory: {path}")


def check_explicit_references(
    root: Path, forbidden_roots: tuple[Path, ...] = ()
) -> None:
    root = root.resolve()
    forbidden = tuple(path.resolve() for path in forbidden_roots)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".md", ".markdown", ".yaml", ".yml", ".json", ".py", ".txt", ".toml"
        }:
            continue
        relative = path.relative_to(root)
        # README/examples contain output paths and prose, not runtime dependencies.
        if path.name != "SKILL.md" and (
            not relative.parts
            or relative.parts[0] != "agents"
            or path.suffix.lower() not in {".yaml", ".yml", ".json", ".toml"}
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in FORBIDDEN_SOURCE_MARKERS:
            if marker in text:
                raise ValidationError(f"Forbidden old source reference in {path}")
        reference_text = FENCED_BLOCK.sub("", text) if path.name == "SKILL.md" else text
        for match in PATH_TOKEN.finditer(reference_text):
            token = match.group(1).split("](", 1)[0].rstrip(TRAILING_PATH_PUNCTUATION)
            if (
                "://" in token
                or "$" in token
                or "{" in token
                or any(char in token for char in "*?[")
            ):
                continue
            if path.name == "SKILL.md" and token.startswith("./"):
                # CLI examples commonly use ./ for generated state or output files.
                continue
            if (
                path.relative_to(root).parts == ("SKILL.md",)
                and token.startswith("../")
                and Path(token).suffix == ""
                and not any(part in token for part in ("/scripts/", "/references/", "/internal/"))
            ):
                # Root wrappers may describe paths resolved by their internal modules.
                continue
            if token in {"../../.claude-plugin/marketplace.json", "../../README.md"}:
                # Eva documents optional GitHub-repository metadata paths.
                continue
            candidates = ((path.parent / token).resolve(), (root / token).resolve())
            valid = [
                candidate
                for candidate in candidates
                if not any(candidate == path or path in candidate.parents for path in forbidden)
            ]
            if not any(candidate.exists() for candidate in valid):
                raise ValidationError(f"Broken explicit reference in {path}: {token}")


def check_python_syntax(root: Path) -> None:
    for path in root.rglob("*.py"):
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise ValidationError(f"Python syntax failure: {path}: {exc}") from exc


def check_manifest_topology(
    manifest: dict,
    roots: dict[str, Path],
    migrated: set[str],
    require_old_source_absent: bool = True,
) -> None:
    skillhub = roots["skillhub"]
    if require_old_source_absent:
        for name in migrated | {EXTERNAL_SKILL}:
            if (skillhub / name).exists() or (skillhub / name).is_symlink():
                raise ValidationError(f"Old SkillHub entry remains: {skillhub / name}")

    codex = roots["codex"]
    expected_codex = set(manifest.get("directEntries", {}).get("codex", []))
    expected_codex.update(manifest.get("runtimeLinks", {}).get("codex", {}).get("external", []))
    expected_codex.update(manifest.get("runtimeLinks", {}).get("codex", {}).get("repo", []))
    expected_codex.update(manifest.get("preservedEntries", {}).get("codex", []))
    actual_codex = iter_entries(codex)
    extra = actual_codex - expected_codex
    if extra:
        raise ValidationError(f"Unregistered Codex entries: {', '.join(sorted(extra))}")

    source_hub = set(manifest.get("sourceOfTruth", {}).get("skillhub", []))
    if source_hub:
        raise ValidationError("sourceOfTruth.skillhub is not empty after migration")

    external = roots.get("external")
    if external is None:
        raise ValidationError("Manifest has no external root")
    external_target = external / EXTERNAL_SKILL
    link = codex / EXTERNAL_SKILL
    if not link.is_symlink() or declared_symlink_target(link) != Path(
        os.path.abspath(str(external_target))
    ):
        raise ValidationError("creator-platform-ingest no longer points to ai-content")


def verify_migration(
    manifest_path: Path,
    snapshot_path: Path,
    require_old_source_absent: bool = True,
) -> None:
    manifest = load_json(manifest_path)
    snapshot = load_json(snapshot_path)
    roots = resolve_roots(manifest)
    migrated = set(snapshot.get("migrated", []))
    if len(migrated) != len(snapshot.get("migrated", [])) or not migrated:
        raise ValidationError("Snapshot has no unique migrated Skill set")

    if set(manifest.get("sourceOfTruth", {}).get("codex", [])) != migrated:
        raise ValidationError("sourceOfTruth.codex does not match snapshot")
    if EXTERNAL_SKILL not in manifest.get("sourceOfTruth", {}).get("external", []):
        raise ValidationError("External Skill is not registered under external source")

    check_direct_entries(manifest, roots, migrated)
    check_runtime_links(manifest, roots, migrated)
    check_manifest_topology(
        manifest,
        roots,
        migrated,
        require_old_source_absent=require_old_source_absent,
    )

    for name in migrated:
        target = roots["codex"] / name
        assert_equal(f"content {name}", snapshot["sources"][name], tree_state(target))
        if not (target / "SKILL.md").is_file():
            raise ValidationError(f"Migrated Skill has no SKILL.md: {target}")
        check_explicit_references(target, forbidden_roots=(roots["skillhub"],))
        check_python_syntax(target)

    external_target = Path(snapshot["external"]["target"])
    if external_target.resolve() != (roots["external"] / EXTERNAL_SKILL).resolve():
        raise ValidationError("External Skill target changed")
    assert_equal(
        "external creator-platform-ingest",
        snapshot["external"]["tree"],
        tree_state(external_target),
    )

    for raw_path, expected_state in snapshot.get("protected", {}).items():
        path = Path(raw_path)
        assert_equal(f"protected content {path}", expected_state, tree_state(path))

    print(f"verify=ok migrated={len(migrated)}")


def build_adversarial_fixture(root: Path) -> tuple[Path, Path]:
    """Create a tiny valid migration layout used only by negative tests."""
    hub = root / "skillhub"
    codex = root / "codex"
    claude = root / "claude"
    agents = root / "agents"
    repo = root / "repo"
    external = root / "external"
    for path in (hub, codex, claude, agents, repo, external):
        path.mkdir(parents=True)
    (hub / "demo" / "references").mkdir(parents=True)
    (hub / "demo" / "SKILL.md").write_text(
        "---\nname: demo\n---\nRead `references/guide.md`.\n", encoding="utf-8"
    )
    (hub / "demo" / "references/guide.md").write_text("guide\n", encoding="utf-8")
    (external / EXTERNAL_SKILL).mkdir()
    (external / EXTERNAL_SKILL / "SKILL.md").write_text("external\n", encoding="utf-8")
    (hub / EXTERNAL_SKILL).symlink_to(external / EXTERNAL_SKILL, target_is_directory=True)
    (codex / ".system").mkdir()
    (codex / ".system" / "marker").write_text("system\n", encoding="utf-8")
    (codex / "codex-primary-runtime").mkdir()
    (codex / "codex-primary-runtime" / "marker").write_text("primary\n", encoding="utf-8")

    pre_manifest = {
        "roots": {
            "repo": str(repo),
            "skillhub": str(hub),
            "codex": str(codex),
            "claude": str(claude),
            "agents": str(agents),
            "external": str(external),
        },
        "sourceOfTruth": {"skillhub": ["demo", EXTERNAL_SKILL], "repo": []},
        "runtimeLinks": {
            "codex": {"skillhub": ["demo"], "external": [EXTERNAL_SKILL]},
            "claude": {"skillhub": ["demo"], "external": [EXTERNAL_SKILL]},
            "agents": {"skillhub": ["demo"], "external": [EXTERNAL_SKILL]},
        },
        "preservedEntries": {"codex": [".system", "codex-primary-runtime"]},
    }
    pre_path = root / "pre.json"
    write_json(pre_path, pre_manifest)
    snapshot_path = root / "snapshot.json"
    snapshot_migration(pre_path, snapshot_path)

    shutil.copytree(hub / "demo", codex / "demo")
    shutil.rmtree(hub / "demo", ignore_errors=True)
    (hub / EXTERNAL_SKILL).unlink()
    for runtime in (claude, agents):
        (runtime / "demo").symlink_to(codex / "demo", target_is_directory=True)
        (runtime / EXTERNAL_SKILL).symlink_to(
            external / EXTERNAL_SKILL, target_is_directory=True
        )
    (codex / EXTERNAL_SKILL).symlink_to(
        external / EXTERNAL_SKILL, target_is_directory=True
    )

    final_manifest = {
        "roots": pre_manifest["roots"],
        "sourceOfTruth": {
            "skillhub": [],
            "codex": ["demo"],
            "external": [EXTERNAL_SKILL],
            "repo": [],
        },
        "directEntries": {"codex": ["demo"]},
        "runtimeLinks": {
            "codex": {"external": [EXTERNAL_SKILL]},
            "claude": {"codex": ["demo"], "external": [EXTERNAL_SKILL]},
            "agents": {"codex": ["demo"], "external": [EXTERNAL_SKILL]},
        },
        "preservedEntries": {"codex": [".system", "codex-primary-runtime"]},
    }
    final_path = root / "manifest.json"
    write_json(final_path, final_manifest)
    return final_path, snapshot_path


def expect_failure(label: str, mutation: Callable[[Path, Path], None]) -> None:
    with tempfile.TemporaryDirectory(prefix="skill-migration-negative-") as raw:
        root = Path(raw)
        manifest, snapshot = build_adversarial_fixture(root)
        mutation(root, manifest)
        try:
            verify_migration(manifest, snapshot)
        except ValidationError:
            print(f"negative={label}: caught")
        else:
            raise ValidationError(f"Negative test was not rejected: {label}")


def run_adversarial_tests() -> None:
    cases: list[tuple[str, Callable[[Path, Path], None]]] = [
        (
            "missing-skill-md",
            lambda root, manifest: (root / "codex/demo/SKILL.md").unlink(),
        ),
        (
            "modified-file",
            lambda root, manifest: (root / "codex/demo/SKILL.md").write_text(
                "changed\n", encoding="utf-8"
            ),
        ),
        (
            "unregistered-duplicate",
            lambda root, manifest: (root / "codex/extra").mkdir(),
        ),
        (
            "broken-claude-link",
            lambda root, manifest: (root / "claude/demo").unlink(),
        ),
        (
            "codex-self-link",
            lambda root, manifest: (
                (root / "codex/demo").rename(root / "codex/demo-real"),
                (root / "codex/demo").symlink_to(root / "codex/demo"),
            ),
        ),
        (
            "claude-points-to-skillhub",
            lambda root, manifest: (
                (root / "claude/demo").unlink(),
                (root / "claude/demo").symlink_to(root / "skillhub/demo"),
            ),
        ),
        (
            "external-source-changed",
            lambda root, manifest: (
                (root / "codex/creator-platform-ingest").unlink(),
                (root / "external/wrong").mkdir(),
                (root / "codex/creator-platform-ingest").symlink_to(
                    root / "external/wrong", target_is_directory=True
                ),
            ),
        ),
        (
            "runtime-link-via-old-source",
            lambda root, manifest: (
                (root / "codex/creator-platform-ingest").unlink(),
                (root / "codex/creator-platform-ingest").symlink_to(
                    root / "skillhub/creator-platform-ingest", target_is_directory=True
                ),
            ),
        ),
        (
            "manifest-missing-target",
            lambda root, manifest: _append_missing_direct_entry(manifest),
        ),
        (
            "invalid-relative-reference",
            lambda root, manifest: (root / "codex/demo/SKILL.md").write_text(
                "Read `references/missing.md`.\n", encoding="utf-8"
            ),
        ),
        (
            "protected-entry-changed",
            lambda root, manifest: (root / "codex/.system/marker").write_text(
                "changed\n", encoding="utf-8"
            ),
        ),
    ]
    for label, mutation in cases:
        expect_failure(label, mutation)
    print(f"adversarial=ok cases={len(cases)}")


def _append_missing_direct_entry(manifest_path: Path) -> None:
    manifest = load_json(manifest_path)
    manifest["sourceOfTruth"]["codex"].append("ghost")
    manifest["directEntries"]["codex"].append("ghost")
    write_json(manifest_path, manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    snapshot.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    verify.add_argument("--snapshot", type=Path, required=True)
    verify.add_argument(
        "--pre-delete",
        action="store_true",
        help="Allow old SkillHub entries to remain during pre-delete validation.",
    )

    subparsers.add_parser("adversarial")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "snapshot":
            snapshot_migration(args.manifest, args.output)
        elif args.command == "verify":
            verify_migration(
                args.manifest,
                args.snapshot,
                require_old_source_absent=not args.pre_delete,
            )
        else:
            run_adversarial_tests()
    except ValidationError as exc:
        print(f"validation=failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
