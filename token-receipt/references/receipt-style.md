# Token Receipt 视觉规范

目标不是做“准确但无聊的表格”，而是做一张能截图传播的热敏纸小票。票面要稳定适配 monospace；Logo 区允许使用 `█░▒▓▐▛▜▌▘▝` 做像素块，金额区允许 `¥` 表示人民币，其余内容尽量保持 ASCII。

## 票面结构

1. 顶部品牌区：像素感头图 + 产品名。
2. 说明区：`THANK YOU FOR CODING WITH ...`、receipt id、日期、provider、model、context used。
3. 明细区：`ITEM / TOKENS` 两列，数字右对齐。
4. 总计区：`TOTAL` 单独加重，不要埋在明细里。
5. 金额区：官方估算金额，按模型条目显示 `USD ESTIMATE` 或 `CNY ESTIMATE`；匹配不到价格时显示 `PRICE: UNMAPPED`。
6. 底部传播区：一句根据模型和当前对话总结生成的短 footer + ASCII 条形码 + receipt id。

## 默认宽度

默认 48 字符；可选 42、48、56、64。脚本必须保证每一行不超过指定宽度。

## 品牌头图方向

顶部 logo 按 Agent 工具决定，不按模型决定。感谢语按模型决定，不按 Agent 工具决定。

Codex：

```text
                  █████
                █    ██   ███
              ███ ██    ██   █
            ██ ██ ██████   ███
            █  ██ ██    ███   █
            ██   ███    █  ██  █
              ███   █████  ██ ██
              █   ██    █  ███
               ███   ██    █
                     █████
                      CODEX
```

Claude Code：

```text
                    ▐▛███▜▌
                    ▜█████▛▘
                     ▘▘ ▝▝
                  CLAUDE CODE
```

Trae：

```text
                 ██████████████
              ███▒▒▒▒▒▒▒▒▒▒▒▒▒▒███
              ███▒▒██████████▒▒███
              ███▒▒██▒▒▒█▒▒▒█▒▒███
              ███▒▒██████████▒▒███
              █████▒▒▒▒▒▒▒▒▒▒▒▒███
                 █████████████
                       TRAE
```

Generic：

```text
          [ AI CHECKOUT ]
```

## 文案原则

- 票面字段保留小票感但提高可读性。通用稳定字段固定为：`Input Tokens`、`Output Tokens`、`Cache Read Tokens`、`TOTAL`。
- 可选字段固定为：`Reasoning Tokens`、`Cache Write Tokens`。有真实字段就显示，没有就省略。
- 不要打印来源不确定的字段。比如 `System Tokens`、`Tool Use Tokens` 不进入首版票面。
- 多币种价格必须保留来源口径。人民币模型可以显示 `RATE NOTE`，例如 `CN MAINLAND` 或 `ALIYUN CN`；MiMo 这类通过 OpenRouter 补价的模型显示 `OPENROUTER`，避免把平台公开价伪装成厂商直连账单。
- 感谢语里的模型/品牌名保留标准写法，例如 `ChatGPT`、`GLM`、`MiniMax`、`DeepSeek`，不要全部压成 `CHATGPT`。
- 条形码使用原版 `|` 细竖线组合，保持轻量的 ASCII 小票质感。
- 终端演示时优先用 `--stream`，让 receipt 一行一行出现；聊天回复则使用代码块保持等宽布局。
- 解释性中文不要放进票面，放在 Skill 回复正文里。
- footer 要短，有传播记忆点，并且尽量根据模型、当前对话总结或用户指定语气变化，例如：
  - `NO REFUNDS ON REASONING.`
  - `KEEP THE CONTEXT WARM.`
  - `SHIP IT BEFORE THE CACHE COOLS.`
  - `CONTEXT WAS HARMED IN THIS CHAT.`
  - `KEEP BUILDING AMAZING THINGS.` + `CLAUDE CODE IS HERE TO HELP.`
