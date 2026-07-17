# Ins Photo Diary Layout Contract

## Contents

- [Shared contract](#shared-contract)
- [`bold-index`](#bold-index)
- [`quiet-journal`](#quiet-journal)
- [`place-note`](#place-note)
- [Renderer validation](#renderer-validation)

Resolve relative paths from the directory containing `layout.json`. Omitting `composition_mode` is backward compatible and selects `bold-index`.

## Shared contract

```json
{
  "canvas": {"width": 1536, "height": 2048},
  "background": "optional/path/to/background.jpg",
  "composition_mode": "bold-index",
  "anchor": "center",
  "source_images": ["photos/a.jpg", "photos/b.jpg", "photos/c.jpg"]
}
```

- `composition_mode`: `bold-index`, `quiet-journal`, or `place-note`.
- `anchor`: `upper`, `center`, or `lower`.
- `source_images`: 3–6 unique JPEG, PNG, or WebP paths with unique content hashes.

Every image segment uses:

```json
{
  "path": "photos/a.jpg",
  "focus": [0.5, 0.45],
  "rotation": 0,
  "shape": "landscape",
  "size": "standard",
  "contains_people": false,
  "contains_text": false,
  "directional": true
}
```

- `focus`: two numbers from `0` to `1`.
- `rotation`: `-90`, `0`, or `90`; at most two images may rotate.
- `shape`: `landscape`, `square`, or `portrait`.
- `size`: `standard` or `small`.
- Any rotated item must set `contains_people`, `contains_text`, and `directional` to false.

## `bold-index`

Use three rows for 3–4 images and four rows for 5–6 images. Each row has one or two items and a unique lowercase label of 3–10 letters.

```json
{
  "composition_mode": "bold-index",
  "anchor": "center",
  "rows": [
    {"label": "weather", "items": [{"path": "photos/a.jpg", "focus": [0.5, 0.45], "rotation": 0, "shape": "landscape", "size": "standard", "contains_people": false, "contains_text": false, "directional": true}]},
    {"label": "food", "items": [{"path": "photos/b.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "square", "size": "standard", "contains_people": false, "contains_text": true, "directional": false}]},
    {"label": "mood", "items": [{"path": "photos/c.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "portrait", "size": "small", "contains_people": true, "contains_text": false, "directional": true}]}
  ]
}
```

## `quiet-journal`

Use two to four rows. Each row has one or two items and a unique lowercase label of 3–16 characters and no more than two words.

```json
{
  "composition_mode": "quiet-journal",
  "anchor": "center",
  "rows": [
    {"label": "soft rain", "items": [{"path": "photos/a.jpg", "focus": [0.5, 0.45], "rotation": 0, "shape": "landscape", "size": "small", "contains_people": false, "contains_text": false, "directional": true}]},
    {"label": "mood", "items": [{"path": "photos/b.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "square", "size": "standard", "contains_people": true, "contains_text": false, "directional": true}]},
    {"label": "small joys", "items": [{"path": "photos/c.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "landscape", "size": "standard", "contains_people": false, "contains_text": false, "directional": false}]}
  ]
}
```

## `place-note`

Use two to four lines. Each line has one to five ordered segments and at most two images. Text is 1–32 English letters, numbers, spaces, apostrophes, ampersands, or hyphens; `scale` is `small`, `standard`, or `large`.

```json
{
  "composition_mode": "place-note",
  "anchor": "lower",
  "lines": [
    {"segments": [
      {"type": "text", "value": "Weekend roaming", "scale": "large"},
      {"type": "image", "item": {"path": "photos/a.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "square", "size": "standard", "contains_people": false, "contains_text": false, "directional": true}}
    ]},
    {"segments": [
      {"type": "text", "value": "IN", "scale": "standard"},
      {"type": "image", "item": {"path": "photos/b.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "square", "size": "small", "contains_people": false, "contains_text": false, "directional": true}}
    ]},
    {"segments": [
      {"type": "text", "value": "Shenzhen", "scale": "standard"},
      {"type": "image", "item": {"path": "photos/c.jpg", "focus": [0.5, 0.5], "rotation": 0, "shape": "landscape", "size": "small", "contains_people": false, "contains_text": false, "directional": true}}
    ]}
  ]
}
```

## Renderer validation

- Canvas must be exactly 1536 × 2048.
- Every `source_images` path must appear exactly once in `rows` or `lines`; no extra path is allowed.
- The background cannot share a content hash with a source image.
- Mode-specific counts, copy, shapes, sizes, focus coordinates, and rotations are validated before rendering.
- `--background` is authoritative. When `background` is declared in JSON, both paths must resolve to the same file.
