---
title: "Ray Curled-in-Tail Sleeping and Late-Paw-Yawn Waking Animation"
type: artifact
description: "Natural red panda curled-in-tail sleeping animation and late-paw-yawn waking lifecycle for Strata's lazy loading model states."
status: active
tags: [ray, web, ui, animation, lazy-load, red-panda, rayface]
created: 2026-11-07
updated: 2026-11-07
last_verified: 2026-11-07
---

# Ray Curled-in-Tail Sleeping and Late-Paw-Yawn Waking Animation

## Summary

This walkthrough documents the design, implementation, and verification of Ray's natural sleeping and waking animations for Strata's lazy-load lifecycle (`live.state === "unloaded"`). While the model is unloaded from GPU/RAM, Ray sits on the Code input box curled into a sleeping red panda ball with his head tucked into his bushy tail. When the model finishes loading, he uncurls, stretches, and yawns with his paw rushing up a beat late to cover his open mouth.

---

## 1. Visual Design (`serve/web/rayface.js`)

- **Curled Red Panda Ball (`pose.curl`, `pose.sleepEye`)**:
  - When `pose.curl === 0`, `pose.sleepEye === 0`, and `pose.yawn === 0`, `pandaCell` is byte-identical to the release upright sitting pose.
  - As `pose.curl` approaches `1`, Ray's body forms a round C-shaped russet back (`C.orange`) on the left with a dark brown tucked shoulder (`C.arm`) in the middle. His head bows face-down on the upper-right so his eyes, nose, and mouth tuck behind his striped bushy tail (`tailCell` front pass), while both white fuzzy ears (`earCell`) and a peek of his left white cheek remain visible above the tail.
  - Two well-spaced sky-blue `ZzZ` floaters (`Z_SM`, `Z_MD`, `Z_LG` in `floaters()`) drift up and right on a `3.6 s` cycle, accompanied by a subtle ear dream-twitch every `6.5 s`.
- **Waking & Late-Paw Yawn (`pose.yawn`, `yawnPaw`)**:
  - Over `2.6 s`, Ray uncurls and lifts his head from his tail (`0.0–1.1 s`), stretches his ears back and opens his mouth into a wide yawn showing his pink tongue (`1.1–2.6 s`), and brings his left paw up a beat late to cover his open mouth before transitioning to `wakeNext`.

---

## 2. Loading-State Lifecycle (`serve/web/app.js`)

| State Transition | Header Pill (`#pill`) & Monitor (`#state-label`) | Avatar Behavior |
| :--- | :--- | :--- |
| **Page opens while model is unloaded** (`live.state === "unloaded"` on first poll) | `"Unloaded · sleeping"` | `RayFace.sleep(true)` — appears immediately curled up in his tail on the input box |
| **Live idle timeout or `/unload`** (`"idle"` $\rightarrow$ `"unloaded"`) | `"Unloaded · sleeping"` | `RayFace.sleep(false)` — plays a `1.0 s` curl-to-sleep transition (bows head into tail, wraps tail around, starts `ZzZ`) |
| **Prompt sent or sleeping Ray clicked while unloaded** (`ensure_loaded()` reading weights from disk) | `"Loading model…"` | Ray stays curled up asleep throughout the weight-loading phase (`codeSetState`, `codeEvent`, and `codeSend` gate `RayFace.thinking()` on `!modelUnloaded`) |
| **Weights finish loading into active prompt** (`live.state !== "unloaded"` or first `"thinking"` / `"tool_call"` / `"text"` event) | `"Reading prompt"` / `"Generating"` | `RayFace.wake("think")` — plays the `2.6 s` uncurl + late-paw yawn, then slides his paw to his chin (`mode = "think"`). If fast reply text arrives mid-yawn, `leave()` sets `wakeNext = "leave"` so he finishes yawning before fading out |
| **Weights finish loading with no active prompt** (e.g. after clicking sleeping Ray to pre-load via `POST /load`) | `"Idle"` | `RayFace.wake("warm")` — finishes his `2.6 s` uncurl + late-paw yawn, gives his warm happy nod, and fades out |

---

## 3. Verification

- **JavaScript Syntax & Media Generation**:
  - `node -c serve/web/rayface.js` and `node -c serve/web/app.js` passed with zero errors.
  - `python3 tools/make_ray_media.py` generated `docs/media/ray/sleeping.gif` and `docs/media/ray/waking.gif` while keeping all existing media assets untouched.
- **State-Machine Unit Test**:
  - Verified `RayFace.sleep(true)` (immediate curled pose + a11y label), `RayFace.sleep(false)` (`1.0 s` curl-to-sleep interpolation), `RayFace.wake("think")` interrupted by `RayFace.leave()` (completes full `2.6 s` yawn before leaving), and `RayFace.wake("warm")` (transitions to warm nod after yawning).

---

## Related

- [Ray's Avatar: Red Panda on the Input Box (Thinking and Talking)](../decisions/ray-talking-face.md)
- [Ray: Assistant Name, Voice and Persona](../decisions/ray-assistant-persona.md)

---

## Sources

- User request & `/grill-me` design alignment, chat, 2026-11-07.
- Strata codebase: `serve/web/rayface.js`, `serve/web/app.js`, `tools/make_ray_media.py`.
- Generated media: `docs/media/ray/sleeping.gif`, `docs/media/ray/waking.gif`.
