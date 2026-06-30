---
name: douyin-focus-shuttle
description: Lightweight focus shuttle for when the user wants to wait in Douyin while the agent works, then be brought back when the agent needs input or is done. Trigger for requests like "让我去刷抖音", "开始任务时切到抖音", "做完叫我回来", "等的时候去抖音", or "别新开抖音页面". Reuses one Douyin recommendation tab and avoids account actions.
---

# Douyin Focus Shuttle

Use only when the user explicitly asks to wait in Douyin during an agent task.

When sending the user away:

```bash
python3 scripts/douyin_focus.py away
```

Before any user-visible question, blocker report, or final answer:

```bash
python3 scripts/douyin_focus.py back
```

Resolve `scripts/douyin_focus.py` relative to this skill folder; use an absolute path if working elsewhere.

Rules: do not scroll, like, follow, log in, scrape, or operate the Douyin account. If automation fails, say it failed and ask the user to manually return to the agent window.
