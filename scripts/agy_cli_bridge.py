"""
Antigravity CLI bridge for Codex skills.

Runs `agy --print` in headless mode and wraps the plain-text response in a
stable JSON envelope for Codex Desktop / Codex CLI collaboration workflows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_PRINT_TIMEOUT = "5m0s"
DEFAULT_REVIEW_CODE_PRINT_TIMEOUT = "15m0s"
DEFAULT_PREFLIGHT_PRINT_TIMEOUT = "30s"
DEFAULT_MAX_FOCUS_BYTES = 200_000
DEFAULT_STATE_DIR = ".codex-antigravity"
DEFAULT_MAX_CONTEXT_BYTES = 50_000
DEFAULT_MAX_DIFF_BYTES = 120_000
DEFAULT_REVIEW_PLAN_MODEL = "Gemini 3.1 Pro (High)"
DEFAULT_REVIEW_CODE_MODEL = "Claude Sonnet 4.6 (Thinking)"
DEFAULT_REVIEW_CODE_FALLBACK_MODEL = "Gemini 3.1 Pro (High)"
DEFAULT_QUICK_MODEL = "Gemini 3.1 Pro (Low)"
MODE_DEFAULT_MODELS = {
    "review-plan": DEFAULT_REVIEW_PLAN_MODEL,
    "review-code": DEFAULT_REVIEW_CODE_MODEL,
    "ask": DEFAULT_QUICK_MODEL,
}

RESPONSE_BUDGETS = {
    "standard": {
        "review-plan": (
            "Response budget: use only Verdict, Blocking Issues, Important Suggestions, and Tests. "
            "Max 8 bullets or 600 words. Omit praise and context recap."
        ),
        "review-code": (
            "Response budget: findings first, max 10 actionable findings or 700 words. "
            "Do not paste large code/diff excerpts. If no blocking issues, say so in one sentence."
        ),
        "ask": "Response budget: answer in 400 words or fewer. Prefer concise bullets.",
    },
    "compact": {
        "review-plan": "Response budget: max 5 bullets or 300 words. Include only blockers, key risks, and test gaps.",
        "review-code": "Response budget: max 5 findings or 350 words. Include only actionable bugs, regressions, and test gaps.",
        "ask": "Response budget: answer in 150 words or fewer.",
    },
}

MODE_INSTRUCTIONS = {
    "review-plan": (
        "Role: independent planning reviewer.\n"
        "Review Codex's plan before implementation. Do not edit files. Do not run modifying commands.\n"
        "Return: verdict (accept/revise), blocking issues, edge cases, test suggestions, and a concise revised plan if needed."
    ),
    "review-code": (
        "Role: code reviewer.\n"
        "Review the current diff or requested files for bugs, regressions, missing tests, and maintainability risks.\n"
        "Do not edit files. Return findings first, ordered by severity."
    ),
    "ask": (
        "Role: second-opinion assistant.\n"
        "Answer the user's request directly. Keep assumptions explicit and avoid unrelated changes."
    ),
}

PATH_RE = re.compile(
    r"""
    (?:
        (?:\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+
        |
        [A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,12}
    )
    """,
    re.VERBOSE,
)


def configure_stdio() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def resolve_executable(name: str, env: dict[str, str]) -> str:
    if os.path.isabs(name) or os.sep in name or (os.altsep and os.altsep in name):
        return name
    path_key = next((key for key in env if key.upper() == "PATH"), "PATH")
    return shutil.which(name, path=env.get(path_key)) or name


def run_command(
    cmd: list[str],
    timeout_s: float | None,
    cwd: Path,
    *,
    stream_status: bool = False,
    stream_status_interval_s: float = 30.0,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    resolved_cmd = cmd.copy()
    resolved_cmd[0] = resolve_executable(resolved_cmd[0], env)
    process = subprocess.Popen(
        resolved_cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(cwd),
    )
    if not stream_status:
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            return 124, stdout, (stderr + "\n[timeout] agy process timed out.").strip()
        return process.returncode, stdout, stderr

    started = time.monotonic()
    interval = max(1.0, stream_status_interval_s)
    while True:
        elapsed = time.monotonic() - started
        if timeout_s is not None and elapsed >= timeout_s:
            process.kill()
            stdout, stderr = process.communicate()
            return 124, stdout, (stderr + "\n[timeout] agy process timed out.").strip()
        wait_s = interval
        if timeout_s is not None:
            wait_s = min(wait_s, max(0.1, timeout_s - elapsed))
        try:
            stdout, stderr = process.communicate(timeout=wait_s)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            print(f"[agy-bridge] still running after {int(elapsed)}s...", file=sys.stderr, flush=True)
    return process.returncode, stdout, stderr


def run_local_command(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
    )
    return res.returncode, res.stdout, res.stderr


def is_authentication_error(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return any(
        marker in text
        for marker in (
            "authentication failed",
            "please sign in",
            "not signed in",
            "sign in to",
            "login required",
        )
    )


def is_timeout_error(rc: int, stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return rc == 124 or "timed out" in text or "timeout waiting for response" in text


def normalize_focus_files(cd_path: Path, files: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    root = cd_path.resolve()
    for raw in files:
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = (root / path).resolve()
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        rel_str = str(rel)
        if rel_str not in seen:
            normalized.append(rel_str)
            seen.add(rel_str)
    return normalized


def extract_focus_files_from_prompt(prompt: str, cd_path: Path, max_files: int) -> list[str]:
    candidates: list[str] = []
    for match in PATH_RE.finditer(prompt):
        token = match.group(0)
        if "://" in token:
            continue
        candidates.append(token)
    return normalize_focus_files(cd_path, candidates)[: max(0, max_files)]


def estimate_focus_bytes(cd_path: Path, focus_files: list[str]) -> int:
    total = 0
    for rel in focus_files:
        try:
            total += (cd_path / rel).stat().st_size
        except OSError:
            continue
    return total


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def filesystem_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_run_id(raw: str | None, mode: str) -> str:
    value = raw.strip() if raw else f"{filesystem_timestamp()}-{mode}"
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned or f"{filesystem_timestamp()}-{mode}"


def path_for_display(path: Path, cd_path: Path) -> str:
    try:
        return str(path.resolve().relative_to(cd_path.resolve()))
    except ValueError:
        return str(path)


def resolve_input_file(raw: str, cd_path: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cd_path / path
    return path.resolve()


def resolve_state_dir(raw: str, cd_path: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cd_path / path
    return path.resolve()


def resolve_state_output_path(raw: str, cd_path: Path, state_dir: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    state_name = state_dir.name
    if path.parts and path.parts[0] == state_name:
        return (cd_path / path).resolve()
    return (state_dir / path).resolve()


def load_context_files(
    raw_paths: list[str],
    cd_path: Path,
    max_context_bytes: int,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    contexts: list[dict[str, Any]] = []
    blocks: list[str] = []
    warnings: list[str] = []
    total_bytes = 0

    for raw in raw_paths:
        path = resolve_input_file(raw, cd_path)
        if not path.is_file():
            raise FileNotFoundError(f"context file does not exist or is not a file: {raw}")
        data = path.read_bytes()
        total_bytes += len(data)
        if total_bytes > max_context_bytes:
            raise ValueError(
                f"context files total {total_bytes:,} bytes, exceeding --max-context-bytes {max_context_bytes:,}"
            )
        text = data.decode("utf-8", errors="replace")
        display = path_for_display(path, cd_path)
        contexts.append({"path": display, "bytes": len(data)})
        blocks.append(f"### {display}\n\n{text.strip()}")

    if contexts and total_bytes > max_context_bytes * 0.8:
        warnings.append(f"Context files total {total_bytes:,} bytes; this is close to the configured limit.")
    return contexts, "\n\n".join(blocks).strip(), warnings


def load_git_diff(cd_path: Path, max_diff_bytes: int) -> tuple[dict[str, Any], str, list[str]]:
    warnings: list[str] = []
    meta: dict[str, Any] = {
        "included": False,
        "truncated": False,
        "diff_bytes": 0,
        "stat_bytes": 0,
        "files": [],
    }

    stat_rc, stat, stat_err = run_local_command(["git", "diff", "--no-ext-diff", "--stat"], cd_path)
    names_rc, names, names_err = run_local_command(["git", "diff", "--no-ext-diff", "--name-only"], cd_path)
    diff_rc, diff, diff_err = run_local_command(["git", "diff", "--no-ext-diff"], cd_path)
    if stat_rc != 0 or names_rc != 0 or diff_rc != 0:
        errors = "\n".join(part.strip() for part in (stat_err, names_err, diff_err) if part.strip())
        warnings.append(f"Unable to load git diff: {errors or 'git diff failed'}")
        return meta, "", warnings

    files = [line.strip() for line in names.splitlines() if line.strip()]
    diff_bytes = len(diff.encode("utf-8", errors="replace"))
    stat_bytes = len(stat.encode("utf-8", errors="replace"))
    meta.update({"diff_bytes": diff_bytes, "stat_bytes": stat_bytes, "files": files})

    if not stat.strip() and not diff.strip():
        return meta, "### Git Diff Snapshot\n\nNo tracked git diff is currently present.", warnings

    if diff_bytes > max_diff_bytes:
        meta["truncated"] = True
        warnings.append(
            f"Git diff is {diff_bytes:,} bytes, exceeding --max-diff-bytes {max_diff_bytes:,}; "
            "included only diff stat and file list."
        )
        file_list = "\n".join(f"- {path}" for path in files) or "- (no files reported)"
        text = (
            "### Git Diff Snapshot (truncated)\n\n"
            f"Diff bytes: {diff_bytes:,}; max allowed: {max_diff_bytes:,}.\n\n"
            "Diff stat:\n```text\n"
            f"{stat.strip()}\n"
            "```\n\n"
            "Changed files:\n"
            f"{file_list}"
        )
        return meta, text, warnings

    meta["included"] = True
    text = (
        "### Git Diff Snapshot\n\n"
        "Diff stat:\n```text\n"
        f"{stat.strip()}\n"
        "```\n\n"
        "Full diff:\n```diff\n"
        f"{diff.strip()}\n"
        "```"
    )
    return meta, text, warnings


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_state(state_dir: Path) -> dict[str, Any]:
    state_file = state_dir / "state.json"
    if not state_file.is_file():
        return {"version": 1, "runs": []}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "runs": []}
    if not isinstance(data, dict):
        return {"version": 1, "runs": []}
    if not isinstance(data.get("runs"), list):
        data["runs"] = []
    data.setdefault("version", 1)
    return data


def write_state(state_dir: Path, run_record: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_dir)
    runs = state.get("runs")
    if not isinstance(runs, list):
        runs = []
    runs.append(run_record)
    state["runs"] = runs[-100:]
    state["phase"] = run_record.get("mode")
    state["updated_at"] = run_record.get("timestamp")
    state["latest_run_id"] = run_record.get("run_id")
    if run_record.get("output"):
        state["latest_output"] = run_record["output"]
    if run_record.get("transcript"):
        state["latest_transcript"] = run_record["transcript"]
    (state_dir / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def archive_current_state(state_dir: Path, run_id: str) -> str | None:
    current_dir = state_dir / "current"
    if not current_dir.exists():
        return None
    archive_dir = state_dir / "archive" / f"{filesystem_timestamp()}-{run_id}"
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    shutil.move(str(current_dir), str(archive_dir))
    return str(archive_dir.relative_to(state_dir))


def run_test_commands(commands: list[str], cwd: Path) -> str:
    blocks = []
    for cmd in commands:
        if not cmd:
            continue
        print(f"[agy-bridge] running test command: {cmd}", file=sys.stderr, flush=True)
        res = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
        )
        status = "PASSED" if res.returncode == 0 else "FAILED"
        block = (
            f"### Test Command: `{cmd}` ({status})\n"
            f"Exit Code: {res.returncode}\n\n"
            f"Stdout:\n```\n{res.stdout.strip()}\n```\n"
        )
        if res.stderr.strip():
            block += f"\nStderr:\n```\n{res.stderr.strip()}\n```\n"
        blocks.append(block)
    return "\n\n".join(blocks).strip()


def response_budget_instruction(mode: str, budget: str) -> str:
    if budget == "none":
        return ""
    return RESPONSE_BUDGETS.get(budget, RESPONSE_BUDGETS["standard"]).get(mode, "")


def build_prompt(
    args: argparse.Namespace,
    focus_files: list[str],
    context_text: str = "",
    test_output: str = "",
    git_diff_text: str = "",
) -> str:
    access_line = "Access: read-only. Do not edit files; propose patches or findings instead."
    budget_line = response_budget_instruction(args.mode, getattr(args, "response_budget", "standard"))
    budget_lines = f"\n{budget_line}" if budget_line else ""

    focus_lines = ""
    if focus_files:
        refs = "\n".join(f"- @{path}" for path in focus_files)
        focus_lines = f"\nFocus files:\n{refs}\n"

    test_lines = ""
    if test_output:
        test_lines = f"\nActual test execution results:\n{test_output}\n"
    elif args.test_command:
        tests = "\n".join(f"- {command}" for command in args.test_command)
        test_lines = f"\nExpected validation commands (not run in this turn):\n{tests}\n"

    context_lines = ""
    if context_text:
        context_lines = f"\nPersisted handoff context:\n{context_text}\n"

    diff_lines = ""
    if git_diff_text:
        diff_lines = f"\nGit diff context:\n{git_diff_text}\n"

    guardrails = ""
    if args.guardrails:
        guardrails = (
            "\nScope guardrails:\n"
            "- Stay within the requested workflow stage.\n"
            "- If more context is required, say exactly what is missing instead of broadening scope silently.\n"
            "- Keep the response concise enough for Codex to act on.\n"
        )

    return (
        f"{MODE_INSTRUCTIONS[args.mode]}\n\n"
        f"{access_line}"
        f"{budget_lines}"
        f"{focus_lines}"
        f"{test_lines}"
        f"{diff_lines}"
        f"{context_lines}"
        f"{guardrails}\n"
        f"User task:\n{args.PROMPT}"
    ).strip()


def build_command(args: argparse.Namespace, prompt: str) -> list[str]:
    cmd = [args.agy_bin]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.print_timeout:
        cmd.extend(["--print-timeout", args.print_timeout])
    if args.sandbox:
        cmd.append("--sandbox")
    for add_dir in args.add_dir:
        cmd.extend(["--add-dir", add_dir])
    if args.conversation:
        cmd.extend(["--conversation", args.conversation])
    elif args.continue_last:
        cmd.append("--continue")
    cmd.extend(["--print", prompt])
    return cmd


def build_preflight_command(args: argparse.Namespace) -> list[str]:
    return [
        args.agy_bin,
        "--print-timeout",
        args.preflight_timeout,
        "--print",
        "Reply with exactly: ok",
    ]


def command_for_meta(cmd: list[str]) -> list[str]:
    if "--print" not in cmd:
        return cmd
    index = cmd.index("--print")
    return [*cmd[: index + 1], "<prompt>"]


def default_model_for_mode(mode: str) -> str:
    return MODE_DEFAULT_MODELS.get(mode, DEFAULT_QUICK_MODEL)


def default_print_timeout_for_mode(mode: str) -> str:
    if mode == "review-code":
        return DEFAULT_REVIEW_CODE_PRINT_TIMEOUT
    return DEFAULT_PRINT_TIMEOUT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Antigravity CLI bridge (Read-Only)")
    parser.add_argument("--PROMPT", required=True, help="Instruction to send to Antigravity CLI.")
    parser.add_argument("--cd", required=True, help="Working directory for agy.")
    parser.add_argument("--mode", choices=sorted(MODE_INSTRUCTIONS), default="ask", help="Workflow stage.")
    parser.add_argument("--agy-bin", default="agy", help="Antigravity CLI executable. Defaults to `agy`.")
    parser.add_argument(
        "--model",
        default="",
        help=(
            "Optional agy model name. Defaults by mode: review-plan uses Gemini 3.1 Pro (High), "
            "review-code uses Claude Sonnet 4.6 (Thinking), ask uses Gemini 3.1 Pro (Low)."
        ),
    )
    parser.add_argument("--print-timeout", default="", help="agy print-mode timeout, e.g. 5m0s. Defaults by mode.")
    parser.add_argument("--timeout-s", type=float, default=1800.0, help="Outer process timeout in seconds.")
    parser.add_argument("--fallback-model", default="", help="Optional model to retry once after a non-authentication timeout.")
    parser.add_argument("--file", dest="files", action="append", default=[], help="Focus file, repeatable.")
    parser.add_argument("--add-dir", action="append", default=[], help="Extra workspace directory for agy, repeatable.")
    parser.add_argument("--test-command", action="append", default=[], help="Validation command to mention to agy.")
    parser.add_argument("--conversation", default="", help="Resume a specific agy conversation id.")
    parser.add_argument("--continue", dest="continue_last", action="store_true", help="Continue the most recent agy conversation.")
    parser.add_argument("--sandbox", action="store_true", help="Pass --sandbox to agy.")
    parser.add_argument("--stream-status", dest="stream_status", action="store_true", default=True, help="Print heartbeat status to stderr while agy is running.")
    parser.add_argument("--no-stream-status", dest="stream_status", action="store_false", help="Disable heartbeat status output.")
    parser.add_argument("--stream-status-interval-s", type=float, default=30.0, help="Heartbeat interval in seconds.")
    parser.add_argument("--guardrails", dest="guardrails", action="store_true", default=True, help="Enable scope guardrails.")
    parser.add_argument("--no-guardrails", dest="guardrails", action="store_false", help="Disable scope guardrails.")
    parser.add_argument(
        "--response-budget",
        choices=["standard", "compact", "none"],
        default="standard",
        help="Constrain agy's response length to reduce host-agent context. Use none for unusually broad audits.",
    )
    parser.add_argument("--auto-extract-files", action="store_true", default=True, help="Auto-detect file paths from PROMPT.")
    parser.add_argument("--no-auto-extract-files", dest="auto_extract_files", action="store_false", help="Disable auto file extraction.")
    parser.add_argument("--max-files", type=int, default=5, help="Cap auto-extracted focus files.")
    parser.add_argument("--max-focus-bytes", type=int, default=DEFAULT_MAX_FOCUS_BYTES, help="Warning threshold for focus file bytes.")
    parser.add_argument("--include-git-diff", dest="include_git_diff", action="store_true", default=None, help="Include a bounded git diff snapshot in review-code prompts.")
    parser.add_argument("--no-include-git-diff", dest="include_git_diff", action="store_false", help="Do not include git diff context.")
    parser.add_argument("--max-diff-bytes", type=int, default=DEFAULT_MAX_DIFF_BYTES, help="Maximum full git diff bytes to include in review-code prompts.")
    parser.add_argument("--preflight", dest="preflight", action="store_true", default=None, help="Run a short agy health check before review-code.")
    parser.add_argument("--no-preflight", dest="preflight", action="store_false", help="Skip agy health check.")
    parser.add_argument("--preflight-timeout", default=DEFAULT_PREFLIGHT_PRINT_TIMEOUT, help="agy print timeout for the preflight check.")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR, help="State directory for handoff files. Defaults to .codex-antigravity.")
    parser.add_argument("--context-file", action="append", default=[], help="Markdown/text context file to include in the prompt, repeatable.")
    parser.add_argument("--write-output", default="", help="Write agy response to this file. Relative paths are under --state-dir.")
    parser.add_argument("--write-transcript", action="store_true", help="Write the full bridge JSON result to --state-dir/transcripts/.")
    parser.add_argument("--max-context-bytes", type=int, default=DEFAULT_MAX_CONTEXT_BYTES, help="Maximum total bytes loaded from --context-file.")
    parser.add_argument("--cleanup", choices=["keep", "archive", "delete"], default="keep", help="Cleanup state after the run.")
    parser.add_argument("--run-id", default="", help="Optional stable id for output/transcript naming.")
    parser.add_argument("--dry-run", action="store_true", help="Build prompt/command and return JSON without running agy.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    cd_path = Path(args.cd).expanduser()
    if not cd_path.is_dir():
        result = {"success": False, "error": f"`--cd` must be an existing directory. Got: {args.cd}"}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2
    state_dir = resolve_state_dir(args.state_dir, cd_path)
    run_id = safe_run_id(args.run_id, args.mode)
    model_source = "explicit" if args.model.strip() else "default"
    args.model = args.model.strip() or default_model_for_mode(args.mode)
    args.print_timeout = args.print_timeout.strip() or default_print_timeout_for_mode(args.mode)
    args.fallback_model = args.fallback_model.strip()
    if args.mode == "review-code" and not args.fallback_model:
        args.fallback_model = DEFAULT_REVIEW_CODE_FALLBACK_MODEL
    if args.include_git_diff is None:
        args.include_git_diff = args.mode == "review-code"
    if args.preflight is None:
        args.preflight = args.mode == "review-code"

    explicit_focus_files = normalize_focus_files(cd_path, args.files)
    auto_focus_files: list[str] = []
    if args.guardrails and args.auto_extract_files and not explicit_focus_files:
        auto_focus_files = extract_focus_files_from_prompt(args.PROMPT, cd_path, args.max_files)
    focus_files = [*explicit_focus_files, *[path for path in auto_focus_files if path not in explicit_focus_files]]

    warnings: list[str] = []
    focus_bytes = estimate_focus_bytes(cd_path, focus_files)
    if args.guardrails and focus_bytes > args.max_focus_bytes:
        warnings.append(f"Focus files total {focus_bytes:,} bytes; consider splitting the task.")

    try:
        context_files, context_text, context_warnings = load_context_files(args.context_file, cd_path, args.max_context_bytes)
    except (FileNotFoundError, ValueError) as error:
        result = {
            "success": False,
            "error": str(error),
            "meta": {
                "cli": "agy",
                "mode": args.mode,
                "run_id": run_id,
                "state_dir": path_for_display(state_dir, cd_path),
                "warnings": warnings,
            },
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 2
    warnings.extend(context_warnings)

    git_diff_meta: dict[str, Any] = {}
    git_diff_text = ""
    if args.include_git_diff:
        git_diff_meta, git_diff_text, git_diff_warnings = load_git_diff(cd_path, args.max_diff_bytes)
        warnings.extend(git_diff_warnings)

    meta: dict[str, Any] = {
        "cli": "agy",
        "mode": args.mode,
        "run_id": run_id,
        "model": args.model,
        "model_source": model_source,
        "sandbox": args.sandbox,
        "state_dir": path_for_display(state_dir, cd_path),
        "focus_files": focus_files,
        "explicit_focus_files": explicit_focus_files,
        "auto_focus_files": auto_focus_files,
        "focus_bytes": focus_bytes,
        "context_files": context_files,
        "git_diff": git_diff_meta,
        "preflight": args.preflight,
        "fallback_model": args.fallback_model,
        "warnings": warnings,
    }

    if args.dry_run:
        prompt = build_prompt(args, focus_files, context_text, "", git_diff_text)
        cmd = build_command(args, prompt)
        meta["command"] = command_for_meta(cmd)
        result = {"success": True, "agent_messages": "", "meta": {**meta, "prompt": prompt, "dry_run": True}}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.preflight:
        preflight_cmd = build_preflight_command(args)
        preflight_meta: dict[str, Any] = {"command": command_for_meta(preflight_cmd)}
        try:
            preflight_rc, preflight_stdout, preflight_stderr = run_command(
                preflight_cmd,
                timeout_s=90.0,
                cwd=cd_path,
                stream_status=False,
            )
        except FileNotFoundError as error:
            result = {
                "success": False,
                "error": f"Failed to execute Antigravity CLI. Is `agy` installed and on PATH?\n\n{error}",
                "meta": {**meta, "preflight": preflight_meta},
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 127
        preflight_meta.update(
            {
                "exit_code": preflight_rc,
                "stdout": preflight_stdout.strip(),
                "stderr": preflight_stderr.strip(),
            }
        )
        meta["preflight"] = preflight_meta
        if preflight_rc != 0 or preflight_stdout.strip().lower() != "ok":
            auth_hint = ""
            if is_authentication_error(preflight_stdout, preflight_stderr):
                auth_hint = (
                    "\n\nAntigravity CLI authentication appears unhealthy. Run `agy` in a terminal to sign in, "
                    "then verify with `agy --print-timeout 30s --print \"Reply with exactly: ok\"`."
                )
            result = {
                "success": False,
                "error": f"Antigravity CLI preflight failed; skipped the longer review-code request.{auth_hint}",
                "meta": meta,
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 1

    test_output = ""
    if args.test_command:
        test_output = run_test_commands(args.test_command, cd_path)

    prompt = build_prompt(args, focus_files, context_text, test_output, git_diff_text)
    cmd = build_command(args, prompt)
    meta["command"] = command_for_meta(cmd)

    try:
        rc, stdout, stderr = run_command(
            cmd,
            timeout_s=args.timeout_s,
            cwd=cd_path,
            stream_status=args.stream_status,
            stream_status_interval_s=args.stream_status_interval_s,
        )
    except FileNotFoundError as error:
        result = {
            "success": False,
            "error": f"Failed to execute Antigravity CLI. Is `agy` installed and on PATH?\n\n{error}",
            "meta": meta,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 127

    if (
        rc != 0
        and args.fallback_model
        and args.fallback_model != args.model
        and not is_authentication_error(stdout, stderr)
        and is_timeout_error(rc, stdout, stderr)
    ):
        primary_model = args.model
        meta["fallback"] = {
            "attempted": True,
            "from_model": primary_model,
            "to_model": args.fallback_model,
            "primary": {
                "exit_code": rc,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            },
        }
        args.model = args.fallback_model
        fallback_cmd = build_command(args, prompt)
        meta["fallback"]["command"] = command_for_meta(fallback_cmd)
        rc, stdout, stderr = run_command(
            fallback_cmd,
            timeout_s=args.timeout_s,
            cwd=cd_path,
            stream_status=args.stream_status,
            stream_status_interval_s=args.stream_status_interval_s,
        )
        meta["model"] = args.model

    agent_messages = stdout.strip()
    meta["exit_code"] = rc
    if stderr.strip():
        meta["stderr"] = stderr.strip()

    success = bool(rc == 0 and agent_messages)
    error_bits = []
    if not success:
        if rc == 124:
            error_bits.append("Antigravity CLI process timed out.")
        elif rc != 0:
            error_bits.append(f"Antigravity CLI exited with code {rc}.")
        if is_authentication_error(stdout, stderr):
            error_bits.append(
                "Antigravity CLI authentication appears unhealthy. Run `agy` in a terminal to sign in, "
                "then verify with `agy --print-timeout 30s --print \"Reply with exactly: ok\"`."
            )
        if stderr.strip():
            error_bits.append(f"[stderr]\n{stderr.strip()}")
        if stdout.strip():
            error_bits.append(f"[stdout]\n{stdout.strip()}")

    result: dict[str, Any] = {"success": success, "agent_messages": agent_messages, "meta": meta}
    if not success:
        result["error"] = "\n\n".join(error_bits).strip() or "Antigravity CLI returned no output."

    output_path: Path | None = None
    if args.write_output:
        output_path = resolve_state_output_path(args.write_output, cd_path, state_dir)
        write_text_file(output_path, agent_messages)
        meta["output_path"] = path_for_display(output_path, cd_path)

    transcript_path: Path | None = None
    if args.write_transcript:
        transcript_path = state_dir / "transcripts" / f"{run_id}-{args.mode}.json"
        meta["transcript_path"] = path_for_display(transcript_path, cd_path)
        write_text_file(transcript_path, json.dumps(result, indent=2, ensure_ascii=False))

    if args.write_output or args.write_transcript:
        run_record = {
            "run_id": run_id,
            "timestamp": utc_now(),
            "mode": args.mode,
            "success": success,
            "output": path_for_display(output_path, cd_path) if output_path else None,
            "transcript": path_for_display(transcript_path, cd_path) if transcript_path else None,
            "context_files": context_files,
            "focus_files": focus_files,
        }
        write_state(state_dir, run_record)

    if args.cleanup == "archive":
        archived = archive_current_state(state_dir, run_id)
        meta["cleanup"] = {"mode": "archive", "archived_current": archived}
    elif args.cleanup == "delete":
        if state_dir.exists():
            shutil.rmtree(state_dir)
        meta["cleanup"] = {"mode": "delete", "deleted": path_for_display(state_dir, cd_path)}

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
