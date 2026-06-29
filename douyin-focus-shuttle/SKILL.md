---
name: douyin-focus-shuttle
description: Use this skill when the user wants the agent to send them to the Douyin recommendation page while the agent works, then bring them back when input is needed or the task is done. Trigger for requests like "任务期间让我去刷抖音", "开始任务时切到抖音推荐页", "做完叫我回来", "Agent 工作时让我等一下", "长线任务别忘了最后切回来", "中途再切回浏览器但别新开页面", or any workflow where the user wants focus shuttled between an agent window and Douyin. The skill prioritizes reusing the same douyin.com browser tab instead of opening duplicates.
license: MIT
compatibility: macOS-first. Requires shell access plus AppleScript automation permission for reliable app and browser focus control. Other platforms should use the documented manual fallback.
metadata:
  version: "0.1.0"
  default_url: "https://www.douyin.com/?recommend=1"
  script: "scripts/douyin_focus.py"
---

# Douyin Focus Shuttle

This skill is a focus shuttle, not a Douyin automation tool.

Use it when the user explicitly wants to wait in Douyin while the agent works, then come back when the agent needs them or has finished. The important behavior is preserving the user's working context: remember where the agent is, reuse one Douyin tab, keep that tab on the recommendation page, and return to the original agent app before asking for input or giving the final result.

## Boundaries

- Do not scroll, click, like, follow, log in, scrape, or otherwise operate the user's Douyin account.
- Do not claim this is a global always-on lifecycle hook. A generic skill can only run after the current task triggers it.
- Do not repeatedly open `douyin.com`. Reuse the existing Douyin page whenever possible.
- When a Douyin tab exists but is not on the recommendation page, navigate that same tab to `https://www.douyin.com/?recommend=1` instead of opening another page.
- Do not hide failures. If browser focus control is unavailable, say what could not be automated and give the manual fallback.

## First step

At the start of a task that triggers this skill, run:

```bash
python3 scripts/douyin_focus.py enter
```

Resolve `scripts/douyin_focus.py` relative to this skill directory. If the agent is working from another project directory, use the absolute path to this skill's script.

Then continue the user's actual task.

`enter` records the current frontmost macOS app as the return target. It then looks for an existing `douyin.com` tab in supported browsers. If it finds one, it reuses that tab and moves it to `https://www.douyin.com/?recommend=1` if needed. If it does not find one, it opens exactly one new recommendation-page tab in a controllable browser and saves that tab as the one to reuse.

If the user later asks to be sent back to Douyin during the same task, run `enter` again. The command is intentionally idempotent: repeated calls should focus the saved or existing Douyin tab, not open more copies.

## Long-running task memory

Do not rely on remembering this skill only in natural language. After the first successful `enter`, create or update the agent's task plan, checklist, or working notes with an explicit unresolved item:

```text
Before asking the user, reporting a blocker, or finalizing, run douyin_focus.py return.
```

Keep that item unresolved until `return` has actually run. In long-running work, check this item before every user-facing message, especially after tool calls, build/test loops, background waits, or context-heavy analysis.

The script also writes persistent state under the user's cache directory, so the saved return target and Douyin tab survive long command sequences. Use `status` if the task has been running for a long time and you need to refresh what was saved.

## Return step

Before any moment that needs the user's attention, run:

```bash
python3 scripts/douyin_focus.py return
```

Resolve the script path the same way as in the first step.

Run this before:

- asking a clarifying question
- reporting a blocker
- giving the final answer
- asking the user to review a result

If the command cannot restore focus, explain the failure briefly and name the saved app it attempted to restore.

## Status checks

Use this when debugging or when you need to decide whether a saved target exists:

```bash
python3 scripts/douyin_focus.py status
```

## Browser strategy

The priority is "do not duplicate the Douyin page", not "always use the default browser".

Supported macOS browsers:

- Google Chrome
- Safari
- Microsoft Edge
- Brave Browser

The script first checks the saved Douyin target from the current task. If that target is no longer available, it searches all supported browsers for a `douyin.com` tab. Only when none exists does it create one new tab. Any reused tab should be moved to `https://www.douyin.com/?recommend=1` in place.

If the default browser is one of the supported browsers, the script prefers it for the first new tab. If not, it uses the first running supported browser, then the first installed supported browser.

## Fallback

If the environment is not macOS, or shell/AppleScript access is unavailable:

1. Tell the user that automatic focus shuttling is unavailable in this environment.
2. Ask them to open `https://www.douyin.com/?recommend=1` manually while the agent works.
3. Before asking for input or finalizing, clearly tell them to return to the agent window.

Keep the fallback honest. Do not imply that the agent restored focus when it did not.
