from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/compose_ins_diary.py"
SPEC = importlib.util.spec_from_file_location("compose_ins_diary", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ComposeInsDiaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.background = self.root / "background.jpg"
        Image.new("RGB", (900, 1200), (35, 105, 145)).save(self.background)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_sources(self, count: int) -> list[Path]:
        sources = []
        for index in range(count):
            path = self.root / f"source-{index}.jpg"
            Image.new(
                "RGB",
                (420 + index * 13, 620 - index * 17),
                ((30 + index * 29) % 255, (80 + index * 37) % 255, (120 + index * 41) % 255),
            ).save(path)
            sources.append(path)
        return sources

    def make_layout(self, sources: list[Path]) -> Path:
        row_count = 3 if len(sources) <= 4 else 4
        rows = [{"label": label, "items": []} for label in ["weather", "mood", "food", "music"][:row_count]]
        for index, source in enumerate(sources):
            row_index = index % row_count
            rows[row_index]["items"].append(
                {
                    "path": source.name,
                    "focus": [0.5, 0.5],
                    "rotation": 0,
                    "shape": "square" if index == len(sources) - 1 else "landscape",
                    "contains_people": False,
                    "contains_text": False,
                    "directional": False,
                }
            )
        layout = {
            "canvas": {"width": 1536, "height": 2048},
            "background": self.background.name,
            "source_images": [source.name for source in sources],
            "rows": rows,
        }
        path = self.root / "layout.json"
        path.write_text(json.dumps(layout), encoding="utf-8")
        return path

    def make_quiet_layout(self, sources: list[Path]) -> Path:
        row_count = 3 if len(sources) <= 5 else 4
        rows = [
            {"label": label, "items": []}
            for label in ["soft rain", "mood", "small joys", "details"][:row_count]
        ]
        for index, source in enumerate(sources):
            rows[index % row_count]["items"].append(
                {
                    "path": source.name,
                    "focus": [0.5, 0.5],
                    "rotation": 0,
                    "shape": ["landscape", "square", "portrait"][index % 3],
                    "size": "small" if index % 2 else "standard",
                    "contains_people": False,
                    "contains_text": False,
                    "directional": False,
                }
            )
        layout = {
            "canvas": {"width": 1536, "height": 2048},
            "background": self.background.name,
            "composition_mode": "quiet-journal",
            "anchor": "center",
            "source_images": [source.name for source in sources],
            "rows": rows,
        }
        path = self.root / "quiet-layout.json"
        path.write_text(json.dumps(layout), encoding="utf-8")
        return path

    def make_place_layout(self, sources: list[Path]) -> Path:
        line_count = 3 if len(sources) <= 5 else 4
        line_text = ["Weekend roaming", "IN", "Shenzhen", "slowly"][:line_count]
        lines = [
            {"segments": [{"type": "text", "value": text, "scale": "standard"}]}
            for text in line_text
        ]
        for index, source in enumerate(sources):
            lines[index % line_count]["segments"].append(
                {
                    "type": "image",
                    "item": {
                        "path": source.name,
                        "focus": [0.5, 0.5],
                        "rotation": 0,
                        "shape": ["square", "landscape", "portrait"][index % 3],
                        "size": "small" if index % 2 else "standard",
                        "contains_people": False,
                        "contains_text": False,
                        "directional": False,
                    },
                }
            )
        layout = {
            "canvas": {"width": 1536, "height": 2048},
            "background": self.background.name,
            "composition_mode": "place-note",
            "anchor": "lower",
            "source_images": [source.name for source in sources],
            "lines": lines,
        }
        path = self.root / "place-layout.json"
        path.write_text(json.dumps(layout), encoding="utf-8")
        return path

    def test_renders_all_supported_counts(self) -> None:
        for count in (3, 4, 5, 6):
            with self.subTest(count=count):
                sources = self.make_sources(count)
                layout = self.make_layout(sources)
                output = self.root / f"output-{count}.png"
                provenance = MODULE.compose(self.background, layout, output)
                with Image.open(output) as rendered:
                    self.assertEqual(rendered.size, (1536, 2048))
                self.assertEqual(len(provenance["sources"]), count)
                used = [item for row in provenance["rows"] for item in row["items"]]
                self.assertEqual(len(used), count)
                for source in sources:
                    source.unlink()

    def test_rejects_too_few_sources(self) -> None:
        sources = self.make_sources(2)
        layout = self.make_layout(sources)
        with self.assertRaisesRegex(MODULE.LayoutError, "3–6"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_rejects_too_many_sources(self) -> None:
        sources = self.make_sources(7)
        layout = self.make_layout(sources)
        with self.assertRaisesRegex(MODULE.LayoutError, "3–6"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_rejects_damaged_source(self) -> None:
        sources = self.make_sources(3)
        sources[1].write_bytes(b"not an image")
        layout = self.make_layout(sources)
        with self.assertRaisesRegex(MODULE.LayoutError, "Unreadable or damaged"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_rejects_duplicate_content(self) -> None:
        sources = self.make_sources(3)
        sources[1].write_bytes(sources[0].read_bytes())
        layout = self.make_layout(sources)
        with self.assertRaisesRegex(MODULE.LayoutError, "duplicate image content"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_rejects_source_as_background(self) -> None:
        sources = self.make_sources(3)
        layout = self.make_layout(sources)
        data = json.loads(layout.read_text())
        data["background"] = sources[0].name
        layout.write_text(json.dumps(data))
        with self.assertRaisesRegex(MODULE.LayoutError, "must not be one"):
            MODULE.compose(sources[0], layout, self.root / "out.png")

    def test_rejects_unsafe_rotation(self) -> None:
        sources = self.make_sources(3)
        layout = self.make_layout(sources)
        data = json.loads(layout.read_text())
        data["rows"][0]["items"][0]["rotation"] = 90
        data["rows"][0]["items"][0]["contains_people"] = True
        layout.write_text(json.dumps(data))
        with self.assertRaisesRegex(MODULE.LayoutError, "Unsafe rotation"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_rejects_more_than_two_rotations(self) -> None:
        sources = self.make_sources(3)
        layout = self.make_layout(sources)
        data = json.loads(layout.read_text())
        for row in data["rows"]:
            row["items"][0]["rotation"] = 90
        layout.write_text(json.dumps(data))
        with self.assertRaisesRegex(MODULE.LayoutError, "At most two"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_writes_jpeg_and_provenance(self) -> None:
        sources = self.make_sources(3)
        layout = self.make_layout(sources)
        output = self.root / "out.jpg"
        provenance = self.root / "out.provenance.json"
        MODULE.compose(self.background, layout, output, provenance)
        with Image.open(output) as rendered:
            self.assertEqual(rendered.format, "JPEG")
        self.assertEqual(json.loads(provenance.read_text())["canvas"]["height"], 2048)

    def test_renders_quiet_journal_with_mixed_shapes(self) -> None:
        sources = self.make_sources(5)
        layout = self.make_quiet_layout(sources)
        output = self.root / "quiet.png"
        provenance = MODULE.compose(self.background, layout, output)
        self.assertEqual(provenance["composition_mode"], "quiet-journal")
        used = [item for row in provenance["rows"] for item in row["items"]]
        self.assertEqual(len(used), 5)
        self.assertIn("portrait", {item["shape"] for item in used})

    def test_renders_place_note_visual_sentence(self) -> None:
        sources = self.make_sources(5)
        layout = self.make_place_layout(sources)
        output = self.root / "place.png"
        provenance = MODULE.compose(self.background, layout, output)
        self.assertEqual(provenance["composition_mode"], "place-note")
        image_segments = [
            segment
            for line in provenance["lines"]
            for segment in line["segments"]
            if segment["type"] == "image"
        ]
        self.assertEqual(len(image_segments), 5)
        self.assertEqual(provenance["anchor"], "lower")

    def test_place_note_rejects_duplicate_source_use(self) -> None:
        sources = self.make_sources(3)
        layout = self.make_place_layout(sources)
        data = json.loads(layout.read_text())
        image_segments = [
            segment
            for line in data["lines"]
            for segment in line["segments"]
            if segment["type"] == "image"
        ]
        image_segments[1]["item"]["path"] = image_segments[0]["item"]["path"]
        layout.write_text(json.dumps(data))
        with self.assertRaisesRegex(MODULE.LayoutError, "more than once"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_rejects_unknown_composition_mode(self) -> None:
        sources = self.make_sources(3)
        layout = self.make_layout(sources)
        data = json.loads(layout.read_text())
        data["composition_mode"] = "random-collage"
        layout.write_text(json.dumps(data))
        with self.assertRaisesRegex(MODULE.LayoutError, "composition_mode"):
            MODULE.compose(self.background, layout, self.root / "out.png")

    def test_lower_third_remains_background_only(self) -> None:
        sources = self.make_sources(6)
        layout = self.make_layout(sources)
        output = self.root / "out.png"
        MODULE.compose(self.background, layout, output)
        with Image.open(output) as rendered:
            pixel = rendered.getpixel((768, 1700))
            self.assertTrue(
                all(abs(actual - expected) <= 2 for actual, expected in zip(pixel, (35, 105, 145)))
            )


if __name__ == "__main__":
    unittest.main()
