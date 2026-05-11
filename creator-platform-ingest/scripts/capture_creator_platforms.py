#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any


XHS_HOME_URL = "https://creator.xiaohongshu.com/new/home"
XHS_NOTES_URL = "https://creator.xiaohongshu.com/new/note-manager"
XHS_ANALYSIS_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
DY_HOME_URL = "https://creator.douyin.com/creator-micro/home"
DY_WORKS_URL = "https://creator.douyin.com/creator-micro/content/manage"

ACTIVE_TOKENS = ("active", "current", "selected", "checked", "is-", "on", "cur")
NON_TEXT_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+", re.IGNORECASE)
ACTION_BLOCK_RE = re.compile(r"> \[!task\] 运营动作(?P<body>.*?)(?=\n> \[!task\] 运营动作|\Z)", re.S)


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def request_json(url: str, data: str | None = None) -> Any:
    payload = None if data is None else data.encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    if payload is not None:
        req.add_header("Content-Type", "text/plain; charset=utf-8")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


class ProxyClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def targets(self) -> list[dict[str, Any]]:
        return request_json(self._url("/targets"))

    def new(self, url: str) -> str:
        encoded = urllib.parse.quote(url, safe="")
        data = request_json(self._url(f"/new?url={encoded}"))
        return data["targetId"]

    def info(self, target: str) -> dict[str, Any]:
        return request_json(self._url(f"/info?target={target}"))

    def eval(self, target: str, expression: str) -> Any:
        data = request_json(self._url(f"/eval?target={target}"), expression)
        return json.loads(data["value"])

    def close(self, target: str) -> None:
        request_json(self._url(f"/close?target={target}"))

    def scroll_bottom(self, target: str) -> None:
        request_json(self._url(f"/scroll?target={target}&direction=bottom"))


@dataclass
class PageCapture:
    target: str
    page: dict[str, Any]
    dom: dict[str, Any]
    parsed: dict[str, Any]


@dataclass
class ArchiveDoc:
    path: str
    title: str
    normalized_title: str
    normalized_stem: str
    normalized_aliases: list[str]
    content_type: str | None


@dataclass
class ActionCard:
    action_id: str
    platform: str | None
    content_links: list[str]
    link_titles: list[str]
    normalized_text: str


def parse_chinese_number(raw: str) -> float | int | None:
    raw = raw.strip().replace(",", "")
    if not raw:
        return None
    if raw.endswith("%"):
        try:
            return float(raw[:-1])
        except ValueError:
            return None
    if raw.endswith("秒"):
        number = raw[:-1]
        try:
            return float(number)
        except ValueError:
            return None
    if raw.endswith("s"):
        try:
            return float(raw[:-1])
        except ValueError:
            return None
    if raw.endswith("h"):
        try:
            return float(raw[:-1])
        except ValueError:
            return None
    multiplier = 1
    number = raw
    if raw.endswith("亿"):
        multiplier = 100000000
        number = raw[:-1]
    elif raw.endswith("万"):
        multiplier = 10000
        number = raw[:-1]
    try:
        value = float(number)
    except ValueError:
        return None
    scaled = value * multiplier
    return int(scaled) if float(scaled).is_integer() else scaled


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize_text(raw: str) -> str:
    lowered = raw.lower().strip()
    lowered = re.sub(r"\s+#\S+", " ", lowered)
    lowered = lowered.replace("｜", "|")
    lowered = lowered.replace("·", " ")
    lowered = NON_TEXT_RE.sub("", lowered)
    return lowered


def clean_title(raw: str) -> str:
    title = raw.strip()
    title = re.sub(r"\s+#\S+", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def build_metric_block(lines: list[str], labels: list[str]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for idx, line in enumerate(lines):
        if line not in labels:
            continue
        value = lines[idx + 1] if idx + 1 < len(lines) else ""
        delta = lines[idx + 2] if idx + 2 < len(lines) and (
            lines[idx + 2].startswith("环比") or lines[idx + 2].startswith("较前")
        ) else None
        metrics[line] = {
            "raw": value,
            "normalized": parse_chinese_number(value),
            "delta": delta,
        }
    return metrics


def parse_duration_seconds(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.fullmatch(r"(\d{2}):(\d{2})", raw.strip())
    if not match:
        return None
    minutes, seconds = match.groups()
    return int(minutes) * 60 + int(seconds)


def format_duration_mmss(total_seconds: int | None) -> str | None:
    if total_seconds is None:
        return None
    minutes, seconds = divmod(int(total_seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def parse_datetime_string(raw: str) -> str | None:
    raw = raw.strip()
    patterns = [
        r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})",
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})",
        r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        year, month, day, hour, minute = [int(part) for part in match.groups()]
        return datetime(year, month, day, hour, minute).isoformat(timespec="minutes")
    return None


def iso_from_unix_timestamp(raw: Any) -> str | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(value).isoformat(timespec="minutes")


def parse_date_range(raw: str | None, reference_dt: datetime) -> dict[str, Any] | None:
    if not raw:
        return None
    cleaned = re.sub(r"（.*?）|\(.*?\)", "", raw).strip()
    match = re.search(
        r"(?:(\d{4})[.\-/年])?(\d{1,2})[.\-/月](\d{1,2})日?\s*(?:至|~|-)\s*(?:(\d{4})[.\-/年])?(\d{1,2})[.\-/月](\d{1,2})日?",
        cleaned,
    )
    if not match:
        return {"raw": raw, "start_date": None, "end_date": None, "days": None}
    start_year_raw, start_month, start_day, end_year_raw, end_month, end_day = match.groups()
    start_year = int(start_year_raw) if start_year_raw else reference_dt.year
    end_year = int(end_year_raw) if end_year_raw else start_year
    start = date(start_year, int(start_month), int(start_day))
    end = date(end_year, int(end_month), int(end_day))
    if end < start and not end_year_raw:
        end = date(start_year + 1, int(end_month), int(end_day))
    return {
        "raw": raw,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": (end - start).days + 1,
    }


def infer_period_label(window: dict[str, Any] | None) -> str | None:
    if not window or not window.get("days"):
        return None
    days = window["days"]
    if days <= 8:
        return "近7日"
    if days <= 31:
        return "近30日"
    return None


def find_date_range_in_lines(lines: list[str], reference_dt: datetime) -> dict[str, Any] | None:
    for line in lines:
        if not re.search(r"\d", line):
            continue
        parsed = parse_date_range(line, reference_dt)
        if parsed and parsed.get("start_date"):
            return parsed
    return None


def make_metric(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return {"raw": cleaned, "normalized": parse_chinese_number(cleaned)}


def format_count_metric(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return make_metric(str(raw))
    return {"raw": str(value), "normalized": value}


def format_ratio_metric(raw: Any, *, decimals: int = 1) -> dict[str, Any] | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    percentage = round(value * 100, decimals)
    return {"raw": f"{percentage:.{decimals}f}%", "normalized": percentage}


def format_seconds_metric(raw: Any, *, decimals: int = 1) -> dict[str, Any] | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    rounded = round(value, decimals)
    return {"raw": f"{rounded:.{decimals}f}s", "normalized": rounded}


def net_followers_metric(subscribe_raw: Any, unsubscribe_raw: Any) -> dict[str, Any] | None:
    try:
        subscribe = int(subscribe_raw or 0)
        unsubscribe = int(unsubscribe_raw or 0)
    except (TypeError, ValueError):
        return None
    net = subscribe - unsubscribe
    return {"raw": str(net), "normalized": net}


def safe_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def safe_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def average_metric(values: list[float | int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def parse_xhs_analysis_title_cell(raw: str) -> tuple[str, str | None]:
    text = raw.strip()
    if not text:
        return "", None
    match = re.search(r"发布于\s*([0-9.\-年月日:\s]+)", text)
    if match:
        title = text[: match.start()].strip()
        published_at_raw = match.group(1).strip()
        return clean_title(title or text), published_at_raw
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", None
    if len(lines) >= 2 and lines[-1].startswith("发布于"):
        return clean_title(" ".join(lines[:-1])), lines[-1].replace("发布于", "", 1).strip()
    return clean_title(lines[0]), None


def select_active_label(interactive: list[dict[str, Any]], labels: list[str]) -> str | None:
    exact = [item for item in interactive if item.get("text") in labels]
    for item in exact:
        class_name = (item.get("className") or "").lower()
        if item.get("ariaSelected") == "true" or item.get("ariaCurrent") or any(token in class_name for token in ACTIVE_TOKENS):
            return item.get("text")
    return None


def collect_labels(lines: list[str], labels: list[str]) -> list[str]:
    return [label for label in labels if label in lines]


def collect_snapshot(proxy: ProxyClient, target: str) -> dict[str, Any]:
    expression = r"""
JSON.stringify((() => {
  const bodyText = document.body && document.body.innerText ? document.body.innerText : "";
  const anchors = Array.from(document.querySelectorAll('a[href]')).map((a, index) => ({
    index,
    text: (a.innerText || a.textContent || "").trim().replace(/\s+/g, " "),
    href: a.href || "",
    className: typeof a.className === "string" ? a.className : "",
    ariaLabel: a.getAttribute("aria-label") || ""
  })).filter(item => item.text || item.href).slice(0, 500);
  const interactive = Array.from(
    document.querySelectorAll('button, [role="tab"], [role="button"], a, .ant-tabs-tab, .el-tabs__item')
  ).map((el, index) => ({
    index,
    tag: el.tagName.toLowerCase(),
    text: (el.innerText || el.textContent || "").trim().replace(/\s+/g, " "),
    className: typeof el.className === "string" ? el.className : "",
    ariaSelected: el.getAttribute("aria-selected"),
    ariaCurrent: el.getAttribute("aria-current"),
    role: el.getAttribute("role"),
    href: el.href || ""
  })).filter(item => item.text).slice(0, 800);
  const xhsNoteCards = location.href.includes('/new/note-manager')
    ? Array.from(document.querySelectorAll('.note')).map((el, index) => {
        const titleEl = el.querySelector('.title');
        const hrefEl = el.querySelector('a[href]');
        const rawLines = (el.innerText || el.textContent || '')
          .split(/\n+/)
          .map(line => line.trim())
          .filter(Boolean);
        let noteId = null;
        try {
          const impression = el.dataset && el.dataset.impression ? JSON.parse(el.dataset.impression) : null;
          noteId =
            impression?.params?.noteTarget?.value?.noteId ||
            impression?.params?.noteId ||
            impression?.noteId ||
            null;
        } catch (error) {}
        const publishedAtLine = rawLines.find(line => line.startsWith('发布于')) || '';
        const durationLine = rawLines.find(line => /^\d{2}:\d{2}$/.test(line)) || '';
        return {
          index,
          title: (titleEl?.innerText || titleEl?.textContent || '').trim().replace(/\s+/g, ' '),
          href: hrefEl?.href || '',
          noteId,
          publishedAtRaw: publishedAtLine.replace(/^发布于\s*/, ''),
          duration: durationLine,
          rawLines: rawLines.slice(0, 20),
        };
      }).filter(item => item.title).slice(0, 500)
    : [];
  const xhsAnalysisHeaders = location.href.includes('/statistics/data-analysis')
    ? Array.from(document.querySelectorAll('thead th'))
        .map(el => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' '))
        .filter(Boolean)
        .slice(0, 50)
    : [];
  const xhsAnalysisRows = location.href.includes('/statistics/data-analysis')
    ? Array.from(document.querySelectorAll('tbody tr')).map((tr, index) => ({
        index,
        cells: Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || td.textContent || '').trim()),
        detailAction: (() => {
          const el = tr.querySelector('.note-detail');
          return el ? (el.innerText || el.textContent || '').trim() : '';
        })(),
      })).filter(item => item.cells.some(Boolean)).slice(0, 500)
    : [];
  return {
    title: document.title,
    url: location.href,
    readyState: document.readyState,
    bodyText,
    anchors,
    interactive,
    xhsNoteCards,
    xhsAnalysisHeaders,
    xhsAnalysisRows
  };
})())
"""
    return proxy.eval(target, expression)


def fetch_xhs_note_cards(proxy: ProxyClient, target: str) -> dict[str, Any]:
    expression = r"""
(async () => {
  const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const extractCards = () => Array.from(document.querySelectorAll('.note')).map((el, index) => {
    const titleEl = el.querySelector('.title');
    const hrefEl = el.querySelector('a[href]');
    const rawLines = (el.innerText || el.textContent || '')
      .split(/\n+/)
      .map(line => line.trim())
      .filter(Boolean);
    let noteId = null;
    try {
      const impression = el.dataset && el.dataset.impression ? JSON.parse(el.dataset.impression) : null;
      noteId =
        impression?.params?.noteTarget?.value?.noteId ||
        impression?.params?.noteId ||
        impression?.noteId ||
        null;
    } catch (error) {}
    const publishedAtLine = rawLines.find(line => line.startsWith('发布于')) || '';
    const durationLine = rawLines.find(line => /^\d{2}:\d{2}$/.test(line)) || '';
    return {
      index,
      title: (titleEl?.innerText || titleEl?.textContent || '').trim().replace(/\s+/g, ' '),
      href: hrefEl?.href || '',
      noteId,
      publishedAtRaw: publishedAtLine.replace(/^发布于\s*/, ''),
      duration: durationLine,
      rawLines: rawLines.slice(0, 24),
    };
  }).filter(item => item.title);

  const containers = Array.from(document.querySelectorAll('*'))
    .filter(el => el.querySelector('.note') && el.scrollHeight > el.clientHeight + 50)
    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
  const container = containers[0] || null;
  const collected = new Map();
  const addVisible = () => {
    for (const card of extractCards()) {
      const key = [card.title, card.publishedAtRaw, card.duration].join('||');
      if (!collected.has(key)) collected.set(key, card);
    }
  };

  addVisible();
  if (container) {
    const maxScroll = Math.max(0, container.scrollHeight - container.clientHeight);
    const step = Math.max(180, Math.floor(container.clientHeight * 0.7));
    const positions = [];
    for (let pos = 0; pos <= maxScroll; pos += step) positions.push(pos);
    if (!positions.includes(maxScroll)) positions.push(maxScroll);
    for (const pos of positions) {
      container.scrollTop = pos;
      container.dispatchEvent(new Event('scroll', { bubbles: true }));
      await delay(350);
      addVisible();
    }
    container.scrollTop = maxScroll;
    container.dispatchEvent(new Event('scroll', { bubbles: true }));
    await delay(600);
    addVisible();
  }

  return JSON.stringify({
    cards: Array.from(collected.values()),
    count: collected.size,
    container: container ? {
      className: typeof container.className === 'string' ? container.className : '',
      scrollHeight: container.scrollHeight,
      clientHeight: container.clientHeight,
    } : null,
  });
})()
"""
    return proxy.eval(target, expression)


def fetch_xhs_analysis_rows(proxy: ProxyClient, target: str) -> dict[str, Any]:
    expression = r"""
(async () => {
  const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const extractRows = () => Array.from(document.querySelectorAll('tbody tr')).map((tr, index) => ({
    index,
    cells: Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || td.textContent || '').trim()),
    detailAction: (() => {
      const el = tr.querySelector('.note-detail');
      return el ? (el.innerText || el.textContent || '').trim() : '';
    })(),
  })).filter(item => item.cells.some(Boolean));

  const pageNodes = Array.from(document.querySelectorAll('.d-pagination-page'))
    .map(el => {
      const text = (el.innerText || el.textContent || '').trim();
      const page = parseInt(text, 10);
      return Number.isNaN(page) ? null : { el, page };
    })
    .filter(Boolean);
  const pages = Array.from(new Set(pageNodes.map(item => item.page))).sort((a, b) => a - b);
  const collected = [];

  const visitPage = async (page) => {
    const pageNode = pageNodes.find(item => item.page === page);
    if (!pageNode) return;
    pageNode.el.click();
    await delay(500);
    const rows = extractRows();
    collected.push({ page, rows });
  };

  if (!pages.length) {
    collected.push({ page: 1, rows: extractRows() });
  } else {
    for (const page of pages) {
      await visitPage(page);
    }
  }

  return JSON.stringify({
    pages,
    collected,
    total_rows: collected.reduce((sum, item) => sum + item.rows.length, 0),
  });
})()
"""
    return proxy.eval(target, expression)


def find_anchor_href(anchors: list[dict[str, Any]], title: str) -> str | None:
    wanted = normalize_text(title)
    if not wanted:
        return None
    best_href = None
    best_score = 0.0
    for anchor in anchors:
        href = anchor.get("href") or ""
        if not href or href.startswith("javascript:"):
            continue
        anchor_text = normalize_text(anchor.get("text") or "")
        if not anchor_text:
            continue
        ratio = SequenceMatcher(None, wanted, anchor_text).ratio()
        if wanted in anchor_text or anchor_text in wanted:
            ratio += 0.2
        if ratio > best_score:
            best_score = ratio
            best_href = href
    return best_href if best_score >= 0.55 else None


def parse_xhs_home(snapshot: dict[str, Any], reference_dt: datetime) -> dict[str, Any]:
    lines = clean_lines(snapshot["bodyText"])
    result: dict[str, Any] = {
        "account_name": None,
        "account_id": None,
        "profile_bio": None,
        "counts": {},
        "period": None,
        "data_window": None,
        "selected_period": None,
        "available_periods": collect_labels(lines, ["近7日", "近30日"]),
        "metrics": {},
        "last_updated": None,
    }
    try:
        idx = lines.index("创作服务平台")
        result["account_name"] = lines[idx + 1]
    except ValueError:
        pass
    for idx, line in enumerate(lines):
        if line.startswith("小红书账号:"):
            result["account_id"] = line.split(":", 1)[1].strip()
            if idx + 1 < len(lines):
                result["profile_bio"] = lines[idx + 1]
        if line in {"关注数", "粉丝数", "获赞与收藏"} and idx > 0:
            result["counts"][line] = {
                "raw": lines[idx - 1],
                "normalized": parse_chinese_number(lines[idx - 1]),
            }
        if line.startswith("统计周期 "):
            result["period"] = line.replace("统计周期 ", "", 1)
            result["data_window"] = parse_date_range(result["period"], reference_dt)
        if line.startswith("数据最后更新时间 "):
            result["last_updated"] = line.replace("数据最后更新时间 ", "", 1)
    selected = select_active_label(snapshot.get("interactive", []), ["近7日", "近30日"])
    result["selected_period"] = selected or infer_period_label(result["data_window"])
    labels = [
        "曝光数",
        "观看数",
        "封面点击率",
        "视频完播率",
        "点赞数",
        "评论数",
        "收藏数",
        "分享数",
        "净涨粉",
        "新增关注",
        "取消关注",
        "主页访客",
    ]
    result["metrics"] = build_metric_block(lines, labels)
    return result


def build_xhs_note_from_card(card: dict[str, Any]) -> dict[str, Any]:
    raw_lines = [line.strip() for line in card.get("rawLines") or [] if line and line.strip()]
    published_at_raw = card.get("publishedAtRaw") or ""
    if not published_at_raw:
        published_line = next((line for line in raw_lines if line.startswith("发布于")), "")
        published_at_raw = published_line.replace("发布于", "", 1).strip()
    numeric = []
    if raw_lines:
        try:
            published_idx = next(i for i, line in enumerate(raw_lines) if line.startswith("发布于"))
        except StopIteration:
            published_idx = 1 if card.get("duration") else 0
        end_idx = next((i for i, line in enumerate(raw_lines[published_idx + 1 :], start=published_idx + 1) if line == "权限设置"), len(raw_lines))
        numeric = raw_lines[published_idx + 1 : end_idx]
    mapped_labels = ["观看", "评论", "点赞", "收藏", "分享"]
    metrics: dict[str, dict[str, Any]] = {}
    for label, raw in zip(mapped_labels, numeric[:5]):
        metrics[label] = {"raw": raw, "normalized": parse_chinese_number(raw)}
    duration = card.get("duration") or None
    title = clean_title(card.get("title") or "")
    return {
        "title": title,
        "title_raw": card.get("title") or title,
        "published_at_raw": published_at_raw,
        "published_at": parse_datetime_string(published_at_raw),
        "duration": duration,
        "duration_seconds": parse_duration_seconds(duration),
        "content_type": "video" if duration else "image_text",
        "metrics": metrics,
        "content_url": card.get("href") or "",
        "note_id": card.get("noteId"),
    }


def parse_xhs_notes(snapshot: dict[str, Any], full_note_cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    lines = clean_lines(snapshot["bodyText"])
    notes: list[dict[str, Any]] = []
    total = None
    for line in lines:
        match = re.match(r"全部笔记\((\d+)\)", line)
        if match:
            total = int(match.group(1))
            break
    if full_note_cards:
        notes = [build_xhs_note_from_card(card) for card in full_note_cards]
        selected_status = select_active_label(snapshot.get("interactive", []), ["已发布", "审核中", "未通过"])
        if not selected_status and notes:
            selected_status = "已发布"
        return {
            "total_notes": total,
            "visible_notes": len(notes),
            "notes": notes,
            "visible_note_cards": len(full_note_cards),
            "selected_status": selected_status,
            "available_statuses": collect_labels(lines, ["已发布", "审核中", "未通过"]),
            "metric_order_assumption": ["观看", "评论", "点赞", "收藏", "分享"],
            "full_capture": True,
        }
    start = 0
    for i, line in enumerate(lines):
        if line in {"未通过", "已发布", "审核中"}:
            start = i + 1
    i = start
    while i < len(lines):
        if lines[i] == "正在加载中...":
            break
        duration = None
        if re.fullmatch(r"\d{2}:\d{2}", lines[i]):
            duration = lines[i]
            i += 1
        if i >= len(lines):
            break
        title = lines[i]
        i += 1
        if i >= len(lines) or not lines[i].startswith("发布于 "):
            continue
        published_at_raw = lines[i].replace("发布于 ", "", 1)
        i += 1
        metric_values: list[str] = []
        while i < len(lines) and lines[i] != "权限设置":
            metric_values.append(lines[i])
            i += 1
        while i < len(lines) and lines[i] in {"权限设置", "置顶", "取消置顶", "编辑", "删除"}:
            i += 1
        numeric = metric_values[:5]
        mapped_labels = ["观看", "评论", "点赞", "收藏", "分享"]
        metrics: dict[str, dict[str, Any]] = {}
        for label, raw in zip(mapped_labels, numeric):
            metrics[label] = {"raw": raw, "normalized": parse_chinese_number(raw)}
        notes.append(
            {
                "title": clean_title(title),
                "title_raw": title,
                "published_at_raw": published_at_raw,
                "published_at": parse_datetime_string(published_at_raw),
                "duration": duration,
                "duration_seconds": parse_duration_seconds(duration),
                "content_type": "video" if duration else "image_text",
                "metrics": metrics,
                "content_url": find_anchor_href(snapshot.get("anchors", []), title),
                "note_id": None,
            }
        )
    note_cards = snapshot.get("xhsNoteCards", [])
    for note in notes:
        best_card = None
        best_score = 0.0
        for card in note_cards:
            score = score_match(normalize_text(note["title"]), normalize_text(card.get("title") or ""))
            note_published = note.get("published_at")
            card_published = parse_datetime_string(card.get("publishedAtRaw") or "")
            if note_published and card_published and note_published[:16] == card_published[:16]:
                score += 0.25
            elif note_published and card_published and note_published[:10] == card_published[:10]:
                score += 0.1
            if score > best_score:
                best_score = score
                best_card = card
        if best_card and best_score >= 0.7:
            note["note_id"] = best_card.get("noteId")
            note["content_url"] = note.get("content_url") or best_card.get("href")
    selected_status = select_active_label(snapshot.get("interactive", []), ["已发布", "审核中", "未通过"])
    if not selected_status and notes:
        selected_status = "已发布"
    return {
        "total_notes": total,
        "visible_notes": len(notes),
        "notes": notes,
        "visible_note_cards": len(note_cards),
        "selected_status": selected_status,
        "available_statuses": collect_labels(lines, ["已发布", "审核中", "未通过"]),
        "metric_order_assumption": ["观看", "评论", "点赞", "收藏", "分享"],
        "full_capture": False,
    }


def parse_xhs_analysis(snapshot: dict[str, Any], reference_dt: datetime, all_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    lines = clean_lines(snapshot["bodyText"])
    headers = snapshot.get("xhsAnalysisHeaders", [])
    rows: list[dict[str, Any]] = []
    source_rows = all_rows if all_rows is not None else snapshot.get("xhsAnalysisRows", [])
    for raw_row in source_rows:
        cells = [cell.strip() for cell in raw_row.get("cells", [])]
        if len(cells) < 10:
            continue
        title, published_at_raw = parse_xhs_analysis_title_cell(cells[0])
        if not title:
            continue
        metric_cells = cells[1:]
        rows.append(
            {
                "title": title,
                "title_raw": cells[0],
                "published_at_raw": published_at_raw,
                "published_at": parse_datetime_string(published_at_raw) if published_at_raw else None,
                "metrics": {
                    "曝光": make_metric(metric_cells[0] if len(metric_cells) > 0 else None),
                    "观看": make_metric(metric_cells[1] if len(metric_cells) > 1 else None),
                    "封面点击率": make_metric(metric_cells[2] if len(metric_cells) > 2 else None),
                    "点赞": make_metric(metric_cells[3] if len(metric_cells) > 3 else None),
                    "评论": make_metric(metric_cells[4] if len(metric_cells) > 4 else None),
                    "收藏": make_metric(metric_cells[5] if len(metric_cells) > 5 else None),
                    "涨粉": make_metric(metric_cells[6] if len(metric_cells) > 6 else None),
                    "分享": make_metric(metric_cells[7] if len(metric_cells) > 7 else None),
                    "人均观看时长": make_metric(metric_cells[8] if len(metric_cells) > 8 else None),
                    "弹幕": make_metric(metric_cells[9] if len(metric_cells) > 9 else None),
                },
                "detail_action": raw_row.get("detailAction") or (metric_cells[10] if len(metric_cells) > 10 else None),
            }
        )
    data_window = find_date_range_in_lines(lines, reference_dt)
    selected_period = select_active_label(snapshot.get("interactive", []), ["近7日", "近30日"]) or infer_period_label(data_window)
    return {
        "data_window": data_window,
        "selected_period": selected_period,
        "available_periods": collect_labels(lines, ["近7日", "近30日"]),
        "headers": headers,
        "visible_rows": len(rows),
        "rows": rows,
        "full_capture": all_rows is not None,
    }


def parse_dy_home(snapshot: dict[str, Any], reference_dt: datetime) -> dict[str, Any]:
    lines = clean_lines(snapshot["bodyText"])
    result: dict[str, Any] = {
        "account_name": None,
        "account_id": None,
        "profile_bio": None,
        "counts": {},
        "period": None,
        "data_window": None,
        "selected_period": None,
        "available_periods": collect_labels(lines, ["近7日", "近30日"]),
        "metrics": {},
        "latest_work": None,
    }
    try:
        idx = lines.index("抖音")
        result["account_name"] = lines[idx + 1]
    except ValueError:
        pass
    for idx, line in enumerate(lines):
        if line.startswith("抖音号："):
            result["account_id"] = line.split("：", 1)[1].strip()
            if idx + 1 < len(lines):
                result["profile_bio"] = lines[idx + 1]
        count_match = re.match(r"^(关注|粉丝|获赞)\s+(.+)$", line)
        if count_match:
            label, raw = count_match.groups()
            result["counts"][label] = {
                "raw": raw,
                "normalized": parse_chinese_number(raw),
            }
        if line.startswith("统计周期："):
            result["period"] = line.replace("统计周期：", "", 1)
            result["data_window"] = parse_date_range(result["period"], reference_dt)
    selected = select_active_label(snapshot.get("interactive", []), ["近7日", "近30日"])
    result["selected_period"] = selected or infer_period_label(result["data_window"])
    summary_slice = lines
    if "数据总览" in lines and "互动管理" in lines:
        start = lines.index("数据总览")
        end = lines.index("互动管理")
        summary_slice = lines[start:end]
    labels = ["播放量", "主页访问量", "作品分享", "作品评论"]
    result["metrics"] = build_metric_block(summary_slice, labels)
    if "最新作品" in lines:
        idx = lines.index("最新作品")
        if idx + 8 < len(lines):
            title = lines[idx + 1]
            latest = {
                "title": clean_title(title),
                "title_raw": title,
                "播放量": lines[idx + 3],
                "点赞量": lines[idx + 5] if idx + 5 < len(lines) else None,
                "评论量": lines[idx + 7] if idx + 7 < len(lines) else None,
                "content_url": find_anchor_href(snapshot.get("anchors", []), title),
            }
            result["latest_work"] = latest
    return result


def build_dy_overview_metric(raw_item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw_item:
        return None
    current_raw = raw_item.get("current_count")
    normalized = parse_chinese_number(str(current_raw)) if current_raw is not None else None
    delta = raw_item.get("last_period_incr")
    return {
        "raw": str(current_raw) if current_raw is not None else None,
        "normalized": normalized,
        "delta": delta,
    }


def build_dy_overview_series(raw_item: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw_item:
        return []
    points = []
    for item in raw_item.get("option_list") or []:
        count_raw = item.get("count")
        points.append(
            {
                "date": item.get("date"),
                "value": {
                    "raw": str(count_raw) if count_raw is not None else None,
                    "normalized": parse_chinese_number(str(count_raw)) if count_raw is not None else None,
                },
                "delta": item.get("last_day_incr_rate"),
            }
        )
    return points


def build_dy_overview_window(raw_overview: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw_overview:
        return None
    play_points = (raw_overview.get("data") or {}).get("play", {}).get("option_list") or []
    dates = []
    for point in play_points:
        raw_date = point.get("date")
        if not raw_date:
            continue
        try:
            dates.append(date.fromisoformat(raw_date))
        except ValueError:
            continue
    if not dates:
        return None
    start = min(dates)
    end = max(dates)
    return {
        "raw": f"{start.isoformat()} -> {end.isoformat()}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": (end - start).days + 1,
    }


def build_dy_overview_summary_metrics(raw_overview: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not raw_overview:
        return {}
    data = raw_overview.get("data") or {}
    mapping = {
        "播放量": "play",
        "主页访问量": "profile",
        "作品分享": "share",
        "作品评论": "comment",
        "点赞量": "digg",
        "新增粉丝": "new_fans",
        "取消关注": "cancel_fans",
    }
    metrics = {}
    for label, key in mapping.items():
        metric = build_dy_overview_metric(data.get(key))
        if metric:
            metrics[label] = metric
    return metrics


def build_dy_works_aggregate(dy_works: PageCapture) -> dict[str, dict[str, Any]]:
    items = dy_works.parsed.get("api", {}).get("items") or []
    if not items:
        return {}
    plays = []
    likes = []
    saves = []
    comments = []
    shares = []
    completion_5s = []
    bounce_2s = []
    avg_play_seconds = []
    for item in items:
        metrics = item.get("metrics") or {}
        if (value := safe_int(metrics.get("view_count"))) is not None:
            plays.append(value)
        if (value := safe_int(metrics.get("like_count"))) is not None:
            likes.append(value)
        if (value := safe_int(metrics.get("favorite_count"))) is not None:
            saves.append(value)
        if (value := safe_int(metrics.get("comment_count"))) is not None:
            comments.append(value)
        if (value := safe_int(metrics.get("share_count"))) is not None:
            shares.append(value)
        if (value := safe_float(metrics.get("completion_rate_5s"))) is not None:
            completion_5s.append(value)
        if (value := safe_float(metrics.get("bounce_rate_2s"))) is not None:
            bounce_2s.append(value)
        if (value := safe_float(metrics.get("avg_view_second"))) is not None:
            avg_play_seconds.append(value)
    return {
        "总播放": format_count_metric(sum(plays)),
        "总点赞": format_count_metric(sum(likes)),
        "总收藏": format_count_metric(sum(saves)),
        "累计视频数": format_count_metric(len(items)),
        "条均5s完播率": format_ratio_metric(average_metric(completion_5s)),
        "条均2s跳出率": format_ratio_metric(average_metric(bounce_2s)),
        "条均播放时长": format_seconds_metric(average_metric(avg_play_seconds)),
        "播放量中位数": format_count_metric(median(plays) if plays else None),
        "条均点赞": format_count_metric(round(average_metric(likes)) if likes else None),
        "条均评论": format_count_metric(round(average_metric(comments)) if comments else None),
        "条均分享": format_count_metric(round(average_metric(shares)) if shares else None),
    }


def parse_dy_works(snapshot: dict[str, Any]) -> dict[str, Any]:
    lines = clean_lines(snapshot["bodyText"])
    total = None
    for line in lines:
        match = re.match(r"共\s+(\d+)\s+个作品", line)
        if match:
            total = int(match.group(1))
            break
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("共 ") and "个作品" in line:
            start = i + 1
            break
    works: list[dict[str, Any]] = []
    i = start
    known_labels = ["播放", "平均播放时长", "封面点击率", "点赞", "评论", "分享", "收藏", "弹幕"]
    while i < len(lines):
        if lines[i] in {"加载中…", "加载中..."}:
            break
        if not re.fullmatch(r"\d{2}:\d{2}", lines[i]):
            i += 1
            continue
        duration = lines[i]
        i += 1
        if i >= len(lines):
            break
        title = lines[i]
        i += 1
        while i < len(lines) and lines[i] not in {"编辑作品"}:
            i += 1
        while i < len(lines) and lines[i] in {"编辑作品", "设置权限", "作品置顶", "删除作品"}:
            i += 1
        if i >= len(lines):
            break
        published_at_raw = lines[i]
        i += 1
        status = None
        if i < len(lines) and lines[i] in {"已发布", "审核中", "未通过"}:
            status = lines[i]
            i += 1
        metrics: dict[str, dict[str, Any]] = {}
        while i < len(lines):
            if re.fullmatch(r"\d{2}:\d{2}", lines[i]) or lines[i] in {"加载中…", "加载中..."}:
                break
            label = lines[i]
            if label in known_labels and i + 1 < len(lines):
                value = lines[i + 1]
                metrics[label] = {"raw": value, "normalized": parse_chinese_number(value)}
                i += 2
                continue
            i += 1
        works.append(
            {
                "title": clean_title(title),
                "title_raw": title,
                "published_at_raw": published_at_raw,
                "published_at": parse_datetime_string(published_at_raw),
                "status": status,
                "duration": duration,
                "duration_seconds": parse_duration_seconds(duration),
                "content_type": "video",
                "metrics": metrics,
                "content_url": find_anchor_href(snapshot.get("anchors", []), title),
            }
        )
    selected_status = select_active_label(snapshot.get("interactive", []), ["全部作品", "已发布", "审核中", "未通过"])
    if not selected_status and works:
        selected_status = "已发布"
    return {
        "total_works": total,
        "visible_works": len(works),
        "works": works,
        "selected_status": selected_status,
        "available_statuses": collect_labels(lines, ["全部作品", "已发布", "审核中", "未通过"]),
    }


def fetch_dy_work_list_api(proxy: ProxyClient, target: str) -> dict[str, Any]:
    expression = r"""
(async () => {
  const pageSize = 20;
  let maxCursor = 0;
  let guard = 0;
  const pages = [];
  const items = [];
  let total = null;
  let hasMore = false;
  while (guard < 10) {
    const url = '/janus/douyin/creator/pc/work_list?status=0&count=' + pageSize + '&max_cursor=' + maxCursor + '&scene=star_atlas&device_platform=android&aid=1128';
    const res = await fetch(url, { credentials: 'include' });
    const data = await res.json();
    const pageItems = data.items || data.aweme_list || [];
    if (total === null && typeof data.total === 'number') total = data.total;
    hasMore = Boolean(data.has_more);
    pages.push({
      request_cursor: maxCursor,
      response_max_cursor: data.max_cursor,
      count: pageItems.length,
      has_more: hasMore,
    });
    items.push(...pageItems);
    if (!hasMore || !pageItems.length || data.max_cursor === maxCursor) break;
    maxCursor = data.max_cursor || 0;
    guard += 1;
  }
  return {
    total,
    fetched_count: items.length,
    has_more: hasMore,
    pages,
    items,
  };
})().then(result => JSON.stringify(result))
"""
    return proxy.eval(target, expression)


def fetch_dy_overview_api(proxy: ProxyClient, target: str, *, last_days_type: int = 1) -> dict[str, Any]:
    expression = f"""
(async () => {{
  const url = '/aweme/janus/creator/data/overview/all/?last_days_type={last_days_type}';
  const res = await fetch(url, {{ credentials: 'include' }});
  const data = await res.json();
  return JSON.stringify({{
    requested_last_days_type: {last_days_type},
    status: res.status,
    ok: res.ok,
    data: data && data.data ? data.data : {{}},
  }});
}})()
"""
    return proxy.eval(target, expression)


def xhs_home_ready(text: str) -> bool:
    return "统计周期" in text and "曝光数" in text and "观看数" in text


def xhs_notes_ready(text: str) -> bool:
    return "全部笔记(" in text and "权限设置" in text


def xhs_analysis_ready(text: str) -> bool:
    return "笔记数据" in text and "封面点击率" in text and "详情数据" in text


def dy_home_ready(text: str) -> bool:
    return "统计周期：" in text and "数据总览" in text and "加载中，请稍候..." not in text


def dy_works_ready(text: str) -> bool:
    return "共 " in text and "编辑作品" in text and "共 0 个作品" not in text


def default_output_dir(base: Path) -> Path:
    return base / ".cache" / "content-pipeline" / "creator-captures" / now_stamp()


def capture_page(
    proxy: ProxyClient,
    url: str,
    parser,
    validator,
    reference_dt: datetime,
    *,
    scroll_bottom: bool = False,
) -> PageCapture:
    target = proxy.new(url)
    last_dom = None
    for _ in range(12):
        page = proxy.info(target)
        dom = collect_snapshot(proxy, target)
        last_dom = dom
        if validator(dom["bodyText"]):
            if scroll_bottom:
                for _ in range(6):
                    proxy.scroll_bottom(target)
                    time.sleep(1)
                    dom = collect_snapshot(proxy, target)
            parsed = parser(dom, reference_dt) if parser in {parse_xhs_home, parse_xhs_analysis, parse_dy_home} else parser(dom)
            return PageCapture(target=target, page=page, dom=dom, parsed=parsed)
        time.sleep(1)
    assert last_dom is not None
    page = proxy.info(target)
    parsed = parser(last_dom, reference_dt) if parser in {parse_xhs_home, parse_xhs_analysis, parse_dy_home} else parser(last_dom)
    return PageCapture(target=target, page=page, dom=last_dom, parsed=parsed)


def load_archive_docs(repo_root: Path) -> list[ArchiveDoc]:
    archive_dir = repo_root / "01-内容生产" / "选题管理" / "03-已发布选题"
    docs: list[ArchiveDoc] = []
    for path in sorted(archive_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = None
        aliases: list[str] = []
        content_type = None
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                continue
            if line.startswith("**抖音标题**：") or line.startswith("**小红书标题**："):
                aliases.append(line.split("：", 1)[1].strip())
            if "内容形式：" in line and content_type is None:
                if "图文" in line:
                    content_type = "image_text"
                elif "视频" in line or "口播" in line:
                    content_type = "video"
        stem = re.sub(r"^\d{8}-", "", path.stem)
        docs.append(
            ArchiveDoc(
                path=str(path),
                title=title or stem,
                normalized_title=normalize_text(title or stem),
                normalized_stem=normalize_text(stem),
                normalized_aliases=sorted({normalize_text(alias) for alias in aliases if normalize_text(alias)}),
                content_type=content_type,
            )
        )
    return docs


def load_action_cards(repo_root: Path, archive_docs: list[ArchiveDoc]) -> list[ActionCard]:
    actions_path = repo_root / "02-业务运营" / "业务规划" / "📋 进行中的运营动作.md"
    if not actions_path.exists():
        return []
    text = actions_path.read_text(encoding="utf-8")
    archive_by_path = {doc.path: doc for doc in archive_docs}
    cards: list[ActionCard] = []
    for match in ACTION_BLOCK_RE.finditer(text):
        body = match.group("body")
        action_id_match = re.search(r"\*\*ID：\*\*\s*(.+)", body)
        platform_match = re.search(r"\*\*Platform：\*\*\s*(.+)", body)
        content_link_match = re.search(r"\*\*Content Link：\*\*\s*(.+)", body)
        link_paths = re.findall(r"`([^`]+\.md)`", content_link_match.group(1) if content_link_match else "")
        absolute_links = [
            str((repo_root / rel).resolve()) if not rel.startswith("/") else rel for rel in link_paths
        ]
        link_titles = []
        for link in absolute_links:
            doc = archive_by_path.get(link)
            if doc:
                link_titles.append(doc.title)
            else:
                link_titles.append(Path(link).stem)
        cards.append(
            ActionCard(
                action_id=action_id_match.group(1).strip() if action_id_match else "UNKNOWN",
                platform=platform_match.group(1).strip() if platform_match else None,
                content_links=absolute_links,
                link_titles=link_titles,
                normalized_text=normalize_text(body),
            )
        )
    return cards


def score_match(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        ratio += 0.2
    return min(ratio, 1.0)


GENERIC_TITLE_PATTERNS = (
    "20s",
    "20秒",
    "30s",
    "30秒",
    "60s",
    "60秒",
    "一分钟",
    "一条",
    "一个",
    "一种",
    "什么是",
    "是什么",
    "到底",
    "速通",
    "讲清",
    "看懂",
    "入门",
    "教程",
    "ai",
    "大模型",
)


def archive_match_core(raw: str) -> str:
    core = normalize_text(raw)
    for pattern in GENERIC_TITLE_PATTERNS:
        core = core.replace(pattern, "")
    return core.strip()


def archive_title_match_score(wanted: str, candidate: str) -> float:
    raw_score = score_match(wanted, candidate)
    if raw_score >= 0.82:
        return raw_score
    wanted_core = archive_match_core(wanted)
    candidate_core = archive_match_core(candidate)
    if not wanted_core or not candidate_core:
        return 0.0
    core_score = score_match(wanted_core, candidate_core)
    # Generic title templates like "20s速通...到底是什么" can look similar
    # while pointing to different concepts. Below the high-confidence band,
    # require the non-generic concept core to agree by containment.
    if not (wanted_core in candidate_core or candidate_core in wanted_core):
        return 0.0
    length_ratio = min(len(wanted_core), len(candidate_core)) / max(len(wanted_core), len(candidate_core))
    if length_ratio < 0.5:
        return 0.0
    return min(max(raw_score, core_score), 1.0)


def row_archive_matches(row_title: str, archives: list[ArchiveDoc]) -> list[dict[str, Any]]:
    wanted = normalize_text(row_title)
    candidates = []
    for doc in archives:
        comparables = [doc.normalized_title, doc.normalized_stem, *doc.normalized_aliases]
        score = max((archive_title_match_score(wanted, candidate) for candidate in comparables if candidate), default=0.0)
        if score >= 0.55:
            candidates.append({"path": doc.path, "title": doc.title, "score": round(score, 3)})
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:3]


def row_action_matches(row_title: str, row_platform: str, action_cards: list[ActionCard]) -> list[str]:
    wanted = normalize_text(row_title)
    matches = []
    for card in action_cards:
        if card.platform and card.platform not in {row_platform, "双平台"}:
            continue
        title_score = max((score_match(wanted, normalize_text(title)) for title in card.link_titles), default=0.0)
        if title_score >= 0.55 or wanted in card.normalized_text:
            matches.append(card.action_id)
    return sorted(set(matches))


def infer_week_window(reference_dt: datetime) -> tuple[date, date]:
    start = reference_dt.date() - timedelta(days=reference_dt.weekday())
    end = start + timedelta(days=6)
    return start, end


def is_current_week(published_at_iso: str | None, reference_dt: datetime) -> bool:
    if not published_at_iso:
        return False
    published_day = datetime.fromisoformat(published_at_iso).date()
    week_start, week_end = infer_week_window(reference_dt)
    return week_start <= published_day <= week_end


def make_content_id(platform: str, published_at_iso: str | None, title: str) -> str:
    base = f"{platform}|{published_at_iso or 'unknown'}|{normalize_text(title)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def build_capture_context(
    captured_at: datetime,
    xhs_home: PageCapture,
    xhs_notes: PageCapture,
    xhs_analysis: PageCapture,
    dy_home: PageCapture,
    dy_works: PageCapture,
) -> dict[str, Any]:
    def context_entry(platform: str, route_name: str, page_capture: PageCapture, *, total_count: int | None = None, visible_count: int | None = None, partial: bool | None = None, data_window: dict[str, Any] | None = None, selected_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "platform": platform,
            "route": route_name,
            "page_url": page_capture.dom.get("url") or page_capture.page.get("url"),
            "page_title": page_capture.dom.get("title") or page_capture.page.get("title"),
            "captured_at": captured_at.isoformat(timespec="seconds"),
            "data_window": data_window,
            "selected_filters": selected_filters or {},
            "list_total_count": total_count,
            "list_visible_count": visible_count,
            "is_partial_result": partial,
        }

    xhs_home_window = xhs_home.parsed.get("data_window")
    dy_home_window = dy_home.parsed.get("data_window")
    return {
        "xhs": {
            "home": context_entry(
                "xhs",
                "home",
                xhs_home,
                data_window=xhs_home_window,
                selected_filters={"period": xhs_home.parsed.get("selected_period")},
            ),
            "note_manager": context_entry(
                "xhs",
                "note_manager",
                xhs_notes,
                total_count=xhs_notes.parsed.get("total_notes"),
                visible_count=xhs_notes.parsed.get("visible_notes"),
                partial=bool(
                    xhs_notes.parsed.get("total_notes")
                    and xhs_notes.parsed.get("visible_notes", 0) < xhs_notes.parsed.get("total_notes", 0)
                ),
                selected_filters={"status": xhs_notes.parsed.get("selected_status")},
            ),
            "content_analysis": context_entry(
                "xhs",
                "content_analysis",
                xhs_analysis,
                visible_count=xhs_analysis.parsed.get("visible_rows"),
                data_window=xhs_analysis.parsed.get("data_window"),
                selected_filters={"period": xhs_analysis.parsed.get("selected_period")},
            ),
        },
        "dy": {
            "home": context_entry(
                "dy",
                "home",
                dy_home,
                data_window=dy_home_window,
                selected_filters={"period": dy_home.parsed.get("selected_period")},
            ),
            "works_manager": context_entry(
                "dy",
                "works_manager",
                dy_works,
                total_count=(
                    dy_works.parsed.get("api", {}).get("total")
                    if dy_works.parsed.get("api", {}).get("total") is not None
                    else dy_works.parsed.get("total_works")
                ),
                visible_count=(
                    dy_works.parsed.get("api", {}).get("fetched_count")
                    if dy_works.parsed.get("api")
                    else dy_works.parsed.get("visible_works")
                ),
                partial=(
                    bool(
                        dy_works.parsed.get("api", {}).get("total")
                        and dy_works.parsed.get("api", {}).get("fetched_count", 0) < dy_works.parsed.get("api", {}).get("total", 0)
                    )
                    if dy_works.parsed.get("api")
                    else bool(
                        dy_works.parsed.get("total_works")
                        and dy_works.parsed.get("visible_works", 0) < dy_works.parsed.get("total_works", 0)
                    )
                ),
                selected_filters={"status": dy_works.parsed.get("selected_status")},
            ),
        },
    }


def build_account_snapshot(xhs_home: PageCapture, dy_home: PageCapture, dy_works: PageCapture) -> dict[str, Any]:
    dy_overview_api = dy_home.parsed.get("overview_api")
    dy_overview_metrics = build_dy_overview_summary_metrics(dy_overview_api) or dy_home.parsed.get("metrics", {})
    return {
        "xhs": {
            "account_name": xhs_home.parsed.get("account_name"),
            "account_id": xhs_home.parsed.get("account_id"),
            "profile_bio": xhs_home.parsed.get("profile_bio"),
            "profile_counts": xhs_home.parsed.get("counts", {}),
            "data_window": xhs_home.parsed.get("data_window"),
            "selected_period": xhs_home.parsed.get("selected_period"),
            "metrics": xhs_home.parsed.get("metrics", {}),
            "last_updated": xhs_home.parsed.get("last_updated"),
        },
        "dy": {
            "account_name": dy_home.parsed.get("account_name"),
            "account_id": dy_home.parsed.get("account_id"),
            "profile_bio": dy_home.parsed.get("profile_bio"),
            "profile_counts": dy_home.parsed.get("counts", {}),
            "data_window": build_dy_overview_window(dy_overview_api) or dy_home.parsed.get("data_window"),
            "selected_period": "近7日" if dy_overview_api else dy_home.parsed.get("selected_period"),
            "metrics": dy_overview_metrics,
            "works_aggregate": build_dy_works_aggregate(dy_works),
            "latest_work": dy_home.parsed.get("latest_work"),
        },
    }


def build_trend_series(xhs_home: PageCapture, dy_home: PageCapture) -> dict[str, Any]:
    xhs_metrics = xhs_home.parsed.get("metrics", {})
    dy_overview_api = dy_home.parsed.get("overview_api")
    dy_metrics = build_dy_overview_summary_metrics(dy_overview_api) or dy_home.parsed.get("metrics", {})
    dy_overview_data = (dy_overview_api or {}).get("data") or {}
    dy_play_series = build_dy_overview_series(dy_overview_data.get("play"))
    dy_profile_series = build_dy_overview_series(dy_overview_data.get("profile"))
    dy_share_series = build_dy_overview_series(dy_overview_data.get("share"))
    dy_comment_series = build_dy_overview_series(dy_overview_data.get("comment"))
    return {
        "xhs": {
            "data_window": xhs_home.parsed.get("data_window"),
            "selected_period": xhs_home.parsed.get("selected_period"),
            "series": {
                "exposure": [],
                "views": [],
                "cover_ctr": [],
                "avg_watch_seconds": [],
                "total_watch_hours": [],
                "completion_rate": [],
            },
            "summary_metrics": {
                "曝光数": xhs_metrics.get("曝光数"),
                "观看数": xhs_metrics.get("观看数"),
                "封面点击率": xhs_metrics.get("封面点击率"),
                "视频完播率": xhs_metrics.get("视频完播率"),
            },
            "status": "summary_only",
            "note": "Current capture resolved the selected-period summary block but did not expose per-day chart points.",
        },
        "dy": {
            "data_window": build_dy_overview_window(dy_overview_api) or dy_home.parsed.get("data_window"),
            "selected_period": "近7日" if dy_overview_api else dy_home.parsed.get("selected_period"),
            "series": {
                "plays": dy_play_series,
                "profile_visits": dy_profile_series,
                "shares": dy_share_series,
                "comments": dy_comment_series,
            },
            "summary_metrics": {
                "播放量": dy_metrics.get("播放量"),
                "主页访问量": dy_metrics.get("主页访问量"),
                "作品分享": dy_metrics.get("作品分享"),
                "作品评论": dy_metrics.get("作品评论"),
            },
            "status": "series_available" if dy_play_series else ("summary_only" if dy_metrics else "missing"),
            "note": (
                "Near-7-day Douyin overview was captured through the homepage overview API."
                if dy_play_series
                else "Homepage summary may stay lazy-loaded. When unavailable, keep the series empty and record the gap explicitly."
            ),
        },
    }


def build_content_rows(
    reference_dt: datetime,
    xhs_notes: PageCapture,
    xhs_analysis: PageCapture,
    dy_works: PageCapture,
    archives: list[ArchiveDoc],
    action_cards: list[ActionCard],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    archive_by_path = {doc.path: doc for doc in archives}
    analysis_rows = xhs_analysis.parsed.get("rows", [])
    unused_analysis = list(analysis_rows)

    for index, note in enumerate(xhs_notes.parsed.get("notes", []), start=1):
        content_id = make_content_id("xhs", note.get("published_at"), note["title"])
        archive_matches = row_archive_matches(note["title"], archives)
        archive_content_type = archive_by_path.get(archive_matches[0]["path"]).content_type if archive_matches else None
        action_matches = row_action_matches(note["title"], "小红书", action_cards)
        row = {
            "platform": "xhs",
            "content_id": content_id,
            "note_id": note.get("note_id"),
            "title": note["title"],
            "title_raw": note["title_raw"],
            "title_normalized": normalize_text(note["title"]),
            "content_type": note.get("content_type") or archive_content_type,
            "duration_raw": note.get("duration"),
            "duration_seconds": note.get("duration_seconds"),
            "published_at": note.get("published_at"),
            "published_at_raw": note.get("published_at_raw"),
            "publish_date": note.get("published_at", "")[:10] or None,
            "list_position": index,
            "content_url": note.get("content_url"),
            "source_ref": f"xhs:{note.get('published_at') or 'unknown'}:{normalize_text(note['title'])}",
            "metrics": {
                "impressions": None,
                "views": note["metrics"].get("观看"),
                "content_ctr": None,
                "likes": note["metrics"].get("点赞"),
                "saves": note["metrics"].get("收藏"),
                "shares": note["metrics"].get("分享"),
                "comments": note["metrics"].get("评论"),
                "followers_gained": None,
                "average_watch_seconds": None,
                "danmaku": None,
            },
            "platform_metrics_raw": note["metrics"],
            "is_current_week": is_current_week(note.get("published_at"), reference_dt),
            "matched_action_ids": action_matches,
            "hit_active_action": bool(action_matches),
            "matched_archive_paths": [item["path"] for item in archive_matches],
            "match_candidates": archive_matches,
            "coverage": {
                "list_visible": True,
                "detail_drilled": False,
                "detail_source": None,
                "missing_core_fields": ["impressions", "content_ctr", "followers_gained"],
            },
        }
        best_match = None
        best_match_index = None
        best_score = 0.0
        for analysis_index, analysis in enumerate(unused_analysis):
            score = score_match(row["title_normalized"], normalize_text(analysis.get("title") or ""))
            if row.get("published_at") and analysis.get("published_at"):
                if row["published_at"][:16] == analysis["published_at"][:16]:
                    score += 0.25
                elif row["published_at"][:10] == analysis["published_at"][:10]:
                    score += 0.1
            if score > best_score:
                best_score = score
                best_match = analysis
                best_match_index = analysis_index
        if best_match and best_score >= 0.7:
            analysis_metrics = best_match.get("metrics", {})
            row["metrics"]["impressions"] = analysis_metrics.get("曝光")
            row["metrics"]["views"] = analysis_metrics.get("观看") or row["metrics"]["views"]
            row["metrics"]["content_ctr"] = analysis_metrics.get("封面点击率")
            row["metrics"]["likes"] = analysis_metrics.get("点赞") or row["metrics"]["likes"]
            row["metrics"]["comments"] = analysis_metrics.get("评论") or row["metrics"]["comments"]
            row["metrics"]["saves"] = analysis_metrics.get("收藏") or row["metrics"]["saves"]
            row["metrics"]["shares"] = analysis_metrics.get("分享") or row["metrics"]["shares"]
            row["metrics"]["followers_gained"] = analysis_metrics.get("涨粉")
            row["metrics"]["average_watch_seconds"] = analysis_metrics.get("人均观看时长")
            row["metrics"]["danmaku"] = analysis_metrics.get("弹幕")
            row["coverage"]["detail_source"] = "content_analysis"
            row["platform_metrics_analysis"] = analysis_metrics
            row["analysis_detail_action"] = best_match.get("detail_action")
            row["coverage"]["missing_core_fields"] = [
                field
                for field in ["impressions", "content_ctr", "followers_gained"]
                if row["metrics"].get(field) is None
            ]
            if best_match_index is not None:
                unused_analysis.pop(best_match_index)
        rows.append(row)

    next_position = len(rows) + 1
    for analysis in unused_analysis:
        title = analysis.get("title") or ""
        if not title:
            continue
        content_id = make_content_id("xhs", analysis.get("published_at"), title)
        archive_matches = row_archive_matches(title, archives)
        archive_content_type = archive_by_path.get(archive_matches[0]["path"]).content_type if archive_matches else None
        action_matches = row_action_matches(title, "小红书", action_cards)
        analysis_metrics = analysis.get("metrics", {})
        row = {
            "platform": "xhs",
            "content_id": content_id,
            "note_id": None,
            "title": title,
            "title_raw": analysis.get("title_raw") or title,
            "title_normalized": normalize_text(title),
            "content_type": archive_content_type,
            "duration_raw": None,
            "duration_seconds": None,
            "published_at": analysis.get("published_at"),
            "published_at_raw": analysis.get("published_at_raw"),
            "publish_date": analysis.get("published_at", "")[:10] or None,
            "list_position": next_position,
            "content_url": "",
            "source_ref": f"xhs_analysis:{analysis.get('published_at') or 'unknown'}:{normalize_text(title)}",
            "metrics": {
                "impressions": analysis_metrics.get("曝光"),
                "views": analysis_metrics.get("观看"),
                "content_ctr": analysis_metrics.get("封面点击率"),
                "likes": analysis_metrics.get("点赞"),
                "saves": analysis_metrics.get("收藏"),
                "shares": analysis_metrics.get("分享"),
                "comments": analysis_metrics.get("评论"),
                "followers_gained": analysis_metrics.get("涨粉"),
                "average_watch_seconds": analysis_metrics.get("人均观看时长"),
                "danmaku": analysis_metrics.get("弹幕"),
            },
            "platform_metrics_raw": {},
            "platform_metrics_analysis": analysis_metrics,
            "analysis_detail_action": analysis.get("detail_action"),
            "is_current_week": is_current_week(analysis.get("published_at"), reference_dt),
            "matched_action_ids": action_matches,
            "hit_active_action": bool(action_matches),
            "matched_archive_paths": [item["path"] for item in archive_matches],
            "match_candidates": archive_matches,
            "coverage": {
                "list_visible": False,
                "detail_drilled": False,
                "detail_source": "content_analysis",
                "missing_core_fields": [
                    field
                    for field in ["impressions", "content_ctr", "followers_gained"]
                    if analysis_metrics.get({"impressions": "曝光", "content_ctr": "封面点击率", "followers_gained": "涨粉"}[field]) is None
                ],
            },
        }
        rows.append(row)
        next_position += 1

    dy_api_items = dy_works.parsed.get("api", {}).get("items") or []
    dy_source_rows = []
    if dy_api_items:
        for item in dy_api_items:
            metrics = item.get("metrics") or {}
            duration_seconds = None
            try:
                duration_seconds = int(round((item.get("video_info", {}) or {}).get("duration", 0) / 1000))
            except (TypeError, ValueError):
                duration_seconds = None
            dy_source_rows.append(
                {
                    "title": clean_title(item.get("description") or ""),
                    "title_raw": item.get("description") or "",
                    "published_at_raw": datetime.fromtimestamp(int(item.get("create_time"))).strftime("%Y年%m月%d日 %H:%M")
                    if item.get("create_time")
                    else None,
                    "published_at": iso_from_unix_timestamp(item.get("create_time")),
                    "status": "已发布" if (item.get("review") or {}).get("status") == 2 else None,
                    "duration": format_duration_mmss(duration_seconds),
                    "duration_seconds": duration_seconds,
                    "content_type": "video",
                    "metrics": {
                        "播放": format_count_metric(metrics.get("view_count")),
                        "点赞": format_count_metric(metrics.get("like_count")),
                        "收藏": format_count_metric(metrics.get("favorite_count")),
                        "分享": format_count_metric(metrics.get("share_count")),
                        "评论": format_count_metric(metrics.get("comment_count")),
                    },
                    "content_url": f"https://www.douyin.com/video/{item.get('id')}" if item.get("id") else None,
                    "platform_item_id": str(item.get("id")) if item.get("id") else None,
                    "api_metrics": metrics,
                }
            )
    else:
        dy_source_rows = list(dy_works.parsed.get("works", []))

    for index, work in enumerate(dy_source_rows, start=1):
        content_id = make_content_id("dy", work.get("published_at"), work["title"])
        archive_matches = row_archive_matches(work["title"], archives)
        action_matches = row_action_matches(work["title"], "抖音", action_cards)
        metrics = work["metrics"]
        api_metrics = work.get("api_metrics") or {}
        followers_gained = net_followers_metric(api_metrics.get("subscribe_count"), api_metrics.get("unsubscribe_count")) if api_metrics else None
        row = {
            "platform": "dy",
            "content_id": content_id,
            "platform_item_id": work.get("platform_item_id"),
            "title": work["title"],
            "title_raw": work["title_raw"],
            "title_normalized": normalize_text(work["title"]),
            "content_type": work.get("content_type"),
            "duration_raw": work.get("duration"),
            "duration_seconds": work.get("duration_seconds"),
            "published_at": work.get("published_at"),
            "published_at_raw": work.get("published_at_raw"),
            "publish_date": work.get("published_at", "")[:10] or None,
            "list_position": index,
            "content_url": work.get("content_url"),
            "source_ref": (
                f"dy_work:{work.get('platform_item_id')}"
                if work.get("platform_item_id")
                else f"dy:{work.get('published_at') or 'unknown'}:{normalize_text(work['title'])}"
            ),
            "status": work.get("status"),
            "metrics": {
                "plays": metrics.get("播放"),
                "likes": metrics.get("点赞"),
                "saves": metrics.get("收藏"),
                "shares": metrics.get("分享"),
                "comments": metrics.get("评论"),
                "followers_gained": followers_gained,
                "five_second_completion_rate": format_ratio_metric(api_metrics.get("completion_rate_5s")) if api_metrics else None,
                "completion_rate": format_ratio_metric(api_metrics.get("completion_rate")) if api_metrics else None,
                "average_play_seconds": (
                    format_seconds_metric(api_metrics.get("avg_view_second")) if api_metrics else metrics.get("平均播放时长")
                ),
                "bounce_2s_rate": format_ratio_metric(api_metrics.get("bounce_rate_2s")) if api_metrics else None,
                "profile_visits": format_count_metric(api_metrics.get("homepage_visit_count")) if api_metrics else None,
                "cover_ctr": (
                    format_ratio_metric(api_metrics.get("cover_click_rate")) if api_metrics.get("cover_click_rate") is not None else metrics.get("封面点击率")
                ),
            },
            "platform_metrics_raw": metrics,
            "platform_metrics_api": api_metrics or None,
            "is_current_week": is_current_week(work.get("published_at"), reference_dt),
            "matched_action_ids": action_matches,
            "hit_active_action": bool(action_matches),
            "matched_archive_paths": [item["path"] for item in archive_matches],
            "match_candidates": archive_matches,
            "coverage": {
                "list_visible": True,
                "detail_drilled": bool(api_metrics),
                "detail_source": "work_list_api" if api_metrics else None,
                "missing_core_fields": [
                    field
                    for field in [
                        "followers_gained",
                        "five_second_completion_rate",
                        "completion_rate",
                        "bounce_2s_rate",
                        "profile_visits",
                    ]
                    if not {
                        "followers_gained": followers_gained,
                        "five_second_completion_rate": format_ratio_metric(api_metrics.get("completion_rate_5s")) if api_metrics else None,
                        "completion_rate": format_ratio_metric(api_metrics.get("completion_rate")) if api_metrics else None,
                        "bounce_2s_rate": format_ratio_metric(api_metrics.get("bounce_rate_2s")) if api_metrics else None,
                        "profile_visits": format_count_metric(api_metrics.get("homepage_visit_count")) if api_metrics else None,
                    }[field]
                ],
            },
        }
        rows.append(row)
    return rows


def build_detail_metrics(content_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for row in content_rows:
        extra_metrics = {}
        source = "content_list"
        if row["platform"] == "dy":
            for key in (
                "followers_gained",
                "five_second_completion_rate",
                "completion_rate",
                "average_play_seconds",
                "bounce_2s_rate",
                "profile_visits",
                "cover_ctr",
            ):
                value = row["metrics"].get(key)
                if value:
                    extra_metrics[key] = value
            if extra_metrics:
                source = row.get("coverage", {}).get("detail_source") or "content_list"
        if row["platform"] == "xhs":
            for key in ("impressions", "content_ctr", "followers_gained", "average_watch_seconds", "danmaku"):
                value = row["metrics"].get(key)
                if value:
                    extra_metrics[key] = value
            if extra_metrics:
                source = "content_analysis"
        if extra_metrics:
            details.append(
                {
                    "content_id": row["content_id"],
                    "platform": row["platform"],
                    "source": source,
                    "metrics": extra_metrics,
                    "status": "partial",
                }
            )
    return details


def build_match_hints(content_rows: list[dict[str, Any]], action_cards: list[ActionCard]) -> dict[str, Any]:
    return {
        "active_action_ids": [card.action_id for card in action_cards],
        "rows": [
            {
                "content_id": row["content_id"],
                "platform": row["platform"],
                "normalized_title": row["title_normalized"],
                "matched_archive_paths": row["matched_archive_paths"],
                "matched_action_ids": row["matched_action_ids"],
                "hit_active_action": row["hit_active_action"],
            }
            for row in content_rows
        ],
    }


def build_capture_coverage(
    capture_context: dict[str, Any],
    trend_series: dict[str, Any],
    content_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    xhs_note_ctx = capture_context["xhs"]["note_manager"]
    xhs_analysis_ctx = capture_context["xhs"]["content_analysis"]
    dy_work_ctx = capture_context["dy"]["works_manager"]
    warnings = []
    if xhs_note_ctx.get("is_partial_result"):
        warnings.append("Xiaohongshu note manager is a partial capture because the list is virtualized.")
    if dy_work_ctx.get("is_partial_result"):
        warnings.append("Douyin works manager is still partial in this capture.")
    if trend_series["dy"]["status"] == "missing":
        warnings.append("Douyin homepage summary metrics were not available in this capture; keep this gap explicit in downstream reports.")
    xhs_rows = [row for row in content_rows if row["platform"] == "xhs"]
    xhs_enriched = sum(1 for row in xhs_rows if row["coverage"].get("detail_source") == "content_analysis")
    xhs_missing = sum(1 for row in xhs_rows if row["metrics"].get("impressions") is None)
    if xhs_analysis_ctx.get("list_visible_count") in {None, 0}:
        warnings.append("Xiaohongshu content analysis page did not yield visible per-note rows, so impressions/content CTR/follower gain remain missing.")
    elif xhs_missing:
        warnings.append(
            f"Xiaohongshu content analysis enriched {xhs_enriched}/{len(xhs_rows)} visible note rows; {xhs_missing} rows still have missing per-note detail fields."
        )
    dy_rows = [row for row in content_rows if row["platform"] == "dy"]
    dy_enriched = sum(1 for row in dy_rows if row["coverage"].get("detail_source") == "work_list_api")
    dy_missing = sum(
        1
        for row in dy_rows
        if any(row["metrics"].get(field) is None for field in ["followers_gained", "five_second_completion_rate", "completion_rate", "bounce_2s_rate", "profile_visits"])
    )
    if dy_rows and dy_enriched < len(dy_rows):
        warnings.append(
            f"Douyin work-list API enriched {dy_enriched}/{len(dy_rows)} work rows; {dy_missing} rows still have missing validation metrics."
        )
    return {
        "pages": {
            "xhs_home": {"captured": True},
            "xhs_note_manager": {
                "captured": True,
                "total_count": xhs_note_ctx.get("list_total_count"),
                "visible_count": xhs_note_ctx.get("list_visible_count"),
                "partial": xhs_note_ctx.get("is_partial_result"),
            },
            "xhs_content_analysis": {
                "captured": True,
                "visible_count": xhs_analysis_ctx.get("list_visible_count"),
                "selected_period": xhs_analysis_ctx.get("selected_filters", {}).get("period"),
                "data_window": xhs_analysis_ctx.get("data_window"),
                "enriched_visible_rows": xhs_enriched,
            },
            "dy_home": {
                "captured": True,
                "summary_metrics_available": trend_series["dy"]["status"] != "missing",
                "trend_points": len(trend_series["dy"]["series"].get("plays", [])),
            },
            "dy_works_manager": {
                "captured": True,
                "total_count": dy_work_ctx.get("list_total_count"),
                "visible_count": dy_work_ctx.get("list_visible_count"),
                "partial": dy_work_ctx.get("is_partial_result"),
                "enriched_visible_rows": dy_enriched,
            },
        },
        "warnings": warnings,
    }


def build_payload(
    repo_root: Path,
    captured_at: datetime,
    xhs_home: PageCapture,
    xhs_notes: PageCapture,
    xhs_analysis: PageCapture,
    dy_home: PageCapture,
    dy_works: PageCapture,
    proxy_url: str,
    keep_tabs: bool,
) -> dict[str, Any]:
    archives = load_archive_docs(repo_root)
    action_cards = load_action_cards(repo_root, archives)
    capture_context = build_capture_context(captured_at, xhs_home, xhs_notes, xhs_analysis, dy_home, dy_works)
    account_snapshot = build_account_snapshot(xhs_home, dy_home, dy_works)
    trend_series = build_trend_series(xhs_home, dy_home)
    content_rows = build_content_rows(captured_at, xhs_notes, xhs_analysis, dy_works, archives, action_cards)
    detail_metrics = build_detail_metrics(content_rows)
    match_hints = build_match_hints(content_rows, action_cards)
    capture_coverage = build_capture_coverage(capture_context, trend_series, content_rows)
    return {
        "schema_version": "2.3",
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "meta": {
            "proxy": proxy_url,
            "keep_tabs": bool(keep_tabs),
            "routes": {
                "xhs_home": XHS_HOME_URL,
                "xhs_notes": XHS_NOTES_URL,
                "xhs_analysis": XHS_ANALYSIS_URL,
                "dy_home": DY_HOME_URL,
                "dy_works": DY_WORKS_URL,
            },
        },
        "capture_context": capture_context,
        "account_snapshot": account_snapshot,
        "trend_series": trend_series,
        "content_rows": content_rows,
        "detail_metrics": detail_metrics,
        "match_hints": match_hints,
        "capture_coverage": capture_coverage,
        "raw_pages": {
            "xhs": {
                "home": {
                    "page": xhs_home.page,
                    "dom": xhs_home.dom,
                    "parsed": xhs_home.parsed,
                },
                "notes": {
                    "page": xhs_notes.page,
                    "dom": xhs_notes.dom,
                    "parsed": xhs_notes.parsed,
                },
                "analysis": {
                    "page": xhs_analysis.page,
                    "dom": xhs_analysis.dom,
                    "parsed": xhs_analysis.parsed,
                },
            },
            "dy": {
                "home": {
                    "page": dy_home.page,
                    "dom": dy_home.dom,
                    "parsed": dy_home.parsed,
                },
                "works": {
                    "page": dy_works.page,
                    "dom": dy_works.dom,
                    "parsed": dy_works.parsed,
                },
            },
        },
    }


def render_report(capture: dict[str, Any]) -> str:
    lines = [
        "# Creator Platform Capture",
        "",
        f"- schema_version: {capture['schema_version']}",
        f"- captured_at: {capture['captured_at']}",
        f"- proxy: {capture['meta']['proxy']}",
        "",
        "## Capture Context",
    ]
    for platform, pages in capture["capture_context"].items():
        lines.append(f"### {platform}")
        for route, ctx in pages.items():
            lines.append(f"- {route}: {ctx['page_url']}")
            if ctx.get("data_window"):
                window = ctx["data_window"]
                lines.append(
                    f"  - window: {window.get('raw')} ({window.get('start_date')} -> {window.get('end_date')})"
                )
            if ctx.get("selected_filters"):
                lines.append(f"  - selected_filters: {ctx['selected_filters']}")
            if ctx.get("list_total_count") is not None:
                lines.append(
                    f"  - coverage: visible {ctx.get('list_visible_count')} / total {ctx.get('list_total_count')} (partial={ctx.get('is_partial_result')})"
                )
        lines.append("")

    lines.extend(["## Account Snapshot", ""])
    for platform, snapshot in capture["account_snapshot"].items():
        lines.append(f"### {platform}")
        lines.append(f"- account: {snapshot.get('account_name')} ({snapshot.get('account_id')})")
        if snapshot.get("data_window"):
            window = snapshot["data_window"]
            lines.append(f"- current_window: {window.get('raw')}")
        for key, value in snapshot.get("metrics", {}).items():
            lines.append(f"- {key}: {value.get('raw')}")
        works_aggregate = snapshot.get("works_aggregate") or {}
        if works_aggregate:
            lines.append("- works_aggregate:")
            for key, value in works_aggregate.items():
                if value:
                    lines.append(f"  - {key}: {value.get('raw')}")
        lines.append("")

    lines.extend(["## Trend Coverage", ""])
    for platform, trend in capture["trend_series"].items():
        points = len((trend.get("series") or {}).get("plays", [])) if platform == "dy" else 0
        suffix = f" points={points}" if points else ""
        lines.append(f"- {platform}: status={trend.get('status')}{suffix} note={trend.get('note')}")
    lines.append("")

    lines.extend(["## Latest Content Rows", ""])
    for row in capture["content_rows"][:8]:
        primary = row["metrics"].get("views") or row["metrics"].get("plays")
        primary_label = "观看" if row["platform"] == "xhs" else "播放"
        extras = []
        if row["platform"] == "xhs":
            if row["metrics"].get("impressions"):
                extras.append(f"曝光 {row['metrics']['impressions']['raw']}")
            if row["metrics"].get("content_ctr"):
                extras.append(f"封面点击率 {row['metrics']['content_ctr']['raw']}")
            if row["metrics"].get("followers_gained"):
                extras.append(f"涨粉 {row['metrics']['followers_gained']['raw']}")
        if row["platform"] == "dy":
            if row["metrics"].get("five_second_completion_rate"):
                extras.append(f"5s完播 {row['metrics']['five_second_completion_rate']['raw']}")
            if row["metrics"].get("followers_gained"):
                extras.append(f"粉丝+ {row['metrics']['followers_gained']['raw']}")
        lines.append(
            f"- {row['platform']} | {row.get('publish_date')} | {row['title']} | {primary_label} {primary.get('raw') if primary else '-'}"
            + (f" | {' | '.join(extras)}" if extras else "")
            + f" | current_week={row['is_current_week']} | hit_action={row['hit_active_action']}"
        )

    lines.extend(["", "## Coverage Warnings"])
    warnings = capture["capture_coverage"].get("warnings", [])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", default="http://127.0.0.1:3456")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--keep-tabs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    proxy = ProxyClient(args.proxy)
    captured_at = datetime.now()
    created_targets: list[str] = []
    try:
        xhs_home = capture_page(proxy, XHS_HOME_URL, parse_xhs_home, xhs_home_ready, captured_at)
        created_targets.append(xhs_home.target)
        xhs_notes = capture_page(
            proxy,
            XHS_NOTES_URL,
            parse_xhs_notes,
            xhs_notes_ready,
            captured_at,
            scroll_bottom=True,
        )
        try:
            xhs_notes.parsed["dom_walk"] = fetch_xhs_note_cards(proxy, xhs_notes.target)
            full_cards = xhs_notes.parsed.get("dom_walk", {}).get("cards") or []
            if full_cards:
                xhs_notes.parsed = parse_xhs_notes(xhs_notes.dom, full_note_cards=full_cards)
                xhs_notes.parsed["dom_walk"] = {"count": len(full_cards)}
        except Exception as error:
            xhs_notes.parsed["dom_walk_error"] = str(error)
        created_targets.append(xhs_notes.target)
        xhs_analysis = capture_page(
            proxy,
            XHS_ANALYSIS_URL,
            parse_xhs_analysis,
            xhs_analysis_ready,
            captured_at,
            scroll_bottom=True,
        )
        try:
            xhs_analysis.parsed["page_walk"] = fetch_xhs_analysis_rows(proxy, xhs_analysis.target)
            collected_pages = xhs_analysis.parsed.get("page_walk", {}).get("collected") or []
            full_rows = []
            for page in collected_pages:
                full_rows.extend(page.get("rows") or [])
            if full_rows:
                reparsed = parse_xhs_analysis(xhs_analysis.dom, captured_at, all_rows=full_rows)
                reparsed["page_walk"] = {
                    "pages": xhs_analysis.parsed.get("page_walk", {}).get("pages") or [],
                    "total_rows": len(full_rows),
                }
                xhs_analysis.parsed = reparsed
        except Exception as error:
            xhs_analysis.parsed["page_walk_error"] = str(error)
        created_targets.append(xhs_analysis.target)
        dy_home = capture_page(proxy, DY_HOME_URL, parse_dy_home, dy_home_ready, captured_at)
        try:
            dy_home.parsed["overview_api"] = fetch_dy_overview_api(proxy, dy_home.target, last_days_type=1)
        except Exception as error:
            dy_home.parsed["overview_api"] = {"error": str(error), "data": {}, "requested_last_days_type": 1}
        created_targets.append(dy_home.target)
        dy_works = capture_page(
            proxy,
            DY_WORKS_URL,
            parse_dy_works,
            dy_works_ready,
            captured_at,
            scroll_bottom=True,
        )
        try:
            dy_works.parsed["api"] = fetch_dy_work_list_api(proxy, dy_works.target)
        except Exception as error:
            dy_works.parsed["api"] = {"error": str(error), "items": [], "fetched_count": 0, "total": dy_works.parsed.get("total_works")}
        created_targets.append(dy_works.target)
    finally:
        if not args.keep_tabs:
            for target in created_targets:
                try:
                    proxy.close(target)
                except Exception:
                    pass

    capture = build_payload(
        repo_root=repo_root,
        captured_at=captured_at,
        xhs_home=xhs_home,
        xhs_notes=xhs_notes,
        xhs_analysis=xhs_analysis,
        dy_home=dy_home,
        dy_works=dy_works,
        proxy_url=args.proxy,
        keep_tabs=bool(args.keep_tabs),
    )

    capture_path = output_dir / "capture.json"
    report_path = output_dir / "report.md"
    capture_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_report(capture), encoding="utf-8")

    print(json.dumps({"capture": str(capture_path), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
