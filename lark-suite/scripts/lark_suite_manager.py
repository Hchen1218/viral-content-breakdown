#!/usr/bin/env python3
"""Maintain the private backends behind the single public lark-suite skill."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

CLI_PACKAGE = "@larksuite/cli"
MCP_PACKAGE = "@larksuiteoapi/lark-mcp"
BOOTSTRAP_CLI_VERSION = "1.0.69"
BOOTSTRAP_MCP_VERSION = "0.5.1"
UPDATE_TTL_SECONDS = 24 * 60 * 60
LOCK_STALE_SECONDS = 15 * 60
MCP_PRESETS = (
    "preset.default,preset.base.batch,preset.task.default,"
    "preset.calendar.default"
)
MCP_TOOLS = MCP_PRESETS + ",authen.v1.userInfo.get"
KEYCHAIN_APP_ID_SERVICE = "lark-suite-app-id"
KEYCHAIN_APP_SECRET_SERVICE = "lark-suite-app-secret"
PUBLIC_ROOTS = {
    "codex": Path.home() / ".codex/skills",
    "claude": Path.home() / ".claude/skills",
    "agents": Path.home() / ".agents/skills",
}
STATE_DIR = Path.home() / ".cache/lark-suite"
STATE_FILE = STATE_DIR / "state.json"
LOCK_DIR = STATE_DIR / "update.lock"
HIDDEN_GUIDES = Path.home() / ".codex/.lark-internal-skills"


def run(command: list[str], *, timeout: int = 120, check: bool = False,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=check,
        env=env,
    )


def parse_version(value: str) -> str | None:
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", value)
    return match.group(1) if match else None


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_FILE.read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, STATE_FILE)


class UpdateLock:
    def __init__(self) -> None:
        self.acquired = False

    def __enter__(self) -> "UpdateLock":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            LOCK_DIR.mkdir()
            self.acquired = True
            (LOCK_DIR / "owner.json").write_text(json.dumps({
                "pid": os.getpid(), "created_at": time.time()
            }))
        except FileExistsError:
            try:
                age = time.time() - LOCK_DIR.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    shutil.rmtree(LOCK_DIR)
                    LOCK_DIR.mkdir()
                    self.acquired = True
            except OSError:
                pass
        return self

    def __exit__(self, *_: object) -> None:
        if self.acquired:
            shutil.rmtree(LOCK_DIR, ignore_errors=True)


def keychain_account() -> str:
    return os.environ.get("USER") or getpass.getuser()


def keychain_get(service: str) -> str | None:
    result = run([
        "security", "find-generic-password", "-a", keychain_account(),
        "-s", service, "-w"
    ], timeout=15)
    return result.stdout.strip() if result.returncode == 0 else None


def keychain_set(service: str, value: str) -> None:
    run([
        "security", "add-generic-password", "-U", "-a", keychain_account(),
        "-s", service, "-w", value
    ], timeout=15, check=True)


def configured_cli_app_id() -> str | None:
    try:
        payload = json.loads((Path.home() / ".lark-cli/config.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if isinstance(payload, dict):
        value = payload.get("appId") or payload.get("app_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def npm_latest(package: str) -> str:
    result = run(["npm", "view", package, "version"], timeout=30, check=True)
    version = parse_version(result.stdout)
    if not version:
        raise RuntimeError(f"npm did not return a valid version for {package}")
    return version


def current_cli_version() -> str | None:
    executable = shutil.which("lark-cli")
    if not executable:
        return None
    result = run([executable, "--version"], timeout=30)
    if result.returncode != 0:
        return None
    return parse_version(result.stdout + result.stderr)


def verify_cli(expected: str | None = None) -> bool:
    version = current_cli_version()
    if not version or (expected and version != expected):
        return False
    result = run(["lark-cli", "--help"], timeout=30)
    return result.returncode == 0 and bool(result.stdout.strip())


def install_cli(version: str) -> None:
    # Intentionally never call `lark-cli update`: it installs public skills.
    run(["npm", "install", "-g", f"{CLI_PACKAGE}@{version}"],
        timeout=300, check=True)


def verify_mcp(version: str) -> bool:
    result = run(["npx", "-y", f"{MCP_PACKAGE}@{version}", "--version"],
                 timeout=180)
    output = result.stdout + result.stderr
    return result.returncode == 0 and (version in output or "lark-mcp" in output)


def mcp_launch(runtime: str, version: str) -> tuple[list[str], dict[str, str]]:
    app_id = keychain_get(KEYCHAIN_APP_ID_SERVICE)
    app_secret = keychain_get(KEYCHAIN_APP_SECRET_SERVICE)
    if not app_id or not app_secret:
        raise RuntimeError("Feishu credentials are missing; run setup")
    port = "3000" if runtime == "codex" else "3001"
    env = os.environ.copy()
    env.update({
        "APP_ID": app_id,
        "APP_SECRET": app_secret,
        "LARK_DOMAIN": "https://open.feishu.cn",
        "LARK_TOKEN_MODE": "user_access_token",
        "LARK_TOOLS": MCP_TOOLS,
    })
    command = [
        "npx", "-y", f"{MCP_PACKAGE}@{version}", "mcp", "--oauth",
        "--token-mode", "user_access_token", "-l", "zh", "-t", MCP_TOOLS,
        "-p", port,
    ]
    return command, env


def mcp_probe(version: str, *, runtime: str = "codex", timeout: int = 20) -> dict[str, Any]:
    command, env = mcp_launch(runtime, version)
    process = subprocess.Popen(
        command,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("MCP stdio was unavailable")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    def send(payload: dict[str, Any]) -> None:
        process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def receive(response_id: int) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not selector.select(timeout=min(0.5, deadline - time.time())):
                continue
            line = process.stdout.readline()
            if not line:
                break
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("id") == response_id:
                return payload
        raise RuntimeError(f"MCP response {response_id} timed out")

    try:
        send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "lark-suite-verify", "version": "1.0"},
            },
        })
        initialize = receive(1)
        if "error" in initialize:
            raise RuntimeError(f"MCP initialize failed: {initialize['error']}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = receive(2)
        tools = listed.get("result", {}).get("tools", [])
        names = [tool.get("name", "") for tool in tools if isinstance(tool, dict)]
        identity_name = next((
            name for name in names
            if "user_info" in name or "user-info" in name or "userinfo" in name.lower()
        ), None)
        identity_ok: bool | None = None
        identity_error: str | None = None
        if identity_name:
            send({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": identity_name, "arguments": {}},
            })
            identity = receive(3)
            result = identity.get("result", {})
            identity_ok = "error" not in identity and not bool(result.get("isError"))
            if not identity_ok:
                content = result.get("content", [])
                texts = [
                    item.get("text", "") for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                identity_error = " ".join(texts)[:1200] or str(identity.get("error", "unknown"))[:1200]
        return {
            "connected": True,
            "tool_count": len(names),
            "identity_tool": identity_name,
            "identity_ok": identity_ok,
            "identity_error": identity_error,
        }
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def refresh_hidden_guides(cli_version: str) -> bool:
    temp_root = Path(tempfile.mkdtemp(prefix="lark-suite-guides-"))
    try:
        repo = temp_root / "repo"
        result = run([
            "git", "clone", "--depth", "1", "--branch", f"v{cli_version}",
            "https://github.com/larksuite/cli.git", str(repo)
        ], timeout=180)
        source = repo / "skills"
        if result.returncode != 0 or not source.is_dir():
            return False
        staged = HIDDEN_GUIDES.with_name(HIDDEN_GUIDES.name + ".new")
        backup = HIDDEN_GUIDES.with_name(HIDDEN_GUIDES.name + ".previous")
        shutil.rmtree(staged, ignore_errors=True)
        shutil.copytree(source, staged)
        if backup.exists():
            shutil.rmtree(backup)
        if HIDDEN_GUIDES.exists():
            os.replace(HIDDEN_GUIDES, backup)
        os.replace(staged, HIDDEN_GUIDES)
        shutil.rmtree(backup, ignore_errors=True)
        return True
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def public_lark_entries() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for name, root in PUBLIC_ROOTS.items():
        if not root.is_dir():
            result[name] = []
            continue
        result[name] = sorted(
            item.name for item in root.iterdir() if item.name.startswith("lark-")
        )
    return result


def single_entry_ok() -> bool:
    return all(entries == ["lark-suite"] for entries in public_lark_entries().values())


def configured_mcp() -> dict[str, bool]:
    codex_config = Path.home() / ".codex/config.toml"
    claude_config = Path.home() / ".claude.json"
    values: dict[str, bool] = {}
    for name, path in (("codex", codex_config), ("claude", claude_config)):
        try:
            text = path.read_text()
        except OSError:
            text = ""
        values[name] = "lark-feishu" in text and "lark_suite_manager.py" in text
    return values


def cli_auth_status() -> str:
    if not shutil.which("lark-cli"):
        return "cli_missing"
    result = run(["lark-cli", "auth", "status"], timeout=30)
    text = (result.stdout + result.stderr).strip()
    try:
        payload = json.loads(text)
        user_status = payload.get("identities", {}).get("user", {}).get("status")
        if user_status == "ready":
            return "user_ready"
        bot_status = payload.get("identities", {}).get("bot", {}).get("status")
        if bot_status == "ready":
            return "bot_only"
        message = payload.get("error", {}).get("message")
        if message == "not configured":
            return "not_configured"
    except (json.JSONDecodeError, AttributeError):
        pass
    return "error" if text else "not_configured"


def perform_update(*, force: bool = False) -> dict[str, Any]:
    state = load_state()
    now = time.time()
    if not force and now - float(state.get("last_update_check", 0)) < UPDATE_TTL_SECONDS:
        return {"status": "fresh", "state": state}

    with UpdateLock() as lock:
        if not lock.acquired:
            return {"status": "locked", "state": state}
        state["last_update_check"] = now
        errors: list[str] = []

        old_cli = current_cli_version()
        try:
            target_cli = npm_latest(CLI_PACKAGE)
            if old_cli != target_cli:
                install_cli(target_cli)
            if not verify_cli(target_cli):
                raise RuntimeError(f"CLI verification failed for {target_cli}")
            state["cli_last_good"] = target_cli
        except Exception as exc:  # update must not block existing functionality
            errors.append(f"cli: {exc}")
            if old_cli and current_cli_version() != old_cli:
                try:
                    install_cli(old_cli)
                    if not verify_cli(old_cli):
                        raise RuntimeError("rollback verification failed")
                    state["cli_last_good"] = old_cli
                except Exception as rollback_exc:
                    errors.append(f"cli_rollback: {rollback_exc}")
            elif old_cli and verify_cli(old_cli):
                state["cli_last_good"] = old_cli

        previous_mcp = str(state.get("mcp_last_good", BOOTSTRAP_MCP_VERSION))
        try:
            target_mcp = npm_latest(MCP_PACKAGE)
            if not verify_mcp(target_mcp):
                raise RuntimeError(f"MCP verification failed for {target_mcp}")
            state["mcp_last_good"] = target_mcp
        except Exception as exc:
            errors.append(f"mcp: {exc}")
            state["mcp_last_good"] = previous_mcp

        guide_version = state.get("cli_last_good")
        if guide_version and state.get("guides_version") != guide_version:
            if refresh_hidden_guides(str(guide_version)):
                state["guides_version"] = guide_version
            else:
                errors.append("guides: refresh failed; previous references retained")

        state["last_update_errors"] = errors
        state["last_update_completed"] = time.time()
        save_state(state)
        return {"status": "updated" if not errors else "degraded", "state": state}


def status_payload() -> dict[str, Any]:
    state = load_state()
    return {
        "cli_version": current_cli_version(),
        "cli_last_good": state.get("cli_last_good"),
        "mcp_last_good": state.get("mcp_last_good", BOOTSTRAP_MCP_VERSION),
        "guides_version": state.get("guides_version"),
        "credentials": {
            "app_id": bool(keychain_get(KEYCHAIN_APP_ID_SERVICE)),
            "app_secret": bool(keychain_get(KEYCHAIN_APP_SECRET_SERVICE)),
        },
        "cli_auth": cli_auth_status(),
        "mcp_configured": configured_mcp(),
        "public_lark_entries": public_lark_entries(),
        "single_entry": single_entry_ok(),
        "last_update_check": state.get("last_update_check"),
        "last_update_errors": state.get("last_update_errors", []),
    }


def command_setup(_: argparse.Namespace) -> int:
    print("Credentials are stored in macOS Keychain and are never written to config files.")
    existing_app_id = configured_cli_app_id()
    suffix = f" [{existing_app_id}]" if existing_app_id else ""
    app_id = input(f"Feishu App ID{suffix}: ").strip() or existing_app_id or ""
    app_secret = getpass.getpass("Feishu App Secret: ").strip()
    if not app_id or not app_secret:
        print("Both App ID and App Secret are required.", file=sys.stderr)
        return 2
    keychain_set(KEYCHAIN_APP_ID_SERVICE, app_id)
    keychain_set(KEYCHAIN_APP_SECRET_SERVICE, app_secret)
    print("Saved. Configure OAuth redirect URLs for http://localhost:3000 and :3001.")
    return 0


def command_status(_: argparse.Namespace) -> int:
    print(json.dumps(status_payload(), ensure_ascii=False, indent=2))
    return 0


def command_update(args: argparse.Namespace) -> int:
    print(json.dumps(perform_update(force=args.force), ensure_ascii=False, indent=2))
    return 0


def command_verify(_: argparse.Namespace) -> int:
    payload = status_payload()
    mcp_version = str(payload["mcp_last_good"])
    try:
        probe = mcp_probe(mcp_version)
    except Exception as exc:
        probe = {"connected": False, "error": str(exc)}
    checks = {
        "cli": verify_cli(),
        "mcp": verify_mcp(mcp_version),
        "mcp_handshake": bool(probe.get("connected")),
        "mcp_tools": int(probe.get("tool_count", 0)) > 0,
        "mcp_identity": probe.get("identity_ok") is True,
        "single_entry": payload["single_entry"],
        "credentials": all(payload["credentials"].values()),
        "mcp_configured": all(payload["mcp_configured"].values()),
    }
    print(json.dumps({"checks": checks, "mcp_probe": probe, "status": payload}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


def command_mcp(args: argparse.Namespace) -> int:
    perform_update(force=False)
    state = load_state()
    version = str(state.get("mcp_last_good", BOOTSTRAP_MCP_VERSION))
    try:
        command, env = mcp_launch(args.runtime, version)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    os.execvpe(command[0], command, env)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup").set_defaults(func=command_setup)
    subparsers.add_parser("status").set_defaults(func=command_status)
    update = subparsers.add_parser("update")
    update.add_argument("--force", action="store_true")
    update.set_defaults(func=command_update)
    subparsers.add_parser("auto-update").set_defaults(func=command_update, force=False)
    subparsers.add_parser("verify").set_defaults(func=command_verify)
    mcp = subparsers.add_parser("mcp")
    mcp.add_argument("--runtime", choices=("codex", "claude"), required=True)
    mcp.set_defaults(func=command_mcp)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
