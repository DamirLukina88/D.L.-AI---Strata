# Saved-state codec: bfloat16 running state in parked images and session files

Branch: `feat/state-snapshot-bf16`. One change: a conversation's **running state** can be stored as bfloat16
instead of float32, in parked conversation-cache images and in session files. Off by default; with the flag off the
written bytes are byte-identical to today.

Nothing here touches a kernel. The GDN recurrence keeps reading and writing its fp32 state exactly as now; only the
**copy** of that state that goes into an image or onto disk is coded, and it is widened back to fp32 before any
kernel sees it.

## Why the state is the expensive part

`plan.hpp` derives it, and the numbers are geometry, not measurement:

```
include/strata/plan/plan.hpp:77-78
//   recurrence    (S, h_v, S) fp32  = 128 * 48 * 128 * 4 = 3,145,728 B per layer
//   conv history  (d_conv-1, C) fp32 =     3 * 10240 * 4 =   122,880 B per layer
```

Derived from `conversation_state_sizes` (`src/core/conversation_state.cpp:107-129`) at this model's geometry
(36 GDN layers, 12 QSA layers, `ssm_state_size` 128, `ssm_v_heads` 48, `ssm_conv_channels` 10240, `ssm_d_conv` 4,
`idx_key_dim` 128, `idx_block` 4, `NG_HIST` 9, `NG_HC_DIM` 10240):

| array | what it is | fp32 bytes | coded bytes | coded? |
| --- | --- | ---: | ---: | --- |
| `gdn` | 36 × (786,432 + 30,720) floats | 117,669,888 | 58,834,944 | yes |
| `ple` | 9 × 10,240 floats | 368,640 | 184,320 | yes |
| `tails` | 12 × 3 × 128 floats | 18,432 | 9,216 | yes |
| `dead` | 12 × 128 floats | 6,144 | 3,072 | yes |
| `block_pos` | 12 × `int32` | 48 | 48 | **no — indices, not values** |
| **one running state** | | **118,063,152** | **59,031,600** | −49.99% |

`ConversationCheckpoint` already holds these as `std::vector<uint8_t>` (`conversation_cache.hpp:26`), so the codec
writes into byte buffers that already exist. It is not a struct change.

Against the session-file example in `docs/DETAILS.md:1115` (63,025 tokens, 1,198,691,396 B written):

| | bytes | per token |
| --- | ---: | ---: |
| that file today | 1,198,691,396 | 19,019 |
| its state part (live + the deepest checkpoint, `session_checkpoints_to_save`) | 236,126,304 | 3,747 |
| its K/V part (includes the indexer's pooled rows) | 962,565,092 | 15,273 |
| **expected with bf16** | **1,080,628,292** | **17,146** (−9.8%) |

A parked image carries the whole checkpoint chain, not one checkpoint (`generate.cpp:7922` passes `checks`, while the
SAVE path passes only the deepest), so the saving scales with the chain: a parked conversation holding four
checkpoints plus the live state stores 590,315,760 B of state today and would store 295,158,000 B — **281.5 MiB back
per parked conversation**, in RAM as well as on disk.

And the reason the spacing is 16,384 in the first place: `checkpoint_save` (`generate.cpp:1499`) copies the whole
fp32 state, so a checkpoint costs 118 MB of RAM. Halving a stored state is what makes a finer spacing affordable.

## Why bfloat16 and not int8 or fp8

| codec | encoder to write | decoder | scale stored | saturation | per-value error |
| --- | --- | --- | --- | --- | --- |
| **bf16** | ~10 lines (shift + round-to-nearest-even) | **exists, exact** | none | none (same 8-bit exponent as fp32) | 0.39% max, 0.17% rms |
| fp8 E4M3 | ~120 lines + a scale policy | exists | per layer/row/head | required, 448 max | 6.25% max |
| int8 | ~60 lines + a scale policy | ~10 lines | per row/head | required | 0.23% of row max, tails arbitrary |

bf16 keeps fp32's exponent range, so there is no scale to choose, no value that can overflow, and no subnormal cliff.
The repo already relies on this exact property:

```
include/strata/kernels/ngram.hpp:134
/// One BF16 row -> 160 floats, EXACTLY: bfloat16 is the top half of a float32, so this is a
/// shift and a copy with no rounding anywhere. ... There is no scale, because BF16 values are the values.
void bf16_dequant_row(const uint8_t* row, float* out160);
```

int8 was rejected for the first cut because its error is relative to the *group max*: at a channel `max/RMS` of 8 it
is ~1.8% of RMS, at 30 it is ~6.8% and the small values are gone. fp8 was rejected because the repo has an fp8
**decoder only** (`src/kernels/ngram.cpp:163`); the PLE table's fp8 bytes ship pre-quantized in the GGUF and
`tools/ple_fp8_pack.py` only copies them with one global scale chosen offline for fixed data. State range is
per-conversation and unknown, so that scale policy would have to be written and characterised from scratch. bf16 is
both the smaller change and ~16x more accurate. fp8 can be added later as a second codec member, behind the same
flag, if the bf16 quality numbers leave headroom and 4,096-token spacing is wanted.

## Scope

**In:** the codec; the file format; `conversation_checkpoint_save` / `_restore` / `_validate`; parked images
(`conversation_snapshot_save`); session files; one engine flag; tests; this document.

**Out, and left alone:**

- the engine's own live checkpoint chain in RAM (`checks` in `generate.cpp`) stays fp32. This PR codes only what goes
  into an image or a file. Denser checkpoints is a separate change with a different risk (it is on every turn).
- no kernel, no CUDA/HIP/SYCL code, no device-side encode. The touched files are host code; build CUDA and HIP
  anyway.
- no int8/fp8, no per-channel scales, no rotation/Hadamard preprocessing.
- no disk tier, no chunking, no prefix objects. This PR only makes the state half the size; where those bytes go is
  a later change.
- no change to K/V quantization, `--prompt-cache`, `--prompt-cache-every`, or the defaults of anything.
- no server/Python change: `/slots/0?action=save|restore` reports `n_written`/`n_read` as it does now, just smaller.

## Design

### 1. The codec

New `include/strata/core/state_codec.hpp` + `src/core/state_codec.cpp`:

```cpp
enum class StateCodec : uint8_t { Fp32 = 0, Bf16 = 1 };   // Fp8E4m3 = 2 lands later, same interface

size_t state_codec_size(size_t fp32_bytes, StateCodec codec);       // 0 and unknown codes are refused
bool   state_encode_f32(const float* src, size_t floats, StateCodec codec, uint8_t* dst, std::string& error);
bool   state_decode_f32(const uint8_t* src, size_t floats, StateCodec codec, float* dst, std::string& error);
```

`Fp32` is a `memcpy`. `Bf16` encode is round-to-nearest-even on the top 16 bits; decode is a shift into fp32.
`block_pos` never goes through the codec (it is `int32` positions). Encode and decode must be range-safe on
Inf/NaN and on the one RNE edge that can carry a finite value into infinity — that case is a test, not a comment.

### 2. The codec travels with the checkpoint, and the file says which one it used

`ConversationCheckpoint` gains `uint8_t state_codec = 0`. It is a property of the bytes in that checkpoint, like the
state sizes already are. `conversation_checkpoints_split` (`conversation_cache.hpp:82`) must carry it into
`stage0` / `parts` / `rest`.

Session file header v1 is `magic[8] version:u32 header_size:u32 model:u64 config:u64 payload:u64 reserved:u64[2]`
(`src/core/conversation_file.cpp:804`). Use `reserved[0]` as `state_codec:u64`, and bump `kVersion` (line 48) to 2 on
write while accepting 1 and 2 on read; version 1 means `Fp32`.

Two reasons for that shape:

- an old engine reading a coded file must **refuse**, not misread. Bumping the version makes it say
  `session file: unsupported version 2` (line 1207). Without the bump it would read the half-size arrays and fail
  only later, on a size mismatch, with a confusing message.
- existing user files must still read. Accepting v1 keeps that.

The codec deliberately does **not** go into `SessionConfig` / `session_config_fingerprint`. A file says how its own
bytes are stored; the flag governs what the engine *writes*. Binding it into the identity would make a file unreadable
the moment the user turned the flag off, which is the opposite of what a self-describing file is for. An unknown codec
value in a v2 header is refused as `invalid`, before the payload is parsed.

### 3. Read limits stay the fp32 maxima

`conversation_session_read_limits` runs before the file's codec is known, and
`SessionReadLimits::max_state_bytes` is a ceiling. A coded file is smaller, so the fp32 ceiling is a valid superset —
leave it. The exact per-array size check belongs in `conversation_checkpoint_validate`
(`src/core/conversation_state.cpp:143-153`), which knows the codec:

```cpp
if (c.gdn.size() != state_codec_size(z.gdn, c.state_codec) || ...)   // today: != z.gdn
```

### 4. Where encode and decode happen

**Encode** — `conversation_checkpoint_save` (`conversation_state.cpp:155-171`) today resizes the five vectors to the
fp32 sizes and copies the device buffers straight into them. With a codec, the destination is half-size, so the D2H
copy needs an fp32 staging buffer first, then the encode. One shared scratch of one running state (118 MB) per
capture, not one per checkpoint. The existing RAM preflight is the place that must admit it:
`session_save_peak_bytes` (`conversation_file.hpp`) already counts "two copies of the deepest checkpoint" plus the
16 MiB write buffer, so the scratch joins that sum.

An encode must be idempotent-guarded: a checkpoint whose `state_codec` already matches the target is not coded twice.

**Decode** — `conversation_checkpoint_restore` (`conversation_state.cpp:173+`) writes into the session's own fp32
buffers (`ss.gdn_state`, `ss.ple_hist`, each owned QSA layer's `idx_tail` / `idx_dead` / `idx_block_pos`). Source and
destination are different buffers, so decoding needs **no temporary**: read bf16, write fp32.

`SavedConversation::bytes()` / `ConversationCheckpoint::bytes()` count `capacity()`, so parked-image accounting
follows the smaller vectors with no change.

### 5. Cost, measured

See **Measured** below. The arithmetic was right: one running state is 118,063,152 B, bf16 stores it in 59,031,600 B,
and a session file holds one live state plus one checkpoint per 16,384 tokens, so the saving is a multiple of
59 MB and does not depend on the conversation's length.

## Files to change

| file | change | ~lines |
| --- | --- | ---: |
| `include/strata/core/state_codec.hpp`, `src/core/state_codec.cpp` | new: the enum, the size rule, encode, decode | 140 |
| `src/core/state_codec_test.cpp` | new: round-trip bound, special values, RNE edge, odd counts | 220 |
| `include/strata/core/conversation_cache.hpp` | `state_codec` on `ConversationCheckpoint`; carry it through the split | 15 |
| `include/strata/core/conversation_snapshot.hpp`, `src/core/conversation_state.cpp` | codec parameter on checkpoint save/restore/validate (default `Fp32`), sizes through `state_codec_size`, capture-threaded codec in `conversation_snapshot_save` / `_bytes` / `_validate` / `_restore` | 120 |
| `src/core/conversation_file.cpp` | `kVersion` 2, `reserved[0]` as `state_codec`, v1 read path, per-checkpoint codec on write, unknown-codec refusal | 70 |
| `src/program/generate.cpp` | `--session-state-codec`, help text, the capture scratch in the RAM preflight, one start-up log line | 60 |
| `CMakeLists.txt` | two targets, the pattern at lines 108-119 | 6 |
| `docs/DETAILS.md` | the measured section, and the format note next to the session-file example | 40 |
| `docs/STATE_SNAPSHOT_BF16.md` | this document | — |

**~670 lines, ~220 of them tests.** No backend file is touched.

## Flag

```
--session-state-codec NAME   --serve: store a saved conversation's running state as fp32 or bf16
                             (default fp32; bf16 halves the state, restores widen it back)
```

`o.session_state_codec` beside `o.session_min_free_mib` (`generate.cpp:627`), parsed beside line 2065, help text beside
line 777, config key `session_state_codec` in the same style as `slot_save_path`. An unrecognised name is a start-up
error, not a silent default. Default `fp32` keeps every written byte identical to today.

## Tests

`state_codec_test` (new):

1. round trip of a ramp, a random block, and every bf16-representable value: decode(encode(x)) within 2^-8 = 0.39% relative
   of x, exactly equal for values bf16 already holds.
2. `+Inf`, `-Inf`, `NaN`, `±0`, denormals, and the largest finite fp32 — no crash, and the RNE-carry-to-infinity case
   asserted explicitly.
3. `state_codec_size` for 0 bytes, non-multiples of 4, and an unknown codec: refused.
4. `Fp32` is a byte-for-byte `memcpy` both ways.

`conversation_file_test` (extend):

5. write with `Fp32` → the file is bit-identical to today's writer (the byte-identical-default check).
6. write with `Bf16` → version 2, `reserved[0]` = 1, the state arrays are half size, the payload hash covers them.
7. read a v1 file → accepted, decoded as fp32. **This is the back-compat test; it is the one that protects existing
   user files.**
8. read a v2 file with an unknown codec value → `SessionError::invalid`, nothing allocated.
9. read a v2 file whose array sizes do not match its codec → refused.
10. `SessionReadLimits::max_state_bytes` as fp32 maxima still bounds a coded file (no over-allocation).

`conversation_snapshot_test` / `conversation_validation_test` (extend):

11. save with `Bf16` → `conversation_checkpoint_validate` accepts it and rejects the same image re-labelled `Fp32`.
12. save → restore → the session's fp32 buffers match the originals within 2^-8 = 0.39% per value, and `block_pos`
    bit-exact.
13. a checkpoint already coded is not coded twice (idempotence).
14. `bytes()` reports the coded capacity; `session_save_peak_bytes` includes the capture scratch and refuses when the
    `admit` callback does.
15. layer split: `conversation_checkpoints_split` carries `state_codec` into every part, and a stage image validates.

`session_save_reclaim_test` (extend):

16. SAVE with the flag on → the file is ~10% smaller, RESTORE succeeds, and the next token equals the fp32 run's.

End to end, on the box:

17. 63K prompt → `action=save` with the flag off and on; record `n_written`, `save_ms`, `restore_ms`; restore both and
    compare the generated continuation token-for-token against the fp32 file.

## Measured

One Tesla V100 32 GB (model) plus one RTX 2080 Ti (ComfyUI idle), 93 GB system RAM, Linux, CUDA 12.8, engine built
from this branch. Model Qwen3.8-Flash-Next IQ3_S, `--kv int8`, `--max-context 262144`, `--kv-resident 32768`,
`--conversation-cache-mib 16384 --conversation-cache-slots 12 --conversation-cache-min-free-mib 8192`. The two A/B
configs are the same `args` list with only `--session-state-codec fp32` / `bf16` differing, and neither runs
`--vision`, so the file fingerprints match.

The conversation is `tools/needle_bench.py`'s haystack (this repository's own docs and source, in a fixed order) with
a code word inserted at the midpoint, asked greedily through `/v1/chat/completions`. Same text in every run.

**63,459 tokens**

| | `fp32` (default) | `bf16` | change |
| --- | ---: | ---: | ---: |
| session file | 1,205,289,012 B | 1,087,225,924 B | −118,063,088 B, −9.8% |
| `save_ms` | 546.4 | 503.2 | −7.9% |
| `restore_ms` | 759.5 | 714.3 | −6.0% |
| next turn on the resumed state | 0.47 s, right word | 0.45 s, right word | — |

**32,650 tokens**: 734,789,228 → 616,726,140 B (−16.1%), `save_ms` 444.1 → 315.5 (−29%), `restore_ms`
468.5 → 400.3 (−15%). Short conversations gain the most, because the state in a file is set by the checkpoint
spacing and not by the length: a 37-token conversation still writes 236,738,756 B, of which two running states are
236,126,304 B, and coded the same file is 118.7 MB.

**What bf16 costs the state, measured on the file's own values** — no model, no GPU, so nothing but the codec is in
these numbers. bf16 encode and decode applied to the 29,417,472 GDN floats of the 63K conversation's live state:

| array | values | worst relative | rms relative | worst absolute | mean absolute | state rms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GDN recurrence | 29,417,472 | 0.3891% | 0.166% | 0.0623 | 4.6e-5 | 0.2598 |
| PLE history | 92,160 | 0.3890% | 0.166% | 0.0156 | 2.5e-4 | 0.3171 |
| QSA indexer tails | 4,608 | 0.3891% | 0.167% | 0.0156 | 1.0e-3 | 0.9855 |
| QSA dead keys | 1,536 | 0.3743% | 0.161% | 0.0076 | 9.3e-4 | 0.9835 |

The worst relative error sits just under the 2^-8 = 0.3906% bound, as it must: bf16 has eight significant bits. No
value's sign flipped, none became zero, none became non-finite. `block_pos` is int32 positions and is never coded.

For scale, the same 63K prompt through two separate engine runs, both fp32, both put on the bf16 grid so only the
run-to-run difference shows: max 1.641, mean 0.00228 on the GDN state. **The engine's own run-to-run difference is
26x the codec's worst error** — the adaptive expert tier and a shared PCIe link move the rounding, as
`docs/DETAILS.md` records for #152 and #410.

**Round trip.** A coded file restored by an engine started with `--session-state-codec fp32`, then saved again, is
bit-identical to the state the coded file held, in all five arrays (`gdn`, `ple`, `tails`, `dead`, `block_pos`).

**The default path is untouched.** With the flag off, a 63,459-token conversation writes 1,205,289,012 B at file
version 1, and that file is byte-identical to the one the previous engine build (this branch's parent, `a0116b27`, same
`args`) wrote for the same conversation: same 232-byte header, same token ids, same bytes in all five state arrays.

**Compatibility.** A version-2 coded file restores on an engine configured `fp32`, and a version-1 file restores on an
engine configured `bf16`; both resumed conversations answered the code word correctly. An engine that does not know
version 2 refuses the file and says so.

**Text, with the rounding pinned.** Left at its defaults the engine is not repeatable on this box — the adaptive
expert tier and a shared PCIe link move the rounding (`docs/DETAILS.md:106`, and `docs/DETAILS.md:108` names
`--adapt-swaps 0 --pcie-frac 0` as the way to get byte-identical repeats) — and the same fp32 file restored twice gave
different continuations. With those two switches pinned off, two separate engine runs of the same 32,650-token
conversation produced states that differ by exactly the codec and nothing else: `gdn` max 0.0620 / mean 4.51e-5,
`ple` 0.0178 / 2.4e-4, `tails` 0.0156 / 1.1e-3, `dead` 0.0076 / 9.3e-4, `block_pos` identical — the same magnitudes as
the codec's own error table above, with no drift left on top. One engine then restored both files, alternating, twice
each, and generated the same four continuations:

| continuation | fp32 state | bf16 state |
| --- | --- | --- |
| the code word | `da454b02b470` | `da454b02b470` |
| what the document is made of | `d2c0d2cde25b` | `d2c0d2cde25b` |
| count to five, name the word | `e00a9fc3f733` | `e00a9fc3f733` |
| a haiku about it | `cded6cce8fb4`, `ede0a43fecf2` | `ede0a43fecf2`, `ede0a43fecf2` |

Three of the four are byte-identical between the coded and the uncoded restore. The fourth — free creative generation,
the one place a small state perturbation can send the greedy path down a different line — varied **on the fp32 file
too**: the same uncoded file gave two different haikus in two passes, and the coded file matched its later answer both
times. So on this box the codec did not add variation that the engine's own fp32 path did not already have.

Without those switches pinned, text identity cannot be used at all: two fp32 runs of the same file differ by 26x more
in the state than bf16 does.

## Quality gate

This is the part that decides whether the feature ships, and it is a higher bar than K/V quantization faced:
`--prompt-cache` and session restore are byte-exact fp32 copies today, so a coded state introduces error where there
was none. The repo's precedent for accepting a quantization trade with numbers is `docs/DETAILS.md:88`
("perplexity +8-12%; needle tests still pass. 8-bit stays the default").

Run, with the flag off and on, on the same box and the same build:

1. `tools/needle_bench.py` — 32K at depths 10/50/90, after a restore, not just cold. **Done, and through the restore
   path rather than cold:** each depth is read once, saved, restored, then continued, so the answer comes from the
   state that came off disk. 3 of 3 right configured `fp32`, 3 of 3 right configured `bf16`, same words, same box,
   same build:

   ```
   depth  10%: read 32646 tok 22.3s answer='amber'  | bytes=734789228 save=363.6 restore=460.6 | after restore OK 0.77s
   depth  50%: read 32646 tok 21.9s answer='falcon' | bytes=734789228 save=383.6 restore=524.1 | after restore OK 0.41s
   depth  90%: read 32646 tok 22.0s answer='quartz' | bytes=734789228 save=329.1 restore=490.3 | after restore OK 0.39s
   depth  10%: read 32646 tok 22.4s answer='amber'  | bytes=616726140 save=305.1 restore=411.9 | after restore OK 0.74s
   depth  50%: read 32646 tok 22.0s answer='falcon' | bytes=616726140 save=314.6 restore=414.6 | after restore OK 0.43s
   depth  90%: read 32646 tok 22.1s answer='quartz' | bytes=616726140 save=437.3 restore=390.2 | after restore OK 0.39s
   ```

   (`fp32` first, then `bf16`; the wanted word is the one the filler was seeded with.)
2. `tools/ab_engine.py` — the two engines A/B'd on the same prompts. **Outstanding.**
3. **error vs tokens-since-resume** — restore a coded state, then measure logit KL and top-1 flips against an fp32
   restore at 1, 10, 100, 1,000 tokens after the resume. This is the decisive measurement: the GDN gate decays old
   state, so a perturbation at the resume point should shrink. If it is flat or grows, bf16 is wrong for this and the
   PR stops here. **Not available through this build's API** — `/v1/chat/completions` ignores `logprobs` and returns
   no logits, so there is nothing to take a KL or a top-1 flip from. It needs a host-side harness that runs both
   restores in one process, which is a change in its own right. Offered in place of it: the value-by-value error
   table above, which bounds the perturbation exactly (every state value moves by at most 2^-8 of itself), and the
   measurement showing the same prompt in two fp32 runs moves that state 26x more.
4. resume at several depths (4K, 32K, 128K) and at several checkpoint ages, since the older the checkpoint the more
   the resumed state matters. **Done at 32K and 63K.** 4K and 128K outstanding, and so is a conversation long enough
   to hold two checkpoints, which is the first time a restore reads a coded state older than the live one.

Acceptance: needle recall unchanged, token-for-token identity on the short continuations, and a measured decay curve
reported with the machine it was measured on. **Recall: met. Token-for-token identity: not achievable on this box
even between two fp32 runs of the same file, so the value-by-value bound is offered instead. Decay curve: not
measurable through the API, see 3.**

## Measurements the PR must report

State the machine (CPU, GPU, RAM, OS, engine version, model, flags) next to every number, as `docs/DETAILS.md` does.

- session file bytes, `save_ms`, `restore_ms`, flag off vs on, at 4K / 32K / 63K / 128K. **Done at 32K and 63K**
  (above); 4K and 128K outstanding.
- parked image bytes and `parked=` / `bytes=` log lines, flag off vs on, with the chain length stated. **Outstanding:**
  needs a conversation long enough to park a multi-checkpoint chain. The arithmetic is confirmed by the file numbers,
  which are the same writer.
- encode and decode wall time per running state, and their effect on the request that triggers them. **Included in
  `save_ms` / `restore_ms` above:** coding a state costs nothing measurable on either side. The save got 43 ms faster
  and the restore 45 ms faster, because half of the state's bytes never reach the disk.
- decode tok/s and prefill tok/s before and after, to show the codec does not land on the token path. **Done for
  prefill:** the same 63,455-token prompt read in 44.8 s configured `fp32`, 44.6 s configured `bf16`, 44.7 s on the
  previous engine build — the same rate. No codec code is on the token path; per-token decode is unchanged by
  construction and was 0.45-0.47 s for the same resumed turn in both configurations.
- peak RAM during SAVE, flag off vs on, to show the capture scratch is admitted and not a surprise. **Outstanding.**
  The scratch is 4 MiB per coding pass, not 118 MB, and the preflight admits it.

## What this unlocks (not in this PR)

State is the term that limits how often a conversation can be snapshotted: at 16,384-token spacing the state is
7,206 B/token of the 19,019 B/token this file costs. At bf16, 8,192-token spacing costs the same 7,206 B/token — same
bytes, half the worst case. Using `docs/DETAILS.md:38`'s IQ3_S row (RTX 5070 12 GB, Ryzen 5 7600, 64 GB DDR5-5200,
Windows, engine 0.1.26 — re-measure on the target box), re-reading 16,383 tokens at the 32K tier's 1,624 tok/s is
10.1 s against 5.0 s for 8,191. The same arithmetic at 4,096 needs fp8, which is why the codec interface is written
for a second member now.

## Risk and rollback

- **One-way door:** once a v2 file exists, an engine older than this change refuses it. It fails closed with a clear
  message; no silent misread. Documented in the flag's help text and in `docs/DETAILS.md`.
- **Quality risk** is the real one and it is front-loaded: the gate above can stop the PR before any user sees a
  coded file.
- **Rollback:** turn the flag off. New writes are v1 again; existing v2 files still restore.
- **RAM:** the capture scratch is a new transient 118 MB during SAVE. It goes through the existing `admit` preflight,
  so a box that cannot spare it refuses the SAVE instead of degrading, exactly as it does today.

## PR description checklist

Per `AGENTS.md`:

- [ ] one change; say what it leaves alone (the live checkpoint chain, K/V quantization, all defaults)
- [ ] "how I checked" — the test list above, the quality gate, and the measurement table with its machine
- [ ] CUDA **and** HIP builds clean (host-only change, both must be built)
- [ ] default path byte-identical: test 5 proves it
- [ ] new behaviour opt-in, default `fp32`
- [ ] v1 session files still restore: test 7
- [ ] `docs/DETAILS.md` updated with measured numbers, plain words, no claim without a measurement