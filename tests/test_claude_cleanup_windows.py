from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts"))
import claude_cleanup_windows as windows


class WindowsCleanupTests(unittest.TestCase):
    def use_context(self, manager):
        # unittest.TestCase.enterContext is only available starting with Python 3.11.
        value = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return value

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="claude cleanup 测试 ")
        self.addCleanup(temp.cleanup)
        self.home = pathlib.Path(temp.name).resolve()
        self.layout = windows.Layout(self.home, self.home / "AppData/Roaming", self.home / "AppData/Local")
        self.output = io.StringIO()
        self.use_context(contextlib.redirect_stdout(self.output))
        self.use_context(contextlib.redirect_stderr(self.output))
        self.use_context(mock.patch.dict(os.environ, {"CLAUDECODE": "", "CLAUDE_CONFIG_DIR": "", "CLAUDE_SECURESTORAGE_CONFIG_DIR": ""}))

    def file(self, relative, content="keep"):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_main(self, answers=(), *, audit=False, table=None, tty=True):
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(windows.Layout, "from_environment", return_value=self.layout),
            mock.patch.object(windows, "process_table", return_value=table or []),
            mock.patch.object(sys.stdin, "isatty", return_value=tty),
            mock.patch("builtins.input", side_effect=answers) as prompt,
        ):
            result = windows.main(["--audit"] if audit else [])
        return result, prompt

    def test_audit_reads_only_and_does_not_prompt_or_show_credentials(self):
        self.file(".claude/.credentials.json", '{"token":"secret-token"}')
        self.file(".claude/cache/entry")
        before = windows.snapshot(self.home)
        result, prompt = self.run_main(audit=True)
        self.assertEqual(result, 0)
        prompt.assert_not_called()
        self.assertEqual(windows.snapshot(self.home), before)
        self.assertNotIn("secret-token", self.output.getvalue())
        self.assertIn(str(self.layout.claude / "cache"), self.output.getvalue())

    def test_cancel_and_noninteractive_execution_write_nothing(self):
        self.file(".claude/cache/entry")
        before = windows.snapshot(self.home)
        result, _ = self.run_main(["n", "n", "n", "0", "NO"])
        self.assertEqual(result, 1)
        self.assertEqual(windows.snapshot(self.home), before)
        result, prompt = self.run_main(tty=False)
        self.assertEqual(result, 2)
        prompt.assert_not_called()
        self.assertEqual(windows.snapshot(self.home), before)

    def test_discovery_limits_desktop_and_msix_to_known_children(self):
        roots = ["AppData/Roaming/Claude", "AppData/Local/Packages/Claude_test/LocalCache/Roaming/Claude"]
        for root in roots:
            self.file(root + "/Cache/entry")
            self.file(root + "/Local Storage/session")
            self.file(root + "/claude_desktop_config.json", "{}")
            self.file(root + "/Claude Extensions/tool")
        unrelated = self.file("AppData/Local/Packages/Other_test/LocalCache/Roaming/Claude/Cache/keep")
        safe, sessions = windows.discover(self.layout)
        self.assertEqual(set(safe), {self.home / root / "Cache" for root in roots})
        self.assertEqual(set(sessions), {self.home / root / "Local Storage" for root in roots})
        self.assertTrue(unrelated.exists())

    def test_full_run_preserves_unselected_data_and_journals_moves(self):
        protected = {name: self.file(f".claude/{name}/keep") for name in ("projects", "skills", "plugins", "hooks", "mcp-servers")}
        settings = {"env": {"DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": None, "TOKEN": "secret"}, "hooks": {"keep": []}}
        windows.common.write_json(self.layout.settings, settings)
        windows.common.write_json(self.layout.identity, {"userID": "old", "machineID": "old", "oauthAccount": {}, "keep": True})
        internal = self.file(".claude/backups/.claude.json.backup.1", '{"userID":"old","keepBackup":true}')
        credential = self.file(".claude/.credentials.json", '{"token":"secret-token"}')
        self.file(".claude/cache/entry")
        desktop_config = self.file("AppData/Roaming/Claude/claude_desktop_config.json", '{"mcpServers":{}}')
        extension = self.file("AppData/Roaming/Claude/Claude Extensions/keep")
        self.file("AppData/Roaming/Claude/Cache/entry")
        self.file("AppData/Roaming/Claude/Local Storage/session")
        result, _ = self.run_main(["y", "y", "y", "1", "CONFIRM"])
        self.assertEqual(result, 0, self.output.getvalue())
        backup, = (self.home / "ClaudeBackups").iterdir()
        self.assertEqual((backup / "dot-claude/.credentials.json").read_text(), '{"token":"secret-token"}')
        self.assertEqual(windows.common.read_json(backup / "claude.json")["userID"], "old")
        self.assertFalse(credential.exists())
        self.assertFalse((self.layout.claude / "cache").exists())
        self.assertTrue(all(path.read_text() == "keep" for path in protected.values()))
        self.assertEqual(desktop_config.read_text(), '{"mcpServers":{}}')
        self.assertEqual(extension.read_text(), "keep")
        updated = windows.common.read_json(self.layout.settings)
        self.assertEqual(windows.common.telemetry(updated), windows.common.telemetry(settings))
        self.assertEqual(updated["hooks"], settings["hooks"])
        self.assertEqual(updated["env"]["TOKEN"], "secret")
        self.assertEqual(updated["env"]["CLAUDE_CODE_SIMPLE"], "1")
        self.assertEqual(windows.common.read_json(self.layout.identity)["userID"], windows.common.read_json(internal)["userID"])
        moves = windows.common.read_json(backup / "moves.json")
        self.assertEqual(len(moves), 4)
        for move in moves:
            self.assertEqual(move["status"], "moved")
            self.assertTrue(pathlib.Path(move["destination"]).exists())
            self.assertFalse(pathlib.Path(move["source"]).exists())

    def test_desktop_only_install_does_not_require_cli_directory(self):
        self.file("AppData/Roaming/Claude/logs/main.log")
        result, _ = self.run_main(["n", "n", "n", "0", "CONFIRM"])
        self.assertEqual(result, 0, self.output.getvalue())
        backup, = (self.home / "ClaudeBackups").iterdir()
        self.assertEqual(windows.common.read_json(backup / "manifest.json")["sources"]["dot-claude"], {})
        self.assertFalse(self.layout.claude.exists())

    def test_empty_install_is_a_noop(self):
        before = windows.snapshot(self.home)
        result, _ = self.run_main(["n", "n", "n", "0"])
        self.assertEqual(result, 0)
        self.assertEqual(windows.snapshot(self.home), before)

    def test_no_cli_directory_can_enable_simple_mode(self):
        result, _ = self.run_main(["n", "n", "n", "1", "CONFIRM"])
        self.assertEqual(result, 0, self.output.getvalue())
        self.assertEqual(windows.common.read_json(self.layout.settings)["env"]["CLAUDE_CODE_SIMPLE"], "1")

    def test_corrupt_json_stops_before_backup(self):
        self.file(".claude/settings.json", "{broken")
        result, prompt = self.run_main()
        self.assertEqual(result, 2)
        prompt.assert_not_called()
        self.assertFalse((self.home / "ClaudeBackups").exists())

    def test_utf8_bom_settings_preserve_values(self):
        path = self.file(".claude/settings.json", '\ufeff{"env":{"DISABLE_TELEMETRY":"0"}}')
        result, _ = self.run_main(["n", "n", "n", "1", "CONFIRM"])
        self.assertEqual(result, 0, self.output.getvalue())
        self.assertEqual(windows.common.read_json(path)["env"]["DISABLE_TELEMETRY"], "0")

    def test_backup_detects_same_size_corruption_before_any_move(self):
        cache = self.file(".claude/cache/entry", "original")
        real_copytree = shutil.copytree

        def corrupt(source, destination, *args, **kwargs):
            real_copytree(source, destination, *args, **kwargs)
            if pathlib.Path(source) == self.layout.claude:
                (pathlib.Path(destination) / "cache/entry").write_text("modified")

        with mock.patch.object(windows.shutil, "copytree", side_effect=corrupt):
            result, _ = self.run_main(["n", "n", "n", "0", "CONFIRM"])
        self.assertEqual(result, 2)
        self.assertEqual(cache.read_text(), "original")
        self.assertFalse((self.home / "ClaudeCleanupTrash").exists())
        self.assertTrue(list((self.home / "ClaudeBackups").glob("*.partial")))

    def test_protected_unknown_and_git_targets_are_rejected(self):
        for target in [self.layout.claude, self.home, self.layout.settings, self.home / "Documents"]:
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                windows.validate_target(target, self.layout)
        self.file(".claude/cache/nested/.git/config")
        with self.assertRaises(RuntimeError):
            windows.validate_target(self.layout.claude / "cache", self.layout)

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_junction_escape_is_rejected_before_backup_or_move(self):
        outside = self.home / "unrelated"
        outside.mkdir()
        (outside / "keep").write_text("keep")
        self.layout.claude.mkdir()
        junction = self.layout.claude / "cache"
        command = "New-Item -ItemType Junction -Path $env:CLEANUP_TEST_LINK -Target $env:CLEANUP_TEST_TARGET | Out-Null"
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], check=True,
                       env={**os.environ, "CLEANUP_TEST_LINK": str(junction), "CLEANUP_TEST_TARGET": str(outside)}, capture_output=True)
        self.addCleanup(lambda: junction.rmdir() if junction.exists() else None)
        result, _ = self.run_main(["n", "n", "n", "0"])
        self.assertEqual(result, 2)
        self.assertEqual((outside / "keep").read_text(), "keep")
        self.assertFalse((self.home / "ClaudeBackups").exists())

    def test_quarantine_rejects_destination_outside_named_root(self):
        cache = self.file(".claude/cache/entry").parent
        with self.assertRaises(RuntimeError):
            windows.quarantine(cache, self.layout, self.home / "Documents/run", 0, credentials=False)
        self.assertTrue(cache.exists())

    def test_partial_move_failure_reports_backup_and_preserves_journal(self):
        self.file(".claude/cache/entry")
        self.file(".claude/telemetry/entry")
        real_quarantine = windows.quarantine

        def move(target, layout, batch, index, **kwargs):
            if index == 1:
                raise PermissionError("file locked")
            return real_quarantine(target, layout, batch, index, **kwargs)

        with mock.patch.object(windows, "quarantine", side_effect=move):
            result, _ = self.run_main(["n", "n", "n", "0", "CONFIRM"])
        self.assertEqual(result, 2)
        backup, = (self.home / "ClaudeBackups").iterdir()
        self.assertEqual([m["status"] for m in windows.common.read_json(backup / "moves.json")], ["moved", "planned"])
        self.assertIn("可能部分完成", self.output.getvalue())
        self.assertIn(str(backup), self.output.getvalue())

    def test_process_detection_distinguishes_node_and_avoids_command_line_output(self):
        node = {"ProcessId": 101, "ParentProcessId": 0, "Name": "node.exe", "CommandLine": 'node "C:\\npm\\node_modules\\@anthropic-ai\\claude-code\\cli.js" secret-token'}
        self.assertTrue(windows.is_claude_process(node))
        self.assertTrue(windows.is_claude_process({**node, "Name": "Claude.exe", "CommandLine": None}))
        self.assertFalse(windows.is_claude_process({**node, "CommandLine": "node server.js"}))
        result, _ = self.run_main(audit=True, table=[node])
        self.assertEqual(result, 0)
        self.assertNotIn("secret-token", self.output.getvalue())

    def test_claude_ancestor_only_allows_audit(self):
        table = [{"ProcessId": os.getppid(), "ParentProcessId": 0, "Name": "claude.exe"}]
        result, prompt = self.run_main(table=table)
        self.assertEqual(result, 2)
        prompt.assert_not_called()
        self.assertEqual(self.run_main(audit=True, table=table)[0], 0)

    def test_running_claude_skips_safe_cleanup_without_writing(self):
        self.file(".claude/cache/entry")
        before = windows.snapshot(self.home)
        table = [{"ProcessId": 987654, "ParentProcessId": 0, "Name": "claude.exe"}]
        result, prompt = self.run_main(["n", "n", "n", "0"], table=table)
        self.assertEqual(result, 0)
        self.assertEqual(prompt.call_count, 4)
        self.assertEqual(windows.snapshot(self.home), before)

    def test_process_starting_after_confirmation_prevents_backup(self):
        self.file(".claude/cache/entry")
        with mock.patch.object(windows, "require_stopped", side_effect=RuntimeError("Claude started")):
            result, _ = self.run_main(["n", "n", "n", "0", "CONFIRM"])
        self.assertEqual(result, 2)
        self.assertFalse((self.home / "ClaudeBackups").exists())

    def test_process_query_failure_is_not_treated_as_no_processes(self):
        with mock.patch.object(windows.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "powershell")):
            with self.assertRaises(subprocess.CalledProcessError):
                windows.process_table()
        for output in ("null", "{}", "[]", "not json"):
            with self.subTest(output=output), mock.patch.object(windows.subprocess, "run", return_value=mock.Mock(stdout=output)):
                with self.assertRaises((ValueError, RuntimeError)):
                    windows.process_table()

    def test_custom_config_allows_only_default_path_audit(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home / "custom")}):
            self.assertEqual(self.run_main(audit=True)[0], 0)
            result, prompt = self.run_main()
        self.assertEqual(result, 2)
        prompt.assert_not_called()
        self.assertFalse((self.home / "ClaudeBackups").exists())

    def test_unselected_changes_are_detected(self):
        path = self.file(".claude/projects/session", "original")
        backup = windows.create_backup(self.layout)
        path.write_text("modified")
        with self.assertRaises(RuntimeError):
            windows.verify_preserved(self.layout, backup, [])

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell integration test")
    def test_powershell_audit_launcher_from_another_directory(self):
        self.file(".claude/cache/entry")
        before = windows.snapshot(self.layout.claude)
        script = pathlib.Path(__file__).parents[1] / "scripts/claude_cleanup_windows.ps1"
        environment = {**os.environ, "USERPROFILE": str(self.home),
                       "APPDATA": str(self.layout.roaming), "LOCALAPPDATA": str(self.layout.local)}
        for name in ("powershell.exe", "pwsh.exe"):
            shell = shutil.which(name)
            if not shell:
                continue
            with self.subTest(shell=name):
                # Allow this local test script only in the child process; no policy is persisted.
                result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", str(script), "-Audit"],
                                        cwd=self.home, env=environment, capture_output=True,
                                        encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(str(self.layout.claude / "cache"), result.stdout)
                self.assertIn("最终 CONFIRM 前不写盘", result.stdout)
                # PowerShell itself may initialize profile/module caches in AppData.
                self.assertEqual(windows.snapshot(self.layout.claude), before)
                for name in (".claude.json", "ClaudeBackups", "ClaudeCleanupTrash"):
                    self.assertFalse((self.home / name).exists())


if __name__ == "__main__":
    unittest.main()
