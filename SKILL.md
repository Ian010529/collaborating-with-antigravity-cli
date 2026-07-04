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

`review-code` defaults: preflight `agy` health check, bounded git diff handoff, `15m0s` print timeout, and one non-auth timeout retry with `Gemini 3.1 Pro (High)`.

Keep `.codex-antigravity/` out of git unless sanitized. Keep handoff files concise; do not pass full transcripts back as context.

## Models

Default model by mode when `--model` is omitted:

- `review-plan`: `Gemini 3.1 Pro (High)`
- `review-code`: `Claude Sonnet 4.6 (Thinking)`
- `ask`: `Gemini 3.1 Pro (Low)`

Use `Gemini 3.5 Flash` only for quick checks. Do not default to Opus unless the task is unusually complex and the user accepts extra latency/cost.

## Commands

Plan review:

```bash
python scripts/agy_cli_bridge.py --cd "$REPO" --mode review-plan \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md --write-transcript \
  --PROMPT "Review Codex's plan for risks, edge cases, and tests."
```

Code review:

```bash
python scripts/agy_cli_bridge.py --cd "$REPO" --mode review-code \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff. Do not edit files."
```

Useful flags: `--model`, `--fallback-model`, `--file`, `--state-dir`, `--context-file`, `--write-output`, `--write-transcript`, `--max-context-bytes`, `--max-diff-bytes`, `--response-budget standard|compact|none`, `--no-preflight`, `--no-include-git-diff`, `--stream-status`, `--cleanup keep|archive|delete`.

## Rules

- Treat `agy` output as advice, not authority.
- Do not rely on `agy` conversation ids; use handoff files.
- `--test-command` executes locally and may create files; use it intentionally, preferably from a clean worktree.
- If preflight fails, run `agy` directly to sign in, then verify with `agy --print-timeout 30s --print "Reply with exactly: ok"`.
- If `agy` requests broader context, narrow the next prompt instead of dumping the whole repo.
