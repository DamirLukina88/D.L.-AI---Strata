# Ray: how fast it is

Measured speed of this fork on its home workstation, and the settings behind each step.

[← Back to the README](../README.md)

## The numbers

Measured on the workstation this fork is built for, with `tools/strata_bench.py` (`bench.sh`):

- **GPU:** AMD Radeon RX 7600 XT, 16 GB (gfx1102, RDNA3), ROCm 7.2 (HIP)
- **RAM:** 32 GB
- **OS:** CachyOS Linux
- **Model:** `qwen3.8-flash-next-coder-iq1_m`, 64K context, int8 KV cache, MTP draft 4

<table>
<tr><td align="center"><b>34.9 tok/s</b><br>peak chat decode (26.3 median)</td>
<td align="center"><b>381.1 tok/s</b><br>16K prompt ingestion</td>
<td align="center"><b>1.48 s</b><br>chat time to first token</td>
<td align="center"><b>33.6 tok/s</b><br>coding-agent decode (peak 40.2)</td></tr>
</table>

Each column adds switches or tuning to the one before it:

| Metric | A: baseline | B: + adaptive overlap | C: + route tail skip 7 | D1: + route resident 0.5 | E: + fusions, coding expert profile | F: + RDNA3 switches, core isolation | v0.1.43.1 / v0.1.45 config | G: v0.2.3 fixes + `STRATA_HC_Q8=1` | H: `vram-reserve 3072` + LACT (`2800/198W`, `-50 mV`) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chat decode (median) | 20.0 tok/s | 20.7 | 22.7 | 21.0 | 20.9 (peak 31.2) | 18.4 (peak 28.0) | 18.3 (peak 29.8) | 24.2 (peak 32.3) | **26.3** (peak **34.9**) |
| Chat time to first token | 2.03 s | 1.93 | 2.13 | 2.03 | 1.86 | 1.81 | 1.62 | 1.82 (1.66–2.06) | **1.48 s** |
| 4K prompt ingestion | 258.4 tok/s | 265.9 | 264.2 | 268.1 | 268.1 | 265.8 | 277.2 | 302.8 | **346.8** |
| 16K prompt ingestion | 281.8 tok/s | 285.6 | 283.9 | 286.0 | 288.8 | 291.7 | 289.9 | 334.4 | **381.1** |
| 16K time to first token | 57.0 s | 56.3 | 56.6 | 56.2 | 55.7 | 55.1 | 55.4 | 48.1 | **42.2 s** |
| Agent decode | 22.8 tok/s | 21.5 | 23.8 | 26.1 | 25.9 | 21.3 | 20.2 | 25.9 (peak 31.0) | **33.6** (peak **40.2**) |
| Agent turn time to first token | 13.3 s | 13.0 | 12.9 | 12.9 | 12.8 | 12.9 | 12.3 | 11.3 | **10.02 s** |

Numbers are medians over the bench's runs (`tools/strata_bench.py --long` for H, engine `0.1.44.1+0.2.12-fixes` on kernel `7.3.3-1-cachyos`). On `--long` in H, 32K prompt ingestion reached **379.7 tok/s** (`84.47 s`, up from `334.7 tok/s` / `95.82 s` on `2026-11-01`).

A repeat of H on `2026-11-14` (`./bench.sh --long --clients 4` against the running server, same settings) gave: chat decode
**29.7 tok/s** median (`23.5–36.8`), chat first token `1.43 s`, 4K / 16K / 32K prompt ingestion `350.0` / `383.1` /
`381.9 tok/s` (32K first token `83.97 s`), agent decode `32.5 tok/s` (peak `42.3`), agent turn first token `9.88 s`,
conversation cache hit `67.1 %`. Four requests at once gave `22.0 tok/s` in total: the server has one slot, so they run
one after another. Every difference from the first H run is inside the spread of the runs.

**Current GPU setting (since 2026-11-14):** after GPU crashes the card runs at `2500 MHz` max core clock, `150 W`
and `-50 mV` (`/etc/lact/config.yaml`). The table above was measured at Column H's settings (`2800 MHz` / `198 W`)
and the earlier columns before them; the runs at the current setting are below.

**At the current setting** (`2500 MHz` / `150 W` / `-50 mV`, 2026-11-16, `tools/strata_bench.py --long` against the
running server, engine `0.1.44.1+0.2.12-fixes`, two runs a few hours apart; the second right after a server restart):

| Metric | Run 1 | Run 2 |
| :--- | ---: | ---: |
| Chat decode (median, range) | 22.6 tok/s (20.6–35.2) | 25.9 (22.2–35.2) |
| Chat time to first token | 1.63 s | 1.52 s |
| 4K prompt ingestion | 318.7 tok/s | 334.4 |
| 16K prompt ingestion | 343.9 tok/s | 363.8 |
| 32K prompt ingestion | 339.8 tok/s (first token 94.4 s) | 362.3 (88.5 s) |
| Agent decode (median, range) | 28.9 tok/s (23.7–35.7) | 33.5 (23.3–37.4) |
| Agent turn time to first token | 10.96 s | 10.37 s |
| Conversation cache hit | 67.3 % | 67.3 % |

The two runs differ by 5–16%; nothing the bench measures changed between them, so that is the spread from one server
start to the next. Against Column H at `2800 MHz` (4K / 16K / 32K: `346.8` / `381.1` / `379.7 tok/s`), prompt
ingestion at `2500 MHz` is 4–11% slower; decode is inside the run-to-run spread.

**Newest run** (2026-11-21, `2500 MHz` / `150 W`, ROCm 10.1 with Arch's `libamdhip64` as the HIP runtime, engine
`0.1.44.1`, commit `71a5118d`, `tools/strata_bench.py --clients 4 --long` against the running server, 3 runs per test):
chat decode **29.2 tok/s** median (`25.4–43.6`), chat first token `1.44 s`, 4K / 16K / 32K prompt ingestion `344.3` /
`371.5` / `368.3 tok/s` (32K first token `87.1 s`), agent decode **33.7 tok/s** (`25.0–39.2`), agent turn first token
`10.04 s`, conversation cache hit `67.6 %`, four clients `23.3 tok/s` in total. Against the same bench on ROCm 7.2.4 the
day before (same engine and power setting), every figure is within 2%. One 32K prompt of seven froze that day
(first full run, GPU idle during the freeze, cause unknown); the other six passed.

The configuration these numbers were measured with combines Arm E, Arm F, Arm G and Column H: `STRATA_ADAPT_OVERLAP=1`,
`STRATA_ADAPT_OVERLAP_RESIDENT=1`, `STRATA_ROUTE_TAIL_SKIP=7`, `STRATA_ROUTE_RESIDENT=0.5`, fusion and RDNA3 switches,
WMMA prompt GEMMs (`STRATA_HIP_WMMA=1`), the gfx1102 SIMT QSA scorer (`STRATA_SELECT_SIMT=1`), Q8_0 hyper-connection weights
(`STRATA_HC_Q8=1`), core isolation (`STRATA_AUX_CPUS=auto`), a custom expert profile built
from coding traces with `tools/make_profile_mix.py`, `--vram-reserve-mib 3072` (`3,664` GPU cache slots and `1,736/1,736`
RAM lendable prompt slots with `0` file blob reads), and LACT GPU settings (`2800 MHz` max core clock, `198 W` power cap,
`-50 mV` GFX voltage offset; verified with `0` kernel/ring errors across `2,595` hwmon samples and 15 transient spike tests).

