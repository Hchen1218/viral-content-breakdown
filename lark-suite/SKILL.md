---
name: lark-suite
description: Single entrypoint for all Feishu/Lark work through the official CLI and MCP. Use for cloud documents, Wiki, Drive, Sheets, Base/Bitable, Slides, Markdown, whiteboards, messages, calendar, tasks, meetings, mail, approvals, attendance, OKR, apps, contacts, events, permissions, search, and authentication. Replaces exposing individual lark-* skills.
---

# Lark Suite

Use the official CLI as the complete backend and the official MCP as an agent-native supplement. Keep this as the only public `lark-*` skill.

## Workflow

1. On the first invocation in a session, run `python3 scripts/lark_suite_manager.py auto-update`. It checks at most once every 24 hours and never blocks normal use when offline.
2. Run `python3 scripts/lark_suite_manager.py status` when authentication, installation, or backend state matters.
3. Prefer MCP for supported reads and simple agent-native operations. Use CLI for document block editing, uploads/downloads, complex writes, missing MCP tools, or raw OpenAPI calls.
4. Select exactly one backend for each write. After it finishes, read the affected resource back and verify the result before reporting success.
5. For CLI calls, inspect `lark-cli <domain> --help` and the relevant subcommand help before constructing an unfamiliar call. Prefer `+` shortcuts, then generated API commands, then `lark-cli api`.
6. Use structured JSON output. Use `--dry-run` when available before consequential or broad mutations.
7. If authorization is missing, tell the user. Run the manager's secure `setup` command locally for app credentials, then use the official OAuth flow. Never request or print the App Secret in chat.

## Domain Map

- Documents and search: `docs`
- Knowledge bases: `wiki`
- Files, permissions, and comments: `drive`
- Spreadsheets: `sheets`
- Base / Bitable: `base`
- Presentations: `slides`
- Markdown conversion and import: `markdown`
- Whiteboards: `whiteboard`
- Messages and group chats: `im`
- Calendar: `calendar`
- Tasks: `task`
- Meetings and minutes: `vc`, `minutes`
- Mail: `mail`
- Approvals and attendance: `approval`, `attendance`
- OKR and application management: `okr`, `apps`
- People and departments: `contact`
- Real-time subscriptions: `event`
- Authentication and profiles: `auth`, `config`, `profile`
- Unsupported or newly added OpenAPI endpoints: `schema`, `api`

## Progressive Detail

Read [references/routing.md](references/routing.md) when backend selection or verification is unclear. Updated upstream domain notes may exist under `/Users/cecilialiu/.codex/.lark-internal-skills/`; they are hidden references, not public skills. Read only the matching domain when CLI help is insufficient. Current CLI help and schemas remain authoritative.

Never run `lark-cli update` or `npx skills add larksuite/cli -g -y`. Both can expose the full upstream skill set. Backend maintenance must go through `scripts/lark_suite_manager.py`.
