# Ins Photo Diary Aesthetic System

## Contents

- [First principles](#first-principles)
- [Image analysis](#image-analysis)
- [Composition routing](#composition-routing)
- [Copy and typography](#copy-and-typography)
- [Background generation](#background-generation)
- [Background scoring](#background-scoring)
- [Final composition scoring](#final-composition-scoring)

## First principles

Separate three jobs:

1. **Atmosphere** — a full-bleed background creates mood, place, scale, color unity, and breathing room.
2. **Evidence** — small untouched fragments make the diary personal and believable.
3. **Narration** — words and parentheses turn fragments into a visual sentence rather than a generic grid.

The formula is `emotional field + lived evidence + editorial syntax + deliberate emptiness`. Restraint is the primary aesthetic feature.

Always preserve this brand grammar:

- 1536 × 2048, 3:4, full-bleed canvas;
- generated background only;
- every user image used exactly once as a hard-edged fragment;
- original local color and photographic character retained;
- white editorial type and functional parentheses;
- one main information cluster and at least one substantial quiet region;
- no stickers, frames, rounding, borders, photo shadows, or scrapbook effects.

Select these variables from the evidence: composition mode, typography, copy, anchor, fragment shape and size, quiet-space direction, and background activity. Do not turn a variable from one reference into a universal rule.

## Image analysis

For each source record:

- `subject`, one or two `mood` adjectives, and two to four palette colors;
- normalized `[x, y]` focal coordinates;
- `contains_people`, `contains_text`, and `directional` flags;
- `safe_to_rotate: true` only when all three flags are false;
- supported evidence of a shared outing, place, time, activity, or emotional condition.

For the set, assess semantic diversity, palette and mood coherence, event energy versus reflective quiet, truthful narrative continuity, and the best anchor and quiet-space direction.

## Composition routing

Choose exactly one mode.

| Mode | Select when | Copy | Typography | Structure | Default anchor |
|---|---|---|---|---|---|
| `bold-index` | Subjects are varied, eventful, colorful, or category-led | One lowercase category word per row | Archivo Black labels; Inter parentheses | Three or four right-aligned rows | `center` |
| `quiet-journal` | Palette and mood coherence are stronger than subject diversity | One or two restrained lowercase words | Cormorant Garamond | Two to four compact centered rows | `center` |
| `place-note` | A shared outing, place, or journey is supported | Two to four short visual-sentence lines | Light Inter | Images act as inline visual nouns | `lower` for open sky; otherwise `center` |

Tie-breaking order:

1. Use `place-note` only with a truthful narrative thread.
2. Otherwise use `quiet-journal` when emotional and palette coherence dominate.
3. Otherwise use `bold-index`.

When two modes remain equally plausible, render one low-resolution layout preview for each against the same selected background and retain the higher-scoring final composition.

## Copy and typography

- Use facts only from the user, reliable metadata, or clear visual evidence.
- Never infer a city from architectural resemblance or invent a relationship, date, season, weather condition, or event.
- Poetic language may describe supported mood but must not fabricate context.
- `bold-index`: prefer concrete categories such as `weather`, `food`, `people`, `faith`, `racing`, or `details`.
- `quiet-journal`: prefer restrained observations such as `soft rain`, `stillness`, `blue hour`, or `small joys` only when supported.
- `place-note`: use a short movement phrase, optional connector, and supported place or neutral context. Omit a named location when it is unknown.
- Avoid filler such as `photo`, `image`, `stuff`, `random`, `vibes`, and invented words.

Parentheses must contain a fragment, connect text to a fragment, separate adjacent fragments, or let a fragment replace a noun. Never use empty parentheses as decoration.

## Background generation

Generate from text only. Never attach or reference foreground images in the generation call.

```text
Asset type: atmospheric 3:4 portrait background for an editorial photo diary
Primary request: <environment supported by the set's mood or context>
Style/medium: natural photographic image, tactile real-world texture, subtle film character, contemporary Instagram editorial restraint
Composition mode: <bold-index | quiet-journal | place-note>
Placement zone: preserve a readable <upper | center | lower> zone for one compact white-type and photo-fragment cluster
Quiet space: preserve one substantial calm region <above | below | beside> the placement zone; total negative space feels at least one third of the canvas
Color palette: <palette derived from source analysis>
Scene activity: <quiet field | active environmental texture with a clear tonal corridor>
Depth: broad environmental scale; optionally one or two small distant elements outside the placement zone
Constraints: background only; no collage, frames, inset photos, text, letters, logos, watermark, foreground portrait, or replicas of source subjects
Avoid: detail that destroys placement-zone readability, stock-photo polish, symmetrical poster design, decorative stickers, obvious AI surrealism
```

Water, sky, rock, waterfall, grass, textured walls, and distant city surfaces are valid when supported. Small birds, a moon, or distant lights may add atmosphere outside the placement zone. Never allow a prominent person or central hero object.

## Background scoring

Score 0–5 on placement-zone usability, palette harmony, overlay contrast, atmosphere and depth, and restraint. Require at least 20/25 with no hard failure.

Hard failures: text, watermark, collage frames, prominent people, a dominant object inside the placement zone, replicas of source subjects, or density that makes the selected composition unreadable. If both candidates fail, regenerate two corrected candidates once; stop if all corrected candidates still fail.

## Final composition scoring

Score 0–5 on mode fit, copy integrity, typographic rhythm, evidence legibility, and atmosphere with restraint. Require at least 21/25 with no hard failure.

Hard failures: missing or duplicated sources, unsupported factual copy, sideways people or text, unreadable typography, lost focal subjects, foreground generation or retouching, a source used as background, or a generic grid or scrapbook result.

When below 21 without a hard failure, adjust copy, anchor, mode, fragment shape, or size and render once more. Never modify source pixels beyond allowed deterministic transforms.
