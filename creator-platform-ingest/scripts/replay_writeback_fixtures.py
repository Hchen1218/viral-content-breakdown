#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CAPTURE_GLOBS = (
    ".cache/content-pipeline/creator-captures/2026-04-10-133332/capture.json",
    ".cache/content-pipeline/creator-captures/2026-04-16-230607/capture.json",
)
REQUIRED_CAPTURE_KEYS = {
    "capture_context",
    "account_snapshot",
    "trend_series",
    "content_rows",
    "detail_metrics",
    "match_hints",
    "capture_coverage",
}
REQUIRED_REPORT_SECTIONS = (
    "## Changed Files",
    "## Unmatched Rows",
    "## Created Archives",
    "## Asset Gaps",
    "## User Supplement Needed",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def copy_path(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def build_temp_repo(source_repo: Path, temp_root: Path) -> Path:
    temp_repo = temp_root / "repo"
    for rel in (
        Path("01-内容生产") / "数据统计" / "内容数据表.md",
        Path("01-内容生产") / "选题管理" / "03-已发布选题",
        Path("02-业务运营") / "业务规划" / "周期复盘",
        Path("02-业务运营") / "业务规划" / "📋 进行中的运营动作.md",
    ):
        copy_path(source_repo / rel, temp_repo / rel)
    return temp_repo


def validate_capture_shape(capture_path: Path) -> list[str]:
    errors: list[str] = []
    payload = read_json(capture_path)
    missing = sorted(REQUIRED_CAPTURE_KEYS - set(payload))
    if missing:
        errors.append(f"{capture_path}: missing top-level keys: {', '.join(missing)}")
    for platform in ("xhs", "dy"):
        if platform not in payload.get("account_snapshot", {}):
            errors.append(f"{capture_path}: account_snapshot.{platform} missing")
        if platform not in payload.get("trend_series", {}):
            errors.append(f"{capture_path}: trend_series.{platform} missing")
    rows = payload.get("content_rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append(f"{capture_path}: content_rows is empty or invalid")
    return errors


def section_body(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    next_start = text.find("\n## ", start + len(heading))
    if next_start < 0:
        return text[start:].strip()
    return text[start:next_start].strip()


def validate_report(report_path: Path, *, strict_resolved: bool) -> list[str]:
    errors: list[str] = []
    text = report_path.read_text(encoding="utf-8")
    for heading in REQUIRED_REPORT_SECTIONS:
        if heading not in text:
            errors.append(f"{report_path}: report section missing: {heading}")
    supplement = section_body(text, "## User Supplement Needed")
    if "平台已发布的标题、正文和 tag 应由 creator-platform-ingest 抓取" not in supplement:
        errors.append(f"{report_path}: User Supplement Needed does not state platform fields are captured")
    if strict_resolved:
        for heading in ("## Unmatched Rows", "## Created Archives", "## Asset Gaps"):
            body = section_body(text, heading)
            if "- none" not in body:
                errors.append(f"{report_path}: expected resolved fixture section to be none: {heading}")
    return errors


def run_one_fixture(source_repo: Path, capture_path: Path, temp_root: Path, *, strict_resolved: bool) -> dict[str, Any]:
    fixture_root = temp_root / capture_path.parent.name
    fixture_root.mkdir(parents=True, exist_ok=True)
    copied_capture = fixture_root / "capture.json"
    shutil.copy2(capture_path, copied_capture)
    temp_repo = build_temp_repo(source_repo, fixture_root)
    errors = validate_capture_shape(copied_capture)
    command = [
        sys.executable,
        str(SCRIPT_DIR / "writeback_capture_to_ai_content.py"),
        "--capture",
        str(copied_capture),
        "--repo-root",
        str(temp_repo),
    ]
    completed = subprocess.run(command, cwd=source_repo, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        errors.append(f"{capture_path}: writeback failed: {completed.stderr.strip() or completed.stdout.strip()}")
    report_path = copied_capture.with_name("writeback-report.md")
    if not report_path.exists():
        errors.append(f"{capture_path}: writeback-report.md was not created")
    else:
        errors.extend(validate_report(report_path, strict_resolved=strict_resolved))
    review_files = sorted((temp_repo / "02-业务运营" / "业务规划" / "周期复盘").glob("*-周运营复盘.md"))
    if not review_files:
        errors.append(f"{capture_path}: weekly review was not generated in temp repo")
    return {
        "capture": str(capture_path),
        "temp_repo": str(temp_repo),
        "report": str(report_path),
        "passed": not errors,
        "errors": errors,
    }


def default_captures(repo_root: Path) -> list[Path]:
    captures = [repo_root / rel for rel in DEFAULT_CAPTURE_GLOBS]
    return [path for path in captures if path.exists()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay creator-platform writeback against historical capture fixtures.")
    parser.add_argument("--repo-root", default=".", help="ai-content repo root")
    parser.add_argument("--capture", action="append", help="capture.json fixture path; repeatable")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temp replay repos for inspection")
    parser.add_argument(
        "--strict-resolved",
        action="store_true",
        help="Assert unmatched rows, created archives, and asset gaps are all none. Use for already-curated fixtures.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    captures = [Path(path).resolve() for path in args.capture] if args.capture else default_captures(repo_root)
    if not captures:
        print(json.dumps({"passed": False, "error": "no capture fixtures found"}, ensure_ascii=False), file=sys.stderr)
        return 2
    missing = [str(path) for path in captures if not path.exists()]
    if missing:
        print(json.dumps({"passed": False, "missing_captures": missing}, ensure_ascii=False), file=sys.stderr)
        return 2

    temp_root = Path(tempfile.mkdtemp(prefix="creator-writeback-replay-"))
    try:
        results = [run_one_fixture(repo_root, capture, temp_root, strict_resolved=args.strict_resolved) for capture in captures]
        passed = all(item["passed"] for item in results)
        output = {"passed": passed, "temp_root": str(temp_root), "results": results}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if args.keep_temp:
            print(f"kept temp root: {temp_root}", file=sys.stderr)
        return 0 if passed else 1
    finally:
        if not args.keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
