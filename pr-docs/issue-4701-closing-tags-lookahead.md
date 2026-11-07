## Title
[Engine] Prevent premature truncation when tool call values list closing tags
Issue: Resolves #4701

## Summary
Fixes an issue where writing files or string arguments containing literal closing tags (`</parameter>`, `</function>`, `</tool_call>`) on lines of their own resulted in `OutputParser` truncating the parameter prematurely and leaking remaining file contents into assistant answer text.

## What changed
- `serve/frontend.py`:
  - Added lookahead buffer window (`RCALL_LOOKAHEAD = 1500`) in `OutputParser`.
  - When a closing sequence (`</parameter>`, `</function>`, `</tool_call>`) appears on its own line, the parser holds the call in `self._final` buffer.
  - The parameter is only finalized if:
    1. The turn ends (`finish("stop")`),
    2. A new `<tool_call>` begins, or
    3. Trailing content with no closing tag arrives.
  - If additional file content follows, the parameter continues accumulating without truncation.
- `serve/test_tool_corpus.py`:
  - Added corpus test cases with markdown files, XML docs, and templates containing standalone closing tags.

## Extra Notes
- **Verification**: Verified byte-for-byte fidelity with multi-kilobyte prompt templates and source code containing raw tool tags.
- Tested with:
  ```bash
  python3 -m unittest serve.test_tool_corpus -v
  ```
  Passes all 30+ corpus test cases including streamed and non-streamed variations.
