## Title
[Engine] Preserve reasoning stream when model quotes closing think tag inside reasoning
Issue: Resolves #4077

## Summary
Fixes an issue where a model reasoning about format instructions, markdown templates, or code fences wrote a literal `</think>` tag inside its reasoning content, causing the parser to prematurely exit reasoning mode and leak subsequent chain-of-thought tokens into the user-visible answer text.

## What changed
- `serve/frontend.py`:
  - Added line-level code fence tracking (`self._in_code()`) and backtick parity checking in `OutputParser`.
  - In `feed()`, a `</think>` tag encountered while inside an open markdown code block (``` ... ```) or within inline backtick quotes (`...`) is kept as reasoning text rather than triggering an answer transition.
  - Added state tracking `self.after_think`: if reasoning officially ends at a top-level `</think>`, any stray redundant `</think>` on subsequent lines is dropped cleanly instead of polluting the assistant answer.
- `serve/test_tool_corpus.py`:
  - Added test specimens: `4077-stray-think-line`, `4077-stray-think-in-a-fence`, `4077-stray-think-after-a-backtick`, and `4077-quoted-think-stays-reasoning`.
- `serve/test_tool_routes.py`:
  - Added end-to-end HTTP route tests verifying that reasoning tokens stay in the `reasoning_content` delta field.

## Extra Notes
- **Verification**:
  ```bash
  python3 -m unittest serve.test_tool_corpus serve.test_tool_routes -v
  ```
  All tests pass; answers remain clean of reasoning bleed.
