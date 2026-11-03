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
<tr><td align="center"><b>32.3 tok/s</b><br>peak decode</td>
<td align="center"><b>334.4 tok/s</b><br>16K prompt ingestion</td>
<td align="center"><b>1.62 s</b><br>chat time to first token</td>
<td align="center"><b>25.9 tok/s</b><br>coding-agent decode</td></tr>
</table>

Each column adds switches to the one before it:

| Metric | A: baseline | B: + adaptive overlap | C: + route tail skip 7 | D1: + route resident 0.5 | E: + fusions, coding expert profile | F: + RDNA3 switches, core isolation | v0.1.43.1 / v0.1.45 config | G: v0.2.3 fixes + `STRATA_HC_Q8=1` |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chat decode (median) | 20.0 tok/s | 20.7 | 22.7 | 21.0 | 20.9 (peak 31.2) | 18.4 (peak 28.0) | 18.3 (peak 29.8) | **24.2** (peak **32.3**) |
| Chat time to first token | 2.03 s | 1.93 | 2.13 | 2.03 | 1.86 | 1.81 | **1.62** | 1.82 (1.66–2.06) |
| 4K prompt ingestion | 258.4 tok/s | 265.9 | 264.2 | 268.1 | 268.1 | 265.8 | 277.2 | **302.8** |
| 16K prompt ingestion | 281.8 tok/s | 285.6 | 283.9 | 286.0 | 288.8 | 291.7 | 289.9 | **334.4** |
| 16K time to first token | 57.0 s | 56.3 | 56.6 | 56.2 | 55.7 | 55.1 | 55.4 | **48.1** |
| Agent decode | 22.8 tok/s | 21.5 | 23.8 | **26.1** | 25.9 | 21.3 | 20.2 | **25.9** (peak **31.0**) |
| Agent turn time to first token | 13.3 s | 13.0 | 12.9 | 12.9 | 12.8 | 12.9 | 12.3 | **11.3** |

Numbers are medians over the bench's runs. The active configuration combines Arm E, Arm F and Arm G: `STRATA_ADAPT_OVERLAP=1`,
`STRATA_ADAPT_OVERLAP_RESIDENT=1`, `STRATA_ROUTE_TAIL_SKIP=7`, `STRATA_ROUTE_RESIDENT=0.5`, fusion and RDNA3 switches,
WMMA prompt GEMMs (`STRATA_HIP_WMMA=1`), the gfx1102 SIMT QSA scorer (`STRATA_SELECT_SIMT=1`), Q8_0 hyper-connection weights
(`STRATA_HC_Q8=1`), core isolation (`STRATA_AUX_CPUS=auto`), and a custom expert profile built
from coding traces with `tools/make_profile_mix.py`.

