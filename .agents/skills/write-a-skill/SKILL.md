---
name: write-a-skill
description: >-
  Interactive workflow to design, scaffold, draft, and refine high-quality agent skills.
  Use this skill whenever authoring a new skill, converting existing procedures into a skill,
  or refining and validating existing SKILL.md documents.
---

# Write A Skill

Guide the user through creating robust, predictable, and token-efficient AI agent skills using Matt Pocock's skill authoring methodology and the standard `SKILL.md` format.

---

## The 4-Phase Authoring Workflow

Follow these four phases sequentially when authoring or refining a skill:

```
┌────────────────────────┐
│ 1. Gather Requirements│ ──► Identify domain, use cases, triggers & scripts
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  2. Draft the Skill    │ ──► Structure SKILL.md, references/, examples/, scripts/
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  3. Review & Validate  │ ──► Check triggers, edge cases & progressive disclosure
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│      4. Finalize       │ ──► Place in skills/<name>/, link references, test syntax
└────────────────────────┘
```

---

## Phase 1: Gather Requirements

Before writing any markdown, interview the user to clarify:

1. **Skill Name & Category**: What specific problem or capability does this skill address? What category does it belong to (e.g., `software`, `for-fun`, or a new domain category)? (Lowercase, hyphenated, matching folder name).
2. **Trigger Criteria**: When should the agent reach for this skill? What user prompts, keywords, or workflows should trigger it?
3. **Execution Model**:
   - **Deterministic Steps**: Can repetitive, fragile, or complex commands be encapsulated into scripts (in `scripts/`)?
   - **Procedural Steps**: What sequence of actions, decisions, and checks must the agent follow?
4. **Reference Material & Depth**:
   - Is there bulky documentation, API specs, or cheatsheets that should be moved into `references/` rather than cluttering `SKILL.md`?
   - Are there concrete input/output examples that belong in `examples/`?

---

## Phase 2: Draft the Skill

Create the skill directory under `skills/<category>/<skill-name>/` (or `.agents/skills/<skill-name>/` for workspace meta-skills) with the following structure:

```text
skills/<category>/<skill-name>/
├── SKILL.md                     # Required: Main instructions, workflow, and category frontmatter
├── references/                  # Optional: Deep reference docs, specs, schemas
│   └── <topic>.md
├── examples/                    # Optional: Concrete examples and walkthroughs
│   └── <example>.md
└── scripts/                     # Optional: Deterministic helper scripts/tools
    └── <script>.[ps1|sh|py|js]
```

### `SKILL.md` Structure Guidelines

Keep the main `SKILL.md` concise (aim for under 500 lines). Structure it as follows:

```markdown
---
name: <skill-name>
description: >-
  [Action-oriented summary of capability]. Use this skill when [specific triggers/scenarios].
category: <software|for-fun|custom-category>
---

# <Skill Title>

[Brief overview of what this skill enables the agent to do].

## Quick Start
[Minimal working example or fast path for the most common scenario].

## Workflows
[Step-by-step numbered procedures with checklists and decision points].

### Workflow 1: [Name]
1. Step one...
2. Step two...

## Advanced Features & References
- For detailed specifications: [topic](references/topic.md)
- For reference examples: [example](examples/example.md)
- For helper scripts: [script](scripts/script.sh)
```

---

## Phase 3: Review & Validate

Audit the drafted skill against the quality checklist:

1. **Frontmatter Description & Category**:
   - Written in third person?
   - Category specified accurately (`software`, `for-fun`, etc.)?
   - Clear on *what* it does and *when* it activates?
   - Free of ambiguous or generic trigger phrases that cause false positives?
2. **Progressive Disclosure**:
   - Is `SKILL.md` focused on procedure rather than bloated reference dumps?
   - Are secondary materials cleanly split into `references/` or `examples/`?
3. **Deterministic vs Stochastic**:
   - Are error-prone multi-step shell commands packaged into `scripts/`?
4. **Link Integrity**:
   - Are all file links valid relative markdown paths?

See the full [Best Practices Guide](references/best-practices.md) and [Quality Checklist](references/checklist.md).

---

## Phase 4: Finalize

1. Save all files to `skills/<category>/<skill-name>/`.
2. Register the new skill in [`skills/README.md`](../../skills/README.md) under its respective category section.
3. Present a summary of the created skill and its trigger conditions to the user.
4. Invite the user to test the skill with a real-world prompt.

---

## Reference Documents

- [Best Practices Guide](references/best-practices.md): Deep dive on context vs cognitive load, trigger tuning, and progressive disclosure.
- [Quality Checklist](references/checklist.md): Step-by-step audit checklist for new skills.
- [Skill Template](templates/SKILL.template.md): Starter template for rapid drafting.
