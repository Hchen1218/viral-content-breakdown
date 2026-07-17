---
name: compose-ins-photo-diary
description: Create a single 3:4 Ins-style photo diary collage from 3–6 user-supplied JPEG, PNG, or WebP images. Use when an agent needs to turn uploaded lifestyle photos into an Instagram-inspired mood collage, visual diary, life-slice poster, travel note, poetic photo cluster, or editorial composition while preserving every foreground photo as user-provided and generating only the atmospheric background.
---

# Compose Ins Photo Diary

Create one 3:4 photo diary from an atmospheric generated background, editorial language, and 3–6 untouched user-photo fragments. Select one coherent visual grammar from the evidence; never randomize styles.

## Requirements

- Require visual understanding and an image-generation tool that returns a bitmap file. If generation is unavailable, stop without offering an API-key fallback.
- Require Python 3 and Pillow. If Pillow is missing, identify the dependency and ask the user to install it in the active environment.
- Accept 3–6 still JPEG, PNG, or WebP images. Ask the user to convert HEIC, PDF, GIF, or animated inputs.

## Workflow

1. Read [references/aesthetic-system.md](references/aesthetic-system.md) completely.
2. Inspect every image and record subject, mood, palette, focal point, people, readable text, directional content, and safe-rotation status.
3. Reject fewer than 3 or more than 6 accepted images. Use every accepted image exactly once.
4. Select `bold-index`, `quiet-journal`, or `place-note`; generate truthful English copy and choose an `upper`, `center`, or `lower` anchor. Do not invent places, dates, weather, identities, or relationships.
5. Convert the analysis into a text-only background brief. Never attach, reference, or upload foreground photos to the image-generation model.
6. Generate two independent 3:4 background candidates. Score them with the aesthetic rubric. Regenerate once with targeted corrections when neither passes; stop if every corrected candidate still has a hard failure.
7. Only after selecting the mode and background, read [references/layout-contract.md](references/layout-contract.md) completely and create `layout.json` for that mode.
8. Keep `rotation: 0` unless a safe environmental image benefits from controlled disorder. Never rotate people, readable text, or directional subjects.
9. Run:

   ```bash
   python scripts/compose_ins_diary.py \
     --background <selected-background> \
     --layout <layout.json> \
     --output <final.png> \
     --provenance <final.provenance.json>
   ```

10. Inspect the full-size render and score the final composition. Confirm every source appears once, copy is truthful and readable, focal subjects survive cropping, one information cluster dominates, and a substantial quiet region remains.
11. Deliver only a passing final image. Keep intermediate backgrounds, layout files, and provenance private unless the user asks for them.

## Non-negotiable invariants

- Generate only the background.
- Never generate, redraw, retouch, relight, recolor, replace, extend, or remove foreground content.
- Limit foreground processing to EXIF orientation correction, sRGB conversion, focal crop, resize, and validated `-90`, `0`, or `90` rotation.
- Never omit, duplicate, silently select among, or use a foreground photo as the background.
- Add no rounded corners, borders, frames, photo shadows, stickers, or decorative overlays.
- Keep parentheses as the shared editorial syntax and use only one typography system per composition.

## Bundled resources

- `references/aesthetic-system.md`: visual reasoning, mode routing, copy, background prompting, and scoring.
- `references/layout-contract.md`: mode-specific JSON schemas and renderer constraints; read only after mode selection.
- `scripts/compose_ins_diary.py`: deterministic renderer and provenance checker.
- `assets/fonts/`: OFL-licensed Archivo Black, Inter, and Cormorant Garamond used by the renderer.
