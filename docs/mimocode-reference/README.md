# MimoCode Reference Code

> **License**: MIT License
> **Copyright**: (c) 2026 MiMo Code, Xiaomi Corporation; (c) 2025 opencode
> **Source**: https://github.com/XiaomiMiMo/MiMo-Code
> **Purpose**: Reference implementation for QuantCode's Memory system (Day 2-4)

## Contents

- `memory/` - Memory system (461 lines TypeScript)
  - `fts.sql.ts` - SQLite FTS5 table schema
  - `paths.ts` - Path parsing + scope detection
  - `service.ts` - Search API (BM25 + CJK support)
  - `reconcile.ts` - Disk ↔ SQLite bidirectional sync
  - `fts-query.ts` - Safe FTS5 MATCH query builder
  - `index.ts` - Module exports

## Attribution

These files are copied from MimoCode (MIT license) for reference during QuantCode development.

Original repository: https://github.com/XiaomiMiMo/MiMo-Code

When porting to Python:
1. Preserve the MIT license header in each file
2. Add `# Ported from MimoCode packages/opencode/src/memory/<filename>`
3. Link back to this reference directory in code comments

## QuantCode Extensions

Our Python implementation extends MimoCode's 3-scope model:

| MimoCode | QuantCode | Purpose |
|---|---|---|
| `global` | `global` | Project-wide config |
| `projects` | `projects` | Project-level knowledge |
| (none) | **`groups`** | Group-private memory (QuantCode 核心扩展) |
| `sessions` | `sessions` | Session checkpoints |
| (none) | **`tasks`** | Task progress (QuantCode 扩展) |

GROUP isolation: `groups/<group>/memory/*.md` can only be read by owner group.
