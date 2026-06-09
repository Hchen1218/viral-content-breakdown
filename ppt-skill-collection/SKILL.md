---
name: ppt-skill-collection
description: 在 7 个开源 AI PPT / HTML deck 项目里做选型、比较和官方安装导航。只要用户想知道“哪个 PPT skill 适合我”“这些 slides skill 有什么区别”“帮我装一个做演示文稿的 skill”“HTML deck / Swiss / 杂志风 / 可编辑 PPTX / 模板库 / open-design / open-slide 怎么选”，就应使用此 skill。默认只推荐 1-2 个最合适的项目，并按 Claude Code、Codex 或通用 Agent 给出官方安装路径。
license: MIT
compatibility: Requires filesystem and shell access; internet access is only needed when printing or running official upstream install routes.
metadata:
  source: local
  catalog: references/catalog.json
  selection_guide: references/selection-guide.md
---

# PPT Skill Collection

这个 skill 是一个公开的选型和安装入口，不是 PPT 生成器。

它的职责只有四件事：

1. 判断用户当前到底要哪一类 PPT / HTML deck 工具。
2. 在固定的 7 个项目里只推荐 1-2 个最合适的。
3. 解释为什么不是另外几个。
4. 按当前 Agent 环境给出官方上游安装路径；只有官方 CLI 路由才代执行。

它绝不做这些事：

- 不直接生成 deck。
- 不把上游仓库内容搬进本地再假装“已经安装”。
- 不把 framework、template library、platform 假装成单一 skill。
- 不把 slash 命令、GUI 操作、clone 教程说成“一键安装”。

## 先读什么

先读 `references/selection-guide.md`，理解分层和推荐逻辑。

需要具体项目信息时，再读 `references/catalog.json`，或直接运行：

```bash
python3 scripts/catalog_cli.py show <project-id>
```

需要某个 Agent 环境下的安装方式时，运行：

```bash
python3 scripts/catalog_cli.py print-install <project-id> --agent <claude_code|codex|generic>
```

用户确认“现在安装”时，才考虑：

```bash
python3 scripts/catalog_cli.py run-install <project-id> --agent <claude_code|codex|generic>
```

如果 route 不是 `direct_command`，脚本会拒绝执行并打印官方步骤。不要绕过这个限制。

## Agent 环境判断

先判断当前应该用哪种安装卡片：

- `claude_code`：
  - 用户明确提到 Claude Code。
  - 用户提到 `/plugin`、`~/.claude/skills`、slash command、Claude skill。
- `codex`：
  - 用户明确提到 Codex、Codex CLI、Codex app。
- `generic`：
  - 其他本地 coding agent。
  - 看不出来时默认 `generic`。

如果用户环境不明确，不要先盘问一轮；先按 `generic` 给结论，并顺手说明“如果你是 Claude Code / Codex，我可以切到对应安装路径”。

## 固定工作流

按这个顺序输出，不要跳步：

### 1. 判断

先用一句话给结论，说明用户要的是哪一类能力：

- 直接做 HTML deck
- 可编辑 PPTX / 多格式设计交付
- 杂志风 / 瑞士风 / 个人表达型演讲
- React 组件化高迭代 slides
- 模板库 / 团队统一视觉
- 整套设计平台

### 2. 推荐

默认只推荐 1-2 个项目。

- 第一推荐必须最明确。
- 第二推荐只在它真的能补充另一个维度时才给。
- 如果用户明确要“完整榜单”或“把 7 个都比一下”，才展开全量比较。

### 3. 为什么不是另外几个

必须明确写出排除理由，不要只写“也可以”。

排除理由要具体，例如：

- 它是 framework，不是直接可装的 skill。
- 它更像模板库，不负责完整工作流。
- 它擅长强迭代 React authoring，不适合想马上出单文件 deck 的人。
- 它是整个平台，学习和安装成本明显更高。

### 4. 官方安装路径

按当前 Agent 环境输出安装卡片。

规则：

- `direct_command`：给出官方命令，可以代执行。
- `chat_command`：逐字给出该聊天命令，不要声称 shell 可以执行它。
- `manual`：逐字给出官方步骤，不要伪造成自动安装。
- `unsupported`：明确说明当前环境没有官方直装路径。

### 5. 下一步

结尾必须问一句：

- “如果你要，我现在可以按这个官方路径继续安装。”

如果第一推荐是 `manual` 或 `chat_command`，就改成：

- “如果你要，我现在可以把这套官方步骤按你的 Agent 环境展开到可执行粒度。”

## 安装执行规则

只有在下面两个条件都满足时，才执行安装：

1. 用户已经明确确认要安装。
2. 该项目在当前 Agent 下的 route `status` 是 `direct_command`。

执行前先简短复述：

- 要装哪个项目
- 当前使用哪个 Agent route
- 这是官方 CLI 路径

然后运行 `python3 scripts/catalog_cli.py run-install ...`。

如果 route 不是 `direct_command`：

- 不要尝试自己拼命令。
- 不要把 `chat_command` 当 shell 跑。
- 不要把 `manual` route 偷偷自动化。
- 直接打印官方步骤并停止。

## 项目分层

这个分层是硬规则，不能混：

- 可直接作为“PPT skill”推荐：
  - `frontend-slides`
  - `huashu-design`
  - `guizang-ppt-skill`
  - `html-ppt-skill`
- framework / runtime：
  - `open-slide`
- template library：
  - `beautiful-html-templates`
- platform / ecosystem：
  - `open-design`

## 回答模板

默认使用这个结构：

```markdown
## 判断
一句话结论。

## 推荐
1. 项目名：为什么它最适合这个场景。
2. 项目名：只有在确实有补充价值时才写。

## 为什么不是另外几个
- 项目名：排除理由。
- 项目名：排除理由。

## 官方安装路径
- 当前环境：Claude Code / Codex / 通用 Agent
- 第一推荐：route 类型 + 官方命令或步骤
- 第二推荐：只有在你真的推荐了第二个时才写

## 下一步
要不要我现在按第一推荐继续安装？
```

## 例子

**例子 1**

输入：
“我要做一套线下分享的杂志风 HTML deck，有点个人风格。”

输出方向：

- 判断：这是“强风格演讲 deck”。
- 第一推荐：`guizang-ppt-skill`
- 第二推荐：可选 `frontend-slides`
- 排除：`open-slide` 太偏 React authoring；`beautiful-html-templates` 只是模板库。

**例子 2**

输入：
“团队里有不会代码的同事，我希望最后还能给他们改 PPT。”

输出方向：

- 判断：这是“HTML deck + 可编辑 PPTX”。
- 第一推荐：`huashu-design`
- 第二推荐：`frontend-slides`
- 排除：`guizang-ppt-skill` 强在美学和 deck，不以 PPTX 协作为核心。

**例子 3**

输入：
“我想用 React 组件写 slides，还能点元素留 comment 改稿。”

输出方向：

- 判断：这是“framework / 高迭代 authoring”。
- 第一推荐：`open-slide`
- 排除：它不是直接安装成单一 skill 的路线，要诚实说明。

## 最后提醒

- 你的价值不是“把 7 个项目背出来”，而是替用户减少选择成本。
- 默认给结论，不给大而全百科。
- 对安装能力要保守、真实、逐字对齐官方上游。
