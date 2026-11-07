## Title
[Engine] Graceful server recovery and engine respawn on fatal GPU error
Issue: Resolves #4350

## Summary
Prevents persistent server outages when an unrecoverable GPU memory fault or kernel execution error occurs (e.g. invalid memory access during conversation state swap or out-of-memory under saturated cache). Instead of hanging client threads or failing all subsequent requests indefinitely, the engine exits with a dedicated error code, and the server returns a clean HTTP 503 while automatically respawning a fresh engine instance on the subsequent request.

## What changed
- `src/program/generate.cpp` / Engine error paths:
  - On fatal GPU execution faults, the engine writes `ERR fatal GPU error: <details>` to stderr and terminates cleanly with exit code 3 (leaving the operating system memory clean).
- `serve/server.py`:
  - Added detection in `Engine.wait_ready()` and request processing: `if (self.last_err or "").startswith("fatal GPU error"): ...`.
  - Terminates the failed request with HTTP 503 (`Service Unavailable: engine experienced a fatal GPU error and is restarting`).
  - Automatically initializes and spawns a new engine process for the next request.
  - Added safety guard limiting automatic respawns to at most 3 times in 10 minutes to prevent crash loops on permanently broken configurations.
- `serve/test_fatal_gpu_restart.py`:
  - Added 7 automated test cases verifying that the server survives fatal GPU error triggers, returns 503 on the failing turn, and successfully processes the next request on a fresh engine process.

## Extra Notes
- **Verification**:
  ```bash
  python3 -m unittest serve.test_fatal_gpu_restart -v
  ```
  Passes all 7 tests.
- **Hardware notes**: Tested under AMD ROCm HIP (`gfx1102`); server-side lifecycle management is backend-agnostic (CUDA/HIP/SYCL).
