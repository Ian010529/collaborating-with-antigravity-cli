# collaborating-with-antigravity-cli

中文 | [English](README_EN.md)

给 **Codex Desktop App / Codex CLI** 使用的 skill。Codex 作为主控和代码作者，调用 **Antigravity CLI** (`agy`) 做只读的计划评审、代码审查和测试输出分析。

本项目迁移自 [`collaborating-with-gemini-cli`](https://github.com/ZhenHuangLab/collaborating-with-gemini-cli)。

## 工作流

1. Codex 写计划到 `.codex-antigravity/current/plan.md`。
2. `review-plan` 调用 Antigravity 审核计划，输出到 `current/plan-review.md`。
3. Codex 整合反馈，写 `current/agreement.md` 并实现代码。
4. `review-code` 调用 Antigravity 审查当前 diff。
5. 需要验证时传 `--test-command`；bridge 在本地执行测试，并把输出交给 `agy` 分析。
6. 任务结束后用 `--cleanup archive` 留痕，或 `--cleanup delete` 删除状态。

`review-code` 默认会先做 30 秒 `agy` 健康检查，把 bounded `git diff` 快照交给 `agy`，并在非认证类超时时用 `Gemini 3.1 Pro (High)` 重试一次。

`.codex-antigravity/` 默认被 `.gitignore` 排除，不应提交敏感上下文或 transcript。

## 安装

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/Ian010529/collaborating-with-antigravity-cli \
  ~/.codex/skills/collaborating-with-antigravity-cli
```

重启或刷新 Codex Desktop App，然后在对话中提到 `collaborating-with-antigravity-cli` 即可。

## 默认模型

- `review-plan`: `Gemini 3.1 Pro (High)`
- `review-code`: `Claude Sonnet 4.6 (Thinking)`
- `ask`: `Gemini 3.1 Pro (Low)`

可用 `--model` 覆盖。快速检查可用 Flash；不建议默认用 Opus，除非任务特别复杂。

## 常用命令

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

有用参数：`--response-budget standard|compact|none`、`--max-context-bytes`、`--write-transcript`、`--stream-status`、`--cleanup keep|archive|delete`。

超时/认证排查：

```bash
agy --print-timeout 30s --print "Reply with exactly: ok"
```

如果提示登录失败，先直接运行 `agy` 完成登录。常用可靠性参数：`--print-timeout`、`--no-preflight`、`--no-include-git-diff`、`--max-diff-bytes`、`--fallback-model`。

## 本地测试

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
```

## License

MIT License. See `LICENSE`.
