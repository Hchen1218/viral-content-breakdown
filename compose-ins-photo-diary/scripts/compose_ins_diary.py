#!/usr/bin/env python3
"""Deterministically compose an Ins-style photo diary from untouched source photos."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover - exercised only without Pillow
    raise SystemExit(
        "Pillow is required. Install it in the active environment, for example: "
        "python -m pip install Pillow"
    ) from exc


CANVAS = (1536, 2048)
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
COMPOSITION_MODES = {"bold-index", "quiet-journal", "place-note"}
ANCHORS = {"upper", "center", "lower"}
ALLOWED_ROTATIONS = {-90, 0, 90}
ALLOWED_SHAPES = {"landscape", "square", "portrait"}
ALLOWED_SIZES = {"small", "standard"}
BOLD_LABEL_RE = re.compile(r"^[a-z]{3,10}$")
JOURNAL_LABEL_RE = re.compile(r"^[a-z][a-z ]{2,15}$")
STORY_TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '&-]{0,31}$")


class LayoutError(ValueError):
    """Raised when layout input violates a non-negotiable invariant."""


@dataclass(frozen=True)
class SourceRecord:
    path: Path
    sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def validate_still_image(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise LayoutError(
            f"Unsupported image format for {path.name}; use JPEG, PNG, or WebP."
        )
    if not path.is_file():
        raise LayoutError(f"Image does not exist: {path}")
    try:
        with Image.open(path) as image:
            if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                raise LayoutError(f"Animated images are not supported: {path}")
            image.verify()
    except LayoutError:
        raise
    except Exception as exc:
        raise LayoutError(f"Unreadable or damaged image: {path}") from exc


def normalize_rgb(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
        icc = image.info.get("icc_profile")
        if icc:
            try:
                source_profile = ImageCms.ImageCmsProfile(BytesIO(icc))
                target_profile = ImageCms.createProfile("sRGB")
                image = ImageCms.profileToProfile(
                    image, source_profile, target_profile, outputMode="RGB"
                )
            except Exception:
                image = image.convert("RGB")
        else:
            image = image.convert("RGB")
    return image


def rotate_focus(focus: tuple[float, float], rotation: int) -> tuple[float, float]:
    x, y = focus
    if rotation == 90:
        return y, 1.0 - x
    if rotation == -90:
        return 1.0 - y, x
    return x, y


def cover_crop(
    image: Image.Image, size: tuple[int, int], focus: tuple[float, float]
) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (max(target_w, round(image.width * scale)), max(target_h, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    center_x = focus[0] * resized.width
    center_y = focus[1] * resized.height
    left = max(0, min(resized.width - target_w, round(center_x - target_w / 2)))
    top = max(0, min(resized.height - target_h, round(center_y - target_h / 2)))
    return resized.crop((left, top, left + target_w, top + target_h))


def normalize_item(
    item: Any,
    *,
    base_dir: Path,
    location: str,
) -> dict[str, Any]:
    if not isinstance(item, dict) or "path" not in item:
        raise LayoutError(f"{location} needs a path.")
    path = resolve_path(str(item["path"]), base_dir)
    focus = item.get("focus", [0.5, 0.5])
    if (
        not isinstance(focus, list)
        or len(focus) != 2
        or any(not isinstance(value, (int, float)) for value in focus)
        or any(value < 0 or value > 1 for value in focus)
    ):
        raise LayoutError("Each focus must contain two numbers between 0 and 1.")
    rotation = item.get("rotation", 0)
    if rotation not in ALLOWED_ROTATIONS:
        raise LayoutError("rotation must be -90, 0, or 90.")
    if rotation:
        unsafe = any(
            bool(item.get(flag, False))
            for flag in ("contains_people", "contains_text", "directional")
        )
        if unsafe:
            raise LayoutError(
                f"Unsafe rotation for {path.name}: people, text, and directional subjects must stay upright."
            )
    shape = item.get("shape", "landscape")
    if shape not in ALLOWED_SHAPES:
        raise LayoutError("shape must be landscape, square, or portrait.")
    size = item.get("size", "standard")
    if size not in ALLOWED_SIZES:
        raise LayoutError("size must be small or standard.")
    return {
        **item,
        "path": path,
        "focus": (float(focus[0]), float(focus[1])),
        "rotation": int(rotation),
        "shape": shape,
        "size": size,
    }


def validate_usage(
    source_paths: list[Path], items: list[dict[str, Any]], *, location: str
) -> None:
    item_paths = [item["path"] for item in items]
    if sum(1 for item in items if item["rotation"]) > 2:
        raise LayoutError("At most two foreground images may be rotated.")
    if len(item_paths) != len(set(item_paths)):
        raise LayoutError(f"A source image appears more than once in {location}.")
    if set(item_paths) != set(source_paths):
        missing = sorted(path.name for path in set(source_paths) - set(item_paths))
        extra = sorted(path.name for path in set(item_paths) - set(source_paths))
        raise LayoutError(
            f"{location.capitalize()} must use every source exactly once; "
            f"missing={missing}, extra={extra}."
        )


def normalize_rows(
    raw_rows: Any,
    *,
    mode: str,
    source_paths: list[Path],
    base_dir: Path,
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list):
        raise LayoutError(f"{mode} requires a rows array.")
    if mode == "bold-index":
        expected = 3 if len(source_paths) <= 4 else 4
        if len(raw_rows) != expected:
            raise LayoutError(
                f"{len(source_paths)} source images require exactly {expected} rows in bold-index."
            )
    elif not 2 <= len(raw_rows) <= 4:
        raise LayoutError("quiet-journal requires two to four rows.")

    labels: set[str] = set()
    normalized_rows: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    for row_index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            raise LayoutError(f"Row {row_index + 1} must be an object.")
        label = row.get("label")
        label_pattern = BOLD_LABEL_RE if mode == "bold-index" else JOURNAL_LABEL_RE
        if not isinstance(label, str) or not label_pattern.fullmatch(label):
            requirement = (
                "one lowercase English word of 3–10 letters"
                if mode == "bold-index"
                else "one or two lowercase English words totaling 3–16 characters"
            )
            raise LayoutError(f"Row {row_index + 1} label must be {requirement}.")
        if label in labels:
            raise LayoutError(f"Duplicate row label: {label}")
        labels.add(label)

        raw_items = row.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 2:
            raise LayoutError(f"Row {row_index + 1} must contain one or two items.")
        items = [
            normalize_item(
                item,
                base_dir=base_dir,
                location=f"Row {row_index + 1} item {item_index + 1}",
            )
            for item_index, item in enumerate(raw_items)
        ]
        all_items.extend(items)
        normalized_rows.append({"label": label, "items": items})

    validate_usage(source_paths, all_items, location="rows")
    return normalized_rows


def normalize_lines(
    raw_lines: Any, *, source_paths: list[Path], base_dir: Path
) -> list[dict[str, Any]]:
    if not isinstance(raw_lines, list) or not 2 <= len(raw_lines) <= 4:
        raise LayoutError("place-note requires two to four lines.")
    normalized_lines: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    text_count = 0
    for line_index, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            raise LayoutError(f"Line {line_index + 1} must be an object.")
        raw_segments = line.get("segments")
        if not isinstance(raw_segments, list) or not 1 <= len(raw_segments) <= 5:
            raise LayoutError(f"Line {line_index + 1} must contain one to five segments.")
        segments: list[dict[str, Any]] = []
        image_count = 0
        for segment_index, segment in enumerate(raw_segments):
            if not isinstance(segment, dict):
                raise LayoutError(
                    f"Line {line_index + 1} segment {segment_index + 1} must be an object."
                )
            segment_type = segment.get("type")
            if segment_type == "text":
                value = segment.get("value")
                if not isinstance(value, str) or not STORY_TEXT_RE.fullmatch(value):
                    raise LayoutError(
                        "Story text must be 1–32 English letters, numbers, spaces, apostrophes, ampersands, or hyphens."
                    )
                scale = segment.get("scale", "standard")
                if scale not in {"small", "standard", "large"}:
                    raise LayoutError("Text scale must be small, standard, or large.")
                segments.append({"type": "text", "value": value, "scale": scale})
                text_count += 1
            elif segment_type == "image":
                image_count += 1
                item = normalize_item(
                    segment.get("item"),
                    base_dir=base_dir,
                    location=f"Line {line_index + 1} image segment {segment_index + 1}",
                )
                segments.append({"type": "image", "item": item})
                all_items.append(item)
            else:
                raise LayoutError("Each story segment type must be text or image.")
        if image_count > 2:
            raise LayoutError(f"Line {line_index + 1} may contain at most two images.")
        normalized_lines.append({"segments": segments})

    if not text_count:
        raise LayoutError("place-note requires at least one text segment.")
    validate_usage(source_paths, all_items, location="lines")
    return normalized_lines


def load_layout(layout_path: Path, background_arg: Path) -> dict[str, Any]:
    try:
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LayoutError(f"Could not read valid layout JSON: {layout_path}") from exc

    base_dir = layout_path.parent.resolve()
    canvas = layout.get("canvas", {})
    if (canvas.get("width"), canvas.get("height")) != CANVAS:
        raise LayoutError("Canvas must be exactly 1536 × 2048.")

    background = background_arg.resolve()
    validate_still_image(background)
    if layout.get("background"):
        declared = resolve_path(str(layout["background"]), base_dir)
        if declared != background:
            raise LayoutError("layout.background and --background must reference the same file.")

    raw_sources = layout.get("source_images")
    if not isinstance(raw_sources, list) or not 3 <= len(raw_sources) <= 6:
        raise LayoutError("source_images must contain 3–6 paths.")
    source_paths = [resolve_path(str(value), base_dir) for value in raw_sources]
    if len(set(source_paths)) != len(source_paths):
        raise LayoutError("source_images contains duplicate paths.")

    records: list[SourceRecord] = []
    hashes: set[str] = set()
    for source in source_paths:
        validate_still_image(source)
        digest = sha256_file(source)
        if digest in hashes:
            raise LayoutError("source_images contains duplicate image content.")
        hashes.add(digest)
        records.append(SourceRecord(source, digest))

    background_hash = sha256_file(background)
    if background_hash in hashes:
        raise LayoutError("The background must not be one of the user source images.")

    mode = layout.get("composition_mode", "bold-index")
    if mode not in COMPOSITION_MODES:
        raise LayoutError("composition_mode must be bold-index, quiet-journal, or place-note.")
    anchor = layout.get("anchor", "center")
    if anchor not in ANCHORS:
        raise LayoutError("anchor must be upper, center, or lower.")

    normalized: dict[str, Any] = {
        "composition_mode": mode,
        "anchor": anchor,
        "background": background,
        "background_hash": background_hash,
        "source_records": records,
    }
    if mode in {"bold-index", "quiet-journal"}:
        normalized["rows"] = normalize_rows(
            layout.get("rows"),
            mode=mode,
            source_paths=source_paths,
            base_dir=base_dir,
        )
    else:
        normalized["lines"] = normalize_lines(
            layout.get("lines"), source_paths=source_paths, base_dir=base_dir
        )
    return normalized


def load_variable_font(path: Path, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    if weight is None:
        return font
    try:
        axes = font.get_variation_axes()
        values = []
        for axis in axes:
            name = axis.get("name", b"")
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            value = weight if str(name).lower() == "weight" else axis["default"]
            values.append(max(axis["minimum"], min(axis["maximum"], value)))
        font.set_variation_by_axes(values)
    except (AttributeError, OSError, KeyError, TypeError):
        pass
    return font


def text_box(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=font)


def centered_text_xy(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: int,
    center_y: int,
) -> tuple[int, int]:
    bbox = text_box(draw, text, font)
    height = bbox[3] - bbox[1]
    return x, center_y - height // 2 - bbox[1]


def photo_size(mode: str, shape: str, size_name: str) -> tuple[int, int]:
    sizes = {
        "bold-index": {
            "landscape": (202, 168),
            "square": (168, 168),
            "portrait": (142, 184),
        },
        "quiet-journal": {
            "landscape": (194, 126),
            "square": (136, 136),
            "portrait": (112, 156),
        },
        "place-note": {
            "landscape": (168, 116),
            "square": (128, 128),
            "portrait": (104, 146),
        },
    }
    width, height = sizes[mode][shape]
    if size_name == "small":
        return round(width * 0.82), round(height * 0.82)
    return width, height


def item_metrics(
    draw: ImageDraw.ImageDraw,
    item: dict[str, Any],
    mode: str,
    paren_font: ImageFont.FreeTypeFont,
) -> tuple[int, tuple[int, int], int, int]:
    size = photo_size(mode, item["shape"], item["size"])
    open_w = text_box(draw, "(", paren_font)[2]
    close_w = text_box(draw, ")", paren_font)[2]
    inner_gap = 14 if mode == "bold-index" else 10
    width = open_w + inner_gap + size[0] + inner_gap + close_w
    return width, size, open_w, inner_gap


def render_item(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: dict[str, Any],
    *,
    mode: str,
    paren_font: ImageFont.FreeTypeFont,
    x: int,
    center_y: int,
    color: tuple[int, int, int],
) -> tuple[int, dict[str, Any]]:
    width, size, open_w, inner_gap = item_metrics(draw, item, mode, paren_font)
    paren_xy = centered_text_xy(draw, "(", paren_font, x, center_y)
    draw.text(paren_xy, "(", font=paren_font, fill=color)
    image_x = x + open_w + inner_gap
    image_y = center_y - size[1] // 2

    photo = normalize_rgb(item["path"])
    focus = item["focus"]
    if item["rotation"]:
        photo = photo.rotate(item["rotation"], expand=True, resample=Image.Resampling.BICUBIC)
        focus = rotate_focus(focus, item["rotation"])
    fragment = cover_crop(photo, size, focus)
    canvas.paste(fragment, (image_x, image_y))

    close_x = image_x + size[0] + inner_gap
    close_xy = centered_text_xy(draw, ")", paren_font, close_x, center_y)
    draw.text(close_xy, ")", font=paren_font, fill=color)
    record = {
        "path": str(item["path"]),
        "sha256": sha256_file(item["path"]),
        "focus": list(item["focus"]),
        "rotation": item["rotation"],
        "shape": item["shape"],
        "size": item["size"],
        "box": [image_x, image_y, size[0], size[1]],
    }
    return x + width, record


def shifted_centers(base: list[int], anchor: str, amount: int = 120) -> list[int]:
    shift = {"upper": -amount, "center": 0, "lower": amount}[anchor]
    return [value + shift for value in base]


def render_bold_index(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    layout: dict[str, Any],
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> list[dict[str, Any]]:
    rows = layout["rows"]
    centers = [550, 800, 1050] if len(rows) == 3 else [520, 755, 990, 1225]
    centers = shifted_centers(centers, layout["anchor"], 100)
    label_right = 675
    first_cursor = 705
    white = (250, 251, 246)
    shadow = (18, 57, 82)
    result: list[dict[str, Any]] = []
    for row, center_y in zip(rows, centers):
        label = row["label"]
        bbox = text_box(draw, label, fonts["bold_label"])
        label_x = label_right - (bbox[2] - bbox[0])
        label_xy = centered_text_xy(draw, label, fonts["bold_label"], label_x, center_y)
        draw.text((label_xy[0] + 4, label_xy[1] + 5), label, font=fonts["bold_label"], fill=shadow)
        draw.text(label_xy, label, font=fonts["bold_label"], fill=white)
        cursor = first_cursor
        rendered_items = []
        for item in row["items"]:
            cursor, record = render_item(
                canvas,
                draw,
                item,
                mode="bold-index",
                paren_font=fonts["bold_paren"],
                x=cursor,
                center_y=center_y,
                color=white,
            )
            cursor += 32
            rendered_items.append(record)
        if cursor > CANVAS[0] - 30:
            raise LayoutError(f"Row {label} overflows the canvas.")
        result.append({"label": label, "items": rendered_items})
    return result


def render_quiet_journal(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    layout: dict[str, Any],
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> list[dict[str, Any]]:
    rows = layout["rows"]
    center_sets = {
        2: [875, 1085],
        3: [760, 955, 1150],
        4: [690, 855, 1020, 1185],
    }
    centers = shifted_centers(center_sets[len(rows)], layout["anchor"], 120)
    white = (247, 247, 241)
    shadow = (34, 42, 42)
    result: list[dict[str, Any]] = []
    for row, center_y in zip(rows, centers):
        label = row["label"]
        label_bbox = text_box(draw, label, fonts["journal"])
        label_w = label_bbox[2] - label_bbox[0]
        item_widths = [
            item_metrics(draw, item, "quiet-journal", fonts["journal_paren"])[0]
            for item in row["items"]
        ]
        total_w = label_w + 28 + sum(item_widths) + 18 * (len(item_widths) - 1)
        if total_w > CANVAS[0] - 140:
            raise LayoutError(f"Row {label} overflows the canvas.")
        cursor = (CANVAS[0] - total_w) // 2
        label_xy = centered_text_xy(draw, label, fonts["journal"], cursor, center_y)
        draw.text((label_xy[0] + 2, label_xy[1] + 3), label, font=fonts["journal"], fill=shadow)
        draw.text(label_xy, label, font=fonts["journal"], fill=white)
        cursor += label_w + 28
        rendered_items = []
        for item in row["items"]:
            cursor, record = render_item(
                canvas,
                draw,
                item,
                mode="quiet-journal",
                paren_font=fonts["journal_paren"],
                x=cursor,
                center_y=center_y,
                color=white,
            )
            cursor += 18
            rendered_items.append(record)
        result.append({"label": label, "items": rendered_items})
    return result


def story_font(fonts: dict[str, ImageFont.FreeTypeFont], scale: str) -> ImageFont.FreeTypeFont:
    return fonts[f"story_{scale}"]


def render_place_note(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    layout: dict[str, Any],
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> list[dict[str, Any]]:
    lines = layout["lines"]
    center_sets = {
        2: [970, 1175],
        3: [885, 1080, 1275],
        4: [790, 950, 1110, 1270],
    }
    centers = shifted_centers(center_sets[len(lines)], layout["anchor"], 120)
    white = (249, 250, 246)
    result: list[dict[str, Any]] = []
    for line, center_y in zip(lines, centers):
        widths: list[int] = []
        for segment in line["segments"]:
            if segment["type"] == "text":
                font = story_font(fonts, segment["scale"])
                bbox = text_box(draw, segment["value"], font)
                widths.append(bbox[2] - bbox[0])
            else:
                widths.append(
                    item_metrics(draw, segment["item"], "place-note", fonts["story_paren"])[0]
                )
        gap = 14
        total_w = sum(widths) + gap * (len(widths) - 1)
        if total_w > CANVAS[0] - 100:
            raise LayoutError("A place-note line overflows the canvas; shorten its text or use smaller images.")
        cursor = (CANVAS[0] - total_w) // 2
        rendered_segments: list[dict[str, Any]] = []
        for segment, width in zip(line["segments"], widths):
            if segment["type"] == "text":
                font = story_font(fonts, segment["scale"])
                xy = centered_text_xy(draw, segment["value"], font, cursor, center_y)
                draw.text(xy, segment["value"], font=font, fill=white)
                rendered_segments.append(
                    {
                        "type": "text",
                        "value": segment["value"],
                        "scale": segment["scale"],
                        "box": [cursor, xy[1], width, text_box(draw, segment["value"], font)[3] - text_box(draw, segment["value"], font)[1]],
                    }
                )
                cursor += width
            else:
                cursor, record = render_item(
                    canvas,
                    draw,
                    segment["item"],
                    mode="place-note",
                    paren_font=fonts["story_paren"],
                    x=cursor,
                    center_y=center_y,
                    color=white,
                )
                rendered_segments.append({"type": "image", "item": record})
            cursor += gap
        result.append({"segments": rendered_segments})
    return result


def render(layout: dict[str, Any], output: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    font_paths = {
        "archivo": root / "assets/fonts/ArchivoBlack-Regular.ttf",
        "inter": root / "assets/fonts/Inter-Variable.ttf",
        "cormorant": root / "assets/fonts/CormorantGaramond-Variable.ttf",
    }
    if any(not path.is_file() for path in font_paths.values()):
        raise LayoutError("Bundled font files are missing from assets/fonts.")

    fonts = {
        "bold_label": load_variable_font(font_paths["archivo"], 82),
        "bold_paren": load_variable_font(font_paths["inter"], 88, 400),
        "journal": load_variable_font(font_paths["cormorant"], 72, 400),
        "journal_paren": load_variable_font(font_paths["cormorant"], 76, 400),
        "story_small": load_variable_font(font_paths["inter"], 60, 300),
        "story_standard": load_variable_font(font_paths["inter"], 76, 300),
        "story_large": load_variable_font(font_paths["inter"], 92, 300),
        "story_paren": load_variable_font(font_paths["inter"], 78, 300),
    }

    background = cover_crop(normalize_rgb(layout["background"]), CANVAS, (0.5, 0.5))
    canvas = background.copy()
    draw = ImageDraw.Draw(canvas)
    mode = layout["composition_mode"]
    if mode == "bold-index":
        rendered_content = render_bold_index(canvas, draw, layout, fonts)
        content_key = "rows"
    elif mode == "quiet-journal":
        rendered_content = render_quiet_journal(canvas, draw, layout, fonts)
        content_key = "rows"
    else:
        rendered_content = render_place_note(canvas, draw, layout, fonts)
        content_key = "lines"

    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        canvas.save(output, quality=94, subsampling=0, optimize=True)
    elif suffix == ".png":
        canvas.save(output, optimize=True)
    else:
        raise LayoutError("Output must use .png, .jpg, or .jpeg.")

    provenance = {
        "output": str(output.resolve()),
        "canvas": {"width": CANVAS[0], "height": CANVAS[1]},
        "composition_mode": mode,
        "anchor": layout["anchor"],
        "background": {
            "path": str(layout["background"]),
            "sha256": layout["background_hash"],
        },
        "sources": [
            {"path": str(record.path), "sha256": record.sha256}
            for record in layout["source_records"]
        ],
        content_key: rendered_content,
    }
    return provenance


def compose(
    background_path: Path,
    layout_path: Path,
    output_path: Path,
    provenance_path: Path | None = None,
) -> dict[str, Any]:
    layout = load_layout(layout_path.resolve(), background_path.resolve())
    provenance = render(layout, output_path.resolve())
    if provenance_path:
        provenance_path = provenance_path.resolve()
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.write_text(
            json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return provenance


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provenance", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        compose(args.background, args.layout, args.output, args.provenance)
    except LayoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(str(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
