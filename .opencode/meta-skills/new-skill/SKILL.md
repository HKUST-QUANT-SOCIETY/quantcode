---
name: compose:new-skill
description: Use when authoring a brand-new skill bundle for the compose workflow
---

# Creating New Skills

## Overview

A skill is a reusable instruction bundle that teaches the agent how to perform
a specific kind of work. Skills live in `.bundle/<skill-name>/SKILL.md` and are
loaded into the system prompt on demand.

## When to create a new skill

- The same multi-step procedure is repeated across tasks or sessions.
- Domain knowledge (heuristics, checklists, templates) must be applied
  consistently without relying on the model's memory.
- A workflow benefits from an explicit sequence of gates and artifacts.

## Anatomy of a skill

A skill is a directory containing at least one `SKILL.md` file.

```
.bundle/
  my-skill/
    SKILL.md          # required: frontmatter + body
    supporting.md     # optional: extended references
    scripts/          # optional: helper scripts
```

## Frontmatter fields

- `name`: unique identifier (kebab-case).
- `description`: one sentence describing when the skill applies.
- `hidden`: optional flag to keep the skill out of listings.
- `allowed-tools`: optional tool allowlist.

## Writing the body

1. State the purpose and the trigger conditions in an Overview section.
2. Decompose the procedure into numbered, verifiable steps.
3. Call out failure modes and the expected artifact for each step.
4. Keep each step self-contained: an agent should be able to resume after
   being interrupted between steps.

## Checklist before shipping

- [ ] The skill loads via the skill loader without errors.
- [ ] Frontmatter is stripped cleanly (no leading `---` in the rendered body).
- [ ] Body exceeds the minimal-size threshold so empty templates are caught.
- [ ] Steps are numbered and each has a verifiable outcome.
- [ ] References to external files use relative paths inside the skill dir.
