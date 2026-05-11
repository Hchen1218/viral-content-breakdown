---
name: creator-platform-ingest
description: Pull logged-in Xiaohongshu Creator and Douyin Creator data from the user's normal Chrome app through the web-access proxy, normalize dashboard and content-list metrics, and feed them into ai-content's existing intake/review workflow. Use this whenever the user asks to抓取/导入/同步创作者后台数据, automate content ops intake, replace manual xlsx export, update 内容数据表, or build weekly creator reviews from creator-platform pages. Always use the user's default Chrome app via the web-access skill; do not spin up an isolated browser unless the user explicitly asks.
---

# Creator Platform Ingest

This skill captures creator-platform data from:
- Xiaohongshu Creator
- Douyin Creator

It is designed for `ai-content`'s existing workflow, not as a parallel reporting system.
Phase 2 is scoped around运营录入自动化, so the capture should favor data that can directly feed:
- `01-内容生产/数据统计/内容数据表.md`
- published-archive data blocks
- `📋 进行中的运营动作.md`
- weekly review drafts

Phase 3 extends that pipeline into direct write-back:
- refresh `内容数据表.md` from the latest capture
- update matched published-archive data blocks
- generate the current weekly review draft
- auto-create archive stubs for newly published but still-unarchived content
- keep unmatched rows, partial coverage, and missing content assets explicit in a sidecar report

## What success looks like

The run is successful when all of the following are true:
- `web-access` is attached to the user's normal Chrome app
- the script captures creator dashboard data and content-list data into a structured JSON file
- the capture is saved under `.cache/content-pipeline/creator-captures/`
- the structured output makes it obvious what was captured, what is partial, and what is still missing
- the assistant can use that capture to update `01-内容生产/数据统计/内容数据表.md` and related review docs if the user asked for write-back

## Mandatory browser rule

- Always use the user's normal Chrome app
- Always go through the local `web-access` proxy on `http://127.0.0.1:3456`
- Never launch a separate browser profile or headless browser unless the user explicitly asks
- Do not operate on the user's existing tabs unless they explicitly ask; open your own background tabs and close them after capture

## Direct routes to use

Use these direct logged-in routes instead of the root landing pages.

### Xiaohongshu Creator
- Home: `https://creator.xiaohongshu.com/new/home`
- Note manager: `https://creator.xiaohongshu.com/new/note-manager`
- Content analysis: `https://creator.xiaohongshu.com/statistics/data-analysis`

### Douyin Creator
- Home: `https://creator.douyin.com/creator-micro/home`
- Works manager: `https://creator.douyin.com/creator-micro/content/manage`

These routes are more stable than opening the bare domain and waiting for intermediate landing tabs.

## Default workflow

### 1. Connect browser

First ensure `web-access` is ready against the user's normal Chrome app:

```bash
bash /Users/cecilialiu/.codex/vendor_imports/web-access/scripts/check-deps.sh
```

If the proxy is not reachable or Chrome debugging is not enabled:
- ask the user to open `chrome://inspect/#remote-debugging`
- ask them to enable `Allow remote debugging for this browser instance`
- retry the check

### 2. Run the capture script

Use the bundled script:

```bash
python3 generated-skills/creator-platform-ingest/scripts/capture_creator_platforms.py
```

Common options:

```bash
python3 generated-skills/creator-platform-ingest/scripts/capture_creator_platforms.py \
  --output-dir .cache/content-pipeline/creator-captures/manual-run \
  --keep-tabs
```

By default the script:
- opens its own background tabs through the proxy
- captures five pages
- normalizes visible metrics into运营字段集合
- saves `capture.json`
- saves `report.md`
- closes its own tabs

### 3. Use the capture in ai-content

If the user asked for data intake or review updates:
- read `运营OS.md`
- follow the `记录数据 / 归档已发布内容` flow
- update `01-内容生产/数据统计/内容数据表.md`
- if requested, update weekly review docs and related published archives

Do not invent unavailable metrics. If a field is not exposed by the page capture, keep it blank and say why.

### 4. Run Phase 3 write-back

When the user explicitly wants the capture written back into `ai-content`, run:

```bash
python3 generated-skills/creator-platform-ingest/scripts/writeback_capture_to_ai_content.py \
  --capture .cache/content-pipeline/creator-captures/<run>/capture.json \
  --repo-root .
```

Use `--dry-run` first when you are changing the write-back logic itself or validating a new capture shape.

The write-back script updates:
- `01-内容生产/数据统计/内容数据表.md`
- matched files under `01-内容生产/选题管理/03-已发布选题/`
- `02-业务运营/业务规划/周期复盘/<current-week>.md`
- `<capture-dir>/writeback-report.md`

It does **not** fabricate missing fields and does **not** silently edit `📋 进行中的运营动作.md` when the latest capture does not hit an active action.
When a freshly published row does not match any existing archive, it now creates a stub under `03-已发布选题/` first, then reruns archive matching so later write-back can land on a real file.
When the archive still lacks `口播稿正文 / 图文正文 / 封面标题`, the script records those gaps in `writeback-report.md` instead of pretending the archive is complete.
The write-back report also includes `User Supplement Needed`; this section must only ask the user for `封面标题 / 完整口播稿 / 图文正文 / 归档合并关系`. Do not ask the user to provide platform-published titles, body copy, or tags, because those should be captured from creator-platform pages.

### 5. Replay write-back fixtures when changing pipeline logic

When changing parser, matching, archive-gap, or write-back behavior, run historical capture replay before claiming the skill still works:

```bash
python3 generated-skills/creator-platform-ingest/scripts/replay_writeback_fixtures.py \
  --repo-root . \
  --strict-resolved
```

The replay script:
- validates capture schema against historical `capture.json` files
- copies the minimal `ai-content` repo state into a temp directory
- runs Phase 3 write-back against the temp repo
- checks `writeback-report.md` contains `Unmatched Rows`, `Created Archives`, `Asset Gaps`, and `User Supplement Needed`
- verifies curated fixtures stay resolved, without mutating the real repo

Use `--capture <path>` for a newly captured fixture and `--keep-temp` when you need to inspect the temp repo.

## Output files

The script writes:

- `capture.json`
  - structured source-of-truth capture
  - must contain these top-level groups:
    - `capture_context`
    - `account_snapshot`
    - `trend_series`
    - `content_rows`
    - `detail_metrics`
    - `match_hints`
    - `capture_coverage`
- `report.md`
  - human-readable summary of the same capture
- `writeback-report.md`
  - generated by Phase 3 write-back
  - must include changed files, unmatched rows, created archives, asset gaps, and user supplement needs

Recommended storage location:

- `.cache/content-pipeline/creator-captures/YYYY-MM-DD-HHMMSS/`

## Current coverage

### Xiaohongshu Creator
- home dashboard summary
- note manager list
- content-analysis table with DOM pagination across visible pages
- current selected data window and selected status filter
- partial-list coverage reporting
- per-note supplement for `曝光 / 观看 / 封面点击率 / 点赞 / 评论 / 收藏 / 涨粉 / 分享 / 人均观看时长 / 弹幕`
- archive-title alias matching so write-back can still target the right published file when the published title differs from the archive H1

### Douyin Creator
- home dashboard summary
- homepage overview API for near-7-day summary + daily series
- works manager list
- current selected data window and selected status filter
- work-list API enrichment for full published works coverage
- per-work supplement for `播放 / 点赞 / 收藏 / 分享 / 评论 / 涨粉 / 5s完播率 / 完播率 / 平均播放时长 / 2s跳出率 / 主页访问 / 封面点击率`
- per-account aggregate derived from full published works for `总播放 / 总点赞 / 总收藏 / 累计视频数 / 条均5s完播率 / 条均2s跳出率 / 条均播放时长 / 播放量中位数`
- Phase 3 write-back into `内容数据表.md` / published archives / weekly review
- Phase 3 archive-gap reporting for `口播稿正文 / 图文正文 / 封面标题`
- Phase 3 auto-stub creation for newly published unmatched rows

## Phase 2 data priorities

Capture priority is fixed in this order:

1. `capture_context`
2. `content_rows`
3. `account_snapshot`
4. `trend_series`
5. `detail_metrics`

Do not widen scope into generic dashboard crawling.

### Must-capture context
- platform
- page URL
- captured time
- current data window
- selected filters
- total row count
- visible row count
- whether the result is partial

### Must-capture content facts

Shared fields:
- platform
- title
- content type
- publish time
- stable content id
- content URL or reversible source ref
- whether it belongs to the current week
- whether it hits an active action card

Xiaohongshu priority fields:
- 曝光
- 观看
- 内容点击率
- 点赞
- 收藏
- 分享
- 涨粉
- 评论

For Xiaohongshu specifically:
- do not expect `new/note-manager` to expose `曝光 / 内容点击率 / 涨粉`
- supplement those fields from `statistics/data-analysis`
- treat `statistics/data-analysis` as the per-note enrichment source, even if `详情数据` drill-down is not yet parsed as a stable extra panel

Douyin priority fields:
- 播放
- 点赞
- 收藏
- 分享
- 评论
- 涨粉
- 5s 完播率
- 完播率
- 平均播放时长
- 2s 跳出率
- 主页访问
- 封面点击率

For Douyin specifically:
- do not rely on visible DOM text alone for validation metrics
- supplement work rows from the logged-in `work_list` API exposed by the works-manager page
- use the page DOM mainly for selected status and fallback rendering context
- derive account-level totals and medians from the full work-list API when those values are needed by `内容数据表.md`

If the current page does not expose some of these fields, keep them blank and explain the gap in `capture_coverage`.

### Must-capture account snapshot

Xiaohongshu:
- 曝光
- 观看
- 平台封面点击率
- 平均观看时长
- 总观看时长
- 完播率
- 笔记数
- 点赞数
- 评论数
- 收藏数
- 分享数
- 净涨粉
- 新增关注
- 取消关注
- 主页访客

Douyin:
- 总播放
- 总点赞
- 总收藏
- 投稿量
- 垂类
- 条均 5s 完播率
- 条均 2s 跳出率
- 条均播放时长
- 播放量中位数

### Trend handling rule

Trend series are required for downstream review logic, but current creator pages may not always expose daily points in stable DOM text.

So the script must:
- prefer the Douyin homepage `overview/all` API for near-7-day trend capture
- treat Xiaohongshu weekly summary metrics as an acceptable capture outcome when daily points are not exposed
- never leave trend gaps silent
- mark the platform trend block as `series_available`, `summary_only`, or `missing` based on the real coverage

When a required field is missing, say so explicitly and keep the raw capture around for debugging.

## Cross-platform distinction rule

- Treat Xiaohongshu and Douyin titles as platform-specific by default
- Treat Xiaohongshu and Douyin published copy正文 and tag as platform-specific by default
- Never overwrite one platform's title/body/tag with the other platform's version just because publish dates are close
- Only collapse two platform rows into the same newly created archive when there is high-confidence evidence that they are the same content
- If confidence is low, create separate archive stubs first and let later manual alignment or archive aliases merge them intentionally

## Parsing assumptions to preserve

### Xiaohongshu note manager

The visible per-note number sequence is currently treated as:

1. `观看`
2. `评论`
3. `点赞`
4. `收藏`
5. `分享`

This mapping is based on observed alignment with prior exported data. If the UI changes, re-check the mapping before writing back to `ai-content`.

### Douyin works manager

The parser reads visible label-value pairs as-is, including:
- `播放`
- `平均播放时长`
- `封面点击率`
- `点赞`
- `评论`
- `分享`
- `收藏`
- `弹幕`

## Scope guard

Do not capture:
- fan persona / audience profile
- revenue / settlement / ecommerce / order data
- private messages / collaboration inbox
- academy / mission center / generic platform activity pages
- any field that cannot feed `内容数据表 / 动作卡 / 周复盘`

## When to stop and ask

Stop and ask the user only if one of these is true:
- the proxy cannot connect to Chrome after the user has enabled debugging
- the creator platform is not logged in
- the page structure has changed so much that the parser no longer matches visible content
- the user wants this skill installed to a different final location than the repo scaffold

## Minimal review format

When reporting back after a capture, keep it concise:

```markdown
## Capture result
- source pages captured:
- output path:
- fields captured:
- fields missing:

## Next step
- update ai-content docs
- inspect a changed parser path
- extend to a deeper page
```

## Bundled files

- Script: `scripts/capture_creator_platforms.py`
- Script: `scripts/writeback_capture_to_ai_content.py`
- Script: `scripts/replay_writeback_fixtures.py`
- Evals: `evals/evals.json`
