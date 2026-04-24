# Token Receipt 可读字段口径

这个 Skill 的默认数据源是 Codex 本地 session JSONL，不是模型自己猜出来的数字。运行：

```bash
python3 scripts/token_receipt.py --show-fields
```

可以查看当前选中 session 或手动参数里真实可用的字段。

## Codex JSONL 目前能读到

来自 `event_msg.payload.type == "token_count"` 的 `info.last_token_usage` 或 `info.total_token_usage`：

- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `reasoning_output_tokens`
- `total_tokens`

来自同一个 `token_count.info`：

- `model_context_window`

来自 `session_meta.payload` 或调用参数：

- `model_provider`
- `id`
- `timestamp`
- `model` / `model_id` / `model_name` / `model_slug`，若日志没有则需要调用者传 `--model`

## 默认票面固定字段

第一版小票只打印这些已经和用户固定的条目，并且只有字段真实存在时才打印：

- `Input Tokens` <- `input_tokens`
- `Output Tokens` <- `output_tokens`
- `Cache Read Tokens` <- `cached_input_tokens`
- `Cache Write Tokens` <- `cache_write_tokens`
- `TOTAL` <- `total_tokens`

## 暂不默认打印

- `Reasoning Tokens`：Codex 日志里可能有 `reasoning_output_tokens`，但用户还没有固定它是否应该成为票面条目，所以默认不打印。
- `System Tokens`：当前 Codex `token_count` 事件没有独立字段。
- `Tool Use Tokens`：当前 Codex `token_count` 事件没有独立字段。
- `Cache Write Tokens`：当前 Codex `token_count` 常见字段里没有；只有手动传入或未来其他 provider 日志提供时才打印。

原则：真实可读字段优先；不可读字段不写；可读但未固定的字段先留在 `--show-fields` 报告里，不进入票面。
