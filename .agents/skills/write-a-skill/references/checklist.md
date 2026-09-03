# Skill Quality Assurance Checklist

Use this checklist to audit a new or modified skill before finalizing.

---

## 1. Metadata & Naming
- [ ] Directory name is lowercase with hyphens (e.g., `git-release-manager`).
- [ ] Frontmatter `name:` matches the directory name exactly.
- [ ] Frontmatter `description:` is written in the third person.
- [ ] `description:` clearly states **what** capability is provided and **when** to trigger it.
- [ ] `description:` is concise (<1024 characters) and free of vague fluff.

## 2. Progressive Disclosure & Sizing
- [ ] `SKILL.md` is under 500 lines.
- [ ] Large manuals, schemas, and extensive documentation are placed in `references/`.
- [ ] Extended reference input/output examples are placed in `examples/`.
- [ ] All internal links to `references/`, `examples/`, and `scripts/` use valid relative markdown links.

## 3. Workflow & Instructions
- [ ] Workflows are organized in clear, numbered sequential steps.
- [ ] Verification steps are included so the agent can check if a step succeeded.
- [ ] Common edge cases, known pitfalls, and troubleshooting steps are documented.
- [ ] Deterministic / fragile command series are packaged into executable scripts in `scripts/`.

## 4. Testing & Validation
- [ ] Tested with realistic prompt variations (including casual phrasing and synonyms).
- [ ] Verified that the skill triggers when appropriate and does not trigger on unrelated prompts.
