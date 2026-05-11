#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from capture_creator_platforms import infer_week_window, load_archive_docs, normalize_text, row_archive_matches, score_match  # noqa: E402


XHS_PLATFORM = "小红书"
DY_PLATFORM = "抖音"

CONTENT_DATA_PATH = Path("01-内容生产") / "数据统计" / "内容数据表.md"
ARCHIVE_DIR = Path("01-内容生产") / "选题管理" / "03-已发布选题"
REVIEW_DIR = Path("02-业务运营") / "业务规划" / "周期复盘"
ACTIONS_PATH = Path("02-业务运营") / "业务规划" / "📋 进行中的运营动作.md"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def metric_raw(metric: dict[str, Any] | None) -> str | None:
    if not metric:
        return None
    raw = metric.get("raw")
    return str(raw) if raw is not None else None


def metric_normalized(metric: dict[str, Any] | None) -> Any:
    if not metric:
        return None
    return metric.get("normalized")


def display_metric(metric: dict[str, Any] | None) -> str:
    if not metric:
        return "-"
    raw = metric_raw(metric)
    normalized = metric_normalized(metric)
    if isinstance(normalized, int):
        return f"{normalized:,}"
    if isinstance(normalized, float) and raw and not raw.endswith(("%", "s", "h")):
        if normalized.is_integer():
            return f"{int(normalized):,}"
        return f"{normalized:g}"
    return raw or "-"


def percentage_text(metric: dict[str, Any] | None) -> str:
    return display_metric(metric)


def format_date_label(raw_window: dict[str, Any] | None) -> str:
    if not raw_window or not raw_window.get("start_date") or not raw_window.get("end_date"):
        return "-"
    return f"{raw_window['start_date']} ~ {raw_window['end_date']}"


def format_window_with_period(raw_window: dict[str, Any] | None, period: str | None) -> str:
    window = format_date_label(raw_window)
    if period and window != "-":
        return f"{window}（{period}）"
    return window


def short_mmdd(iso_or_date: str | None) -> str:
    if not iso_or_date:
        return "-"
    return iso_or_date[5:10]


def parse_markdown_table_rows(section_text: str) -> list[list[str]]:
    rows = []
    lines = [line.strip() for line in section_text.splitlines() if line.strip().startswith("|")]
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
    return rows


def extract_section(text: str, heading_prefix: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(heading_prefix):
            end = idx + 1
            while end < len(lines) and not (lines[end].startswith("## ") or lines[end].startswith("### ")):
                end += 1
            return "\n".join(lines[idx:end]).strip()
    return None


def extract_existing_xhs_type_hints(content_data_text: str) -> dict[str, str]:
    hints: dict[str, str] = {}
    for heading, content_type in (("#### 视频", "video"), ("#### 图文", "image_text"), ("#### 待识别体裁", "unknown")):
        section = extract_section(content_data_text, heading)
        if not section:
            continue
        for cells in parse_markdown_table_rows(section):
            if len(cells) >= 2:
                hints[normalize_text(cells[1])] = content_type
    return hints


def parse_history_rows(content_data_text: str, heading_prefix: str) -> tuple[list[str], list[list[str]]]:
    section = extract_section(content_data_text, heading_prefix)
    if not section:
        return [], []
    lines = [line.rstrip() for line in section.splitlines()]
    table_lines = [line for line in lines if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], []
    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows = []
    for line in table_lines[2:]:
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return headers, rows


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    def escape_cell(value: str) -> str:
        return value.replace("|", "\\|")

    lines = [
        "| " + " | ".join(escape_cell(header) for header in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        padded = row + [""] * (len(headers) - len(row))
        lines.append("| " + " | ".join(escape_cell(str(cell)) for cell in padded[: len(headers)]) + " |")
    return "\n".join(lines)


def update_snapshot_rows(existing_rows: list[list[str]], new_row: list[str]) -> list[list[str]]:
    if not new_row:
        return existing_rows
    snapshot_date = new_row[0]
    filtered = [row for row in existing_rows if not row or row[0] != snapshot_date]
    return [new_row, *filtered]


def parse_archive_content_type(path: str) -> str | None:
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if "内容形式：" not in line:
            continue
        if "图文" in line:
            return "image_text"
        if "视频" in line or "口播" in line:
            return "video"
    return None


def resolve_xhs_content_type(
    row: dict[str, Any],
    existing_type_hints: dict[str, str],
    archive_content_types: dict[str, str | None],
) -> str:
    if row.get("content_type") in {"video", "image_text"}:
        return row["content_type"]
    archive_path = best_archive_path(row)
    if archive_path and archive_content_types.get(archive_path) in {"video", "image_text"}:
        return archive_content_types[archive_path] or "unknown"
    hinted = existing_type_hints.get(normalize_text(row["title"]))
    if hinted in {"video", "image_text"}:
        return hinted
    wanted = normalize_text(row["title"])
    best_hint = None
    best_score = 0.0
    for normalized_title, hint in existing_type_hints.items():
        score = score_match(wanted, normalized_title)
        if score > best_score:
            best_score = score
            best_hint = hint
    if best_hint in {"video", "image_text"} and best_score >= 0.72:
        return best_hint
    if row.get("duration_seconds"):
        return "video"
    return "unknown"


def best_archive_path(row: dict[str, Any]) -> str | None:
    if "resolved_archive_paths" in row:
        paths = row.get("resolved_archive_paths") or []
    else:
        paths = row.get("matched_archive_paths") or []
    return paths[0] if paths else None


def stripped_title(title: str) -> str:
    title = re.sub(r"\s*#\S+$", "", title).strip()
    return title.replace("❗️", "").replace("❗", "").strip()


def archive_filename_component(title: str) -> str:
    stem = stripped_title(title)
    stem = re.sub(r'[\\/:*?"<>|]+', "-", stem)
    stem = re.sub(r"[“”\"'‘’]+", "", stem)
    stem = re.sub(r"[!！?？]+", "", stem)
    stem = re.sub(r"[，,。；;：:、（）()【】\[\]]+", "-", stem)
    stem = re.sub(r"\s+", "", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return stem[:60] or "未命名内容"


def content_form_label(xhs_row: dict[str, Any] | None, dy_row: dict[str, Any] | None) -> str:
    if dy_row:
        return "口播视频"
    if xhs_row and xhs_row.get("resolved_content_type") == "image_text":
        return "图文"
    if xhs_row and xhs_row.get("resolved_content_type") == "video":
        return "口播视频"
    return "待识别"


def core_archive_title(xhs_row: dict[str, Any] | None, dy_row: dict[str, Any] | None) -> str:
    if dy_row:
        return stripped_title(dy_row["title"])
    if xhs_row:
        return stripped_title(xhs_row["title"])
    return "未命名内容"


def row_publish_iso(row: dict[str, Any] | None) -> str:
    if not row:
        return "1970-01-01"
    return (row.get("published_at") or row.get("publish_date") or "1970-01-01")[:10]


def pair_unmatched_rows(rows: list[dict[str, Any]]) -> list[dict[str, dict[str, Any] | None]]:
    xhs_rows = [row for row in rows if row["platform"] == "xhs"]
    dy_rows = [row for row in rows if row["platform"] == "dy"]
    paired: list[dict[str, dict[str, Any] | None]] = []
    remaining_xhs = xhs_rows[:]
    for dy_row in sorted(dy_rows, key=lambda row: row_publish_iso(row), reverse=True):
        best_idx = None
        best_score = 0.0
        dy_date = row_publish_iso(dy_row)
        for idx, xhs_row in enumerate(remaining_xhs):
            xhs_date = row_publish_iso(xhs_row)
            day_gap = abs((datetime.fromisoformat(dy_date) - datetime.fromisoformat(xhs_date)).days)
            if day_gap > 1:
                continue
            score = score_match(normalize_text(stripped_title(dy_row["title"])), normalize_text(stripped_title(xhs_row["title"])))
            if score > best_score:
                best_score = score
                best_idx = idx
        # Cross-platform variants often ship with different titles/body/tag.
        # Only auto-pair when both publish timing and title similarity strongly agree.
        if best_idx is not None and best_score >= 0.78:
            paired.append({"xhs": remaining_xhs.pop(best_idx), "dy": dy_row})
        else:
            paired.append({"xhs": None, "dy": dy_row})
    for xhs_row in remaining_xhs:
        paired.append({"xhs": xhs_row, "dy": None})
    return paired


def build_archive_stub_markdown(xhs_row: dict[str, Any] | None, dy_row: dict[str, Any] | None) -> str:
    title = core_archive_title(xhs_row, dy_row)
    form_label = content_form_label(xhs_row, dy_row)
    row_dates = [row_publish_iso(row) for row in (xhs_row, dy_row) if row]
    created_date = min(row_dates) if row_dates else "1970-01-01"
    platforms = " / ".join(platform for platform, row in ((XHS_PLATFORM, xhs_row), (DY_PLATFORM, dy_row)) if row) or "-"
    blocks = []
    if xhs_row:
        blocks.append(render_archive_block(XHS_PLATFORM, xhs_row))
    if dy_row:
        blocks.append(render_archive_block(DY_PLATFORM, dy_row))
    lines = [f"# {title}", ""]
    if blocks:
        lines.append("\n\n---\n\n".join(blocks))
        lines.extend(["", "---", ""])
    lines.extend(
        [
            "## 基本信息",
            f"- 创建日期：{created_date}",
            f"- 目标平台：{platforms}",
            f"- 内容形式：{form_label}",
            "- 来源：creator-platform-ingest 自动归档",
            "- 状态：待补内容资产",
            "",
            "## 来源说明",
            "",
            "- 本条内容已在创作者后台发布，数据已由 creator-platform-ingest 自动写回。",
            "- 小红书和抖音经常会使用不同标题、正文和 tag；自动归档默认保留平台差异，不做低置信度合并。",
            "- 当前归档为自动创建壳子，口播稿正文 / 图文正文 / 封面标题仍需人工补齐后再进入完整归档状态。",
        ]
    )
    if form_label == "口播视频":
        lines.extend(["", "## 完整口播文案（待补）", "", "（待补）"])
    if form_label == "图文":
        lines.extend(["", "## 图文正文（待补）", "", "（待补）"])
    return "\n".join(lines).rstrip() + "\n"


def create_archive_stubs(repo_root: Path, rows: list[dict[str, Any]], dry_run: bool) -> list[str]:
    created_paths: list[str] = []
    for pair in pair_unmatched_rows(rows):
        xhs_row = pair.get("xhs")
        dy_row = pair.get("dy")
        title = core_archive_title(xhs_row, dy_row)
        published_at = row_publish_iso(xhs_row or dy_row).replace("-", "")
        path = repo_root / ARCHIVE_DIR / f"{published_at}-{archive_filename_component(title)}.md"
        if path.exists():
            continue
        if not dry_run:
            path.write_text(build_archive_stub_markdown(xhs_row, dy_row), encoding="utf-8")
        created_paths.append(str(path))
    return created_paths


def with_recomputed_archive_matches(rows: list[dict[str, Any]], archives: list[Any]) -> list[dict[str, Any]]:
    patched = []
    for row in rows:
        row = dict(row)
        matches = row_archive_matches(row["title"], archives)
        row["resolved_archive_paths"] = [item["path"] for item in matches]
        row["resolved_archive_matches"] = matches
        patched.append(row)
    return patched


def row_primary_metric(row: dict[str, Any]) -> int:
    metric = row["metrics"].get("views") or row["metrics"].get("plays")
    normalized = metric_normalized(metric)
    return int(normalized) if isinstance(normalized, (int, float)) else 0


def row_in_window(row: dict[str, Any], window: dict[str, Any] | None) -> bool:
    if not window or not window.get("start_date") or not window.get("end_date") or not row.get("published_at"):
        return False
    published = row["published_at"][:10]
    return window["start_date"] <= published <= window["end_date"]


def row_in_platform_window(row: dict[str, Any], payload: dict[str, Any]) -> bool:
    platform = row["platform"]
    window = payload.get("account_snapshot", {}).get(platform, {}).get("data_window")
    return row_in_window(row, window)


def xhs_row_analysis(row: dict[str, Any]) -> str:
    views = metric_normalized(row["metrics"].get("views")) or 0
    ctr = metric_normalized(row["metrics"].get("content_ctr")) or 0
    saves = metric_normalized(row["metrics"].get("saves")) or 0
    followers = metric_normalized(row["metrics"].get("followers_gained")) or 0
    impressions = metric_normalized(row["metrics"].get("impressions")) or 0
    if views >= 10000 or saves >= 300:
        return "🔥 强表现（观看和收藏都已经进入爆款区）"
    if views >= 1000 or saves >= 30 or followers >= 10:
        return "✅ 中腰部验证（当前窗口里拿到了有效观看承接）"
    if ctr >= 12 and views < 400:
        return "待优化（点击有了，但分发还没放大）"
    if impressions >= 500 and ctr < 5:
        return "⚠️ 待复盘（平台给了展示，但封面承接偏弱）"
    if views < 100:
        return "⚠️ 待复盘（当前样本太小，先别下题材结论）"
    return "待观察（有基础承接，继续补样本）"


def dy_row_analysis(row: dict[str, Any]) -> str:
    plays = metric_normalized(row["metrics"].get("plays")) or 0
    five_sec = metric_normalized(row["metrics"].get("five_second_completion_rate")) or 0
    saves = metric_normalized(row["metrics"].get("saves")) or 0
    followers = metric_normalized(row["metrics"].get("followers_gained")) or 0
    bounce = metric_normalized(row["metrics"].get("bounce_2s_rate")) or 0
    if plays >= 10000 or followers >= 30:
        return "🔥 强表现（播放和转粉已经进入放大区）"
    if saves >= 15 and plays >= 800:
        return "✅ 中位验证（内容有带走感，可以继续优化开头）"
    if five_sec >= 45 and plays < 3000:
        return "待优化（钩子成立，但分发还没有放大）"
    if five_sec < 35 or bounce >= 55:
        return "⚠️ 扑街（前 5 秒承接偏弱，跳出偏高）"
    return "待观察（指标中位，还需要更多样本）"


def render_xhs_table(rows: list[dict[str, Any]]) -> str:
    headers = ["日期", "标题", "曝光", "观看", "内容点击率（单条口径）", "点赞", "收藏", "分享", "涨粉", "分析"]
    lines = [f"#### 视频（{sum(1 for row in rows if row['resolved_content_type'] == 'video')}条）", ""]
    video_rows = [row for row in rows if row["resolved_content_type"] == "video"]
    lines.append(
        render_markdown_table(
            headers,
            [
                [
                    short_mmdd(row.get("publish_date")),
                    row["title"],
                    display_metric(row["metrics"].get("impressions")),
                    display_metric(row["metrics"].get("views")),
                    percentage_text(row["metrics"].get("content_ctr")),
                    display_metric(row["metrics"].get("likes")),
                    display_metric(row["metrics"].get("saves")),
                    display_metric(row["metrics"].get("shares")),
                    display_metric(row["metrics"].get("followers_gained")),
                    xhs_row_analysis(row),
                ]
                for row in video_rows
            ],
        )
    )
    image_rows = [row for row in rows if row["resolved_content_type"] == "image_text"]
    lines.extend(
        [
            "",
            f"#### 图文（{len(image_rows)}条）",
            "",
            render_markdown_table(
                headers,
                [
                    [
                        short_mmdd(row.get("publish_date")),
                        row["title"],
                        display_metric(row["metrics"].get("impressions")),
                        display_metric(row["metrics"].get("views")),
                        percentage_text(row["metrics"].get("content_ctr")),
                        display_metric(row["metrics"].get("likes")),
                        display_metric(row["metrics"].get("saves")),
                        display_metric(row["metrics"].get("shares")),
                        display_metric(row["metrics"].get("followers_gained")),
                        xhs_row_analysis(row),
                    ]
                    for row in image_rows
                ],
            ),
        ]
    )
    unknown_rows = [row for row in rows if row["resolved_content_type"] == "unknown"]
    if unknown_rows:
        lines.extend(
            [
                "",
                f"#### 待识别体裁（{len(unknown_rows)}条）",
                "",
                render_markdown_table(
                    headers,
                    [
                        [
                            short_mmdd(row.get("publish_date")),
                            row["title"],
                            display_metric(row["metrics"].get("impressions")),
                            display_metric(row["metrics"].get("views")),
                            percentage_text(row["metrics"].get("content_ctr")),
                            display_metric(row["metrics"].get("likes")),
                            display_metric(row["metrics"].get("saves")),
                            display_metric(row["metrics"].get("shares")),
                            display_metric(row["metrics"].get("followers_gained")),
                            "待识别（analysis 已补核心指标，但体裁没有稳定来源）",
                        ]
                        for row in unknown_rows
                    ],
                ),
            ]
        )
    return "\n".join(lines)


def render_dy_table(rows: list[dict[str, Any]]) -> str:
    headers = ["日期", "标题", "体裁", "播放", "点赞", "收藏", "分享", "评论", "粉丝+", "5s完播", "完播率", "平均时长", "分析"]
    return render_markdown_table(
        headers,
        [
            [
                short_mmdd(row.get("publish_date")),
                row["title"],
                "视频",
                display_metric(row["metrics"].get("plays")),
                display_metric(row["metrics"].get("likes")),
                display_metric(row["metrics"].get("saves")),
                display_metric(row["metrics"].get("shares")),
                display_metric(row["metrics"].get("comments")),
                display_metric(row["metrics"].get("followers_gained")),
                percentage_text(row["metrics"].get("five_second_completion_rate")),
                percentage_text(row["metrics"].get("completion_rate")),
                display_metric(row["metrics"].get("average_play_seconds")),
                dy_row_analysis(row),
            ]
            for row in rows
        ],
    )


def build_cross_platform_rows(rows: list[dict[str, Any]], archive_titles: dict[str, str]) -> list[list[str]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        archive_path = best_archive_path(row)
        if not archive_path:
            continue
        grouped[archive_path][row["platform"]] = row
    rendered = []
    for archive_path, platform_rows in grouped.items():
        xhs_row = platform_rows.get("xhs")
        dy_row = platform_rows.get("dy")
        xhs_views = metric_normalized((xhs_row or {}).get("metrics", {}).get("views")) or 0
        dy_plays = metric_normalized((dy_row or {}).get("metrics", {}).get("plays")) or 0
        if xhs_row and dy_row:
            if dy_plays >= 100000 and xhs_views >= 10000:
                conclusion = "两平台都爆，抖音爆发更强"
            elif dy_plays >= max(xhs_views * 8, 3000):
                conclusion = "抖音显著更强，优先继续放大视频表达"
            elif xhs_views >= max(dy_plays * 0.8, 500):
                conclusion = "小红书更稳，说明标题和收藏承接更适合这题"
            else:
                conclusion = "两边都在中位区，需要继续靠包装和形式拉开差异"
        elif xhs_row:
            conclusion = "当前只有小红书样本，先看搜索和收藏承接"
        else:
            conclusion = "当前只有抖音样本，先看能不能进入更高播放区"
        rendered.append(
            [
                archive_titles.get(archive_path, Path(archive_path).stem),
                display_metric((dy_row or {}).get("metrics", {}).get("plays")),
                display_metric((xhs_row or {}).get("metrics", {}).get("views")),
                display_metric((dy_row or {}).get("metrics", {}).get("likes")),
                display_metric((xhs_row or {}).get("metrics", {}).get("likes")),
                conclusion,
            ]
        )
    rendered.sort(key=lambda item: (item[1] != "-", int(item[1].replace(",", "")) if item[1] not in {"-", ""} and item[1].replace(",", "").isdigit() else 0), reverse=True)
    return rendered


def build_xhs_key_trends(rows: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[str]:
    window = snapshot.get("data_window")
    period_rows = [row for row in rows if row_in_window(row, window)]
    period_rows = sorted(period_rows, key=row_primary_metric, reverse=True)
    exposure = display_metric(snapshot.get("metrics", {}).get("曝光数"))
    views = display_metric(snapshot.get("metrics", {}).get("观看数"))
    ctr = display_metric(snapshot.get("metrics", {}).get("封面点击率"))
    completion = display_metric(snapshot.get("metrics", {}).get("视频完播率"))
    bullets = [
        f"**当前窗口总曝光 {exposure}、总观看 {views}、平台封面点击率 {ctr}**：这是当前近 7 日账号快照，不再混写到单条内容里。",
        f"**当前窗口完播率 {completion}**：说明账号层的内容承接已经从 03 月下旬的低位开始恢复，但还没出现真正的大放量样本。",
    ]
    if period_rows:
        top_row = period_rows[0]
        bullets.append(
            f"**{short_mmdd(top_row.get('publish_date'))}《{top_row['title']}》是窗口内观看最高的新样本**："
            f"`{display_metric(top_row['metrics'].get('views'))}` 观看、`{display_metric(top_row['metrics'].get('saves'))}` 收藏。"
        )
    high_ctr = max(period_rows, key=lambda row: metric_normalized(row["metrics"].get("content_ctr")) or 0, default=None)
    if high_ctr:
        bullets.append(
            f"**窗口内点击承接最好的是《{high_ctr['title']}》**：内容点击率 `{display_metric(high_ctr['metrics'].get('content_ctr'))}`，"
            f"说明当前标题和封面更能带来第一步点进。"
        )
    return bullets


def build_dy_key_trends(rows: list[dict[str, Any]], trend_series: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    play_series = trend_series.get("series", {}).get("plays", [])
    plays = [metric_normalized(point.get("value")) or 0 for point in play_series]
    average = round(sum(plays) / len(plays)) if plays else 0
    bullets = []
    if plays:
        direction = "回升" if plays[-1] >= plays[0] else "回落"
        bullets.append(
            f"**近7日播放序列已抓到 {len(plays)} 个日点**：日均播放 `{average:,}`，从 `{plays[0]:,}` 到 `{plays[-1]:,}`，当前处在{direction}段。"
        )
    summary_metrics = snapshot.get("metrics", {})
    if summary_metrics:
        bullets.append(
            f"**当前窗口主页访问 {display_metric(summary_metrics.get('主页访问量'))}、作品分享 {display_metric(summary_metrics.get('作品分享'))}**："
            "这层数据现在已经能跟单条作品判断一起看，不需要再靠导出表补。"
        )
    window = snapshot.get("data_window")
    period_rows = [row for row in rows if row_in_window(row, window)]
    period_rows = sorted(period_rows, key=row_primary_metric, reverse=True)
    if period_rows:
        top_row = period_rows[0]
        bullets.append(
            f"**窗口内播放最高的新内容是《{top_row['title']}》**："
            f"`{display_metric(top_row['metrics'].get('plays'))}` 播放、`{display_metric(top_row['metrics'].get('saves'))}` 收藏、"
            f"`{display_metric(top_row['metrics'].get('five_second_completion_rate'))}` 5s 完播。"
        )
    return bullets


def build_top_data_section(
    payload: dict[str, Any],
    xhs_rows: list[dict[str, Any]],
    dy_rows: list[dict[str, Any]],
) -> str:
    xhs_snapshot = payload["account_snapshot"]["xhs"]
    dy_snapshot = payload["account_snapshot"]["dy"]
    xhs_window = xhs_snapshot.get("data_window")
    dy_window = dy_snapshot.get("data_window")
    xhs_metrics = xhs_snapshot.get("metrics", {})
    dy_aggregate = dy_snapshot.get("works_aggregate", {})
    note_count = payload["capture_context"]["xhs"]["note_manager"].get("list_total_count") or len(xhs_rows)
    xhs_headers = [
        ["曝光", display_metric(xhs_metrics.get("曝光数"))],
        ["观看", display_metric(xhs_metrics.get("观看数"))],
        ["平台封面点击率（账号口径）", display_metric(xhs_metrics.get("封面点击率"))],
        ["平均观看时长", "-"],
        ["总观看时长", "-"],
        ["完播率", display_metric(xhs_metrics.get("视频完播率"))],
        ["笔记数", f"{note_count}条"],
    ]
    dy_overview_rows = [
        ["总播放", display_metric(dy_aggregate.get("总播放"))],
        ["总点赞", display_metric(dy_aggregate.get("总点赞"))],
        ["总收藏", display_metric(dy_aggregate.get("总收藏"))],
        ["投稿量", display_metric(dy_aggregate.get("累计视频数"))],
        ["垂类", "科技,财经"],
        ["封面点击率（账号口径）", "-"],
        ["条均5s完播率", display_metric(dy_aggregate.get("条均5s完播率"))],
        ["条均2s跳出率", display_metric(dy_aggregate.get("条均2s跳出率"))],
        ["条均播放时长", display_metric(dy_aggregate.get("条均播放时长"))],
        ["播放量中位数", display_metric(dy_aggregate.get("播放量中位数"))],
    ]
    cross_rows = build_cross_platform_rows([*xhs_rows, *dy_rows], {doc.path: doc.title for doc in load_archive_docs(Path.cwd())})
    return "\n".join(
        [
            "## 2026年数据 - 小红书",
            "",
            f"### 账号概览（{format_window_with_period(xhs_window, xhs_snapshot.get('selected_period'))}）",
            "",
            "> 指标口径说明（小红书）：",
            "> - `平台封面点击率（账号口径）`：直接取自创作者后台账号概览，不等于单条内容的 `观看/曝光`。",
            "> - `内容点击率（单条口径）`：来自 `content-analysis` 页的单篇 `封面点击率`。",
            "> - 当前首页没有稳定暴露 `平均观看时长 / 总观看时长`，所以暂时保留为 `-`，不再臆造。",
            "",
            render_markdown_table(["指标", "数值"], xhs_headers),
            "",
            f"### 关键趋势（{format_window_with_period(xhs_window, xhs_snapshot.get('selected_period'))}）",
            "",
            *[f"- {bullet}" for bullet in build_xhs_key_trends(xhs_rows, xhs_snapshot)],
            "",
            "### 单条内容明细（全量）",
            "",
            render_xhs_table(xhs_rows),
            "",
            "## 2026年数据 - 抖音",
            "",
            f"### 账号概览（{format_window_with_period(dy_window, dy_snapshot.get('selected_period'))}）",
            "",
            "> 注：账号层当前仍以 `works_aggregate` 为主，封面点击率没有平台级汇总，所以继续留空。",
            "",
            render_markdown_table(["指标", "数值"], dy_overview_rows),
            "",
            f"### 关键趋势（{format_window_with_period(dy_window, dy_snapshot.get('selected_period'))}）",
            "",
            *[f"- {bullet}" for bullet in build_dy_key_trends(dy_rows, payload["trend_series"]["dy"], dy_snapshot)],
            "",
            render_dy_table(dy_rows),
            "",
            "## 跨平台对比",
            "",
            "### 同题/同源变体不同平台表现",
            "",
            "> 注：下表用于比较同一核心选题在不同平台的承接差异，部分内容是同题不同包装或同源改写，不等于逐字同稿。",
            "",
            render_markdown_table(["内容", "抖音播放", "小红书观看", "抖音点赞", "小红书点赞", "结论"], cross_rows),
            "",
            "### 平台特性差异",
            "",
            render_markdown_table(
                ["维度", "抖音", "小红书"],
                [
                    ["流量分发", "算法推荐为主", "搜索+推荐双驱动"],
                    ["用户行为", "刷视频，快速消费", "搜索教程，主动学习"],
                    ["内容偏好", "热点解释、概念科普、横评", "教程、工具、清单、图文承接"],
                    ["互动特点", "点赞和涨粉更明显", "收藏和搜索意图更明显"],
                ],
            ),
        ]
    )


def build_snapshot_footer(payload: dict[str, Any], content_data_text: str, xhs_rows: list[dict[str, Any]], dy_rows: list[dict[str, Any]], captured_at: datetime) -> str:
    xhs_snapshot = payload["account_snapshot"]["xhs"]
    dy_snapshot = payload["account_snapshot"]["dy"]
    xhs_headers, xhs_existing_rows = parse_history_rows(content_data_text, "### 小红书账号成长")
    dy_headers, dy_existing_rows = parse_history_rows(content_data_text, "### 抖音账号成长")
    today = captured_at.strftime("%m-%d")
    xhs_new_row = [
        today,
        format_window_with_period(xhs_snapshot.get("data_window"), xhs_snapshot.get("selected_period")),
        display_metric(xhs_snapshot.get("metrics", {}).get("曝光数")),
        display_metric(xhs_snapshot.get("metrics", {}).get("观看数")),
        display_metric(xhs_snapshot.get("metrics", {}).get("封面点击率")),
        "-",
        "-",
        display_metric(xhs_snapshot.get("metrics", {}).get("视频完播率")),
        str(payload["capture_context"]["xhs"]["note_manager"].get("list_total_count") or len(xhs_rows)),
        "改为 creator-platform 抓取，content-analysis 已补全 29 条单篇指标",
    ]
    dy_new_row = [
        today,
        format_date_label(dy_snapshot.get("data_window")),
        display_metric(dy_snapshot.get("works_aggregate", {}).get("总播放")),
        display_metric(dy_snapshot.get("works_aggregate", {}).get("总点赞")),
        display_metric(dy_snapshot.get("works_aggregate", {}).get("总收藏")),
        display_metric(dy_snapshot.get("works_aggregate", {}).get("累计视频数")),
        "改为 creator-platform 抓取，首页趋势和作品级验证指标已打通",
    ]
    xhs_rows_updated = update_snapshot_rows(xhs_existing_rows, xhs_new_row)
    dy_rows_updated = update_snapshot_rows(dy_existing_rows, dy_new_row)
    previous_dy_row = dy_existing_rows[0] if dy_existing_rows else None
    dy_growth_rows = [dy_new_row, *(dy_existing_rows[:5])]
    return "\n".join(
        [
            "---",
            "",
            f"*最后更新：{captured_at.date().isoformat()}*",
            "*数据来源：creator-platform-ingest（web-access 抓取）*",
            "",
            "---",
            "",
            "## 历史快照",
            "",
            "> 每次导入数据时，记录一次账号概览快照，用于追踪成长趋势。",
            "",
            "### 小红书账号成长",
            "",
            render_markdown_table(
                xhs_headers or ["快照日期", "数据周期", "曝光", "观看", "平台封面点击率（账号口径）", "平均时长", "总时长", "完播率", "累计笔记数", "备注"],
                xhs_rows_updated,
            ),
            "",
            "### 抖音账号成长",
            "",
            render_markdown_table(
                dy_headers or ["快照日期", "数据周期", "总播放", "总点赞", "总收藏", "累计视频数", "备注"],
                dy_rows_updated,
            ),
            "",
            f"### 抖音账号整体指标（{format_date_label(dy_snapshot.get('data_window'))}）",
            "",
            render_markdown_table(
                ["指标", "数值"],
                [
                    ["投稿量", display_metric(dy_snapshot.get("works_aggregate", {}).get("累计视频数"))],
                    ["垂类", "科技,财经"],
                    ["条均5s完播率", display_metric(dy_snapshot.get("works_aggregate", {}).get("条均5s完播率"))],
                    ["条均2s跳出率", display_metric(dy_snapshot.get("works_aggregate", {}).get("条均2s跳出率"))],
                    ["条均播放时长", display_metric(dy_snapshot.get("works_aggregate", {}).get("条均播放时长"))],
                    ["播放量中位数", display_metric(dy_snapshot.get("works_aggregate", {}).get("播放量中位数"))],
                    ["条均点赞", display_metric(dy_snapshot.get("works_aggregate", {}).get("条均点赞"))],
                    ["条均评论", display_metric(dy_snapshot.get("works_aggregate", {}).get("条均评论"))],
                    ["条均分享", display_metric(dy_snapshot.get("works_aggregate", {}).get("条均分享"))],
                ],
            ),
            "",
            "### 成长趋势分析",
            "",
            "#### 小红书近7日监控",
            "",
            *[f"- {bullet}" for bullet in build_xhs_key_trends(xhs_rows, xhs_snapshot)],
            "",
            "#### 抖音趋势",
            "",
            render_markdown_table(
                ["快照日期", "总播放", "总点赞", "总收藏", "视频数"],
                [[row[0], row[2], row[3], row[4], row[5]] for row in dy_growth_rows if len(row) >= 6],
            ),
            "",
            "**关键洞察**：",
            f"- 当前抖音总播放已到 `{display_metric(dy_snapshot.get('works_aggregate', {}).get('总播放'))}`，"
            f"较上一轮 `{previous_dy_row[2] if previous_dy_row and len(previous_dy_row) > 2 else '-'}` 继续上升。",
            f"- 当前小红书内容表已经能直接回写 `{len(xhs_rows)}` 条单篇样本，不再需要手工拿 xlsx 做二次拼表。",
            f"- Capture coverage 告警仍保留：{'; '.join(payload['capture_coverage']['warnings']) if payload['capture_coverage']['warnings'] else '本轮无显式告警'}",
        ]
    )


def replace_between_markers(text: str, start_heading: str, end_heading: str, replacement: str) -> str:
    start = text.find(start_heading)
    end = text.find(end_heading)
    if start == -1 or end == -1 or start >= end:
        raise ValueError(f"Could not replace block between {start_heading!r} and {end_heading!r}")
    return text[:start] + replacement.rstrip() + "\n\n" + text[end:]


def replace_footer(text: str, replacement: str) -> str:
    marker = "\n*最后更新："
    idx = text.find(marker)
    if idx == -1:
        idx = text.find("\n## 历史快照")
    if idx == -1:
        raise ValueError("Could not find footer marker in 内容数据表.md")
    return text[:idx].rstrip() + "\n\n" + replacement.rstrip() + "\n"


def extract_archive_front(text: str) -> tuple[str, dict[str, str], str]:
    lines = text.splitlines()
    if not lines:
        return "", {}, ""
    h1 = lines[0]
    blocks: dict[str, str] = {}
    idx = 1
    while idx < len(lines):
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines) and lines[idx].strip() == "---":
            idx += 1
            continue
        if idx >= len(lines) or not lines[idx].startswith("## 数据表现（"):
            break
        start = idx
        platform = XHS_PLATFORM if XHS_PLATFORM in lines[idx] else DY_PLATFORM
        idx += 1
        while idx < len(lines):
            if lines[idx].strip() == "---":
                lookahead = idx + 1
                while lookahead < len(lines) and not lines[lookahead].strip():
                    lookahead += 1
                if lookahead < len(lines) and lines[lookahead].startswith("## 数据表现（"):
                    blocks[platform] = "\n".join(lines[start:idx]).strip()
                    idx = lookahead
                    break
                blocks[platform] = "\n".join(lines[start:idx]).strip()
                idx = lookahead
                return h1, blocks, "\n".join(lines[idx:]).lstrip("\n")
            if lines[idx].startswith("## ") and not lines[idx].startswith("## 数据表现（"):
                blocks[platform] = "\n".join(lines[start:idx]).strip()
                return h1, blocks, "\n".join(lines[idx:]).lstrip("\n")
            idx += 1
        else:
            blocks[platform] = "\n".join(lines[start:idx]).strip()
            return h1, blocks, ""
    return h1, blocks, "\n".join(lines[idx:]).lstrip("\n")


def extract_existing_cover_title(block_text: str | None) -> str | None:
    if not block_text:
        return None
    match = re.search(r"\*\*封面标题\*\*：(.+)", block_text)
    return match.group(1).strip() if match else None


def find_any_cover_title(text: str) -> str | None:
    match = re.search(r"\*\*封面标题\*\*：(.+)", text)
    return match.group(1).strip() if match else None


def extract_section_by_prefixes(text: str, prefixes: tuple[str, ...]) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if any(line.startswith(prefix) for prefix in prefixes):
            end = idx + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            return "\n".join(lines[idx:end]).strip()
    return None


def archive_asset_gaps(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    gaps: list[str] = []
    is_video = "内容形式：口播视频" in text or "内容形式：视频" in text
    is_image_text = "内容形式：图文" in text
    if is_video and not re.search(r"\*\*封面标题\*\*：\s*(?!（未填写）)(.+)", text):
        gaps.append("封面标题")
    if is_video:
        oral_section = extract_section_by_prefixes(text, ("## 完整口播文案", "## 实际发布文案（抖音版）"))
        if not oral_section or "（待补）" in oral_section or "表格中无口播文案数据" in oral_section:
            gaps.append("口播稿正文")
    if is_image_text:
        image_section = extract_section_by_prefixes(text, ("## 图文正文", "## 实际发布文案（小红书版）"))
        if not image_section or "（待补）" in image_section:
            gaps.append("图文正文")
    return gaps


def render_archive_block(platform: str, row: dict[str, Any], cover_title: str | None = None) -> str:
    publish_date = row.get("publish_date") or "-"
    if platform == XHS_PLATFORM:
        table = render_markdown_table(
            ["指标", "数值"],
            [
                ["曝光", display_metric(row["metrics"].get("impressions"))],
                ["观看", display_metric(row["metrics"].get("views"))],
                ["内容点击率（单条口径）", display_metric(row["metrics"].get("content_ctr"))],
                ["点赞", display_metric(row["metrics"].get("likes"))],
                ["收藏", display_metric(row["metrics"].get("saves"))],
                ["分享", display_metric(row["metrics"].get("shares"))],
                ["涨粉", display_metric(row["metrics"].get("followers_gained"))],
            ],
        )
        return "\n".join(
            [
                f"## 数据表现（小红书 {publish_date}）",
                "",
                table,
                "",
                f"**小红书标题**：{row['title']}",
                "",
                f"**表现评级**：{xhs_row_analysis(row)}",
            ]
        )
    table = render_markdown_table(
        ["指标", "数值"],
        [
            ["播放量", display_metric(row["metrics"].get("plays"))],
            ["完播率", display_metric(row["metrics"].get("completion_rate"))],
            ["5s完播率", display_metric(row["metrics"].get("five_second_completion_rate"))],
            ["封面点击率", display_metric(row["metrics"].get("cover_ctr"))],
            ["2s跳出率", display_metric(row["metrics"].get("bounce_2s_rate"))],
            ["平均播放时长", display_metric(row["metrics"].get("average_play_seconds"))],
            ["点赞", display_metric(row["metrics"].get("likes"))],
            ["收藏", display_metric(row["metrics"].get("saves"))],
            ["评论", display_metric(row["metrics"].get("comments"))],
            ["分享", display_metric(row["metrics"].get("shares"))],
            ["主页访问", display_metric(row["metrics"].get("profile_visits"))],
            ["涨粉", display_metric(row["metrics"].get("followers_gained"))],
        ],
    )
    lines = [
        f"## 数据表现（抖音 {publish_date}）",
        "",
        table,
        "",
        f"**抖音标题**：{row['title']}",
    ]
    if cover_title:
        lines.extend(["", f"**封面标题**：{cover_title}"])
    lines.extend(["", f"**表现评级**：{dy_row_analysis(row)}"])
    return "\n".join(lines)


def update_archive_file(path: Path, xhs_row: dict[str, Any] | None, dy_row: dict[str, Any] | None) -> bool:
    original = path.read_text(encoding="utf-8")
    h1, existing_blocks, remainder = extract_archive_front(original)
    new_blocks = []
    xhs_block = render_archive_block(XHS_PLATFORM, xhs_row) if xhs_row else existing_blocks.get(XHS_PLATFORM)
    preserved_cover = extract_existing_cover_title(existing_blocks.get(DY_PLATFORM)) or find_any_cover_title(original)
    dy_block = render_archive_block(DY_PLATFORM, dy_row, preserved_cover) if dy_row else existing_blocks.get(DY_PLATFORM)
    for block in (xhs_block, dy_block):
        if block:
            new_blocks.append(block)
    front = f"{h1}\n\n" + "\n\n---\n\n".join(new_blocks) if new_blocks else h1
    updated = front.rstrip()
    if remainder.strip():
        updated += "\n\n---\n\n" + remainder.lstrip("\n")
    else:
        updated += "\n"
    if updated == original:
        return False
    path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    return True


def build_review_markdown(payload: dict[str, Any], xhs_rows: list[dict[str, Any]], dy_rows: list[dict[str, Any]], captured_at: datetime) -> tuple[str, str]:
    review_start, review_end = infer_week_window(captured_at)
    review_name = f"{captured_at.isocalendar().year}-W{captured_at.isocalendar().week:02d}-周运营复盘.md"
    review_path = REVIEW_DIR / review_name
    xhs_window = payload["account_snapshot"]["xhs"].get("data_window")
    dy_window = payload["account_snapshot"]["dy"].get("data_window")
    xhs_recent = sorted([row for row in xhs_rows if row_in_window(row, xhs_window)], key=row_primary_metric, reverse=True)
    dy_recent = sorted([row for row in dy_rows if row_in_window(row, dy_window)], key=row_primary_metric, reverse=True)
    active_action_ids = payload.get("match_hints", {}).get("active_action_ids", [])
    hit_rows = [row for row in payload["content_rows"] if row.get("matched_action_ids")]
    lines = [
        f"# {captured_at.isocalendar().year} W{captured_at.isocalendar().week:02d} 周运营复盘",
        "",
        f"- **周期**：{review_start.isoformat()} ~ {review_end.isoformat()}",
        f"- **复盘口径**：基于 creator-platform 近7日抓取窗口（小红书 {format_date_label(xhs_window)} / 抖音 {format_date_label(dy_window)}）",
        "- **状态说明**：本次是 Phase 3 自动写回产物，动作卡只在命中样本时自动建议，未命中时保留原状态。",
        "",
        "## 本周结果",
        "",
        "### 抖音",
    ]
    if dy_recent:
        for row in dy_recent[:3]:
            lines.append(
                f"- `{short_mmdd(row.get('publish_date'))} {row['title']}`："
                f"`{display_metric(row['metrics'].get('plays'))}` 播放、"
                f"`{display_metric(row['metrics'].get('five_second_completion_rate'))}` 5s 完播、"
                f"`{display_metric(row['metrics'].get('saves'))}` 收藏。{dy_row_analysis(row)}"
            )
    else:
        lines.append("- 当前窗口没有新的抖音作品样本。")
    lines.extend(["", "### 小红书"])
    if xhs_recent:
        for row in xhs_recent[:3]:
            lines.append(
                f"- `{short_mmdd(row.get('publish_date'))} {row['title']}`："
                f"`{display_metric(row['metrics'].get('views'))}` 观看、"
                f"`{display_metric(row['metrics'].get('content_ctr'))}` 点击率、"
                f"`{display_metric(row['metrics'].get('saves'))}` 收藏。{xhs_row_analysis(row)}"
            )
    else:
        lines.append("- 当前窗口没有新的小红书样本。")
    lines.extend(
        [
            "",
            "## 关键问题",
            f"1. **当前活跃动作仍是旧的 API 系列**：active action ids = `{', '.join(active_action_ids) if active_action_ids else '-'}`，但本轮抓取没有命中新的 API 样本。",
            "2. **小红书首页没有稳定暴露平均观看时长 / 总观看时长**：这两个字段现在继续显式留空，不再拿旧 xlsx 口径硬填。",
            "3. **小红书 note-manager 仍是虚拟列表**：但 content-analysis 已经补齐单篇核心指标，所以 Phase 3 可以继续写回。",
            "",
            "## 进行中动作判断",
        ]
    )
    if hit_rows:
        for row in hit_rows:
            lines.append(
                f"- `{row['title']}` 命中动作 `{', '.join(row.get('matched_action_ids') or [])}`，"
                f"当前主指标为 `{display_metric(row['metrics'].get('views') or row['metrics'].get('plays'))}`，建议人工确认是否更新 `Actual Result`。"
            )
    else:
        lines.append("- 本轮抓取没有命中 `📋 进行中的运营动作.md` 里的活动样本，所以动作卡暂不自动改写。")
    lines.extend(
        [
            "",
            "## 下周建议动作",
            "1. 抖音继续优先做能过前 5 秒的明确结果型表达，不再测试过底层的纯概念题。",
            "2. 小红书继续保留判断型标题，但要同步优化分发承接，不要只看点击率。",
            "3. 先把当前几条新内容的口播稿 / 封面标题补齐，再决定是否新建动作卡。",
            "",
            "## 停做建议",
            "- 暂停把旧的 xlsx 手工导入当成主流程，这轮 capture 已经够写回核心文档。",
            "- 暂停把没有平台样本的动作卡继续写得更复杂，先拿到真实样本再判断。",
            "",
            "## 本周结论",
            "- **系统层面**：Creator Platform Ingest 已经能覆盖抓取、补单篇、回写三段主链路。",
            "- **内容层面**：抖音和小红书都需要继续拿新样本，不要让历史爆款替代当前判断。",
            "- **流程层面**：从这周开始，`内容数据表 / 已发布稿 / 周复盘` 可以直接从 capture 写回，不再手动拼表。",
        ]
    )
    return str(review_path), "\n".join(lines).rstrip() + "\n"


def build_report(
    changed_files: list[str],
    untouched_archives: int,
    unmatched_rows: list[str],
    created_archives: list[str],
    asset_gaps: dict[str, list[str]],
    action_hits: int,
    dry_run: bool,
    review_path: str,
) -> str:
    lines = [
        "# Phase 3 Writeback Report",
        "",
        f"- mode: {'dry-run' if dry_run else 'apply'}",
        f"- updated_files: {len(changed_files)}",
        f"- untouched_archives: {untouched_archives}",
        f"- created_archives: {len(created_archives)}",
        f"- action_hits: {action_hits}",
        f"- weekly_review_target: {review_path}",
        "",
        "## Changed Files",
    ]
    if changed_files:
        lines.extend([f"- {path}" for path in changed_files])
    else:
        lines.append("- none")
    lines.extend(["", "## Unmatched Rows"])
    if unmatched_rows:
        lines.extend([f"- {title}" for title in unmatched_rows[:20]])
    else:
        lines.append("- none")
    lines.extend(["", "## Created Archives"])
    if created_archives:
        lines.extend([f"- {path}" for path in created_archives])
    else:
        lines.append("- none")
    lines.extend(["", "## Asset Gaps"])
    if asset_gaps:
        for path, gaps in asset_gaps.items():
            lines.append(f"- {path}: {', '.join(gaps)}")
    else:
        lines.append("- none")
    lines.extend(["", "## User Supplement Needed"])
    lines.append(
        "> 只需要人工补 `封面标题 / 完整口播稿 / 图文正文 / 归档合并关系`。"
        "平台已发布的标题、正文和 tag 应由 creator-platform-ingest 抓取，不要求用户手填。"
    )
    if not asset_gaps and not unmatched_rows and not created_archives:
        lines.append("- none")
    else:
        for path, gaps in asset_gaps.items():
            fields = " / ".join(gaps)
            lines.append(f"- `{path}`：补 `{fields}`。")
        if unmatched_rows:
            for title in unmatched_rows[:20]:
                lines.append(f"- 归档归属待确认：`{title}`。判断它应独立归档，还是并入某篇现有归档。")
        if dry_run and created_archives:
            for path in created_archives:
                lines.append(f"- dry-run 将新建归档壳子：`{path}`；正式写回后再按 Asset Gaps 补内容资产。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True, help="Path to capture.json")
    parser.add_argument("--repo-root", default=".", help="ai-content repo root")
    parser.add_argument("--dry-run", action="store_true", help="Do not modify repo files")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    capture_path = Path(args.capture).resolve()
    payload = read_json(capture_path)
    captured_at = datetime.fromisoformat(payload["captured_at"])
    content_data_path = repo_root / CONTENT_DATA_PATH
    content_data_text = content_data_path.read_text(encoding="utf-8")

    initial_archives = load_archive_docs(repo_root)
    initial_rows = with_recomputed_archive_matches(payload["content_rows"], initial_archives)
    initial_unmatched = [row for row in initial_rows if not best_archive_path(row) and row_in_platform_window(row, payload)]
    created_archives = create_archive_stubs(repo_root, initial_unmatched, args.dry_run)

    archives = load_archive_docs(repo_root)
    archive_content_types = {doc.path: doc.content_type for doc in archives}
    rows = with_recomputed_archive_matches(payload["content_rows"], archives)
    existing_type_hints = extract_existing_xhs_type_hints(content_data_text)
    xhs_rows = [dict(row) for row in rows if row["platform"] == "xhs"]
    dy_rows = [dict(row) for row in rows if row["platform"] == "dy"]
    for row in xhs_rows:
        row["resolved_content_type"] = resolve_xhs_content_type(row, existing_type_hints, archive_content_types)
    xhs_rows.sort(key=lambda row: (row.get("published_at") or "", row_primary_metric(row)), reverse=True)
    dy_rows.sort(key=lambda row: (row.get("published_at") or "", row_primary_metric(row)), reverse=True)

    top_section = build_top_data_section(payload, xhs_rows, dy_rows)
    footer = build_snapshot_footer(payload, content_data_text, xhs_rows, dy_rows, captured_at)
    updated_content_data = replace_between_markers(content_data_text, "## 2026年数据 - 小红书", "## 数据分析", top_section)
    updated_content_data = replace_footer(updated_content_data, footer)

    changed_files: list[str] = []
    for path in created_archives:
        changed_files.append(path)
    if updated_content_data != content_data_text:
        if not args.dry_run:
            content_data_path.write_text(updated_content_data.rstrip() + "\n", encoding="utf-8")
        changed_files.append(str(content_data_path))

    grouped_archives: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    unmatched_rows = []
    for row in rows:
        archive_path = best_archive_path(row)
        if archive_path:
            grouped_archives[archive_path][row["platform"]] = row
        else:
            unmatched_rows.append(f"{row['platform']}: {row['title']}")
    untouched_archives = 0
    for doc in archives:
        row_group = grouped_archives.get(doc.path)
        if not row_group:
            untouched_archives += 1
            continue
        archive_changed = False
        if not args.dry_run:
            archive_changed = update_archive_file(Path(doc.path), row_group.get("xhs"), row_group.get("dy"))
        else:
            archive_changed = True
        if archive_changed:
            changed_files.append(doc.path)

    current_window_archive_paths = {
        best_archive_path(row)
        for row in rows
        if best_archive_path(row) and row_in_platform_window(row, payload)
    }
    asset_gap_map: dict[str, list[str]] = {}
    for archive_path in sorted(path for path in current_window_archive_paths if path):
        gaps = archive_asset_gaps(Path(archive_path))
        if gaps:
            asset_gap_map[archive_path] = gaps

    review_path, review_text = build_review_markdown(payload, xhs_rows, dy_rows, captured_at)
    if not args.dry_run:
        target = repo_root / Path(review_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(review_text, encoding="utf-8")
    changed_files.append(str((repo_root / Path(review_path)).resolve()))

    report_text = build_report(
        changed_files=changed_files,
        untouched_archives=untouched_archives,
        unmatched_rows=unmatched_rows,
        created_archives=created_archives,
        asset_gaps=asset_gap_map,
        action_hits=sum(1 for row in rows if row.get("matched_action_ids")),
        dry_run=args.dry_run,
        review_path=review_path,
    )
    report_path = capture_path.with_name("writeback-report.md")
    report_path.write_text(report_text, encoding="utf-8")
    print(json.dumps({"report": str(report_path), "changed_files": changed_files}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
