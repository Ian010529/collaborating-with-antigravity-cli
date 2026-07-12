---
name: collaborating-with-antigravity-cli
description: "Use Antigravity CLI (`agy`) as a read-only second model from Codex Desktop or Codex CLI for plan review, code auditing, and test-output analysis via scripts/agy_cli_bridge.py."
---

# Collaborating with Antigravity CLI

Use when Codex needs an external read-only reviewer. Codex remains the controller and writes code; Antigravity reviews plans, diffs, and test output.

## Workflow

1. Codex writes `.codex-antigravity/current/plan.md`.
2. Run `review-plan`; save `current/plan-review.md`.
3. Codex writes `.codex-antigravity/current/agreement.md` and implements.
4. Run `review-code`; save `current/code-review.md`.
5. If validation is needed, pass `--test-command`; the bridge runs the command locally and gives output to `agy` for analysis.
6. Archive or delete `.codex-antigravity` after completion.

`review-code` defaults: preflight `agy` health check, bounded git diff handoff, `15m0s` print timeout, PTY execution on POSIX, and `Gemini 3.1 Pro (High)`.

Keep `.codex-antigravity/` out of git unless sanitized. Keep handoff files concise; do not pass full transcripts back as context.

## Authentication handling

Prefer the bridge's default PTY mode. Do not add `--no-pty` unless PTY output is demonstrably broken; non-PTY execution cannot reliably accept pasted OAuth authorization codes and may not reuse the same auth state as interactive `agy`.

Before long reviews, verify authentication through the bridge, not by running `agy` directly from Codex:

```bash
"$PYTHON" "$BRIDGE" --cd "$REPO" --mode ask \
  --no-preflight --no-include-git-diff --response-budget none \
  --PROMPT "Reply with exactly: ok"
```

Do not run `agy --print-timeout ...` directly from Codex. Direct `agy` calls can open browser login pages outside the bridge, cannot reliably accept copied OAuth codes, and can leak raw OAuth URLs into tool logs.

On macOS, the bridge enables `--auto-browser-auth` by default. It watches OAuth prompts and reads copied/browser-visible authorization codes, but it does not open OAuth URLs by default because `agy` may already open the browser. `--open-auth-url` is rejected by default; only set `AGY_BRIDGE_ALLOW_OPEN_AUTH_URL=1` and pass `--open-auth-url` after confirming agy prints a URL but does not open a browser. Then the bridge opens each OAuth URL once in Chrome by default (`AGY_AUTH_BROWSER="Google Chrome"`). During a PTY run, if `agy` prints an OAuth URL or asks for an authorization code, the bridge will:

1. detect the OAuth URL and, only with `AGY_BRIDGE_ALLOW_OPEN_AUTH_URL=1` plus `--open-auth-url`, open it in Chrome;
2. poll Chrome first, then Edge/Chromium/Safari tab URLs and readable page text for an OAuth `code`;
3. detect codes embedded in callback-page links such as `?code=...`, including HTML-escaped relative URLs;
4. while the OAuth prompt is active, keep polling the clipboard so the page's "Copy to Clipboard" button can be read even when `agy` prints no further output;
5. if browser JavaScript access is disabled, briefly copy visible front-browser page text via clipboard, then restore the previous clipboard;
6. submit the code to `agy` through the PTY without writing it to disk.

Because agy's first-time OAuth prompt may expire quickly, the bridge supports explicit authentication retries, but defaults to a single attempt (`--auth-retries 1`) to avoid repeatedly opening login pages. `--auth-retries > 1` is rejected by default; increase it only after setting `AGY_BRIDGE_ALLOW_AUTH_RETRIES=1`, when the user is actively completing browser login and accepts repeated fresh OAuth URLs:

```bash
AGY_BRIDGE_ALLOW_AUTH_RETRIES=1 \
--auth-retries 5
```

The bridge redacts OAuth URLs and one-time codes in JSON output and transcripts.

If Chrome reports "Executing JavaScript through AppleScript is turned off" and macOS denies Accessibility to `osascript`, the bridge cannot click the page's "Copy to Clipboard" button by itself. In that case, either enable Chrome's View > Developer > Allow JavaScript from Apple Events, grant Accessibility for the controlling terminal/app, or have the user click the page's Copy button while the bridge is waiting; the bridge will read the clipboard in memory and submit the code.

The clipboard fallback only runs while an OAuth prompt is active. Disable it with:

```bash
AGY_BROWSER_AUTH_CLIPBOARD=0
```

Disable all browser-code extraction with:

```bash
--no-auto-browser-auth
```

Do not create local files for OAuth values. The bridge extracts the browser-visible OAuth value in memory and writes it only to the running PTY.

If a non-PTY run reports authentication failure, the bridge automatically retries once with PTY. Treat authentication failures as an incomplete review; never say agy accepted a change unless a review response was actually returned.

## Models

Default model by mode when `--model` is omitted:

- `review-plan`: `Claude Sonnet 4.6 (Thinking)`, with `Gemini 3.1 Pro (High)` fallback for quota/limit errors
- `review-code`: `Gemini 3.1 Pro (High)`
- `ask`: `Gemini 3.1 Pro (Low)`

Use `Gemini 3.5 Flash` only for quick checks. Do not default to Opus unless the task is unusually complex and the user accepts extra latency/cost.

If agy appears to switch to a Flash model when the requested model is not Flash, the bridge treats the run as failed instead of accepting a downgraded review.

## Commands

Resolve the bundled bridge script from this skill directory; do not assume the
target repository has a `scripts/agy_cli_bridge.py` file. Use the active
project interpreter when available (`.venv/bin/python`), otherwise use
`python3`.

```bash
BRIDGE="${CODEX_HOME:-$HOME/.codex}/skills/collaborating-with-antigravity-cli/scripts/agy_cli_bridge.py"
PYTHON=".venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"
```

Plan review:

```bash
"$PYTHON" "$BRIDGE" --cd "$REPO" --mode review-plan \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md --write-transcript \
  --PROMPT "Review Codex's plan for risks, edge cases, and tests."
```

Code review:

```bash
"$PYTHON" "$BRIDGE" --cd "$REPO" --mode review-code \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff. Do not edit files."
```

Useful flags: `--model`, `--fallback-model`, `--file`, `--state-dir`, `--context-file`, `--write-output`, `--write-transcript`, `--max-context-bytes`, `--max-diff-bytes`, `--response-budget standard|compact|none`, `--open-auth-url`, `--no-preflight`, `--no-include-git-diff`, `--stream-status`, `--cleanup keep|archive|delete`.

On POSIX systems the bridge runs `agy` behind a pseudo-terminal by default, so
print-mode reviews reuse the same authentication/session behavior as an
interactive terminal. If this causes terminal-control noise or a platform issue,
pass `--no-pty` only as a last resort; if authentication fails, rerun without
`--no-pty`.

## Rules

- Treat `agy` output as advice, not authority.
- Do not rely on `agy` conversation ids; use handoff files.
- `--test-command` executes locally and may create files; use it intentionally, preferably from a clean worktree.
- If preflight fails, do not run direct `agy` from Codex. Ask the user to complete manual sign-in in a terminal if needed, then verify through the bridge auth-check command above. Do not create local files for OAuth values; rerun the bridge with default PTY and browser extraction enabled.
- If `agy` requests broader context, narrow the next prompt instead of dumping the whole repo.
