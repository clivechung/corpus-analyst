# Skill Authoring Best Practices

Key principles and heuristics for creating agent skills that are predictable, token-efficient, and maintainable.

---

## 1. Context Load vs Cognitive Load

Every skill balances two constraints:

- **Context Load**: The token cost incurred when a skill's description (or full content) is present in the LLM's context window.
- **Cognitive Load**: The mental overhead required from the user to remember and manually invoke skills.

### Guidelines
- **High-Frequency, Targeted Skills**: Use specific, unambiguous descriptions so the agent loads them automatically only when relevant.
- **Progressive Disclosure**: Keep `SKILL.md` strictly under 500 lines. Place deep documentation, API specs, schemas, and lengthy guidelines in `references/`, and examples in `examples/`. The agent will only fetch them if needed.
- **Avoid Universal Trigger Bloat**: Do not write overly broad descriptions like "Use this skill for all coding tasks" as this bloats every conversation turn.

---

## 2. Crafting the Description

The YAML frontmatter `description` is the **router**. It is the only part of the skill the agent evaluates before deciding whether to read `SKILL.md`.

### Rules for Descriptions
- **Write in Third Person**: "Use this skill when..." rather than "I can help you..."
- **Specify Actions & Triggers**: Mention both the action performed and the explicit triggering context (keywords, file patterns, task types).
- **Keep it under 1024 characters**: Be punchy and descriptive.

### Examples

✅ **Good**:
```yaml
description: >-
  Runs and analyzes end-to-end Playwright tests with video recording and artifact capture.
  Use this skill when running E2E tests, debugging test flakiness, or configuring Playwright runners.
```

❌ **Bad**:
```yaml
description: >-
  Testing helper.
```

---

## 3. Determinism vs Stochasticity

LLMs excel at reasoning and synthesis, but struggle with exact multi-step command sequences, complex regex parsing, or fragile CLI pipelines.

- **Encapsulate Deterministic Work**: If a procedure requires 5 precise CLI commands with exact flags, wrap it in a script in `scripts/` (e.g., PowerShell `.ps1` or Bash `.sh` or Python `.py`).
- **Use the Agent for Decision-Making**: Instruct the agent to run the script and interpret its output or handle failures.

---

## 4. Structuring Workflows

- Use numbered lists for sequential steps.
- Provide clear verification criteria: How does the agent know step N succeeded before moving to step N+1?
- Include fallback/troubleshooting steps for common error modes.
