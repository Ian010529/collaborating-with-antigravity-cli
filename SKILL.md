---
name: collaborating-with-antigravity-cli
description: "Use Antigravity CLI (`agy`) as a read-only second model from Codex Desktop or Codex CLI. Supports the workflow: Codex plans, Antigravity CLI reviews the plan, Codex implements the agreed changes, and Antigravity CLI reviews the final code changes. Includes a Python JSON bridge around `agy --print` with file-based handoff, transcripts, and cleanup."
---

# Collaborating with Antigravity CLI (Read-Only)

Use this skill when the user wants Codex to coordinate with Antigravity CLI (`agy`) for second-opinion review or auditing.

Preferred workflow:

1. **Planning**: Codex inspects the repository and writes a plan to `.codex-antigravity/current/plan.md`.
2. **Plan Review**: Run `agy_cli_bridge.py --mode review-plan --context-file .codex-antigravity/current/plan.md --write-output current/plan-review.md`. Codex resolves feedback and they agree on `.codex-antigravity/current/agreement.md`.
3. **Implementation**: Codex writes/updates the code based on the agreement.
4. **Conceptual Code Review**: Run `agy_cli_bridge.py --mode review-code --context-file .codex-antigravity/current/agreement.md --write-output current/code-review.md` (without test commands) to conceptually review the code. Iterate/resolve suggestions until both agents reach an agreement on the code draft.
5. **Validation (Real Test)**: Once the code draft is agreed, run `review-code` with `--test-command` to execute real tests.
   - If tests pass (`PASSED`), the workflow finishes.
   - If tests fail (`FAILED`), `agy` analyzes the output, returns debugging suggestions to Codex, and they return to Step 4 (modify and re-review).
6. Archive or delete `.codex-antigravity` when the task is complete.

## Requirements

- Antigravity CLI available as `agy`.
- Antigravity CLI authenticated and usable in headless print mode.
- Python 3.

Check locally:

```bash
agy --version
agy --print "Reply with exactly: ok"
agy --model "Gemini 3.1 Pro (High)" --print "Reply with exactly: ok"
agy --model "Claude Sonnet 4.6 (Thinking)" --print "Reply with exactly: ok"
```

## Bridge

Use the bundled bridge from the skill directory:

```bash
python scripts/agy_cli_bridge.py --cd "/path/to/repo" --mode review-plan --PROMPT "Review this Codex plan: ..."
```

The bridge calls `agy --print`, then returns JSON:

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

## File-Based Handoff

Use file-based handoff instead of relying on Antigravity conversation ids. The default state directory is `.codex-antigravity`, and the bridge writes only when asked.

Suggested layout:

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

Important parameters:

- `--state-dir .codex-antigravity`: state directory, default.
- `--model MODEL`: override the mode default model.
- `--context-file PATH`: include a markdown/text handoff file in the prompt.
- `--write-output current/name.md`: write Antigravity's response under the state directory.
- `--write-transcript`: save the full bridge JSON result to `transcripts/`.
- `--max-context-bytes 50000`: cap loaded handoff context.
- `--stream-status` / `--no-stream-status`: print heartbeat status to stderr during long runs. Enabled by default.
- `--cleanup keep|archive|delete`: keep, archive `current/`, or delete the state directory.

Keep `.codex-antigravity/` out of git unless the user explicitly wants to commit sanitized handoff files.

## Model Defaults

The bridge chooses a model automatically when `--model` is omitted:

- `review-plan`: `Gemini 3.1 Pro (High)` for planning critique, edge cases, and test strategy.
- `review-code`: `Claude Sonnet 4.6 (Thinking)` for code review and reasoning over diffs.
- `ask`: `Gemini 3.1 Pro (Low)` for quick, lightweight checks.

Override with `--model` when needed:

```bash
python scripts/agy_cli_bridge.py --cd "/repo" --mode ask --model "Gemini 3.5 Flash (High)" --PROMPT "Quickly sanity-check this."
```

Do not default to `Claude Opus 4.6 (Thinking)` unless the task is unusually complex and the user accepts the extra cost/latency.

## Modes

- `review-plan`: read-only planning review. Use before implementation.
- `review-code`: read-only code review of a diff or focused files.
- `ask`: generic second opinion.

## Examples

Plan review:

```bash
python scripts/agy_cli_bridge.py \
  --cd "/repo" \
  --mode review-plan \
  --model "Gemini 3.1 Pro (High)" \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md \
  --write-transcript \
  --PROMPT "Review Codex's plan for missing risks, edge cases, and tests."
```

Code review after implementation:

```bash
python scripts/agy_cli_bridge.py \
  --cd "/repo" \
  --mode review-code \
  --model "Claude Sonnet 4.6 (Thinking)" \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff for bugs and missing tests. Do not edit files."
```

## Notes For Codex

- Treat Antigravity CLI output as advice or a proposed change, not authority.
- Since `agy` is strictly read-only, Codex must write the actual code changes.
- Iterative Review: If `agy` identifies bugs or logic flaws during `review-code`, Codex must modify the code and run `review-code` again. Repeat this loop until no new issues are found and agreement is reached.
- Do not rely on `SESSION_ID`; use `.codex-antigravity/current/*.md` as the reliable handoff.
- Use `--cleanup archive` after a completed task when the user wants an audit trail.
- Use `--cleanup delete` when the user wants to remove all handoff state for the task.
