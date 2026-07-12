# collaborating-with-antigravity-cli

[中文](README.md) | English

A skill for **Codex Desktop App / Codex CLI**. Codex stays the controller and code author, while **Antigravity CLI** (`agy`) acts as a read-only reviewer for plans, code diffs, and test-output analysis.

Migrated from [`collaborating-with-gemini-cli`](https://github.com/ZhenHuangLab/collaborating-with-gemini-cli).

## Workflow

1. Codex writes a plan to `.codex-antigravity/current/plan.md`.
2. `review-plan` asks Antigravity to review the plan and writes `current/plan-review.md`.
3. Codex reconciles feedback, writes `current/agreement.md`, and implements.
4. `review-code` asks Antigravity to review the current diff.
5. For validation, pass `--test-command`; the bridge runs tests locally and gives the output to `agy` for analysis.
6. After the task, use `--cleanup archive` to keep an audit trail or `--cleanup delete` to remove state.

`review-code` now runs an `agy` login/health check with PTY execution, uses a `15m0s` print timeout, and sends a bounded `git diff` snapshot to `agy`. If you explicitly choose another primary model, non-authentication timeouts can fall back to `Gemini 3.1 Pro (High)`.

`.codex-antigravity/` is ignored by git by default. Do not commit sensitive context or transcripts. Keep handoff files concise; do not pass full transcripts back as the next context.

## Install

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/Ian010529/collaborating-with-antigravity-cli \
  ~/.codex/skills/collaborating-with-antigravity-cli
```

Restart or refresh Codex Desktop App, then mention `collaborating-with-antigravity-cli` in a conversation.

## Default Models

- `review-plan`: `Claude Sonnet 4.6 (Thinking)`
- `review-code`: `Gemini 3.1 Pro (High)`
- `ask`: `Gemini 3.1 Pro (Low)`

Override with `--model`. `review-plan` falls back to `Gemini 3.1 Pro (High)` after Claude quota/limit errors; `review-code` also defaults to `Gemini 3.1 Pro (High)` as its fallback model. Authentication failures do not trigger model fallback; if `agy` appears to switch to Flash while the requested model is not Flash, the bridge marks the run failed. Use Flash for quick checks; do not default to Opus unless the task is unusually complex.

## Default Behavior

- `review-plan` and `ask` default to `--print-timeout 5m0s`; `review-code` defaults to `15m0s`; the outer process timeout defaults to `--timeout-s 1800`.
- POSIX systems enable `--pty` by default, so print-mode authentication/session behavior is closer to interactive `agy`. Use `--no-pty` only when PTY output is demonstrably broken.
- `review-code` enables `--preflight` by default and first runs `agy --print-timeout 30s --print "Reply with exactly: ok"`. If login is missing, expired, or otherwise unhealthy, the bridge skips the longer review and tells you to run `agy` directly to sign in; a non-PTY authentication failure is retried once with PTY.
- `review-code` includes the current tracked `git diff` by default. If the diff is under `--max-diff-bytes` (default 120000), it sends the full diff; larger diffs are reduced to diff stat and file list.
- When no explicit `--file` is provided, the bridge auto-extracts in-repo file paths from `--PROMPT`, capped by `--max-files 5`; it only warns when focus files exceed `--max-focus-bytes 200000`.
- `--context-file` is repeatable and has a default combined cap of `--max-context-bytes 50000`. Missing files or over-limit context block the run.
- `--test-command` runs locally in the working directory and sends actual test output to `agy`. Prefer using it from a clean worktree because test commands can create files.
- The bridge always prints JSON with `success`, `agent_messages`, and `meta`, plus `error` on failure. `--dry-run` builds the prompt/command and returns JSON without calling `agy`.
- Relative `--write-output` paths are written under `--state-dir`; `--write-transcript` writes to `transcripts/` and updates `state.json` with the latest 100 runs.

## OAuth Handling

On macOS, `--auto-browser-auth` is enabled by default. The bridge listens for OAuth prompts and reads copied/browser-visible codes, but does not open OAuth URLs by default so it does not duplicate `agy`'s own browser open. `--open-auth-url` is rejected by default; only set `AGY_BRIDGE_ALLOW_OPEN_AUTH_URL=1` and pass `--open-auth-url` after confirming `agy` prints a URL but does not open a browser. Then the bridge opens it once in Chrome by default (`AGY_AUTH_BROWSER="Google Chrome"`). It defaults to `--auth-retries 1`, so it tries login once; `--auth-retries > 1` is also rejected by default. Set `AGY_BRIDGE_ALLOW_AUTH_RETRIES=1` before increasing it only when the user is actively completing browser login and accepts repeated fresh OAuth URLs.

During a PTY run, if `agy` prints an OAuth URL or asks for an authorization code, the bridge handles the code in memory. It does not create an `auth-code` file, and OAuth URLs or one-time codes are redacted from JSON output and transcripts. It will:

- Parse the OAuth URL from `agy` output; only `AGY_BRIDGE_ALLOW_OPEN_AUTH_URL=1` plus `--open-auth-url` makes the bridge open it in Chrome.
- Poll Chrome first, then Edge/Chromium/Safari tab URLs and readable page text.
- Extract codes from callback-page `?code=...` URLs, HTML-escaped links, visible page text, or clipboard content.
- Keep polling the clipboard while the OAuth prompt is active, so the page's `Copy to Clipboard` button can be read even when `agy` prints no further output; if needed, briefly copy front-browser page text and restore the previous clipboard.
- Submit the code back to `agy` through the PTY without writing it to disk.

If Chrome reports "Executing JavaScript through AppleScript is turned off", or macOS denies Accessibility to `osascript`/Terminal/Codex, the bridge cannot automatically read the page or click copy controls. Fix it by enabling Chrome View > Developer > Allow JavaScript from Apple Events, granting Accessibility to the controlling terminal or Codex, or manually clicking the page's Copy button while the bridge waits; it will read the clipboard while the OAuth prompt is active. Set `AGY_BROWSER_AUTH_CLIPBOARD=0` to disable the clipboard fallback, or pass `--no-auto-browser-auth` to disable all browser code extraction.

## Common Commands

```bash
python scripts/agy_cli_bridge.py --cd "$REPO" --mode review-plan \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md --write-transcript \
  --PROMPT "Review Codex's plan for risks, edge cases, and tests."

python scripts/agy_cli_bridge.py --cd "$REPO" --mode review-code \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff. Do not edit files."
```

Useful flags: `--agy-bin`, `--model`, `--print-timeout`, `--timeout-s`, `--fallback-model`, `--file`, `--add-dir`, `--test-command`, `--conversation`, `--continue`, `--sandbox`, `--pty`, `--no-pty`, `--auto-browser-auth`, `--no-auto-browser-auth`, `--open-auth-url`, `--no-open-auth-url`, `--auth-retries`, `--state-dir`, `--context-file`, `--write-output`, `--write-transcript`, `--run-id`, `--dry-run`, `--max-context-bytes`, `--max-diff-bytes`, `--response-budget standard|compact|none`, `--no-preflight`, `--no-include-git-diff`, `--no-auto-extract-files`, `--stream-status`, `--no-stream-status`, `--cleanup keep|archive|delete`.

Login/auth check:

```bash
agy --print-timeout 30s --print "Reply with exactly: ok"
```

If authentication fails, run `agy` directly and sign in, then repeat the health check above. The bridge recognizes `authentication failed`, `please sign in`, `not signed in`, `sign in to`, `login required`, `authentication required`, `authentication timed out`, `authorization code`, and related auth failures so they are not mistaken for ordinary fallback-eligible timeouts. On `Ctrl-C`, the bridge exits cleanly with a JSON error and status 130.

Reliability flags: `--print-timeout`, `--preflight-timeout`, `--no-preflight`, `--no-include-git-diff`, `--max-diff-bytes`, `--fallback-model`, `--stream-status-interval-s`, `--no-pty`, `--no-auto-browser-auth`.

## Local Tests

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
```

## License

MIT License. See `LICENSE`.
