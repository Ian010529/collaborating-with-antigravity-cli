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

`review-code` now runs an `agy` login/health check, uses a `15m0s` print timeout, sends a bounded `git diff` snapshot to `agy`, and retries once with `Gemini 3.1 Pro (High)` after non-authentication timeouts.

`.codex-antigravity/` is ignored by git by default. Do not commit sensitive context or transcripts. Keep handoff files concise; do not pass full transcripts back as the next context.

## Install

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/Ian010529/collaborating-with-antigravity-cli \
  ~/.codex/skills/collaborating-with-antigravity-cli
```

Restart or refresh Codex Desktop App, then mention `collaborating-with-antigravity-cli` in a conversation.

## Default Models

- `review-plan`: `Gemini 3.1 Pro (High)`
- `review-code`: `Claude Sonnet 4.6 (Thinking)`
- `ask`: `Gemini 3.1 Pro (Low)`

Override with `--model`. `review-code` defaults to `Gemini 3.1 Pro (High)` as its fallback model, and only retries after non-authentication timeouts. Use Flash for quick checks; do not default to Opus unless the task is unusually complex.

## Default Behavior

- `review-plan` and `ask` default to `--print-timeout 5m0s`; `review-code` defaults to `15m0s`; the outer process timeout defaults to `--timeout-s 1800`.
- `review-code` enables `--preflight` by default and first runs `agy --print-timeout 30s --print "Reply with exactly: ok"`. If login is missing, expired, or otherwise unhealthy, the bridge skips the longer review and tells you to run `agy` directly to sign in.
- `review-code` includes the current tracked `git diff` by default. If the diff is under `--max-diff-bytes` (default 120000), it sends the full diff; larger diffs are reduced to diff stat and file list.
- When no explicit `--file` is provided, the bridge auto-extracts in-repo file paths from `--PROMPT`, capped by `--max-files 5`; it only warns when focus files exceed `--max-focus-bytes 200000`.
- `--context-file` is repeatable and has a default combined cap of `--max-context-bytes 50000`. Missing files or over-limit context block the run.
- `--test-command` runs locally in the working directory and sends actual test output to `agy`. Prefer using it from a clean worktree because test commands can create files.
- The bridge always prints JSON with `success`, `agent_messages`, and `meta`, plus `error` on failure. `--dry-run` builds the prompt/command and returns JSON without calling `agy`.
- Relative `--write-output` paths are written under `--state-dir`; `--write-transcript` writes to `transcripts/` and updates `state.json` with the latest 100 runs.

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

Useful flags: `--agy-bin`, `--model`, `--print-timeout`, `--timeout-s`, `--fallback-model`, `--file`, `--add-dir`, `--test-command`, `--conversation`, `--continue`, `--sandbox`, `--state-dir`, `--context-file`, `--write-output`, `--write-transcript`, `--run-id`, `--dry-run`, `--max-context-bytes`, `--max-diff-bytes`, `--response-budget standard|compact|none`, `--no-preflight`, `--no-include-git-diff`, `--no-auto-extract-files`, `--stream-status`, `--no-stream-status`, `--cleanup keep|archive|delete`.

Login/auth check:

```bash
agy --print-timeout 30s --print "Reply with exactly: ok"
```

If authentication fails, run `agy` directly and sign in, then repeat the health check above. The bridge recognizes `authentication failed`, `please sign in`, `not signed in`, `sign in to`, `login required`, and related auth failures so they are not mistaken for ordinary fallback-eligible timeouts.

Reliability flags: `--print-timeout`, `--preflight-timeout`, `--no-preflight`, `--no-include-git-diff`, `--max-diff-bytes`, `--fallback-model`, `--stream-status-interval-s`.

## Local Tests

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
```

## License

MIT License. See `LICENSE`.
