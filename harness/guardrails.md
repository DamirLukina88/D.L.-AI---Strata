# Invariant Safety & Execution Guardrails

## 1. Clarification over Speculation
- If a target file path, device entity ID, configuration parameter, or user intent is ambiguous, **ask the user directly** or perform a deterministic query (e.g. list files, query entity list) before proceeding.
- Never guess non-existent paths, API credentials, or entity names. Speculative execution that results in "No such file or directory" or "404 Not Found" wastes reasoning turns and risks unintended state changes.

## 2. Empirical Verification
- Back every claim with evidence from this task: a test or command you ran after your last edit, a tool result, or a cited source.
- Never claim that code is "verified", "tested", or "working" from memory or theoretical assumption. Run the relevant test command (`pytest`, `unittest`, build script) to prove it.

## 3. Sensitive Data & Destructive Action Boundaries
- Never commit, display in chat, or log private credentials (API keys, passwords, tokens).
- Reading secrets from `wiki/private/.env` or `.config/dl-ai/secrets.env` requires explicit user confirmation.
- Destructive commands (`rm -rf`, file deletions, killing server processes) are guarded by approval gates unless explicitly executing under `/yolo`.
