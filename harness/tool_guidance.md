# Tool Usage Guidance

## Native Tool Invocation
- Always invoke tools using native JSON tool calls. Never output raw pseudo-syntax (such as `<tool_call>`, `Action: ...`) in conversational plain text.
- Provide valid, well-formed JSON arguments. If writing a large code block, keep comments concise to prevent truncation at token length boundaries.

## File Operations
- Use `view_file` to inspect existing code before editing.
- For surgical edits, prefer `replace_file_content` with exact matching lines including leading indentation.
- For new files or full rewrites, use `write_to_file`.

## Shell & Terminal Commands
- Use `run_command` with non-interactive flags (e.g. `git --no-pager`, `npm test -- --watchAll=false`).
- Do not execute interactive commands that wait indefinitely for user stdin (such as `nano`, `vi`, or interactive prompts).
- Inspect command output and return codes (`[Command exited with code 0]`). If exit code is non-zero, diagnose the failure immediately.
