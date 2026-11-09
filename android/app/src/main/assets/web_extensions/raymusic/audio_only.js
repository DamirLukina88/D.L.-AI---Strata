// Ray's lock-screen player plays the song version (album art, sound only) instead of the music video, whenever
// YouTube Music has one: less mobile data and battery (the user's choice, 2026-11-09).  A video with no song
// version (live clips, uploads) keeps playing as a video.  Lines starting "[ray-audio]" reach logcat (GeckoConsole).
(function () {
  "use strict";
  let lastClick = 0;
  let lastLog = "";

  function log(message) {
    if (message === lastLog) return;
    lastLog = message;
    console.log("[ray-audio] " + message);
  }

  // YouTube Music's Song | Video switch: <ytmusic-av-toggle playback-mode="ATV_PREFERRED|OMV_PREFERRED">, or any
  // element reading exactly "Song" next to one reading "Video" (the mobile page may draw it differently)
  function songSwitch() {
    const toggle = document.querySelector("ytmusic-av-toggle");
    if (toggle) {
      const button = toggle.querySelector(".song-button, [class*='song-button']") ||
        Array.from(toggle.querySelectorAll("*")).find(e => e.children.length === 0 && e.textContent.trim() === "Song");
      // toggle-disabled: this video has no song version the switch can play (a click only changed its label,
      // Bohemian Rhapsody fJ9rUzIMcZQ on 2026-11-09)
      if (toggle.hasAttribute("toggle-disabled")) return { button: null, mode: toggle.getAttribute("playback-mode") || "" };
      return { button: button, mode: toggle.getAttribute("playback-mode") || "" };
    }
    const songs = Array.from(document.querySelectorAll("button, [role='tab'], [role='button'], span, div"))
      .filter(e => e.children.length === 0 && e.textContent.trim() === "Song");
    for (const button of songs) {
      const around = button.parentElement && button.parentElement.parentElement;
      if (around && /\bVideo\b/.test(around.textContent)) return { button: button, mode: "" };
    }
    return null;
  }

  // No usable song version (the switch is disabled on this page, 2026-11-09): the video plays at YouTube's lowest
  // quality, 144p ("tiny"), the user's choice.  The sound is a separate stream, so it doesn't change
  function lowestQuality(video, size) {
    const el = document.getElementById("movie_player");
    const player = el && el.wrappedJSObject;          // the page's own player object (content scripts see a wrapper)
    if (!player || typeof player.setPlaybackQualityRange !== "function") {
      log("video " + size + ": no player API, quality unchanged");
      return;
    }
    let quality = "";
    try { quality = player.getPlaybackQuality ? String(player.getPlaybackQuality()) : ""; } catch (e) {}
    if (quality === "tiny" || video.videoHeight <= 144) {
      log("video " + size + " at the lowest quality (" + (quality || "?") + ")");
      return;
    }
    const now = Date.now();
    if (now - lastClick < 8000) return;
    lastClick = now;
    try {
      player.setPlaybackQualityRange("tiny", "tiny");
      if (player.setPlaybackQuality) player.setPlaybackQuality("tiny");
      log("video " + size + " (quality " + (quality || "?") + "): asked for 144p");
    } catch (e) {
      log("video " + size + ": quality change failed: " + e);
    }
  }

  function check() {
    const video = document.querySelector("video");
    if (!video || video.paused || !(video.videoWidth > 0)) return;     // nothing playing, or sound only already
    const size = video.videoWidth + "x" + video.videoHeight;
    const s = songSwitch();
    if (!s || !s.button) {
      lowestQuality(video, size);
      return;
    }
    if (s.mode === "ATV_PREFERRED") {
      log("song mode, picture " + size);
      return;
    }
    const now = Date.now();
    if (now - lastClick < 8000) return;
    lastClick = now;
    log("video " + size + " (mode " + (s.mode || "?") + "): switching to the song");
    s.button.click();
  }

  setInterval(check, 2000);
})();
