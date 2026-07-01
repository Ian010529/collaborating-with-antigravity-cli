# collaborating-with-antigravity-cli (Read-Only)

[中文](README.md) | English

This is a skill for **Codex Desktop App / Codex CLI**. It lets Codex call **Antigravity CLI** (`agy`) as a read-only second model from the local machine for plan review and code auditing.

Recommended workflow:

1. **Codex plans**: Codex inspects the project, writes an implementation plan, and saves it to `.codex-antigravity/current/plan.md`.
2. **Antigravity reviews the plan**: `agy` checks risks, edge cases, and test coverage without editing files, writing its response to `current/plan-review.md`.
3. **Codex reconciles feedback**: implementation starts only after the plan is agreed upon and saved as `current/agreement.md`.
4. **Codex implements**: Codex independently writes all the code changes.
5. **Conceptual Code Review**: `agy` reviews the diff and suggests improvements. Codex resolves feedback and updates the code until both agree on the code draft.
6. **Real Test Verification**: Once the code draft is agreed, `agy` (via the bridge) runs the real tests.
   - If tests pass (`PASSED`), the workflow finishes.
   - If tests fail (`FAILED`), the errors are returned to Codex to modify the code, starting the review and testing cycle again.

This project is migrated from [`collaborating-with-gemini-cli`](https://github.com/ZhenHuangLab/collaborating-with-gemini-cli).

## Entry Points

- `SKILL.md`: Codex skill definition and workflow.
- `scripts/agy_cli_bridge.py`: Antigravity CLI JSON bridge (Read-Only version).
- `tests/test_agy_cli_bridge.py`: local unit tests.

## Requirements

- Python 3.
- Antigravity CLI installed and authenticated:

```bash
agy --version
agy --print "Reply with exactly: ok"
```

This migration was tested locally with `agy 1.0.14`.

Optional model checks:

```bash
agy --model "Gemini 3.1 Pro (High)" --print "Reply with exactly: ok"
agy --model "Claude Sonnet 4.6 (Thinking)" --print "Reply with exactly: ok"
```

## Install For Codex Desktop App

Place this project under `~/.codex/skills/`:

```bash
mkdir -p ~/.codex/skills
cp -R "/path/to/collaborating-with-antigravity-cli" ~/.codex/skills/collaborating-with-antigravity-cli
```

Or clone it directly into the skills directory:

```bash
cd ~/.codex/skills
git clone <your-repo-url> collaborating-with-antigravity-cli
```

Restart or refresh Codex Desktop App. Then ask for:

```text
Use collaborating-with-antigravity-cli: Codex plans, Antigravity reviews the plan, Codex implements changes, and Antigravity reviews the final diff.
```

Codex will load `SKILL.md` and call the bridge when needed. Reliable collaboration uses `.codex-antigravity/current/*.md` handoff files.

## Reliable One-Shot Workflow

`agy --print` does not currently expose a stable conversation id, so this project stores reviewable handoff context on disk:

```text
.codex-antigravity/
  state.json
  current/
    plan.md
    plan-review.md
    agreement.md
    code-review.md
  transcripts/
  archive/
```

`.gitignore` excludes `.codex-antigravity/` by default to avoid pushing transcripts or sensitive context. Normal bridge calls do not create the state directory; files are written only when `--write-output`, `--write-transcript`, or `--cleanup` is used.

Useful parameters:

- `--model MODEL`: override the default model.
- `--context-file PATH`: include a plan, review, or agreement file as explicit context for `agy`.
- `--write-output current/name.md`: write `agy`'s response to `.codex-antigravity/current/name.md`.
- `--write-transcript`: save the full JSON transcript under `.codex-antigravity/transcripts/`.
- `--max-context-bytes 50000`: cap context loaded back into the prompt.
- `--stream-status`: print heartbeat status to stderr during long runs. Enabled by default.
- `--cleanup archive`: archive `current/` under `archive/` after the task.
- `--cleanup delete`: delete the entire `.codex-antigravity/` directory.

## Default Model Strategy

When `--model` is omitted, the bridge selects a model by mode:

- `review-plan`: `Gemini 3.1 Pro (High)` for plan critique, edge cases, and test strategy.
- `review-code`: `Claude Sonnet 4.6 (Thinking)` for code review and diff reasoning.
- `ask`: `Gemini 3.1 Pro (Low)` for quick lightweight checks.

For faster checks, override explicitly:

```bash
python scripts/agy_cli_bridge.py \
  --cd "/path/to/repo" \
  --mode ask \
  --model "Gemini 3.5 Flash (High)" \
  --PROMPT "Run a quick sanity check."
```

Do not default to `Claude Opus 4.6 (Thinking)` unless the task is unusually complex and the user accepts the extra latency/cost.

## Manual Usage

Plan review:

```bash
python scripts/agy_cli_bridge.py \
  --cd "/path/to/repo" \
  --mode review-plan \
  --model "Gemini 3.1 Pro (High)" \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md \
  --write-transcript \
  --PROMPT "Review Codex's plan for risks, edge cases, and tests."
```

Code review:

```bash
python scripts/agy_cli_bridge.py \
  --cd "/path/to/repo" \
  --mode review-code \
  --model "Claude Sonnet 4.6 (Thinking)" \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff for bugs and missing tests. Do not edit files."
```

Output is JSON:

```json
{
  "success": true,
  "agent_messages": "Antigravity response...",
  "meta": {
    "cli": "agy",
    "mode": "review-plan",
    "focus_files": []
  }
}
```

## Safety Model

- The bridge is strictly **read-only**, containing no options or logic to edit local files. This guarantees that your workspace remains clean and free of accidental edits.
- `agy --print` does not currently behave like the old Gemini CLI JSON mode and this bridge does not guarantee a returned `SESSION_ID`; use one-shot calls plus handoff files by default.
- State files are ignored by git by default; use `--cleanup archive` when an audit trail is useful and `--cleanup delete` when the task state should be removed.

## Local Tests

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
python scripts/agy_cli_bridge.py --cd . --mode ask --PROMPT "Reply with exactly: ok"
```

## Push To Your Own Remote

Because this repository starts as a clone of the original project, `origin` still points upstream. After migration, point it at your own repository:

```bash
git remote remove origin
git remote add origin <your-repo-url>
git branch -M main
git add .
git commit -m "Migrate skill to read-only Antigravity CLI collaboration"
git push -u origin main
```

## License

MIT License. See `LICENSE`.
