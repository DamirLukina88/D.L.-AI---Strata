# Community benchmark on AMD Radeon

Measured on 2026-10-16 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: AMD Radeon, 16 GiB VRAM
- CPU: AMD Ryzen 5 3600 6-Core Processor (6 cores, 12 threads); installed RAM: 31.3 GiB; storage: not measured
- OS: Linux 7.2.9-2-cachyos; GPU driver: 7.2.9-2-cachyos; CUDA: not read
- Strata: project 0.1.44.1, commit 79e27070; engine 0.1.44.1
- Background workloads and power limits: not recorded

## Model and configuration

- Model and quantization: qwen3.8-flash-next-coder-iq1_m
- Context: 65536 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

## Method

Run by `python tools/strata_bench.py` against the HTTP API of a Strata server (already running); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 88 (85-93) | 0 | 100 (100-100) | 9 | not measured | 24.0 (22.9-28.1) | 1.71 (1.66-1.77) |
| 4K prompt, fresh | 4021 (4021-4021) | 0 (0-0) | 24 cap | 3 | 302.3 (297.3-303.0) | not measured | 13.35 (13.31-13.57) |
| 16K prompt, fresh | 16058 (16058-16058) | 0 (0-0) | 24 cap | 3 | 332.1 (331.6-333.0) | not measured | 48.41 (48.28-48.48) |
| agent session, follow-up turns | 14237 (14171-14240) at the last turn | see below | up to 64 | 3 | see below | 25.4 (14.7-31.8) | 11.27 (6.94-12.12) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 68.5 % (68.1-68.5); earlier-turn tokens read again per session: 4 (2-74) (earlier turns that the cache did not hold; the 13351 (13350-13351) new tokens of the files are read once); first turn (nothing cached) first token: 4.67 s (4.54-4.71).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 647 | 0 | 647 | 143.7 | 4.542 | 20.5 |
| 1 | 3444 | 702 | 2742 | 244.3 | 11.274 | 25.2 |
| 2 | 4977 | 3508 | 1469 | 198.2 | 7.457 | 25.4 |
| 3 | 8421 | 5041 | 3380 | 282.3 | 12.025 | 24.8 |
| 4 | 11336 | 8474 | 2862 | 237.2 | 12.12 | 17.4 |
| 5 | 14237 | 11338 | 2899 | 248.7 | 11.709 | 14.7 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load and power limits are not recorded. Total time of the suite: 460 s.
