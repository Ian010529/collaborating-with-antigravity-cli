from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "scripts" / "agy_cli_bridge.py"
SPEC = importlib.util.spec_from_file_location("agy_cli_bridge", BRIDGE_PATH)
assert SPEC is not None
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


def run_git(root: Path, args: list[str]) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def init_clean_repo(root: Path) -> None:
    run_git(root, ["init"])
    run_git(root, ["config", "user.email", "test@example.com"])
    run_git(root, ["config", "user.name", "Test User"])
    (root / "README.md").write_text("original readme\n", encoding="utf-8")
    (root / "src.py").write_text("print('original')\n", encoding="utf-8")
    run_git(root, ["add", "README.md", "src.py"])
    run_git(root, ["commit", "-m", "initial"])


class AgyCliBridgeTests(unittest.TestCase):
    def test_normalize_focus_files_keeps_only_files_inside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            outside = root.parent / "outside.txt"
            outside.write_text("nope\n", encoding="utf-8")

            files = bridge.normalize_focus_files(root, ["src/app.py", "missing.py", str(outside)])

            self.assertEqual(files, ["src/app.py"])

    def test_review_plan_prompt_is_read_only(self) -> None:
        args = argparse.Namespace(
            mode="review-plan",
            full_access=False,
            yolo=False,
            guardrails=True,
            test_command=[],
            PROMPT="Review this plan.",
        )

        prompt = bridge.build_prompt(args, ["README.md"])

        self.assertIn("independent planning reviewer", prompt)
        self.assertIn("Do not edit files", prompt)
        self.assertIn("@README.md", prompt)

    def test_command_meta_redacts_prompt(self) -> None:
        args = argparse.Namespace(
            agy_bin="agy",
            model="",
            print_timeout="5m0s",
            sandbox=True,
            yolo=False,
            add_dir=[],
            conversation="",
            continue_last=False,
        )

        cmd = bridge.build_command(args, "secret prompt")

        self.assertEqual(bridge.command_for_meta(cmd), ["agy", "--print-timeout", "5m0s", "--sandbox", "--print", "<prompt>"])

    def test_default_model_for_mode(self) -> None:
        self.assertEqual(bridge.default_model_for_mode("review-plan"), "Gemini 3.1 Pro (High)")
        self.assertEqual(bridge.default_model_for_mode("review-code"), "Claude Sonnet 4.6 (Thinking)")
        self.assertEqual(bridge.default_model_for_mode("ask"), "Gemini 3.1 Pro (Low)")

    def test_main_wraps_agy_stdout_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = ["--cd", tmp, "--PROMPT", "Say hi."]

            with mock.patch.object(bridge, "run_command", return_value=(0, "hi\n", "")):
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["agent_messages"], "hi")
            self.assertEqual(payload["meta"]["cli"], "agy")
            self.assertEqual(payload["meta"]["model"], "Gemini 3.1 Pro (Low)")
            self.assertEqual(payload["meta"]["model_source"], "default")

    def test_main_uses_review_plan_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = ["--cd", tmp, "--mode", "review-plan", "--PROMPT", "Review plan.", "--dry-run"]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["meta"]["model"], "Gemini 3.1 Pro (High)")
            self.assertEqual(payload["meta"]["model_source"], "default")
            self.assertIn("--model", payload["meta"]["command"])
            self.assertIn("Gemini 3.1 Pro (High)", payload["meta"]["command"])

    def test_main_uses_review_code_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = ["--cd", tmp, "--mode", "review-code", "--PROMPT", "Review code.", "--dry-run"]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["meta"]["model"], "Claude Sonnet 4.6 (Thinking)")
            self.assertEqual(payload["meta"]["model_source"], "default")
            self.assertIn("Claude Sonnet 4.6 (Thinking)", payload["meta"]["command"])

    def test_explicit_model_overrides_mode_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--model",
                "Gemini 3.5 Flash (High)",
                "--PROMPT",
                "Quick check.",
                "--dry-run",
            ]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["meta"]["model"], "Gemini 3.5 Flash (High)")
            self.assertEqual(payload["meta"]["model_source"], "explicit")
            self.assertIn("Gemini 3.5 Flash (High)", payload["meta"]["command"])

    def test_context_file_is_included_in_dry_run_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plan.md").write_text("Agreed plan goes here.\n", encoding="utf-8")
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--PROMPT",
                "Review the context.",
                "--context-file",
                "plan.md",
                "--dry-run",
            ]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertIn("Persisted handoff context", payload["meta"]["prompt"])
            self.assertIn("Agreed plan goes here.", payload["meta"]["prompt"])
            self.assertEqual(payload["meta"]["context_files"][0]["path"], "plan.md")

    def test_context_file_size_limit_blocks_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "large.md").write_text("abcdef", encoding="utf-8")
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--PROMPT",
                "Review the context.",
                "--context-file",
                "large.md",
                "--max-context-bytes",
                "3",
            ]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertFalse(payload["success"])
            self.assertIn("exceeding --max-context-bytes", payload["error"])

    def test_write_output_transcript_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--PROMPT",
                "Say hi.",
                "--run-id",
                "run-1",
                "--write-output",
                "current/result.md",
                "--write-transcript",
            ]

            with mock.patch.object(bridge, "run_command", return_value=(0, "hi\n", "")):
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            state_dir = root / ".codex-antigravity"
            self.assertEqual(exit_code, 0)
            self.assertEqual((state_dir / "current" / "result.md").read_text(encoding="utf-8"), "hi")
            transcript = state_dir / "transcripts" / "run-1-ask.json"
            self.assertTrue(transcript.is_file())
            state = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["latest_run_id"], "run-1")
            self.assertEqual(state["latest_output"], ".codex-antigravity/current/result.md")
            self.assertEqual(payload["meta"]["transcript_path"], ".codex-antigravity/transcripts/run-1-ask.json")

    def test_cleanup_archive_moves_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / ".codex-antigravity" / "current"
            current.mkdir(parents=True)
            (current / "agreement.md").write_text("done\n", encoding="utf-8")
            stdout = StringIO()
            argv = ["--cd", tmp, "--PROMPT", "Archive.", "--run-id", "archive-run", "--cleanup", "archive"]

            with mock.patch.object(bridge, "run_command", return_value=(0, "archived\n", "")):
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertFalse(current.exists())
            archive_rel = payload["meta"]["cleanup"]["archived_current"]
            self.assertTrue((root / ".codex-antigravity" / archive_rel / "agreement.md").is_file())

    def test_cleanup_delete_removes_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".codex-antigravity"
            state_dir.mkdir()
            (state_dir / "state.json").write_text("{}", encoding="utf-8")
            stdout = StringIO()
            argv = ["--cd", tmp, "--PROMPT", "Delete.", "--cleanup", "delete"]

            with mock.patch.object(bridge, "run_command", return_value=(0, "deleted\n", "")):
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            self.assertEqual(exit_code, 0)
            self.assertFalse(state_dir.exists())

    @mock.patch("subprocess.run")
    def test_test_command_runs_and_populates_prompt(self, mock_run: mock.MagicMock) -> None:
        mock_res = mock.MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "all tests passed"
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        with tempfile.TemporaryDirectory() as tmp:
            output = bridge.run_test_commands(["pytest tests"], Path(tmp))
            self.assertIn("### Test Command: `pytest tests` (PASSED)", output)
            self.assertIn("all tests passed", output)

    @mock.patch("subprocess.run")
    def test_main_runs_test_command_when_not_dry_run(self, mock_run: mock.MagicMock) -> None:
        mock_res = mock.MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "all tests passed"
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--PROMPT",
                "Review code.",
                "--test-command",
                "pytest tests",
            ]
            with mock.patch.object(bridge, "run_command", return_value=(0, "ok", "")):
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)
            
            self.assertEqual(exit_code, 0)
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(args[0], "pytest tests")


if __name__ == "__main__":
    unittest.main()
