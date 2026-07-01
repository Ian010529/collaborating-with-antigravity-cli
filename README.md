# collaborating-with-antigravity-cli (Read-Only)

中文 | [English](README_EN.md)

这是一个给 **Codex Desktop App / Codex CLI** 使用的 skill：让 Codex 在本机调用 **Antigravity CLI** (`agy`) 作为只读第二模型进行方案评审与代码审计。

推荐工作流：

1. **Codex 规划**：Codex 读取项目并提出实现计划，写入 `.codex-antigravity/current/plan.md`。
2. **Antigravity 审核规划**：`agy` 只读检查计划风险、边界条件和测试点，回复写入 `current/plan-review.md`。
3. **Codex 合并反馈**：双方达成一致后，Codex 编写最终方案 `current/agreement.md`。
4. **Codex 执行**：Codex 独立进行代码实现。
5. **Antigravity 概念评审**：`agy` 只读审查修改后的代码并提出建议，Codex 根据反馈修改代码，双方就代码修改达成一致。
6. **真实测试验证**：代码达成一致后，由 `agy`（通过桥接程序）执行真实测试验证。
   - 若测试通过，则任务结束。
   - 若测试发现问题，则将问题和报错返回给 Codex 重新修改代码，并再次进入概念评审和测试流程。

本项目迁移自 [`collaborating-with-gemini-cli`](https://github.com/ZhenHuangLab/collaborating-with-gemini-cli)。

## 主要入口

- `SKILL.md`：Codex skill 定义和使用流程。
- `scripts/agy_cli_bridge.py`：Antigravity CLI JSON bridge（只读版）。
- `tests/test_agy_cli_bridge.py`：本地单元测试。

## 依赖

- Python 3。
- Antigravity CLI 已安装并可用：

```bash
agy --version
agy --print "Reply with exactly: ok"
```

本机验证过的命令是 `agy 1.0.14`。

可选模型验证：

```bash
agy --model "Gemini 3.1 Pro (High)" --print "Reply with exactly: ok"
agy --model "Claude Sonnet 4.6 (Thinking)" --print "Reply with exactly: ok"
```

## 在 Codex Desktop App 中安装

把本项目放到 `~/.codex/skills/` 下：

```bash
mkdir -p ~/.codex/skills
cp -R "/path/to/collaborating-with-antigravity-cli" ~/.codex/skills/collaborating-with-antigravity-cli
```

或者直接 clone 到 skills 目录：

```bash
cd ~/.codex/skills
git clone <your-repo-url> collaborating-with-antigravity-cli
```

然后重启或刷新 Codex Desktop App。在对话里提到：

```text
使用 collaborating-with-antigravity-cli：Codex 先规划，让 Antigravity 审核规划，达成一致后由 Codex 实现，最后由 Antigravity 审计代码。
```

Codex 会读取 `SKILL.md`，并在需要时调用 bridge。可靠协作默认通过 `.codex-antigravity/current/*.md` 做文件化交接。

## 可靠 one-shot 工作流

`agy --print` 当前用文件保存可审计上下文：

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

默认 `.gitignore` 会排除 `.codex-antigravity/`。普通调用不会创建状态目录；只有传 `--write-output`、`--write-transcript` 或 `--cleanup` 时才会写文件。

常用参数：

- `--model MODEL`：覆盖默认模型。
- `--context-file PATH`：把计划、审核结果或 agreement 文件作为显式上下文交给 `agy`。
- `--write-output current/name.md`：把 `agy` 回复写入 `.codex-antigravity/current/name.md`。
- `--write-transcript`：保存完整 JSON transcript 到 `.codex-antigravity/transcripts/`。
- `--max-context-bytes 50000`：限制被塞回 prompt 的上下文大小。
- `--stream-status`：长任务运行时定期向 stderr 打心跳，默认开启。
- `--cleanup archive`：任务完成后把 `current/` 归档到 `archive/`。
- `--cleanup delete`：删除整个 `.codex-antigravity/`。

## 默认模型策略

不传 `--model` 时，bridge 会按模式自动选择：

- `review-plan`：`Gemini 3.1 Pro (High)`，用于计划审查、边界条件和测试策略。
- `review-code`：`Claude Sonnet 4.6 (Thinking)`，用于代码审查和 diff 推理。
- `ask`：`Gemini 3.1 Pro (Low)`，用于快速轻量检查。

如需快速检查，可以显式覆盖：

```bash
python scripts/agy_cli_bridge.py \
  --cd "/path/to/repo" \
  --mode ask \
  --model "Gemini 3.5 Flash (High)" \
  --PROMPT "快速 sanity check。"
```

不建议默认使用 `Claude Opus 4.6 (Thinking)`，除非任务特别复杂且你接受更高延迟/成本。

## 手动运行

规划审核：

```bash
python scripts/agy_cli_bridge.py \
  --cd "/path/to/repo" \
  --mode review-plan \
  --model "Gemini 3.1 Pro (High)" \
  --context-file .codex-antigravity/current/plan.md \
  --write-output current/plan-review.md \
  --write-transcript \
  --PROMPT "请审查 Codex 计划的风险、边界条件和测试点。"
```

代码审查：

```bash
python scripts/agy_cli_bridge.py \
  --cd "/path/to/repo" \
  --mode review-code \
  --model "Claude Sonnet 4.6 (Thinking)" \
  --context-file .codex-antigravity/current/agreement.md \
  --write-output current/code-review.md \
  --PROMPT "Review the current git diff for bugs and missing tests. Do not edit files."
```

输出是 JSON：

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

## 安全策略

- 桥接程序强制为**只读模式**，没有任何改写本地文件的参数，确保不会意外污染工作树。
- `agy --print` 当前不会像旧 Gemini CLI 一样稳定返回 `SESSION_ID`，所以本项目默认按 one-shot + 文件交接使用。
- 状态文件默认不进 Git；需要留痕时用 `--cleanup archive`，需要清理时用 `--cleanup delete`。

## 本地测试

```bash
python3 -m py_compile scripts/agy_cli_bridge.py tests/test_agy_cli_bridge.py
python3 -m unittest discover -s tests -v
python scripts/agy_cli_bridge.py --cd . --mode ask --PROMPT "Reply with exactly: ok"
```

## 推送到你自己的远端仓库

当前仓库是从原项目 clone 的，远端默认仍指向上游。建议改成你自己的远端：

```bash
git remote remove origin
git remote add origin <your-repo-url>
git branch -M main
git add .
git commit -m "Migrate skill to read-only Antigravity CLI collaboration"
git push -u origin main
```

## License

MIT License，详见 `LICENSE`。
