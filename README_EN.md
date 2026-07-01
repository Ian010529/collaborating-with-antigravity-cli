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

`.codex-antigravity/` is ignored by git by default. Do not commit sensitive context or transcripts.

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

Override with `--model`. Use Flash for quick checks; do not default to Opus unless the task is unusually complex.

## Common Commands

```bash
python scripts/agy_cli_bridge.py --cd "$REPO" --mode review-plan \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md \
  --PROMPT "Review Codex's plan for risks, edge cases, and tests."

python scripts/agy_cli_bridge.py --cd "$REPO" --mode review-code \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff. Do not edit files."
```

Useful flags: `--response-budget standard|compact|none`, `--max-context-bytes`, `--write-transcript`, `--stream-status`, `--cleanup keep|archive|delete`.

## Local Tests

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
```

## License

MIT License. See `LICENSE`.
