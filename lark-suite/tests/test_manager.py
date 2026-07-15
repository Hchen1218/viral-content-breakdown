import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "scripts/lark_suite_manager.py"
SPEC = importlib.util.spec_from_file_location("lark_suite_manager", MODULE_PATH)
manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(manager)


class ManagerTests(unittest.TestCase):
    def test_parse_version_ignores_noise(self):
        self.assertEqual(manager.parse_version("lark-cli v1.0.69\n"), "1.0.69")
        self.assertIsNone(manager.parse_version("not installed"))

    def test_failed_cli_command_is_not_a_valid_version(self):
        completed = manager.subprocess.CompletedProcess(
            ["lark-cli", "--version"], 1, "", "download 1.0.69 failed"
        )
        with mock.patch.object(manager.shutil, "which", return_value="/tmp/lark-cli"), \
             mock.patch.object(manager, "run", return_value=completed):
            self.assertIsNone(manager.current_cli_version())

    def test_fresh_update_is_idempotent_and_offline_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(json.dumps({
                "last_update_check": manager.time.time(),
                "mcp_last_good": "0.5.1",
            }))
            with mock.patch.object(manager, "STATE_FILE", state_file), \
                 mock.patch.object(manager, "npm_latest", side_effect=AssertionError):
                result = manager.perform_update()
            self.assertEqual(result["status"], "fresh")
            self.assertEqual(result["state"]["mcp_last_good"], "0.5.1")

    def test_bad_mcp_version_keeps_previous_last_good(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            state_file.write_text(json.dumps({"mcp_last_good": "0.5.1"}))
            with mock.patch.object(manager, "STATE_DIR", root), \
                 mock.patch.object(manager, "STATE_FILE", state_file), \
                 mock.patch.object(manager, "LOCK_DIR", root / "lock"), \
                 mock.patch.object(manager, "current_cli_version", return_value="1.0.69"), \
                 mock.patch.object(manager, "npm_latest", side_effect=["1.0.69", "9.9.9"]), \
                 mock.patch.object(manager, "verify_cli", return_value=True), \
                 mock.patch.object(manager, "verify_mcp", return_value=False), \
                 mock.patch.object(manager, "refresh_hidden_guides", return_value=True):
                result = manager.perform_update(force=True)
            self.assertEqual(result["state"]["mcp_last_good"], "0.5.1")
            self.assertEqual(result["status"], "degraded")

    def test_bad_cli_version_reinstalls_previous_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            state_file.write_text(json.dumps({"mcp_last_good": "0.5.1"}))
            with mock.patch.object(manager, "STATE_DIR", root), \
                 mock.patch.object(manager, "STATE_FILE", state_file), \
                 mock.patch.object(manager, "LOCK_DIR", root / "lock"), \
                 mock.patch.object(manager, "current_cli_version", side_effect=["1.0.28", "1.0.69"]), \
                 mock.patch.object(manager, "npm_latest", side_effect=["1.0.69", "0.5.1"]), \
                 mock.patch.object(manager, "install_cli") as install, \
                 mock.patch.object(manager, "verify_cli", side_effect=[False, True]), \
                 mock.patch.object(manager, "verify_mcp", return_value=True), \
                 mock.patch.object(manager, "refresh_hidden_guides", return_value=True):
                result = manager.perform_update(force=True)
            self.assertEqual(install.call_args_list, [mock.call("1.0.69"), mock.call("1.0.28")])
            self.assertEqual(result["state"]["cli_last_good"], "1.0.28")
            self.assertEqual(result["status"], "degraded")

    def test_concurrent_update_uses_existing_last_good_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            state_file.write_text(json.dumps({"mcp_last_good": "0.5.1"}))
            lock = root / "lock"
            lock.mkdir()
            with mock.patch.object(manager, "STATE_DIR", root), \
                 mock.patch.object(manager, "STATE_FILE", state_file), \
                 mock.patch.object(manager, "LOCK_DIR", lock):
                result = manager.perform_update(force=True)
            self.assertEqual(result["status"], "locked")
            self.assertEqual(result["state"]["mcp_last_good"], "0.5.1")

    def test_single_entry_requires_only_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lark-suite").mkdir()
            with mock.patch.object(manager, "PUBLIC_ROOTS", {"test": root}):
                self.assertTrue(manager.single_entry_ok())
                (root / "lark-docs").mkdir()
                self.assertFalse(manager.single_entry_ok())

    def test_mcp_presets_match_approved_plan(self):
        self.assertEqual(
            manager.MCP_PRESETS,
            "preset.default,preset.base.batch,preset.task.default,preset.calendar.default",
        )
        self.assertTrue(manager.MCP_TOOLS.endswith(",authen.v1.userInfo.get"))

    def test_cli_app_id_can_seed_secure_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"appId": "cli_example", "appSecret": "ref"}))
            fake_home = mock.Mock()
            fake_home.__truediv__ = mock.Mock(return_value=config)
            with mock.patch.object(manager.Path, "home", return_value=fake_home):
                self.assertEqual(manager.configured_cli_app_id(), "cli_example")

    def test_mcp_runtime_ports_do_not_conflict(self):
        with mock.patch.object(manager, "keychain_get", side_effect=["app", "secret", "app", "secret"]):
            codex_command, _ = manager.mcp_launch("codex", "0.5.1")
            claude_command, _ = manager.mcp_launch("claude", "0.5.1")
        self.assertEqual(codex_command[codex_command.index("-p") + 1], "3000")
        self.assertEqual(claude_command[claude_command.index("-p") + 1], "3001")


if __name__ == "__main__":
    unittest.main()
