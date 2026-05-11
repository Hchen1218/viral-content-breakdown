---
name: lark-suite
description: Use for any Feishu/Lark task involving docs, sheets, drive, calendar, chat, contacts, mail, tasks, wiki, meetings, whiteboards, slides, attendance, approvals, search, or Lark OpenAPI exploration. This is the single entrypoint for the local Lark toolkit and replaces the former lark-doc, lark-sheets, lark-im, lark-calendar, lark-drive, lark-mail, lark-task, lark-wiki, lark-vc, lark-whiteboard, lark-whiteboard-cli, lark-minutes, lark-contact, lark-base, lark-event, lark-openapi-explorer, lark-slides, lark-attendance, lark-approval, and related workflow skills.
license: MIT
metadata:
  github_url: https://github.com/larksuite/cli
  github_hash: 7fb71c6947499cffea502fd1a060593ac3cf6515
  version: "1.0.9"
  created_at: 2026-04-07T00:00:00+08:00
  entry_point: SKILL.md
  dependencies:
    - lark-cli
---

# Lark Suite

This is the single-entry wrapper for the local Feishu/Lark toolkit.

Use this skill instead of exposing the underlying `lark-*` skills directly in the main skill list.

This wrapper stays aligned to the upstream `larksuite/cli` repository while preserving a clean one-skill user experience. The current local toolchain is `lark-cli 1.0.9`, with skills installed under `/Users/cecilialiu/.agents/skills`.

Treat `/Users/cecilialiu/.agents/skills` as the source of truth for the installed Lark skills in this environment. Do not assume stale legacy paths under `/Users/cecilialiu/.codex/.lark-internal-skills` are complete.

## How To Use This Wrapper

1. Start with the shared rules at `/Users/cecilialiu/.agents/skills/lark-shared/SKILL.md` for auth, identity, scopes, and safety.
2. Load only the specific internal workflow files relevant to the user's task.
3. Keep the user-facing experience simple: refer to this as `lark-suite` unless naming an internal workflow is genuinely helpful.
4. Before any write or delete operation on the user's Lark data, confirm intent unless the user already explicitly asked you to make the change.

## Internal Workflow Map

- Search for a spreadsheet, doc, or workspace file by title or keyword:
  Read `/Users/cecilialiu/.agents/skills/lark-doc/SKILL.md`
- Read or update spreadsheets:
  Read `/Users/cecilialiu/.agents/skills/lark-sheets/SKILL.md`
- Work with docs:
  Read `/Users/cecilialiu/.agents/skills/lark-doc/SKILL.md`
- Work with chat and messages:
  Read `/Users/cecilialiu/.agents/skills/lark-im/SKILL.md`
- Work with calendar:
  Read `/Users/cecilialiu/.agents/skills/lark-calendar/SKILL.md`
- Work with files and drive:
  Read `/Users/cecilialiu/.agents/skills/lark-drive/SKILL.md`
- Work with contacts:
  Read `/Users/cecilialiu/.agents/skills/lark-contact/SKILL.md`
- Work with mail:
  Read `/Users/cecilialiu/.agents/skills/lark-mail/SKILL.md`
- Work with tasks:
  Read `/Users/cecilialiu/.agents/skills/lark-task/SKILL.md`
- Work with wiki:
  Read `/Users/cecilialiu/.agents/skills/lark-wiki/SKILL.md`
- Work with meetings, minutes, and call artifacts:
  Read `/Users/cecilialiu/.agents/skills/lark-vc/SKILL.md` and `/Users/cecilialiu/.agents/skills/lark-minutes/SKILL.md`
- Work with whiteboards:
  Read `/Users/cecilialiu/.agents/skills/lark-whiteboard/SKILL.md`
- Build or script whiteboard diagrams with the Node CLI helper:
  Read `/Users/cecilialiu/.agents/skills/lark-whiteboard-cli/SKILL.md`
- Work with Base:
  Read `/Users/cecilialiu/.agents/skills/lark-base/SKILL.md`
- Handle approval and permission flows:
  Read `/Users/cecilialiu/.agents/skills/lark-approval/SKILL.md`
- Work with attendance and check-in records:
  Read `/Users/cecilialiu/.agents/skills/lark-attendance/SKILL.md`
- Work with presentations and slide pages:
  Read `/Users/cecilialiu/.agents/skills/lark-slides/SKILL.md`
- Work with event subscriptions:
  Read `/Users/cecilialiu/.agents/skills/lark-event/SKILL.md`
- Explore lower-level Lark APIs:
  Read `/Users/cecilialiu/.agents/skills/lark-openapi-explorer/SKILL.md`
- Use bundled Lark workflows:
  Read `/Users/cecilialiu/.agents/skills/lark-workflow-meeting-summary/SKILL.md` or `/Users/cecilialiu/.agents/skills/lark-workflow-standup-report/SKILL.md`
- Create or extend Lark-focused skills:
  Read `/Users/cecilialiu/.agents/skills/lark-skill-maker/SKILL.md`

## Intent

This wrapper exists to keep the skill list clean while preserving access to the full local Lark toolkit on disk.
