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

`review-code` 默认会先做 `agy` 登录/健康检查，使用 PTY 执行、`15m0s` print timeout，并把 bounded `git diff` 快照交给 `agy`。如果显式选择了其他主模型，非认证类 timeout 可 fallback 到 `Gemini 3.1 Pro (High)`。

`.codex-antigravity/` 默认被 `.gitignore` 排除，不应提交敏感上下文或 transcript。保持 handoff 文件简洁，不要把完整 transcript 当作下一轮上下文。

## 安装

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/Ian010529/collaborating-with-antigravity-cli \
  ~/.codex/skills/collaborating-with-antigravity-cli
```

重启或刷新 Codex Desktop App，然后在对话中提到 `collaborating-with-antigravity-cli` 即可。

## 默认模型

- `review-plan`: `Gemini 3.1 Pro (High)`
- `review-code`: `Gemini 3.1 Pro (High)`
- `ask`: `Gemini 3.1 Pro (Low)`

可用 `--model` 覆盖。`review-code` 的默认 fallback 是 `Gemini 3.1 Pro (High)`，只在非认证类 timeout 后重试。快速检查可用 Flash；不建议默认用 Opus，除非任务特别复杂。

## 默认行为

- `review-plan` 和 `ask` 默认 `--print-timeout 5m0s`；`review-code` 默认 `15m0s`；外层进程 timeout 默认 `--timeout-s 1800`。
- POSIX 系统默认启用 `--pty`，让 print-mode 的认证/session 行为更接近交互式 `agy`。只有 PTY 输出确实异常时才用 `--no-pty`。
- `review-code` 默认启用 `--preflight`，先执行 `agy --print-timeout 30s --print "Reply with exactly: ok"`。如果检测到未登录、登录失效或认证失败，会跳过长审查并提示先直接运行 `agy` 登录；非 PTY 认证失败时会自动用 PTY 重试一次。
- `review-code` 默认包含当前 tracked `git diff`。diff 小于 `--max-diff-bytes`（默认 120000）时传完整 diff；超过后只传 diff stat 和文件列表。
- 如果没有显式 `--file`，bridge 会从 `--PROMPT` 自动提取仓库内文件路径，最多 `--max-files 5` 个；焦点文件总量超过 `--max-focus-bytes 200000` 时只给 warning。
- `--context-file` 可重复传入，默认总上限 `--max-context-bytes 50000`。超限或文件不存在会直接阻止运行。
- `--test-command` 会在本地工作目录执行，输出作为实际测试结果交给 `agy`。在干净工作区使用，避免测试命令生成的文件混入后续 diff。
- bridge 总是输出 JSON，主要字段是 `success`、`agent_messages`、`meta`，失败时会附带 `error`。`--dry-run` 只构建 prompt/command 并返回 JSON，不调用 `agy`。
- `--write-output` 的相对路径会写到 `--state-dir` 下；`--write-transcript` 写入 `transcripts/`，并更新 `state.json` 中最近 100 次运行记录。

## OAuth 登录处理

macOS 默认启用 `--auto-browser-auth`。bridge 会优先用 Chrome 打开 OAuth URL（默认 `AGY_AUTH_BROWSER="Google Chrome"`），而不是依赖系统默认浏览器；需要时可把 `AGY_AUTH_BROWSER` 改成其他浏览器应用名。默认 `--auth-retries 1`，只尝试一次登录，避免在用户未操作时频繁弹出新登录页；只有用户正在主动完成登录并接受重复打开新 OAuth URL 时才提高，例如 `--auth-retries 5`。

在 PTY 运行中，如果 `agy` 打印 OAuth URL 或要求输入 authorization code，bridge 会在内存中处理 code，不创建 `auth-code` 文件，也不会把 OAuth URL 或一次性 code 原样写入 JSON/transcript。它会：

- 解析 `agy` 输出里的 OAuth URL，并用 Chrome 打开。
- 轮询 Chrome，随后检查 Edge/Chromium/Safari 的 tab URL 和可读页面文本。
- 从 callback 页面里的 `?code=...`、HTML 转义链接里的 `code`、可见页面文本或剪贴板内容中提取 code。
- 优先读取用户点击页面 `Copy to Clipboard` 后进入剪贴板的 code；必要时短暂复制前台浏览器页面文本，再恢复原剪贴板。
- 通过 PTY 把 code 写回 `agy`，不落盘。

如果 Chrome 报 “Executing JavaScript through AppleScript is turned off”，或 macOS 没给 `osascript`/终端/Codex Accessibility 权限，bridge 不能自动读取页面或点击复制按钮。处理方式：在 Chrome 的 View > Developer 中开启 “Allow JavaScript from Apple Events”，给控制它的终端或 Codex 授权 Accessibility，或手动点击页面的 Copy 按钮；bridge 会在 OAuth prompt 活跃时读取剪贴板并提交。可用 `AGY_BROWSER_AUTH_CLIPBOARD=0` 关闭剪贴板 fallback，或用 `--no-auto-browser-auth` 关闭所有浏览器 code 提取。

## 常用命令

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

有用参数：`--agy-bin`、`--model`、`--print-timeout`、`--timeout-s`、`--fallback-model`、`--file`、`--add-dir`、`--test-command`、`--conversation`、`--continue`、`--sandbox`、`--pty`、`--no-pty`、`--auto-browser-auth`、`--no-auto-browser-auth`、`--auth-retries`、`--state-dir`、`--context-file`、`--write-output`、`--write-transcript`、`--run-id`、`--dry-run`、`--max-context-bytes`、`--max-diff-bytes`、`--response-budget standard|compact|none`、`--no-preflight`、`--no-include-git-diff`、`--no-auto-extract-files`、`--stream-status`、`--no-stream-status`、`--cleanup keep|archive|delete`。

登录/认证排查：

```bash
agy --print-timeout 30s --print "Reply with exactly: ok"
```

如果提示登录失败，先直接运行 `agy` 完成登录，再重复上面的健康检查。bridge 会识别 `authentication failed`、`please sign in`、`not signed in`、`sign in to`、`login required`、`authentication required`、`authentication timed out`、`authorization code` 等认证错误，并避免把认证失败误判成可 fallback 的普通 timeout。按 `Ctrl-C` 中断时，bridge 会返回干净的 JSON 错误并以 130 退出。

常用可靠性参数：`--print-timeout`、`--preflight-timeout`、`--no-preflight`、`--no-include-git-diff`、`--max-diff-bytes`、`--fallback-model`、`--stream-status-interval-s`、`--no-pty`、`--no-auto-browser-auth`。

## 本地测试

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
```

## License

MIT License. See `LICENSE`.
