#!/usr/bin/env python3
"""macOS focus shuttle between the current agent app and a reusable Douyin tab."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DOUYIN_URL = "https://www.douyin.com/?recommend=1"
DOUYIN_PATTERN = "douyin.com"
RECOMMEND_PATTERN = "recommend=1"

BROWSERS = [
    {
        "id": "chrome",
        "app": "Google Chrome",
        "kind": "chromium",
        "bundle": "com.google.Chrome",
    },
    {
        "id": "safari",
        "app": "Safari",
        "kind": "safari",
        "bundle": "com.apple.Safari",
    },
    {
        "id": "edge",
        "app": "Microsoft Edge",
        "kind": "chromium",
        "bundle": "com.microsoft.edgemac",
    },
    {
        "id": "brave",
        "app": "Brave Browser",
        "kind": "chromium",
        "bundle": "com.brave.Browser",
    },
]

BROWSER_APPS = {browser["app"] for browser in BROWSERS}
AGENT_APP_CANDIDATES = (
    "Codex",
    "Claude",
    "Claude Code",
    "Terminal",
    "iTerm2",
    "Warp",
    "Visual Studio Code",
    "Cursor",
)


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / "Library" / "Caches"
    return root / "douyin-focus-shuttle"


STATE_PATH = cache_dir() / "state.json"


def run(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def osascript(script: str) -> str:
    proc = run(["osascript", "-e", script])
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "osascript failed"
        raise RuntimeError(message)
    return proc.stdout.strip()


def ensure_macos() -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("automatic focus shuttling is macOS-only in v1")


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def app_is_running(app_name: str) -> bool:
    script = f'tell application "System Events" to (name of processes) contains "{app_name}"'
    return osascript(script).lower() == "true"


def app_exists(app_name: str) -> bool:
    proc = run(["mdfind", f"kMDItemKind == 'Application' && kMDItemDisplayName == '{app_name}.app'"])
    if proc.returncode == 0 and proc.stdout.strip():
        return True
    return Path("/Applications", f"{app_name}.app").exists()


def frontmost_app() -> dict[str, str]:
    script = (
        'tell application "System Events"\n'
        '  set frontProc to first application process whose frontmost is true\n'
        '  set appName to name of frontProc\n'
        '  set windowTitle to ""\n'
        '  try\n'
        '    set windowTitle to name of front window of frontProc\n'
        '  end try\n'
        '  return appName & "\\n" & windowTitle\n'
        'end tell'
    )
    output = osascript(script).splitlines()
    return {
        "app": output[0].strip() if output else "",
        "window": output[1].strip() if len(output) > 1 else "",
    }


def activate_app(app_name: str) -> None:
    osascript(f'tell application "{app_name}" to activate')


def js_string(value: str) -> str:
    return json.dumps(value)


def parse_tab_ref(ref: str) -> tuple[int, int] | None:
    match = re.match(r"^(\d+):(\d+)$", ref.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def find_tab(browser: dict[str, str], pattern: str = DOUYIN_PATTERN) -> tuple[int, int] | None:
    app = browser["app"]
    pattern_lit = js_string(pattern)
    if browser["kind"] == "safari":
        script = f'''
tell application "{app}"
  repeat with w from 1 to count of windows
    repeat with t from 1 to count of tabs of window w
      set tabUrl to ""
      try
        set tabUrl to URL of tab t of window w
      end try
      if tabUrl contains {pattern_lit} then return (w as text) & ":" & (t as text)
    end repeat
  end repeat
end tell
return ""
'''
    else:
        script = f'''
tell application "{app}"
  repeat with w from 1 to count of windows
    repeat with t from 1 to count of tabs of window w
      set tabUrl to ""
      try
        set tabUrl to URL of tab t of window w
      end try
      if tabUrl contains {pattern_lit} then return (w as text) & ":" & (t as text)
    end repeat
  end repeat
end tell
return ""
'''
    output = osascript(script)
    return parse_tab_ref(output)


def focus_tab(browser: dict[str, str], window_index: int, tab_index: int) -> None:
    app = browser["app"]
    if browser["kind"] == "safari":
        script = f'''
tell application "{app}"
  activate
  set current tab of window {window_index} to tab {tab_index} of window {window_index}
  set index of window {window_index} to 1
end tell
'''
    else:
        script = f'''
tell application "{app}"
  activate
  set active tab index of window {window_index} to {tab_index}
  set index of window {window_index} to 1
end tell
'''
    osascript(script)


def tab_contains(browser: dict[str, str], window_index: int, tab_index: int, pattern: str = DOUYIN_PATTERN) -> bool:
    return pattern in get_tab_url(browser, window_index, tab_index)


def get_tab_url(browser: dict[str, str], window_index: int, tab_index: int) -> str:
    app = browser["app"]
    script = f'''
tell application "{app}"
  set tabUrl to ""
  try
    set tabUrl to URL of tab {tab_index} of window {window_index}
  end try
  return tabUrl
end tell
'''
    try:
        return osascript(script)
    except RuntimeError:
        return ""


def set_tab_url(browser: dict[str, str], window_index: int, tab_index: int, url: str = DOUYIN_URL) -> None:
    app = browser["app"]
    url_lit = js_string(url)
    script = f'''
tell application "{app}"
  set URL of tab {tab_index} of window {window_index} to {url_lit}
end tell
'''
    osascript(script)


def ensure_recommend_url(browser: dict[str, str], window_index: int, tab_index: int) -> None:
    current_url = get_tab_url(browser, window_index, tab_index)
    if DOUYIN_PATTERN in current_url and RECOMMEND_PATTERN not in current_url:
        set_tab_url(browser, window_index, tab_index)


def open_new_tab(browser: dict[str, str], url: str = DOUYIN_URL) -> tuple[int, int]:
    app = browser["app"]
    url_lit = js_string(url)
    if browser["kind"] == "safari":
        script = f'''
tell application "{app}"
  activate
  if (count of windows) = 0 then
    make new document with properties {{URL:{url_lit}}}
    return "1:1"
  else
    tell window 1
      set newTab to make new tab with properties {{URL:{url_lit}}}
      set current tab to newTab
      return "1:" & (index of newTab as text)
    end tell
  end if
end tell
'''
    else:
        script = f'''
tell application "{app}"
  activate
  if (count of windows) = 0 then
    make new window
  end if
  tell window 1
    set newTab to make new tab with properties {{URL:{url_lit}}}
    set active tab index to (count of tabs)
    return "1:" & ((count of tabs) as text)
  end tell
end tell
'''
    output = osascript(script)
    parsed = parse_tab_ref(output)
    if not parsed:
        found = find_tab(browser)
        if found:
            return found
        raise RuntimeError(f"opened {app}, but could not identify the Douyin tab")
    return parsed


def browser_by_id(browser_id: str | None) -> dict[str, str] | None:
    if not browser_id:
        return None
    return next((browser for browser in BROWSERS if browser["id"] == browser_id), None)


def supported_default_browser() -> dict[str, str] | None:
    proc = run(
        [
            "osascript",
            "-e",
            'id of application (path to default application for URL "https://www.douyin.com/")',
        ]
    )
    if proc.returncode != 0:
        return None
    bundle_id = proc.stdout.strip()
    return next((browser for browser in BROWSERS if browser["bundle"] == bundle_id), None)


def choose_browser() -> dict[str, str] | None:
    default_browser = supported_default_browser()
    if default_browser and (app_is_running(default_browser["app"]) or app_exists(default_browser["app"])):
        return default_browser

    for browser in BROWSERS:
        if app_is_running(browser["app"]):
            return browser

    for browser in BROWSERS:
        if app_exists(browser["app"]):
            return browser

    return None


def find_any_douyin_tab() -> tuple[dict[str, str], int, int] | None:
    for browser in BROWSERS:
        try:
            if not app_is_running(browser["app"]):
                continue
            found = find_tab(browser)
            if found:
                return browser, found[0], found[1]
        except RuntimeError:
            continue
    return None


def saved_tab_available(state: dict[str, Any]) -> tuple[dict[str, str], int, int] | None:
    douyin = state.get("douyin", {})
    browser = browser_by_id(douyin.get("browser_id"))
    if not browser:
        return None
    window_index = douyin.get("window_index")
    tab_index = douyin.get("tab_index")
    if not isinstance(window_index, int) or not isinstance(tab_index, int):
        return None
    try:
        if not app_is_running(browser["app"]):
            return None
        if not tab_contains(browser, window_index, tab_index):
            return None
        ensure_recommend_url(browser, window_index, tab_index)
        focus_tab(browser, window_index, tab_index)
        return browser, window_index, tab_index
    except RuntimeError:
        return None


def saved_tab_status(state: dict[str, Any]) -> tuple[dict[str, str], int, int] | None:
    douyin = state.get("douyin", {})
    browser = browser_by_id(douyin.get("browser_id"))
    if not browser:
        return None
    window_index = douyin.get("window_index")
    tab_index = douyin.get("tab_index")
    if not isinstance(window_index, int) or not isinstance(tab_index, int):
        return None
    try:
        if not app_is_running(browser["app"]):
            return None
        if not tab_contains(browser, window_index, tab_index):
            return None
        return browser, window_index, tab_index
    except RuntimeError:
        return None


def app_window_title(app_name: str) -> str:
    script = f'''
tell application "System Events"
  set windowTitle to ""
  try
    set targetProc to first application process whose name is "{app_name}"
    set windowTitle to name of front window of targetProc
  end try
  return windowTitle
end tell
'''
    try:
        return osascript(script)
    except RuntimeError:
        return ""


def make_return_target(app_name: str, window_title: str = "") -> dict[str, str]:
    return {"app": app_name, "window": window_title}


def is_agent_app(app_name: str | None) -> bool:
    return bool(app_name) and app_name in AGENT_APP_CANDIDATES


def infer_agent_return_target() -> dict[str, str] | None:
    for app_name in AGENT_APP_CANDIDATES:
        try:
            if app_is_running(app_name):
                return make_return_target(app_name, app_window_title(app_name))
        except RuntimeError:
            continue
    return None


def remember_return_target(
    state: dict[str, Any],
    *,
    return_app: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    if return_app:
        target = make_return_target(return_app, app_window_title(return_app))
        state["return_target"] = target
        return target

    saved_target = state.get("return_target", {})
    if state.get("active") and saved_target and not force:
        if is_agent_app(saved_target.get("app")):
            return saved_target
        inferred = infer_agent_return_target()
        if inferred:
            state["return_target"] = inferred
            return inferred
        return saved_target

    target = frontmost_app()
    if target["app"] and target["app"] not in BROWSER_APPS:
        state["return_target"] = target
        return target

    inferred = infer_agent_return_target()
    if inferred:
        state["return_target"] = inferred
        return inferred

    if saved_target and not force:
        return saved_target

    if target["app"]:
        return target
    return state.get("return_target", {})


def mark_active(state: dict[str, Any]) -> None:
    state["active"] = True
    state["must_return"] = True
    state.setdefault("started_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def mark_returned(state: dict[str, Any]) -> None:
    state["must_return"] = False
    state["returned_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def mark_finished(state: dict[str, Any]) -> None:
    state["active"] = False
    state["must_return"] = False
    state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def enter(*, return_app: str | None = None, active: bool = False) -> int:
    ensure_macos()
    state = load_state()
    return_target = remember_return_target(state, return_app=return_app)
    if active:
        mark_active(state)

    saved = saved_tab_available(state)
    if saved:
        browser, window_index, tab_index = saved
        state["douyin"]["url"] = DOUYIN_URL
        save_state(state)
        print(
            f"Focused saved Douyin recommendation tab in {browser['app']} "
            f"(window {window_index}, tab {tab_index}). Return target: {return_target.get('app', 'unknown')}."
        )
        return 0

    found = find_any_douyin_tab()
    if found:
        browser, window_index, tab_index = found
        ensure_recommend_url(browser, window_index, tab_index)
        focus_tab(browser, window_index, tab_index)
        state["douyin"] = {
            "browser_id": browser["id"],
            "browser_app": browser["app"],
            "window_index": window_index,
            "tab_index": tab_index,
            "url": DOUYIN_URL,
        }
        save_state(state)
        print(
            f"Focused existing Douyin recommendation tab in {browser['app']} "
            f"(window {window_index}, tab {tab_index}). Return target: {return_target.get('app', 'unknown')}."
        )
        return 0

    browser = choose_browser()
    if not browser:
        raise RuntimeError("no supported controllable browser found")

    window_index, tab_index = open_new_tab(browser)
    state["douyin"] = {
        "browser_id": browser["id"],
        "browser_app": browser["app"],
        "window_index": window_index,
        "tab_index": tab_index,
        "url": DOUYIN_URL,
    }
    save_state(state)
    print(
        f"Opened one new Douyin recommendation tab in {browser['app']} "
        f"(window {window_index}, tab {tab_index}). Future enter calls will reuse it."
    )
    return 0


def away(return_app: str | None = None) -> int:
    return enter(return_app=return_app, active=True)


def start(return_app: str | None = None) -> int:
    return away(return_app=return_app)


def restore_return_target(*, clear_must_return: bool = True) -> int:
    ensure_macos()
    state = load_state()
    target = state.get("return_target", {})
    app_name = target.get("app")
    if not app_name:
        raise RuntimeError("no saved return target")
    activate_app(app_name)
    if clear_must_return:
        mark_returned(state)
        save_state(state)
    print(f"Returned focus to {app_name}.")
    return 0


def before_reply() -> int:
    ensure_macos()
    state = load_state()
    if state.get("active") and state.get("must_return"):
        return restore_return_target(clear_must_return=True)
    print("No pending return needed.")
    return 0


def finish() -> int:
    ensure_macos()
    state = load_state()
    if state.get("active") and state.get("must_return"):
        restore_return_target(clear_must_return=True)
        state = load_state()
    mark_finished(state)
    save_state(state)
    print("Finished douyin focus shuttle session.")
    return 0


def back() -> int:
    return finish()


def guard(command: list[str], return_app: str | None = None) -> int:
    if not command:
        raise RuntimeError("guard requires a command after --")
    start(return_app=return_app)
    proc = subprocess.run(command)
    restore_return_target(clear_must_return=True)
    state = load_state()
    mark_finished(state)
    save_state(state)
    return proc.returncode


def status() -> int:
    ensure_macos()
    state = load_state()
    return_target = state.get("return_target", {})
    douyin = state.get("douyin", {})
    saved = saved_tab_status(state)
    if saved:
        browser, window_index, tab_index = saved
        availability = f"available in {browser['app']} window {window_index}, tab {tab_index}"
    elif douyin:
        availability = "saved but not currently focusable"
    else:
        availability = "not saved"

    print(json.dumps(
        {
            "state_path": str(STATE_PATH),
            "active": state.get("active", False),
            "must_return": state.get("must_return", False),
            "return_target": return_target or None,
            "douyin_target": douyin or None,
            "douyin_availability": availability,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Focus shuttle between an agent app and a reusable Douyin tab.")
    parser.add_argument(
        "command",
        choices=["away", "back", "start", "enter", "before-reply", "finish", "return", "status", "guard"],
    )
    parser.add_argument(
        "--return-app",
        help="Explicit app to return to, for example Codex. Useful when the current frontmost app is a browser.",
    )
    args, remainder = parser.parse_known_args()

    try:
        if args.command == "away":
            return away(return_app=args.return_app)
        if args.command == "back":
            return back()
        if args.command == "start":
            return start(return_app=args.return_app)
        if args.command == "enter":
            return enter(return_app=args.return_app)
        if args.command == "before-reply":
            return before_reply()
        if args.command == "finish":
            return finish()
        if args.command == "return":
            return restore_return_target()
        if args.command == "status":
            return status()
        if args.command == "guard":
            command = remainder
            if command and command[0] == "--":
                command = command[1:]
            return guard(command, return_app=args.return_app)
    except RuntimeError as exc:
        print(f"douyin-focus-shuttle: {exc}", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
