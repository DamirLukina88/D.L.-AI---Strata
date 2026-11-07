# [Engine] Add GET /v1/models/{model_id} single model retrieve endpoint

## Problem and result
Visual Studio 2026's BYOK custom-OpenAI provider (18.10 preview) validates custom models by probing `GET {base}/v1/models/{model_id}` before accepting a connection. Previously, `serve/server.py` handled `GET /v1/models` and `GET /models`, but any path below them fell through to the generic 404 handler (`{"error":{"message":"not found"}}`), preventing Visual Studio 2026 and other OpenAI spec-following clients from connecting.

After this change, `serve/server.py` implements the OpenAI-compatible model retrieve endpoint (`GET /v1/models/{model_id}` and `GET /models/{model_id}`). Querying an active model ID or alias returns its individual model object with HTTP 200, while nonexistent models return a standard OpenAI 404 with code `model_not_found`.

## Related discussion
Fixes #5460 (and follows #4100).

## Approach
- In `serve/server.py`, extended the model route condition from `path in ("/v1/models", "/models")` to also match paths starting with `/v1/models/` or `/models/`.
- The list endpoint behavior and output for `GET /v1/models` and `GET /models` remain byte-identical.
- For subpaths: percent-decodes the model ID (`unquote`), matches it against loaded models, aliases, and image models, and returns the single model entry.
- Unknown model IDs return HTTP 404 with OpenAI-shaped JSON (`{"error": {"message": "...", "type": "invalid_request_error", "param": "model", "code": "model_not_found"}}`).

## Validation
**Passed:**
- `python3 -m unittest serve.test_server.ModelAliases -v` on revision `dd2a60c5` (rebased on `upstream/main` `146df3c4`), Linux x86_64, Python 3.14. All 6 tests passed cleanly in 1.08s, including the two new test methods `test_model_retrieve_single_and_alias` and `test_model_retrieve_unknown_returns_404`.
- Manual curl validation against mock server:
  - `curl -s http://127.0.0.1:8080/v1/models/qwen` -> HTTP 200 with model JSON.
  - `curl -s http://127.0.0.1:8080/v1/models/non-existent-xyz` -> HTTP 404 with `model_not_found` error.

**Failed:**
none observed.

**Not run:**
GPU hardware compilation checks (CUDA, HIP, SYCL) - not run because this change touches only Python HTTP routing in `serve/server.py` and has no C++ engine or kernel modifications.

## Limits
None. The endpoint reuses the server's existing model list inspection.
