---
name: dbs-update
description: 更新官方 dbskill，并保留其他 Skill 与用户存档。用户要求更新、升级、检查 dbskill 版本，或在更新提醒后回复 1 时使用。
---

# dbs-update：更新 dbskill 单入口

当前上游版本：`2.18.31`。

用户已经明确要求更新 dbskill，或在上一条 dbskill 更新提醒后回复了 `1`。两种情况都直接执行更新，不再做第二次文字确认；宿主若要求 Shell 权限，由用户在宿主的权限窗口中决定。

只有上一条助手回复明确包含 dbskill 更新提醒时，单独回复的 `1` 才代表更新。缺少这段上下文时，不要自行解释数字含义。

## 更新范围

- 只更新官方仓库 `dontbesilent2025/dbskill`。
- 保留用户在 `~/.dbs/` 中的存档、报告和决策记录。
- 不更新用户安装的其他 Skill。
- 不创建后台任务、定时任务或 Agent Hook。
- 本机只保留 `dbskill/SKILL.md` 一个用户入口；`references/` 是内部实现，不注册为独立 Skill。
- 不重新加入 `dbs-bridge`、`dbs-content-system`、`dbs-wechat-html`。

## 执行步骤

1. 不要运行任何会把上游全部模块注册成独立 Skill 的全量安装命令。

2. 应将官方 `skills/dbs/SKILL.md` 和需要的 `dbs-*/SKILL.md` 同步到本目录的 `references/`，再更新根入口的版本哈希与路由；不要创建新的顶层 Skill 目录。

3. 保留本机包装层的单入口约束，并排除不需要的 `dbs-bridge`、`dbs-content-system`、`dbs-wechat-html`。

4. 更新成功后记录本次更新时间，避免当前对话仍加载旧 Skill 时重复提醒：

   ```bash
   mkdir -p "$HOME/.dbs" && date +%s > "$HOME/.dbs/update_check_at"
   ```

5. 根据同步和校验结果确认是否完成。成功时告诉用户更新已完成，并提醒用户新建一次对话后再使用新能力。

6. 同步失败时，用一句话说明失败原因和下一步需要用户处理的权限或网络问题。不要把完整终端日志直接贴给用户，除非用户要求。

## 回复格式

成功：

> dbskill 已更新完成。当前对话如果还没有读取到新能力，新建一次对话后即可使用。

失败：

> dbskill 没有更新完成：{简短原因}。处理完 {权限或网络问题} 后，再说一次「更新 dbskill」。

## 边界

- 用户只问版本、更新内容或是否需要更新时，先回答问题，不执行命令。
- 用户明确要求检查更新且希望实际同步时，按本 Skill 更新。
- 不使用 `npx skills update`，该命令可能更新用户安装的其他 Skill。

---

完成当前任务后直接结束。只有用户明确询问下一步，且当前环境已经安装 `/dbs` 时，简短提示：「下一步不确定时，可以输入 `/dbs`。」
