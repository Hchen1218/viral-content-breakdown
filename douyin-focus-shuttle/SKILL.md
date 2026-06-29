---
name: douyin-focus-shuttle
description: Use this skill when the user wants the agent to send them to the Douyin recommendation page while the agent works, then bring them back when input is needed or the task is done. Trigger for requests like "任务期间让我去刷抖音", "开始任务时切到抖音推荐页", "做完叫我回来", "Agent 工作时让我等一下", "长线任务别忘了最后切回来", "中途再切回浏览器但别新开页面", or any workflow where the user wants focus shuttled between an agent window and Douyin. The skill prioritizes reusing the same douyin.com browser tab instead of opening duplicates and uses lifecycle commands so long tasks remember to return before replying.
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

## Lifecycle commands

At the start of a task that triggers this skill, run:

```bash
python3 scripts/douyin_focus.py start
```

Resolve `scripts/douyin_focus.py` relative to this skill directory. If the agent is working from another project directory, use the absolute path to this skill's script.

If the current frontmost app might already be a browser because of a preflight check, pass the return target explicitly:

```bash
python3 scripts/douyin_focus.py start --return-app Codex
```

Then continue the user's actual task.

`start` records the return target, marks the session active, then looks for an existing `douyin.com` tab in supported browsers. If it finds one, it reuses that tab and moves it to `https://www.douyin.com/?recommend=1` if needed. If it does not find one, it opens exactly one new recommendation-page tab in a controllable browser and saves that tab as the one to reuse.

If the user later asks to be sent back to Douyin during the same task, run `enter` again. The command is intentionally idempotent: repeated calls should focus the saved or existing Douyin tab, not open more copies.

```bash
python3 scripts/douyin_focus.py enter
```

## Long-running task memory

Do not rely on remembering this skill only in natural language. The script writes active session state under the user's cache directory. Before any user-visible message, run:

```bash
python3 scripts/douyin_focus.py before-reply
```

If the session is active and still needs return, `before-reply` restores the agent app. If no return is needed, it exits cleanly. This keeps the prompt short and makes long build/test loops safer.

At final task completion, run:

```bash
python3 scripts/douyin_focus.py finish
```

Use `finish` rather than plain `return` when the task is complete, because it also clears the active session flag.

For long shell commands, prefer wrapping them:

```bash
python3 scripts/douyin_focus.py guard -- <command> <args>
```

`guard` starts the shuttle, runs the command, returns focus when the command ends, marks the session finished, and exits with the wrapped command's exit code.

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
