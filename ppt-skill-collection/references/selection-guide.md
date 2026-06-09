# PPT Skill Collection Selection Guide

这个文件定义的是“怎么替用户做判断”，不是项目百科。

## 一句话原则

- 默认只推荐 1-2 个。
- 先看用户想解决什么，再看项目星数。
- 先分层，再比较同层项目。
- 如果用户只是要一个轻量可用的 deck skill，不要先推 framework 或 platform。

## 分层硬规则

### 1. 可直接作为 PPT / HTML deck skill 推荐

- `frontend-slides`
- `huashu-design`
- `guizang-ppt-skill`
- `html-ppt-skill`

这四个是“用户说我要一个做演示文稿的 skill”时的主要候选。

### 2. Framework / runtime

- `open-slide`

这个项目适合“想把 slides 当代码产品长期维护”的人，不适合“先给我装一个现成 skill”的人。

### 3. Template library

- `beautiful-html-templates`

它更像模板素材层。适合给其他 skill 或团队流程提供模板，不适合作为第一推荐去满足“现在就做一套 deck”。

### 4. Platform / ecosystem

- `open-design`

这是整个平台。只有当用户明确说“我要的不只是 PPT”或“我要整套设计工作流”时，才应把它抬到第一推荐。

## 默认推荐映射

### 快速做出有设计感的 HTML deck

第一推荐：`frontend-slides`

理由：

- 有“先看 3 个风格方向再选”的机制。
- 对不擅长描述审美的用户最友好。
- HTML deck 路线清晰，适合 pitch、分享、演讲。

第二推荐：`html-ppt-skill`

只在用户更看重模板密度和快速出第一版时给。

### HTML deck，同时希望能交付可编辑 PPTX 或更宽泛设计产物

第一推荐：`huashu-design`

理由：

- 不只做 HTML deck，还能给 editable PPTX、原型、动画。
- 更适合团队协作和多格式交付。

第二推荐：`frontend-slides`

只在用户其实主要还是想做 HTML deck，但偶尔会考虑其他交付物时给。

### 线下分享、杂志风、瑞士风、强个人表达

第一推荐：`guizang-ppt-skill`

理由：

- 这是它最强的定位，不是顺带支持。
- 美学约束更强，适合个人风格表达和线下 talk。

第二推荐：`frontend-slides`

只在用户接受“风格不必固定在杂志 / 瑞士路线”时给。

### React 组件化、强迭代、点选评论改稿

第一推荐：`open-slide`

理由：

- 用户要的不是单一 skill，而是 runtime / framework。
- 重点在 React、注释迭代、present mode、comments workflow。

这时通常不给第二推荐，除非用户又补了一句“但我也想快速出第一版”，才可补 `frontend-slides`。

### 模板多、快速出第一版、模板党

第一推荐：`html-ppt-skill`

理由：

- 强项是主题、布局、动画和 presenter mode 数量。
- 更像“模板军火库”。

第二推荐：`frontend-slides`

只在用户还很在意整体美感判断时给。

### 要统一视觉模板库给 agent 选

第一推荐：`beautiful-html-templates`

理由：

- 这是模板库本职，不是假装工作流。
- 适合团队统一视觉、批量 deck 和给其他 skill 喂模板。

第二推荐：`frontend-slides`

只在用户同时需要“拿模板库去驱动一个现成 deck workflow”时给。

### 我要整套本地优先设计平台，不只要 PPT

第一推荐：`open-design`

理由：

- 用户已经超出 deck skill 范围。
- 他们要的是平台、design systems、plugins、skills、artifact 工作流。

第二推荐：`huashu-design`

只在用户其实没那么想上平台，只是想要多格式设计产物时给。

## 同层项目的区分句式

### `frontend-slides` vs `html-ppt-skill`

- `frontend-slides` 更像“带审美引导的 deck workflow”。
- `html-ppt-skill` 更像“模板和主题库存很厚的 HTML PPT studio”。

### `frontend-slides` vs `guizang-ppt-skill`

- `frontend-slides` 更通用，更适合先看风格方向再选。
- `guizang-ppt-skill` 更鲜明，更适合杂志风 / 瑞士风 / 个人表达。

### `huashu-design` vs `frontend-slides`

- `huashu-design` 更大一层，覆盖 deck、editable PPTX、原型、动画。
- `frontend-slides` 更聚焦 HTML 演示文稿本身。

### `open-slide` vs 所有 PPT skill

- `open-slide` 不是“装上就用”的 deck skill，而是写 React slides 的工程框架。
- 如果用户没有明确说 React、comments、iterative authoring，不要优先推它。

### `beautiful-html-templates` vs 所有 PPT skill

- 它是模板库，不是完整工作流。
- 只有当用户明确需要“模板资产层”时，才把它排第一。

### `open-design` vs 所有 PPT skill

- `open-design` 是平台，不是轻量上手工具。
- 只有当用户明确需要全套设计能力时，才值得承担它的复杂度。

## 默认排除逻辑

当你写“为什么不是另外几个”时，优先使用这些真实理由：

- 它不是单 skill，而是 framework / template library / platform。
- 它的安装和学习成本更高。
- 它不以 editable PPTX 为核心。
- 它不以强个人表达风格为核心。
- 它的价值在模板密度，不在审美判断。
- 它适合长期工程化 authoring，不适合现在马上出 deck。

## 输出控制

- 默认不要列全 7 个。
- 默认不要写成长篇项目百科。
- 默认不要说“都可以，看你喜好”。
- 如果用户没有要求全量比较，就给结论和行动建议。
