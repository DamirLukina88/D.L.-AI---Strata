---
title: "Ray's Avatar: Red Panda on the Input Box (Thinking and Talking)"
type: decision
description: "Dot-matrix red panda sitting on the Code tab input box: thinks while the model works, animates to Piper server audio, About switches; history of the face iterations"
status: active
tags: [web, tts, ray, code-tab]
created: 2026-10-28
updated: 2026-10-29
last_verified: 2026-10-28
---

# Ray's Avatar: Red Panda on the Input Box (Thinking and Talking)

## Summary

**Current (2026-10-28):**
- **Look:** Ray is a red panda drawn in dots (`serve/web/rayface.js`), sitting on the top-left edge of the Code tab's input box, with no box around him.
- **Thinking:** paw on his chin, with question marks rising.
  - A typed prompt shows him from Send until the first answer text (he stays through tool calls), then a quick fade.
  - A spoken prompt shows him thinking, then talking to the Piper server audio, then a warm goodbye.
- **About switches:** "Show Ray while speaking" (`tts_orb`) and "Show Ray thinking on every prompt" (`tts_think_all`).
- **The same panda is the app icon:** `tools/make_ray_icons.py`.
- **Below:** the sections in date order record every iteration; the ones before "Red panda on the input box" are history.

First version (replaced):
Added 2026-10-28 in serve/web/rayface.js (commit 616ec4c6). Choices made with the user: docked above the input (card bottom-right on wide screens, a full-width 112 px strip on phones at 768 px and below); lips estimated from the text because browser speechSynthesis gives no audio; expressions from simple rules on each sentence (no prompt change); shown for any speech (auto-speak and the speaker button), not for the Settings test button.

## Key Facts

- **Hooks** in `TTSController` (`serve/web/app.js`): `u.onstart` calls `RayFace.say(chunk, rate)`, `u.onboundary` calls `RayFace.boundary(charIndex)`, `u.onend` calls `RayFace.chunkEnd()`, and `pause`/`resume` call `RayFace.pause()`. `stop()` calls `RayFace.end(finished)`: about 1 s of warm face after a finished reply, half that after a manual stop, then a 240 ms fade. It fades in over 140 ms.
- **Lip sync:** each chunk gets an estimated timeline (13.5 characters/s at rate 1, spaces at 0.55 of a letter, 0.22 s at `,;:`, 0.42 s at `.!?`). Word-boundary events resync it. The speed is learned from each chunk's real length (moving average, clamped 0.6-1.8). There are 10 mouth shapes by letter class.
- **Expressions:** neutral, happy, excited, surprised, curious, thinking, concerned, and warm (the goodbye). Rules are checked in order on each sentence: concerned words (error, failed, sorry…) > wow/whoa > ending in `!` > ending in `?` > happy words > maybe/hmm. There are also blinks every 2.2-5.4 s and small glances.
- **Drawing:** a 44×26 face grid on a canvas. Wider panels show more dark dots around it. Lit dots are sky blue `#38bdf8`, the brightest near white. The display stays dark in both themes.
- **Toggle:** About > voice card, "Show Ray's face while speaking" (`localStorage` key `tts_face`, on by default). Turning it off mid-speech fades the face out.
- **Gotcha:** in a hidden browser pane `requestAnimationFrame` does not run, so the face does not animate there. The timeline logic was tested in Node with stubs instead (`RayFace.state` exposes the live values).

## Verification (2026-10-28)

- Node with stubs: the mouth opens and closes along the text; happy, then concerned on "failed with an error", then curious on the question; the warm face at the end; hidden after the fade. A mood check: "Is it ready?" gives curious.
- Built-in browser: the card appears in the Code column in split view at 1280×800, and the strip above the input at 375×812. The toggle changes `isFaceOn()`.
- Not tested yet: real speech on the PC (Piper through speech-dispatcher) and on a phone, including whether those engines send word-boundary events.

## Step 1 of the sync work (2026-10-28, commit after 616ec4c6)

- The user found the face "ok", but asked for it to look more female. On the PC the lips kept moving through the speech's pauses.
- **Cause:** the PC voice goes through speech-dispatcher's generic Piper module, which sends no word-boundary events and reports `start` before Piper has made the audio. It also adds 0.2 s of silence after each sentence. The face can only estimate, so this cannot be fixed with browser TTS alone.
- **Plan agreed in steps, so each can be evaluated:**
  1. English mouth shapes, the female look and click-to-stop (done).
  2. Server-side Piper audio, with the mouth driven by the audio's loudness. This also gives phones Ray's Piper voice.
  3. Maybe later: TalkingHead's HeadAudio, which detects mouth shapes from the audio itself.
- **Measured Piper cost for step 2:** about 0.6 s of CPU wall time for 8.5 s of speech (one ~150-character reply, `en_US-hfc_female-medium`, model loaded per run, 12-thread CPU). That is about 154 MB peak RAM per run, and the 22,050 Hz 16-bit WAV is about 43 KB per second of speech (about 365 KB per 8.5 s).
- **Mouth shapes:** `serve/web/lipsync-en.js` is ported from TalkingHead's `modules/lipsync-en.mjs` (MIT, Mika Suominen, commit 166b443a), with the license text kept in the header. It has the letter-to-sound rules and viseme durations; number expansion is left out, and digits are spoken as single digit names. One viseme unit is 0.088 s at rate 1. Pauses in units: space 0.8, `,;:` 3.5, `.!?` 5.5.
- **Look:** bigger eyes (rx 4.1) with a white iris that follows the gaze plus a dark catchlight, two lash dots flicking up and out, thin arched brows at 60% brightness, a pink blush under the eyes (stronger when smiling), and rose lips (`#f9a8d4`) with a small dip in the upper lip.
- **Click to stop:** the panel is `role="button"`; click or Enter calls `RayFace.onStop`, which is set to `TTSController.stop()`. When faded out it has `pointer-events: none`.

## Portrait restyle (2026-10-28)

- The user disliked the cartoon look and the pink, and sent two reference images of a blue holographic face in a white shell (Overwatch's Echo).
- **Now:** a shaded blue portrait on the dot matrix in the original palette (`#38bdf8`, near white above 0.8). It has an oval face narrowing to a soft chin, almond eyes with a winged liner and glowing irises, a light nose bridge and tip with dark nostrils, and fuller lips (the lower one catches the light). A white shell covers the forehead and sides, parted from the face by a dark seam.
- The reference's forehead emblem is deliberately not copied: the design is inspired by it, not a copy of the character.
- **Grid:** 36×46 face units drawn at 1.35 dots per unit. The panel is 156×192 px on wide screens, and the phone strip is 150 px tall.
- The `arc` expression channel became `squint`: happy and warm lift the lower lids and the cheeks instead of drawing ^ ^ eyes.

## Back to the first style (2026-10-28)

- The user "completely" disliked both later looks: the pink cartoon (6dc050f8) and the shaded portrait in a shell (73099f88). They asked for the first style with a slight female tweak.
- **Now:** 616ec4c6's 44×26 grid, expressions (happy ^ ^ arcs) and blue palette are back, with the 216×132 panel and the 112 px phone strip. The female touches, all in blue: two lash dots at each outer eye corner, thin arched brows at 60% brightness, slightly rounder eyes (rx 4.4, ry 3.5), and a soft, shorter lower lip under the closed mouth line.
- **Kept:** TalkingHead's English mouth shapes, click-to-stop and the About toggle.
- **Preference:** keep the face simple and in blue; no pink and no realistic portrait.

## Replaced by a voice orb and the server voice (2026-10-28)

- The user still found the face uncanny. They asked for the approach from a note they pasted: a synthetic Piper voice should not get a human face. Instead: a small audio-reactive shape off to the side, with a colour shift while thinking and a settle at the end. The motion should lead the audio by about 1 to 3 frames.
- **Server voice:** `serve/speech.py` serves `POST /v1/audio/speech` (OpenAI-style `input`, `voice`, `speed`; WAV) and `GET /v1/audio/speech/status`. It runs `~/.local/bin/piper` (old C++ piper, no alignment output) with `en_US-hfc_female-medium`. OpenAI voice names (alloy, nova…) map to Ray's voice. `--sentence_silence 0.25`, at most 2 runs at once, 4,000 characters per request. Measured on this PC: 0.39 s for 3.4 s of speech; requests without the key get 401.
- **Web app:**
  - `TTSController` fetches each 240-character chunk from the server and plays it through Web Audio, fetching the next chunk while the current one plays.
  - The path is source → analyser → 50 ms delay → speakers, so the orb sees the sound before it is heard.
  - If a request fails, the rest is read with the browser voice until reload, with a toast.
  - About has "Use Ray's voice from the server (Piper)" (`tts_server`, on).
  - The first tap or key press unlocks Web Audio, which phones require.
- **Orb (`serve/web/rayorb.js`):**
  - Size: 76 px (60 px on phones) at the bottom right of the Code feed, above the input box.
  - Motion: the edge waves with the loudness (RMS with a noise gate, fast attack, slower release). The spectral centroid of the voice pushes it towards cyan and faster ripples. Strong onsets send out a ring.
  - States: indigo with a circling highlight while Ray thinks about a spoken prompt (from send until the answer is read, or the turn ends with nothing to say). The browser voice gets a text-estimated pulse.
  - The end: a 1.1 s settle with one soft breath out, then a 0.7 s fade (fade-in 0.18 s). A click or Enter stops the speech.
  - About has "Show Ray's voice orb" (`tts_orb`, on).
- **Removed:** the dot-matrix face (`rayface.js`) and the TalkingHead viseme port (`lipsync-en.js`); they are in git history (9c7105ef).
- **Verified:** `serve/test_speech.py` (3 tests), and the live endpoint (200 with the key, 401 without). In the built-in browser with stubbed speech audio, the orb's level followed the syllables and dropped in a 0.5 s pause; it was indigo `(129,140,248)` while thinking and blue `(61,193,248)` while speaking; a failed request fell back to the browser voice; a click stopped it. Node with stubs covered the browser-voice pulse and the settle and hide.
- **Not verified:** real Piper audio heard through the speakers, and phones.

## Original face with a waveform mouth (2026-10-28, replaced)

- The user tried the orb with real speech on the PC and the phone; the server voice works on both. They then asked for:
  - the first face's style and palette, which looked neutral (neither male nor female), with the lips replaced by a waveform in the same style;
  - calmer motion;
  - a small thinking avatar in the same style with a subtle thinking animation, at the left (instead of a thinking circle);
  - the talking box on phones as a box, not full width.
- **Face (`serve/web/rayface.js`):**
  - Drawing: 616ec4c6's 44×26 grid, eyes, brows, moods and blue palette.
  - Mouth: 9 dot columns each side of the centre on a line that curves with the smile. Bar heights come from 10 log bands of 120-4,000 Hz times the gated loudness (server voice), or from a text-estimated loudness (browser voice). The bars rise quickly (0.32 per frame) and fall slowly (0.09).
  - Calmer motion: expression easing 0.06 per frame, glances every 3.5-7 s (60% back to centre), blinks every 3-6 s, and a 0.9 s nod at the end.
  - The end: a 1.8 s warm goodbye after a finished reply (0.9 s after a stop), then a 0.7 s fade. It fades in over 0.16 s.
- **Thinking face:** 112×70 px (96×60 on phones) at the bottom left above the input box. It shows from a spoken prompt's send until Ray speaks or the turn ends. The eyes look up and drift side to side (about a 16 s cycle), the brow asymmetry follows the gaze, it blinks every 3.5-6.5 s, and a soft light moves along the closed mouth. A new spoken prompt during the last reply's goodbye ends the goodbye at once.
- **Sizes:** the talking box is 216×132 px, and 176×108 px on phones, bottom right.
- **Kept:** the server Piper voice, the 50 ms lead, click-to-stop and the About toggles (`tts_server`, `tts_orb`). The orb (`rayorb.js`) is removed, but it is in git history (4ab332f6).
- **Verified:** Node with stubs (waveform levels, moods, warm goodbye, thinking show and hide). In the built-in browser with stubbed audio: the face at 1280×800 and 375×812, the thinking face at the bottom left, and the handoff from thinking to talking and back.

## Calmer, softer, neutral (2026-10-28)

- **User feedback with real speech:** the motion was not calm enough, the thinking face looked angry, the waveform looked too much like an open mouth, and the brows looked angry and male. The ending was good. They want it "more neutral but pleasant".
- **Changes:**
  - Brows: short (half-width 3.3), faint (55%), softly arched; the inner end can only rise, never drop.
  - Moods: used at 60% of their distance from neutral and held at least 2 s. Neutral has smile 0.3 and a hint of the happy eye arc (0.1). Concerned is mild (tilt 0.6, smile -0.1), and thinking is friendly (brows up, smile 0.15).
  - Mouth: a thin waveform line travelling along the mouth, at most 1.6 cells high, with neighbouring columns joined.
  - Motion: easing 0.035 per frame; glances every 6-10 s, 70% back to centre, smaller; blinks every 3.5-7 s; loudness attack 0.2 and release 0.06.
  - Thinking face: gaze drifts side to side, the right brow rises a little only when looking right, smile 0.2.
- **Kept:** the ending (1.8 s warm look and nod, 0.7 s fade).

## Level-meter mouth; Ray is male (2026-10-28)

- **The user's choices:** the mouth should look like a volume meter / frequency bar chart animating from the centre outwards. The bars grow up and down from the mouth line, and the motion is a ripple from the centre. For the extras, they had no preference; I chose gaps between bars and bright tips, and no peak-hold dots, since those would make it busier.
- **Mouth:** 5 bars each side (every second column, so one-dot gaps), plus the plain mouth line between them. Each frame stores the loudness in a 64-frame history. Bar k shows the loudness from 3k frames ago (about 50 ms per step at 60 fps), times (1 - 0.12k), at most 2.4 cells each way. Bars rise at 0.3 per frame and fall at 0.08. The tip dots are near white and the body blue.
- **Same day, after the user saw it** ("Mouth looks creepy. Remove the extras you added"): no gaps and no bright tips. Every column is a bar (10 each side), all one brightness (0.85). Bar k shows the loudness from 2k frames ago (about 35 ms per step), times (1 - 0.07k).
- **Removed:** the spectrum read (the meter uses loudness only); the `readAudio` analyser is RMS only now.
- Ray is now male (he/him), with the Piper HFC male voice: see [Ray: Assistant Name, Voice and Persona](ray-assistant-persona.md).
- **Verified:** in the built-in browser with stubbed audio the bars were `1.73 1.69 1.58 1.41 1.17` from the centre out mid-speech, and the screenshot shows gapped bars on the line. Server status reports `en_US-hfc_male-medium`, and a request returned 200 in 0.34 s.

## Mouth studies page (2026-10-28)

- While reviewing the meter mouth, the user asked for animated mouth options as pictures only, with no app code changed. They are on a private artifact: `https://claude.ai/artifact/WVj4L2EtyXS8jVnUuevp3j`.
  - Options 1-10: the current meter, Breathing line, Oscilloscope, Pulse dots, Soft jaw, Equalizer, Smile flex, Trio, Echo dashes, Glow line.
  - Options 11-20 were asked for "like the soft jaw / breathing line" with **no mouth visible when not talking**: Soft oval, Pill, Lens, Round O, Open smile, Parting lips, Bloom, Crescent, Squash pill, Ripple ring.
- **Correction from the user:** what they meant is "a single or multiple lines expanding horizontally when talking, condensing to the middle when there is no volume, and disappearing when not talking". Set two (11-20) was replaced with ten such line mouths:
  - single lines: Single line, Soft-ended line, Dotted line, Split line, Smiling line, Thick centre;
  - more than one line: Two lips, Short top long bottom, Three lines, Echo lines.
  - Their length follows the loudness. They open fast (0.35 per frame) and close slower (0.07), and nothing is drawn below a one-dot half-length.
- **Preference so far:** a mouth that is only horizontal line(s) whose length follows the voice, with no mouth when silent. The bar-meter extras (gaps, bright tips) looked creepy.

## Expression studies from animation research (2026-10-28)

- **User feedback:** "All of them are uncanny valley", meaning every mouth on the mouth studies page, including the line mouths. They asked for research on Pixar face animation and expression motion, and 20 completely new examples on Ray's face.
- **Research summary** (sources on the artifact page):
  - Anki's Cozmo and Vector (animated by former Pixar artists) and Pixar's EVE have no mouth: the emotion is in eye shape and timing. The WALL-E team relied on timing and motion because there was no mouth to smile with.
  - Blinks should be motivated, on a change of thought; large eyes blink more slowly.
  - A moving hold keeps a still pose alive.
  - Anticipation, ease in and out, and follow-through.
  - Squash and stretch that keeps volume.
  - Asymmetry and arcs for appeal (Victor Navone's Pixar facial animation workshop lists asymmetry and appeal).
- **Studies page:** private artifact `https://claude.ai/artifact/WVj4L2EtyXS8jVnUuevp3j` is the mouth page. The expression page is the separate private artifact `https://claude.ai/artifact/FJ5wjeYXHsgUva1YdaE92Q`. It has 20 studies, each one principle, mostly without a mouth:
  - Syllable squash, Smiling on the beat, Emphasis nod, Breath first, Thought blink;
  - Moving hold, Look on an arc, Settle after a line, Blink the look away, One-sided squint;
  - Surprise stretch, Curious tilt, Lean in, Inner light, Talking lids;
  - Accent only, Listening nods, Soft worry, Warm goodbye, All together.
- **Direction:** move away from mouths that copy speech; carry speech through eye squash, lids, timing and whole-face motion.

## Red panda on the input box (2026-10-28, current)

- **The user's direction:**
  - Ray's character is a little red panda: our own design, drawn on the dot matrix, with a reference image used only as a starting idea.
  - The palette is the display's blues plus a few oranges, browns and whites. He has a round, sitting body, no window or container, and sits at the top edge of the input box at the left, with less clutter and no overlap with buttons.
- **Preference:** the reference is only the base idea; the design must stay clearly our own and different from it, and project texts, code comments and commits never describe or name the reference.
- **Drawing (`serve/web/rayface.js`):**
  - A 46×40 dot grid.
  - Head (`headCell`): wide orange, big white ears with orange at the base, a dark fur tuft, slanted white brow marks, large navy eyes with a highlight, a white muzzle and cheek patches, dusky blush, a navy nose with a line and a small frown.
  - Body: brown with a dark edge, arms, forward feet with light pads, and an orange tail with brown rings.
  - Only the panda's dots are drawn, with no unlit grid and no rim. The canvas is 138×120 px (104×90 on phones), `left: 14px`, bottom on the composer's top edge (`composer.offsetHeight - 3`).
- **Motion:**
  - Squash and stretch with the loudness, and a nod plus an ear and tail flick on stressed syllables (loudness rising past 0.72).
  - A settle and a blink 280 ms into a pause, with a 45% chance of a gaze change hidden in the blink.
  - Breathing (4.2 s), a slow tail sway, an ear twitch every 3.5-7.5 s, and an idle blink every 4.5-7.5 s.
  - Moods at 60%, held 2 s: happy arcs, a curious tilt, drooping ears for concern.
  - The mouth opens only above 0.8 loudness.
- **Rounder (same day):** the user found the body too skinny and wanted it more fluffy and cuddly. The body is now a wide bean (rx 10.2, ry 7) with a fur-tufted edge; the arms are chubby with dark outlines; the feet are bigger and splayed, with a pad and a toe; the tail is thicker with a tufted edge and dark rings. Committed locally, not pushed.
- **Thinking and talking** are one character in one place: `thinking()` shows him with the paw to the chin, eyes up and to the right, and a "?" rising every 2.6 s. The paw drops when speech starts. The ending is happy eyes and a nod for 1.8 s, then a 0.7 s fade. The separate `#ray-think` box is removed.
- **Verified:** poses rendered to an image (neutral, thinking, happy, accent, concerned, curious). In the browser at 1280×800 he sits at the left on the input box above the command chips. In Node, the paw is 1.0 while thinking, 0 once talking, and he is hidden after the ending.

## Readable over text and on the light theme (2026-10-28)

- **The user's report (on the phone):** text behind him showed through his dots and was distracting, and on the light theme his whites blended into the white page.
- **The user's choices:** both a solid silhouette and room in the feed; a one-dot outline; the same size on phones.
- **Changes:**
  - `draw()` computes every cell first.
  - Empty cells next to a lit one become `C.edge` (`#3a2216`), the outline.
  - Every lit and outline cell is filled as a square in the page colour (read from `.code-mobile-card-view` every 500 ms, so a theme switch follows) before the dots are drawn.
  - The question marks are drawn last, with no outline or backing.
  - While he is shown, `.code-mobile-card-view.ray-room` gives the feed `padding-bottom: 128px` (98 px on phones), and a feed that was at its end is scrolled to the end.
- **Light theme follow-up (same day):** on the phone he looked washed out on white. On a light page (page colour luminance > 0.5) each cell's backing square is now the dot's own colour at 80%, and the dots are 0.47 of the pitch instead of 0.4. The dark theme was unchanged at first, but he then blended into the dark background, so the same fill now applies on both themes. The outline is dark brown (`#3a2216`) on a light page. On a dark page there is none: a light tan edge was tried and the user found it horrible, and from slate, soft grey, display blue or none they chose none.
- **Verified:**
  - In the browser (375 px wide), the room class and the 98 px padding apply.
  - Canvas pixels in the light theme: a gap between dots inside him is opaque, outside him is transparent, and there are 181 outline dots.
  - An offline render over text shows dark and light themes with no text showing through.

## App icon and thinner outline (2026-10-28)

- **Outline:** on the light theme the one-dot dark outline was too heavy ("much thinner"). It is now a thin `#3a2216` line, 0.32 of the dot pitch (at least 1.5 px; 0.2 was a little too thin), drawn along the outer edges of his lit cells. The dark theme has no outline.
- **App icon:** the user asked for the phone home-screen shortcut and the favicon to be the panda.
  - `tools/make_ray_icons.py` runs `pandaCell` from `rayface.js` in node (his full sitting body, neutral pose; at first it was the head only, and the user asked for the whole body) and writes:
    - `favicon.svg` (crisp squares, runs merged);
    - `favicon.ico` (16, 32 and 48 px);
    - `icon-180.png` (apple-touch-icon, square corners);
    - `icon-192.png` and `icon-512.png` (solid-dot style on the dark surface `#12161b`, with rounded corners).
  - `manifest.webmanifest` sets `display: "browser"`, so a shortcut opens the normal browser view, as before.
  - `index.html` links them; the manifest uses `crossorigin="use-credentials"` so it loads behind Cloudflare Access.
  - The server's `/web/` route also serves `.png` and `.webmanifest` (the server was restarted).
  - **Rerun the tool after changing his head.** A phone keeps an existing shortcut's icon: remove and add the shortcut again to see the panda.

## Thinking on every prompt (2026-10-28)

- **The user's request:** show Ray's thinking pose whenever the model is working, not only for spoken prompts, with an on/off switch in About.
- **How:**
  - `codeSetState` watches the session's `busy` flag. When it turns on, `RayFace.thinking()` runs, if About > "Show Ray thinking on every prompt" (`tts_think_all`, on by default) is set.
  - When `busy` turns off, he says goodbye after 400 ms, unless the speech has started; `codeOnTurnEnd` also ends him when there is nothing to read aloud.
  - With the switch off, only spoken prompts show him, as before.
  - The pose lasts the whole turn: reasoning, tool calls and the written answer.
- **Verified in the browser:**
  - Busy shows the thinking pose; done gives the goodbye, then he is hidden.
  - The switch off means busy shows nothing.
  - Speech that starts before `busy` drops keeps him talking.

## Typed prompts: only while thinking (2026-10-28)

- On a typed prompt Ray appears when the turn starts and stays through thinking and tool calls. When the first answer text arrives he fades out quickly (700 ms), with no goodbye. If the model thinks or calls a tool again after some text, he comes back.
- Spoken prompts are unchanged: he thinks, reads the answer aloud, then says goodbye.
- Code: `RayFace.leave()` in `serve/web/rayface.js`, called from `codeEvent` in `serve/web/app.js` (`codeRayTyped`).

## Pictures and branding (2026-10-28)

- **The generator:** `tools/make_ray_media.py` runs `rayface.js` itself in node, with its internals exposed and a fixed random seed, and draws with PIL. Output goes to `docs/media/ray/`:
  - `ray.png`, the README header;
  - `mood-*.png` and `moods.png`, the eight moods settled at the app's 60% strength, with the goodbye at full strength;
  - `thinking.gif`, `talking.gif` and `goodbye.gif` at 15 fps;
  - `social.png`, 1280 × 640.
- **talking.gif** is driven by real Piper speech of a three-sentence line at pitch 1.5, through a fake analyser read at the fake clock, so it shows the real loudness motion and sentence moods.
- **GIF corners** use one transparent palette colour, so the rounded tiles work on GitHub's light and dark themes.
- **README:** the panda above the title, the tagline "The household's little red panda", a "Meet Ray" section with the three GIFs and the mood sheet, and the old blue-face text replaced.
- **Web app header:** the panda icon (`favicon.svg`) sits next to "Ray".
- **The moods are subtle at 60%:** they are shown as the app really draws them. The pictures don't exaggerate them.
- **Not done by code:** GitHub's social preview has no API. `docs/media/ray/social.png` has to be uploaded in the repository's Settings → General → Social preview.

## Cocoa break while thinking (2026-10-29)

- **The user's request:** now and then while thinking, Ray holds and drinks a hot, steaming cup of hot chocolate with two hands; not every time. Five versions were drawn on a private studies page first (`https://claude.ai/artifact/RSg4dddrHkzokLG6KWjgAv`).
- **The user's choices:** a chance after a while (8 s into a think, 1 in 3, never on two thinks in a row); the mug sits beside him on the input box and he picks it up; cosy closed eyes on the sip; the **muzzle-white mug**. The first five studies varied the mug colour, but the user wanted different *animation styles*, not colours; they then picked four styles to mix, one picked at random per break (never the same twice running).
- **Styles (`STYLES` in `serve/web/rayface.js`):** classic (one long sip, "ahh", ~9 s), savour (cradled under the chin, breathing in the steam, swaying, two sips with a sigh, ~17 s), hot (blows, test sip, startled jolt with a steam puff, blows again, sips, ~12 s), thinking (keeps the thinking look and question marks with the mug in both paws, sips now and then, ~13 s). The quick-sip study was not chosen.
- **Drawing:** a 9 x 8 white mug on whole cells, cocoa at the rim, a dark edge when in front of him; dark paws and forearms; steam as two wisps of dashes with no backing (warm grey on a light page). No reduced-motion breaks.
- **Interruptions:** speech, `end()` or `leave()` take the mug away in 250 ms.
- **Trying it:** `RayFace.cocoa("classic" | "savour" | "hot" | "thinking")` while he is thinking; `RayFace.state.cocoa` and `.phase` show it.
- **Verified:** Node with stubs: a break starts 8 s into a think and runs every phase, the paw is back on the chin after, no break on the next think, speech mid-break shrinks the mug away. Not yet seen in the real app.

## Sources

- User, chat, 2026-10-28: brand the project with the red panda; images of his states and emotions in the repo description

- User, chat, 2026-10-28: Ray visible only while the model thinks on a typed prompt

1. User, chat, 2026-10-28 ("a pixel art face should move lips, talk and make expressions that match the tts speech"; "add a option in the about settings with a toggle").
2. `https://github.com/met4citizen/TalkingHead` (MIT, accessed 2026-10-28); `https://www.microsoft.com/en-us/research/project/vasa-1/` and `https://arxiv.org/html/2605.31294v1` reviewed and not used (no released code; 3D/photoreal, large GPU).
3. `serve/speech.py`, `serve/server.py` (`_audio_speech`), `serve/web/rayface.js`; earlier `serve/web/rayorb.js`; earlier `serve/web/lipsync-en.js`, `serve/web/rayface.js` (git history), `serve/web/app.js` (`TTSController`), `serve/web/app.css`, `serve/web/index.html`.
