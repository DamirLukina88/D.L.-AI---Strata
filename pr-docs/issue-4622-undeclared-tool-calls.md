## Title
[Engine] Let harness handle undeclared tool calls via config and non-terminal refusal
Issue: Resolves #4622

## Summary
Implements the requested harness control over undeclared tool call handling. When an agent harness (e.g. Claude Code, D.L. CLI, or custom autonomous loops) executes models with dynamic/deferred toolsets, well-formed `<tool_call>` blocks that name tools not present in the prompt's declared schema are routed directly to the client instead of being downgraded to plain text.

## What changed
- `serve/server.py`:
  - Added configuration parser `undeclared_tool_calls_setting(cfg)` reading `"undeclared_tool_calls": "text" | "call"` (default: `"text"`).
  - Supported environment variable override via `STRATA_UNDECLARED_TOOL_CALLS`.
  - Added `self.undeclared_tool_calls` on the service instance and passed `deferred=(mode == "call")` into `OutputParser`.
  - Added non-terminal rejection signal `strata_rejected_tool_calls` in `/v1/chat/completions` responses when undeclared calls occur on the default `"text"` path.
- `serve/frontend.py`:
  - In `OutputParser.__init__`, added `deferred: bool = False`.
  - In `OutputParser._callable(name)`, return `True` if `self.deferred` is active, allowing well-formed calls of undeclared tools to parse into structured `tool_calls`.
- `serve/test_server.py`:
  - Added `test_undeclared_tool_calls_call_hands_the_call_to_the_client()` and `test_undeclared_tool_calls_setting()`.

## Extra Notes
- **Byte-identical default path**: When `"undeclared_tool_calls"` is unset or `"text"`, output formatting, finish reason (`stop`), and rejection tracking remain 100% byte-identical to prior releases.
- **Verification**:
  - `python3 -m unittest serve.test_server.TestServer.test_undeclared_tool_calls_setting` (PASS)
  - `python3 -m unittest serve.test_server.TestServer.test_undeclared_tool_calls_call_hands_the_call_to_the_client` (PASS)
