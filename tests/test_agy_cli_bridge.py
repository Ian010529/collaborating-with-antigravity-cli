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

    def test_response_budget_is_added_by_default(self) -> None:
        args = argparse.Namespace(
            mode="review-code",
            guardrails=True,
            test_command=[],
            response_budget="standard",
            PROMPT="Review code.",
        )

        prompt = bridge.build_prompt(args, [])

        self.assertIn("Response budget:", prompt)
        self.assertIn("max 10 actionable findings", prompt)

    def test_response_budget_can_be_compact_or_disabled(self) -> None:
        compact_args = argparse.Namespace(
            mode="review-plan",
            guardrails=True,
            test_command=[],
            response_budget="compact",
            PROMPT="Review plan.",
        )
        none_args = argparse.Namespace(
            mode="review-plan",
            guardrails=True,
            test_command=[],
            response_budget="none",
            PROMPT="Review plan.",
        )

        compact_prompt = bridge.build_prompt(compact_args, [])
        none_prompt = bridge.build_prompt(none_args, [])

        self.assertIn("max 5 bullets", compact_prompt)
        self.assertNotIn("Response budget:", none_prompt)

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
        self.assertEqual(bridge.default_model_for_mode("review-plan"), "Claude Sonnet 4.6 (Thinking)")
        self.assertEqual(bridge.default_model_for_mode("review-code"), "Gemini 3.1 Pro (High)")
        self.assertEqual(bridge.default_model_for_mode("ask"), "Gemini 3.1 Pro (Low)")

    def test_default_print_timeout_for_mode(self) -> None:
        self.assertEqual(bridge.default_print_timeout_for_mode("review-code"), "15m0s")
        self.assertEqual(bridge.default_print_timeout_for_mode("ask"), "5m0s")
        self.assertEqual(bridge.default_print_timeout_for_mode("review-plan"), "5m0s")

    def test_review_code_dry_run_includes_git_diff_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_clean_repo(root)
            (root / "src.py").write_text("print('changed')\n", encoding="utf-8")
            stdout = StringIO()
            argv = ["--cd", tmp, "--mode", "review-code", "--PROMPT", "Review code.", "--dry-run"]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertIn("Git diff context", payload["meta"]["prompt"])
            self.assertIn("Full diff", payload["meta"]["prompt"])
            self.assertIn("print('changed')", payload["meta"]["prompt"])
            self.assertTrue(payload["meta"]["git_diff"]["included"])
            self.assertIn("15m0s", payload["meta"]["command"])

    def test_review_code_dry_run_can_disable_git_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_clean_repo(root)
            (root / "src.py").write_text("print('changed')\n", encoding="utf-8")
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--no-include-git-diff",
                "--PROMPT",
                "Review code.",
                "--dry-run",
            ]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertNotIn("Git diff context", payload["meta"]["prompt"])
            self.assertEqual(payload["meta"]["git_diff"], {})

    def test_large_git_diff_is_truncated_to_stat_and_file_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_clean_repo(root)
            (root / "src.py").write_text("print('changed a lot')\n" * 20, encoding="utf-8")
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--max-diff-bytes",
                "10",
                "--PROMPT",
                "Review code.",
                "--dry-run",
            ]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["meta"]["git_diff"]["truncated"])
            self.assertIn("Git Diff Snapshot (truncated)", payload["meta"]["prompt"])
            self.assertIn("- src.py", payload["meta"]["prompt"])
            self.assertIn("exceeding --max-diff-bytes", " ".join(payload["meta"]["warnings"]))

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
            self.assertIn("5m0s", payload["meta"]["command"])

    def test_main_uses_review_plan_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = ["--cd", tmp, "--mode", "review-plan", "--PROMPT", "Review plan.", "--dry-run"]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["meta"]["model"], "Claude Sonnet 4.6 (Thinking)")
            self.assertEqual(payload["meta"]["model_source"], "default")
            self.assertIn("--model", payload["meta"]["command"])
            self.assertIn("Claude Sonnet 4.6 (Thinking)", payload["meta"]["command"])
            self.assertEqual(payload["meta"]["fallback_model"], "Gemini 3.1 Pro (High)")

    def test_main_uses_review_code_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = ["--cd", tmp, "--mode", "review-code", "--PROMPT", "Review code.", "--dry-run"]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["meta"]["model"], "Gemini 3.1 Pro (High)")
            self.assertEqual(payload["meta"]["model_source"], "default")
            self.assertIn("Gemini 3.1 Pro (High)", payload["meta"]["command"])
            self.assertIn("15m0s", payload["meta"]["command"])
            self.assertEqual(payload["meta"]["auth_retries"], 1)
            self.assertEqual(payload["meta"]["use_pty"], bridge.os.name != "nt")
            self.assertEqual(payload["meta"]["auto_browser_auth"], bridge.sys.platform == "darwin")
            self.assertFalse(payload["meta"]["open_auth_url"])

    def test_preflight_failure_skips_review_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--no-include-git-diff",
                "--PROMPT",
                "Review code.",
                "--test-command",
                "pytest tests",
            ]

            with mock.patch.object(bridge, "run_command", return_value=(1, "", "authentication failed or timed out")) as mock_run:
                with mock.patch("subprocess.run") as mock_subprocess_run:
                    with redirect_stdout(stdout):
                        exit_code = bridge.main(argv)

            mock_subprocess_run.assert_not_called()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertFalse(payload["success"])
            self.assertIn("preflight failed", payload["error"])
            self.assertIn("sign in", payload["error"])
            mock_run.assert_called_once()
            self.assertIn("--model", mock_run.call_args.args[0])
            self.assertIn("Gemini 3.1 Pro (High)", mock_run.call_args.args[0])

    def test_fallback_model_retries_non_auth_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--no-preflight",
                "--no-include-git-diff",
                "--model",
                "Claude Sonnet 4.6 (Thinking)",
                "--PROMPT",
                "Review code.",
            ]

            with mock.patch.object(
                bridge,
                "run_command",
                side_effect=[(1, "", "timeout waiting for response"), (0, "ok", "")],
            ) as mock_run:
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["meta"]["model"], "Gemini 3.1 Pro (High)")
            self.assertTrue(payload["meta"]["fallback"]["attempted"])
            self.assertEqual(mock_run.call_count, 2)

    def test_review_plan_falls_back_on_quota_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-plan",
                "--PROMPT",
                "Review plan.",
            ]

            with mock.patch.object(
                bridge,
                "run_command",
                side_effect=[(1, "", "quota exceeded"), (0, "ok", "")],
            ) as mock_run:
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["meta"]["model"], "Gemini 3.1 Pro (High)")
            self.assertEqual(payload["meta"]["fallback"]["from_model"], "Claude Sonnet 4.6 (Thinking)")
            self.assertEqual(payload["meta"]["fallback"]["to_model"], "Gemini 3.1 Pro (High)")
            self.assertEqual(mock_run.call_count, 2)

    def test_fallback_model_does_not_retry_auth_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--no-preflight",
                "--no-include-git-diff",
                "--PROMPT",
                "Review code.",
            ]

            with mock.patch.object(bridge, "run_command", return_value=(1, "", "authentication failed or timed out")) as mock_run:
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertFalse(payload["success"])
            self.assertNotIn("fallback", payload["meta"])
            self.assertIn("sign in", payload["error"])
            self.assertEqual(mock_run.call_count, 1)

    def test_extract_authorization_code_from_callback_url_and_html(self) -> None:
        direct = "https://antigravity.google/callback?state=x&code=4/abcDEFghiJKLmnopQRSTuvwxYZ1234567890"
        escaped = "/callback?state=x&amp;code=4/htmlEscapedCodeValue1234567890"

        self.assertEqual(
            bridge.extract_authorization_code(direct),
            "4/abcDEFghiJKLmnopQRSTuvwxYZ1234567890",
        )
        self.assertEqual(
            bridge.extract_authorization_code(escaped),
            "4/htmlEscapedCodeValue1234567890",
        )

    def test_redact_auth_material_hides_urls_and_codes(self) -> None:
        text = (
            "Open https://accounts.google.com/o/oauth2/auth?client_id=abc&state=secret "
            "then paste 4/superSecretOAuthCodeValue1234567890."
        )

        redacted = bridge.redact_auth_material(text)

        self.assertIn(bridge.REDACTED_AUTH_URL, redacted)
        self.assertIn(bridge.REDACTED_OAUTH_CODE, redacted)
        self.assertNotIn("client_id=abc", redacted)
        self.assertNotIn("superSecretOAuthCodeValue", redacted)

    def test_open_auth_url_uses_single_chrome_open_call(self) -> None:
        mock_res = mock.MagicMock()
        mock_res.returncode = 0

        with mock.patch.object(bridge.sys, "platform", "darwin"):
            with mock.patch.dict(bridge.os.environ, {"AGY_AUTH_BROWSER": "Google Chrome"}):
                with mock.patch.object(bridge.subprocess, "run", return_value=mock_res) as mock_run:
                    opened = bridge.open_auth_url("https://accounts.google.com/o/oauth2/auth?client_id=abc")

        self.assertTrue(opened)
        mock_run.assert_called_once()
        self.assertEqual(
            mock_run.call_args.args[0],
            ["open", "-a", "Google Chrome", "https://accounts.google.com/o/oauth2/auth?client_id=abc"],
        )

    def test_dry_run_can_enable_bridge_oauth_opening(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = [
                "--cd",
                tmp,
                "--mode",
                "review-code",
                "--open-auth-url",
                "--PROMPT",
                "Review code.",
                "--dry-run",
            ]

            with redirect_stdout(stdout):
                exit_code = bridge.main(argv)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["meta"]["open_auth_url"])

    def test_read_clipboard_authorization_code_uses_copied_callback(self) -> None:
        callback = "https://antigravity.google/callback?code=4/copiedCodeValue1234567890"

        with mock.patch.object(bridge.sys, "platform", "darwin"):
            with mock.patch.object(bridge, "run_local_command", return_value=(0, callback, "")):
                code, source = bridge.read_clipboard_authorization_code()

        self.assertEqual(code, "4/copiedCodeValue1234567890")
        self.assertEqual(source, "clipboard")

    def test_browser_authorization_prefers_clipboard_when_enabled(self) -> None:
        callback = "https://antigravity.google/callback?code=4/copiedCodeValue1234567890"

        with mock.patch.object(bridge.sys, "platform", "darwin"):
            with mock.patch.object(bridge, "run_local_command", return_value=(0, callback, "")):
                with mock.patch.object(bridge, "read_browser_tabs_text") as mock_tabs:
                    code, source = bridge.read_browser_authorization_code(use_clipboard=True)

        self.assertEqual(code, "4/copiedCodeValue1234567890")
        self.assertEqual(source, "clipboard")
        mock_tabs.assert_not_called()

    def test_auth_retries_default_to_one_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                bridge,
                "run_command",
                return_value=(1, "", "authentication required"),
            ) as mock_run:
                rc, stdout, stderr, attempts = bridge.run_command_with_auth_retries(
                    ["agy", "--print", "hi"],
                    timeout_s=1,
                    cwd=Path(tmp),
                    auto_browser_auth=True,
                    auth_retries=1,
                )

        self.assertEqual(rc, 1)
        self.assertEqual(stdout, "")
        self.assertIn("authentication", stderr)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(mock_run.call_count, 1)

    def test_unrequested_flash_model_output_fails_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            argv = ["--cd", tmp, "--mode", "review-code", "--no-preflight", "--PROMPT", "Review code."]

            with mock.patch.object(
                bridge,
                "run_command",
                return_value=(0, "Using model Gemini 3.5 Flash (High)\nreview text\n", ""),
            ):
                with redirect_stdout(stdout):
                    exit_code = bridge.main(argv)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["meta"]["model_violation"]["reason"], "unrequested_flash_model")
        self.assertIn("Flash model", payload["error"])

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
