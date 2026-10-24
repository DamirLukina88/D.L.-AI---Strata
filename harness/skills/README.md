# Ray Specialist Skills Library

Skills are modular, on-demand procedural playbooks loaded into context only when needed by the current task.
This keeps Ray's baseline system prompt lean (~2,295 tokens) while providing detailed step-by-step guidance for specialized workflows.

## Skill Structure
Each skill resides in its own directory:
`harness/skills/<skill_name>/SKILL.md`

`SKILL.md` contains:
- **Title & Description**: What the skill accomplishes and triggers.
- **Prerequisites**: Required tools or MCP servers.
- **Step-by-Step Procedure**: Exact command/payload formats and verification checks.
- **Common Gotchas**: Pitfalls and known failure modes.
