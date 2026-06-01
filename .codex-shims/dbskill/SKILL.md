---
name: dbskill
description: dontbesilent 商业工具箱的 Codex 入口。用于商业诊断、对标分析、内容诊断、标题优化、目标拆解与多角色讨论；触发后立即读取原始 dbskill 工作流并按原规则执行。
---

# dbskill

这是给 Codex 用的轻量可见性包装层，不是 `dbskill` 的真源。

使用这个 skill 时：

1. 立即读取 `/Users/cecilialiu/.skillshub/dbskill/SKILL.md`
2. 严格按原始 `dbskill` 的规则、路由和工作流执行
3. 原始 skill 里引用的文件，一律相对 `/Users/cecilialiu/.skillshub/dbskill/` 解析
4. 不要把这个包装层当成原始 skill 内容，也不要在这里维护上游规则

这个包装层存在的唯一目的，是让 Codex 更稳定地把 `dbskill` 放进技能列表并可触发。
