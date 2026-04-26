---
name: token-receipt
description: Use when the user wants to view AI conversation token usage as a receipt, invoice, checkout slip, token bill, cost snapshot, or creative monospace thermal-paper artifact. Always consider this skill for Chinese prompts like 查看本次对话 Token 消耗, 生成 token 小票, 对话发票, AI 用量账单, or any request to make token/context usage visually shareable.
---

# Token Receipt

把本次 AI 对话的 Token 消耗做成一张可截图传播的 monospace 热敏纸小票。视觉优先级高于报表完整性，但数据口径必须诚实：真实日志优先，官方价格估算其次，缺失信息要明确标注。

## 快速执行

优先运行脚本生成小票：

```bash
python3 scripts/token_receipt.py --stream
```

常用参数：

```bash
python3 scripts/token_receipt.py --agent-tool codex --model gpt-5.4 --width 48 --stream
python3 scripts/token_receipt.py --session /path/to/rollout.jsonl --scope session
python3 scripts/token_receipt.py --provider anthropic --agent-tool claude-code --model claude-sonnet-4-5 --input-tokens 12487 --cached-input-tokens 8742 --output-tokens 3215
python3 scripts/token_receipt.py --provider openai --agent-tool trae --model gpt-5.4 --input-tokens 12487 --output-tokens 3215
python3 scripts/token_receipt.py --provider alibaba --agent-tool trae --model qwen3.6-plus --input-tokens 1000000 --output-tokens 1000000
python3 scripts/token_receipt.py --footer-tone snarky --conversation-summary "用户正在反复打磨 Claude Code 小票的传播视觉"
python3 scripts/token_receipt.py --show-fields
```

在终端里优先用 `--stream`，让小票一行一行打印出来。若是在聊天框里回复，则把输出包在 Markdown 代码块里返回给用户，保持 monospace 视觉。

## 数据口径

1. 默认读取 `~/.codex/sessions` 和 `~/.codex/archived_sessions` 中最新的 Codex JSONL 会话。
2. 默认使用最新 `token_count` 事件里的 `last_token_usage`，即“最新一轮小票”。
3. 如果用户要求累计账单，使用 `--scope session` 读取 `total_token_usage`。
4. 供应商优先读 `session_meta.payload.model_provider`；模型名读不到时，要求调用者传 `--model`，否则小票显示 `MODEL: UNRECORDED`。
5. 价格只按 `references/pricing.json` 的官方价格表估算。匹配不到模型时显示 `PRICE: UNMAPPED`，不要自己编金额。
6. 价格表按模型条目保留币种；美元模型显示 `USD ESTIMATE`，人民币模型显示 `CNY ESTIMATE`。GLM 使用已标注的百炼 CNY 公开价格，MiMo 使用 OpenRouter 路由价格；不要把平台价伪装成厂商直连账单。
7. 主标题使用 `THANK YOU FOR CODING WITH ...`，让它更像真实品牌小票；不要在票面再放 `DATA: SNAPSHOT`。
8. 顶部 logo 按 Agent 工具决定：Codex 使用 Codex logo，Claude Code 使用 Claude Code logo，Trae 使用 Trae logo。感谢语按实际模型/供应商品牌决定：Claude 模型写 Claude，GPT 模型写 ChatGPT，GLM 写 GLM，MiniMax 写 MiniMax，不能把工具 logo 当成模型名。
9. 运行 `--show-fields` 可以查看当前日志里真实可读的字段。更详细说明见 `references/available-fields.md`。

## 视觉原则

- 默认宽度 48 字符；Logo 区可使用 `█░▒▓▐▛▜▌▘▝` 像素字符，金额区允许人民币符号 `¥`，其他票面尽量使用 ASCII。
- 顶部要像品牌小票，而不是普通表格：
  - Codex：使用用户指定的半色调像素标志 + `CODEX`。
  - Claude Code：使用参考图的像素螃蟹轮廓等比缩小版 + `CLAUDE CODE`。
  - Trae：使用用户指定的像素块标志 + `TRAE`。
  - 未识别供应商：`AI CHECKOUT`。
- 中段用真实小票结构：`ITEM / TOKENS` 两列、横线分隔、数字右对齐。
- 三个工具通用的稳定票面字段固定为：`Input Tokens`、`Output Tokens`、`Cache Read Tokens`、`TOTAL`。这些字段只有能从日志或手动参数中查到时才打印；不要把未确认字段写上小票。
- 可选字段固定为：`Reasoning Tokens`、`Cache Write Tokens`。有真实字段就显示，没有就省略；其中 `Cache Write Tokens` 在 Codex 日志中通常没有，Anthropic cache 相关数据或手动参数提供时才显示。
- 当前 Codex 日志常见可读字段包括 `input_tokens`、`cached_input_tokens`、`output_tokens`、`reasoning_output_tokens`、`total_tokens`、`model_context_window`。
- 不再输出 `SCOPE LATEST-TURN`；改为 `CONTEXT USED`，展示本轮上下文输入量，若有上下文窗口则显示 `used/window`。
- `TOTAL` 要有视觉重量，底部必须有短口号、ASCII 条形码、receipt id。默认 footer 为模型/品牌/当前对话总结感知的自动文案；调用时优先用 `--conversation-summary` 传入当前对话一句话总结，也可以用自定义 `--footer`。
- 更详细的布局规则见 `references/receipt-style.md`。

## 验证

完成或修改 Skill 后至少运行：

```bash
python3 scripts/validate_receipt.py
```

它会检查行宽、必备字段、Claude block logo、条形码、未知价格降级，以及未固定字段不会被打印。
