# Shared Skills Workspace

This repository is the source of truth for the self-managed skills that both Codex and Claude Code should use on this Mac.

## Layout

- Source repo: `/Users/cecilialiu/Documents/Codex/Skills`
- Codex runtime entrypoints: `/Users/cecilialiu/.codex/skills`
- Claude Code runtime entrypoints: `/Users/cecilialiu/.claude/skills`
- Compatibility link kept for migration: `/Users/cecilialiu/.agents/skills/superpowers`

The runtime directories should only contain symlinks for the shared set. The actual repo-managed sources live here in the repository.

## Shared Set

### Repo-managed skills

These skills are maintained in this repository and published to both clients:

- `anthropic-skill-creator`
- `github-to-skills`
- `skill-evolution-manager`
- `skill-manager`
- `viral-content-breakdown`
- `dbskill`
- `follow-builders`
- `humanizer-zh`
- `lark-suite`
- `superpowers`

### External shared entrypoints

These stay upstream-managed in the existing Codex vendor/internal layout. Claude gets symlinks to the same real directories:

- `claude-mem`
- `pua`
- `web-access`

## Runtime Rebuild

The shared layout is defined in [shared-skills.json](./shared-skills.json).

Rebuild both runtime entrypoint trees with:

```bash
python3 scripts/rebuild_shared_skill_links.py
```

The script will:

1. Create `~/.claude/skills` if it does not exist.
2. Point `~/.codex/skills/<skill>` for repo-managed skills back to this repository.
3. Point `~/.claude/skills/<skill>` for repo-managed skills back to this repository.
4. Point `~/.claude/skills/{claude-mem,pua,web-access}` to the same upstream directories Codex already uses.
5. Keep `~/.agents/skills/superpowers` as a compatibility symlink.
6. Move replaced runtime directories into `~/.codex/.shared-skill-backups/<timestamp>/`.

Use `--dry-run` first if you want to inspect the planned changes:

```bash
python3 scripts/rebuild_shared_skill_links.py --dry-run
```

## Notes

- `lark-suite` remains a wrapper over `/Users/cecilialiu/.codex/.lark-internal-skills`.
- `superpowers` remains a wrapper over `/Users/cecilialiu/.codex/.superpowers-internal/skills`.
- `follow-builders` is kept as source only. Local feed snapshots, state files, nested `.git`, and `node_modules` are intentionally excluded from this repo.
- `skill-manager` still scans `~/.codex/skills` and `~/.agents/skills`; it does not scan `~/.claude/skills`, so the Claude entrypoints do not create duplicate inventory rows.
