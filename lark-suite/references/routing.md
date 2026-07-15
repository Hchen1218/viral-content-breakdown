# Backend Routing

## Selection rules

| Operation | Primary backend | Fallback / reason |
| --- | --- | --- |
| Supported reads, identity, search, simple agent calls | MCP | CLI when the tool is absent or returns an unsupported-operation error |
| Document block editing and rich document writes | CLI | Raw OpenAPI through CLI |
| Upload, download, export, local file transfer | CLI | Raw OpenAPI through CLI |
| Complex or high-volume write | CLI | MCP only when the selected preset explicitly supports the full operation |
| Base batch operations | MCP `preset.base.batch` | CLI for unsupported fields or formats |
| Calendar and task operations | MCP presets | CLI for missing endpoints or complex payloads |
| Slides, whiteboard, Markdown, OKR, Apps | CLI | Raw OpenAPI through CLI |
| Newly released endpoint | CLI schema/API | No guessed MCP tool names |

Do not retry a write on a second backend unless the first backend clearly failed before creating or changing data. If the result is ambiguous, read first and reconcile.

## Write verification

1. Capture the resource identifier returned by the write.
2. Read the same resource with the most reliable available backend.
3. Compare the fields, blocks, rows, or permissions requested by the user.
4. Report success only after the read matches; otherwise report the mismatch and preserve the identifier for recovery.

## Maintenance

The manager supports internal commands:

- `setup`: store App ID and App Secret in macOS Keychain.
- `status`: inspect versions, credentials presence, auth, MCP registration, and public entry count.
- `update`: update CLI, verify/pin MCP, refresh hidden upstream references, and retain rollback state.
- `verify`: run strict health and single-entry checks.

MCP is launched with Chinese tool descriptions, OAuth, `user_access_token`, presets `preset.default,preset.base.batch,preset.task.default,preset.calendar.default`, and the identity probe `authen.v1.userInfo.get`. Codex uses callback port 3000; Claude uses 3001.
