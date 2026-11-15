// serve/web/app-10-phone.js - part of the web app (see app-01-util.js): phone sensors and the Android companion bridge.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ Phone Sensors & Live Stream
let sensorPollTimer = null;
let sensorCanvasAnimFrame = null;
let currentSensorData = null;
let sensorActiveFilter = "all";
let sensorSearchQuery = "";

function openSensors(open = true) {
  const dlg = $("sensors-dialog");
  if (!dlg) return;
  if (open) {
    if (typeof dlg.showModal === "function") {
      try { dlg.showModal(); } catch (e) { dlg.setAttribute("open", ""); }
    } else {
      dlg.setAttribute("open", "");
    }
    startSensorPolling();
  } else {
    stopSensorPolling();
    if (typeof dlg.close === "function") dlg.close();
    else dlg.removeAttribute("open");
  }
}

function startSensorPolling() {
  if (sensorPollTimer) clearInterval(sensorPollTimer);
  fetchSensorData();
  sensorPollTimer = setInterval(fetchSensorData, 140);
  startSensorCanvasRender();
}

function stopSensorPolling() {
  if (sensorPollTimer) {
    clearInterval(sensorPollTimer);
    sensorPollTimer = null;
  }
  if (sensorCanvasAnimFrame) {
    cancelAnimationFrame(sensorCanvasAnimFrame);
    sensorCanvasAnimFrame = null;
  }
}

async function fetchSensorData() {
  try {
    // 1. If on Ray Android WebView companion, use direct native bridge for zero-latency 100 Hz reading
    if (typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.getLiveSensors === "function") {
      const jsonStr = window.RayAndroid.getLiveSensors();
      if (jsonStr && jsonStr !== "{}") {
        const data = JSON.parse(jsonStr);
        applySensorData(data);
        return;
      }
    }
    // 2. Fetch from server endpoint
    const r = await fetch("api/phone/sensors/stream", { headers: headers() });
    if (r.ok) {
      const data = await r.json();
      if (data && Object.keys(data).length > 0) {
        applySensorData(data);
      }
    }
  } catch (err) {
    // ignore transient fetch errors during high-frequency poll
  }
}

function applySensorData(data) {
  currentSensorData = data;
  const isStreaming = Boolean(data.streaming);

  // Update pills & badges
  const pill = $("sensor-stream-pill");
  const status = $("sensor-stream-status");
  const timer = $("sensor-stream-timer");
  const stopBtn = $("sensor-stop-btn");
  const startCustomBtn = $("sensor-start-custom-btn");
  const startIndefiniteBtn = $("sensor-start-indefinite-btn");

  if (pill) pill.setAttribute("data-state", isStreaming ? "generating" : "idle");
  if (status) status.textContent = isStreaming ? "Streaming (100 Hz)" : "Idle";
  if (stopBtn) stopBtn.hidden = !isStreaming;
  if (startCustomBtn) startCustomBtn.disabled = isStreaming;
  if (startIndefiniteBtn) startIndefiniteBtn.disabled = isStreaming;

  if (timer) {
    if (isStreaming) {
      if (data.is_indefinite) {
        timer.textContent = `Streaming: Indefinite (until stopped) • ${data.samples || 0} samples`;
      } else {
        const rem = data.remaining_sec !== undefined && data.remaining_sec >= 0 ? `${data.remaining_sec}s left • ` : "";
        timer.textContent = `Streaming: ${rem}${data.samples || 0} samples`;
      }
      timer.style.color = "var(--st-accent)";
    } else {
      timer.textContent = "Ready to stream";
      timer.style.color = "";
    }
  }

  // Total sensor count badge
  if ($("sensor-count-badge")) {
    $("sensor-count-badge").textContent = `${data.total_sensor_count || 108} Sensors`;
  }

  // Spirit Level info
  const level = data.level || {};
  const pitch = Number(level.pitch_deg || 0);
  const roll = Number(level.roll_deg || 0);
  const tilt = Number(level.total_tilt_deg || 0);
  const isLevel = Boolean(level.is_level);

  if ($("level-pitch")) $("level-pitch").textContent = `${pitch >= 0 ? "+" : ""}${pitch.toFixed(2)}°`;
  if ($("level-roll")) $("level-roll").textContent = `${roll >= 0 ? "+" : ""}${roll.toFixed(2)}°`;
  if ($("level-tilt")) $("level-tilt").textContent = `${tilt.toFixed(2)}°`;
  if ($("level-guidance")) $("level-guidance").textContent = level.guidance || (isLevel ? "Perfect level surface!" : "Keep phone flat on surface");

  const badge = $("level-badge");
  if (badge) {
    badge.textContent = level.status || (isLevel ? "Level" : "Tilted");
    badge.className = "st-badge " + (isLevel ? "st-badge--reading" : "");
    if (isLevel) {
      badge.style.background = "var(--st-success, #10b981)";
      badge.style.color = "#fff";
    } else {
      badge.style.background = "";
      badge.style.color = "";
    }
  }

  // 6-Axis Motion & IMU
  const imu = data.imu || {};
  if ($("imu-gforce-val") && imu.g_force !== undefined) {
    $("imu-gforce-val").textContent = `${Number(imu.g_force).toFixed(2)} G`;
  }
  if ($("imu-accel-xyz") && imu.ax !== undefined) {
    $("imu-accel-xyz").textContent = `${imu.ax.toFixed(2)}, ${imu.ay.toFixed(2)}, ${imu.az.toFixed(2)}`;
  }
  if ($("imu-gyro-xyz") && imu.gx_rads !== undefined) {
    $("imu-gyro-xyz").textContent = `${imu.gx_rads.toFixed(2)}, ${imu.gy_rads.toFixed(2)}, ${imu.gz_rads.toFixed(2)}`;
  }
  if ($("imu-lin-xyz") && imu.lax !== undefined) {
    $("imu-lin-xyz").textContent = `${imu.lax.toFixed(2)}, ${imu.lay.toFixed(2)}, ${imu.laz.toFixed(2)}`;
  }

  // Telemetry details
  const comp = data.compass || {};
  if ($("tel-heading")) $("tel-heading").textContent = comp.heading_deg !== undefined ? `${comp.heading_deg.toFixed(1)}°` : "--°";
  if ($("tel-cardinal")) $("tel-cardinal").textContent = comp.cardinal || "--";
  if ($("tel-mag-field")) $("tel-mag-field").textContent = comp.field_strength_ut !== undefined ? `${comp.field_strength_ut.toFixed(1)} µT` : "-- µT";

  const env = data.environment || {};
  if ($("tel-pressure")) $("tel-pressure").textContent = env.pressure_hpa !== undefined ? `${env.pressure_hpa.toFixed(1)} hPa` : "-- hPa";
  if ($("tel-altitude")) $("tel-altitude").textContent = env.altitude_m !== undefined ? `${env.altitude_m.toFixed(1)} m` : "-- m";
  if ($("tel-lux")) $("tel-lux").textContent = env.front_lux !== undefined ? `${env.front_lux.toFixed(0)} lux` : "-- lux";
  if ($("tel-proximity")) $("tel-proximity").textContent = env.proximity_cm !== undefined ? `${env.proximity_cm.toFixed(0)} cm` : "-- cm";

  // Render All Sensors Table
  renderSensorsTable();
}

function formatSensorValues(s) {
  const vals = Array.isArray(s.values) ? s.values : [];
  if (vals.length === 0) return "--";

  const t = String(s.string_type || "").toLowerCase();
  if (t.includes("accelerometer") && vals.length >= 3) {
    return `x=${vals[0].toFixed(2)}, y=${vals[1].toFixed(2)}, z=${vals[2].toFixed(2)} m/s²`;
  }
  if (t.includes("gyroscope") && vals.length >= 3) {
    return `x=${vals[0].toFixed(3)}, y=${vals[1].toFixed(3)}, z=${vals[2].toFixed(3)} rad/s`;
  }
  if (t.includes("magnetic") && vals.length >= 3) {
    return `x=${vals[0].toFixed(1)}, y=${vals[1].toFixed(1)}, z=${vals[2].toFixed(1)} µT`;
  }
  if (t.includes("pressure") && vals.length >= 1) {
    return `${vals[0].toFixed(2)} hPa`;
  }
  if (t.includes("light") && vals.length >= 1) {
    return `${vals[0].toFixed(1)} lux`;
  }
  if (t.includes("proximity") && vals.length >= 1) {
    return `${vals[0].toFixed(1)} cm`;
  }
  if (t.includes("orientation") && vals.length >= 3) {
    return `heading=${vals[0].toFixed(1)}°, pitch=${vals[1].toFixed(1)}°, roll=${vals[2].toFixed(1)}°`;
  }
  if (t.includes("step") && vals.length >= 1) {
    return `${Math.round(vals[0])} steps`;
  }

  return `[${vals.map(v => typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) : v).join(", ")}]`;
}

function renderSensorsTable() {
  const tbody = $("sensors-table-body");
  if (!tbody || !currentSensorData) return;

  const rawSensors = Array.isArray(currentSensorData.sensors) ? currentSensorData.sensors : [];
  const q = sensorSearchQuery.trim().toLowerCase();

  const filtered = rawSensors.filter((s, idx) => {
    // 1. Text search
    if (q) {
      const name = String(s.name || "").toLowerCase();
      const vendor = String(s.vendor || "").toLowerCase();
      const stype = String(s.string_type || "").toLowerCase();
      if (!name.includes(q) && !vendor.includes(q) && !stype.includes(q)) return false;
    }

    // 2. Category filter
    if (sensorActiveFilter === "active") {
      return Boolean(s.active || (s.values && s.values.length > 0));
    }
    const t = String(s.string_type || "").toLowerCase();
    if (sensorActiveFilter === "motion") {
      return t.includes("accel") || t.includes("gyro") || t.includes("motion") || t.includes("grav") ||
             t.includes("step") || t.includes("tilt") || t.includes("rotation");
    }
    if (sensorActiveFilter === "environment") {
      return t.includes("pressure") || t.includes("light") || t.includes("temp") || t.includes("humid") ||
             t.includes("cct") || t.includes("flicker") || t.includes("tof");
    }
    if (sensorActiveFilter === "heading") {
      return t.includes("magnet") || t.includes("orient") || t.includes("compass");
    }
    if (sensorActiveFilter === "xiaomi") {
      return t.includes("xiaomi") || String(s.vendor || "").toLowerCase().includes("xiaomi");
    }
    return true;
  });

  if ($("sensor-explorer-count")) {
    $("sensor-explorer-count").textContent = `(Showing ${filtered.length} of ${rawSensors.length} sensors)`;
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:16px;">No sensors match filter '${esc(sensorActiveFilter)}'</td></tr>`;
    return;
  }

  let html = "";
  for (let i = 0; i < filtered.length; i++) {
    const s = filtered[i];
    const isAct = Boolean(s.active || (s.values && s.values.length > 0));
    let valsStr = "--";
    try {
      valsStr = formatSensorValues(s);
    } catch (_) {
      valsStr = "--";
    }
    const badgeClass = isAct ? "st-badge--reading" : "";
    const badgeText = isAct ? "Active" : (s.wakeup ? "Wakeup" : "Standby");

    const valColor = isAct ? "var(--st-accent)" : "var(--st-text-muted, #888)";
    const valWeight = isAct ? "600" : "normal";

    html += `<tr>
      <td class="muted small" style="width:40px;text-align:center;">${i + 1}</td>
      <td>
        <strong style="color:var(--st-text);">${esc(s.name || "Unknown")}</strong>
        <div class="muted small">${esc(s.vendor || "Android")}</div>
      </td>
      <td>
        <code style="font-size:11px;background:var(--st-surface-variant);padding:2px 4px;border-radius:4px;">${esc(s.string_type || "type." + s.type)}</code>
      </td>
      <td>
        <span style="font-family:var(--st-font-mono,monospace);font-size:11.5px;font-weight:${valWeight};color:${valColor};">${esc(valsStr)}</span>
      </td>
      <td style="width:70px;text-align:center;">
        <span class="st-badge ${badgeClass}" style="font-size:10px;">${badgeText}</span>
      </td>
    </tr>`;
  }
  tbody.innerHTML = html;
}

function startSensorCanvasRender() {
  function render() {
    drawSpiritLevelCanvas();
    drawWaveformCanvas();
    const dlg = $("sensors-dialog");
    if (dlg && (dlg.hasAttribute("open") || dlg.open)) {
      sensorCanvasAnimFrame = requestAnimationFrame(render);
    }
  }
  if (!sensorCanvasAnimFrame) {
    sensorCanvasAnimFrame = requestAnimationFrame(render);
  }
}

function drawSpiritLevelCanvas() {
  const canvas = $("level-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const maxR = cx - 12;

  ctx.clearRect(0, 0, w, h);

  // Background target rings
  ctx.save();
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";

  // Concentric target circles
  for (const r of [maxR * 0.25, maxR * 0.5, maxR * 0.75, maxR]) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Crosshairs
  ctx.beginPath();
  ctx.moveTo(cx - maxR, cy);
  ctx.lineTo(cx + maxR, cy);
  ctx.moveTo(cx, cy - maxR);
  ctx.lineTo(cx, cy + maxR);
  ctx.stroke();

  // Bullseye inner ring (0.5 degree target)
  const targetR = 14;
  const level = currentSensorData?.level || {};
  const isLevel = Boolean(level.is_level);
  ctx.lineWidth = 2;
  ctx.strokeStyle = isLevel ? "#10b981" : "rgba(255, 255, 255, 0.4)";
  ctx.beginPath();
  ctx.arc(cx, cy, targetR, 0, Math.PI * 2);
  ctx.stroke();

  // Bubble position based on roll and pitch
  const roll = Number(level.roll_deg || 0);
  const pitch = Number(level.pitch_deg || 0);

  // 1 degree = 6 pixels deflection
  const scale = 6.0;
  let bx = cx + roll * scale;
  let by = cy - pitch * scale;

  // Clamp bubble inside outer ring
  const dist = Math.hypot(bx - cx, by - cy);
  if (dist > maxR - 12) {
    const angle = Math.atan2(by - cy, bx - cx);
    bx = cx + Math.cos(angle) * (maxR - 12);
    by = cy + Math.sin(angle) * (maxR - 12);
  }

  // Draw bubble
  const bubbleR = 14;
  const grad = ctx.createRadialGradient(bx - 3, by - 3, 2, bx, by, bubbleR);
  if (isLevel) {
    grad.addColorStop(0, "#86efac");
    grad.addColorStop(1, "#10b981");
  } else {
    grad.addColorStop(0, "#7dd3fc");
    grad.addColorStop(1, "#0284c7");
  }

  ctx.shadowColor = isLevel ? "#10b981" : "#0284c7";
  ctx.shadowBlur = 10;
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(bx, by, bubbleR, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawWaveformCanvas() {
  const canvas = $("waveform-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  // Draw grid & 1.0G baseline
  ctx.save();
  ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let y = 20; y < h; y += 30) {
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
  }
  ctx.stroke();

  // Baseline at 1.0G
  const baseY = h * 0.65;
  ctx.strokeStyle = "rgba(255, 255, 255, 0.25)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(0, baseY);
  ctx.lineTo(w, baseY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Label 1.0 G
  ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
  ctx.font = "10px monospace";
  ctx.fillText("1.0 G", 6, baseY - 4);

  // Waveform points
  const waveform = Array.isArray(currentSensorData?.waveform) ? currentSensorData.waveform : [];
  if (waveform.length > 1) {
    ctx.beginPath();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#38bdf8";
    ctx.shadowColor = "#38bdf8";
    ctx.shadowBlur = 6;

    const dx = w / Math.max(80, waveform.length - 1);
    for (let i = 0; i < waveform.length; i++) {
      const g = Number(waveform[i]);
      // Scale: 1G at baseY, 0G at baseY + 35px, 2G at baseY - 35px
      const y = Math.max(4, Math.min(h - 4, baseY - (g - 1.0) * 35));
      const x = i * dx;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  } else {
    ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Click 'Start Stream' to observe real-time waveform", w / 2, h / 2);
  }
  ctx.restore();
}

async function startLiveSensorStream(durationSec = 15) {
  const isIndef = durationSec <= 0;
  const label = isIndef ? "indefinitely until stopped" : `for ${durationSec}s`;

  if (typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.startSensorStream === "function") {
    try {
      window.RayAndroid.startSensorStream("all", durationSec, 100);
      if (typeof toast === "function") toast("info", "Live Sensor Stream", `Streaming Xiaomi 17 Ultra sensors ${label} at 100 Hz`);
      fetchSensorData();
      return;
    } catch (e) {}
  }

  try {
    if (typeof toast === "function") toast("info", "Starting Sensor Stream...", `Engaging high-frequency 100 Hz sensors (${label})`);
    const r = await fetch("api/phone/tool/call", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        tool: "phone_sensor_stream",
        args: { action: "start", mode: "all", duration_sec: durationSec, sample_rate_hz: 100 }
      })
    });
    const res = await r.json();
    if (res.result && typeof toast === "function") {
      toast("success", "Sensor Stream Active", res.result.split("\n")[0]);
    }
    fetchSensorData();
  } catch (err) {
    if (typeof toast === "function") toast("error", "Stream Error", err.message);
  }
}

async function stopLiveSensorStream() {
  if (typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.stopSensorStream === "function") {
    try {
      window.RayAndroid.stopSensorStream();
      if (typeof toast === "function") toast("info", "Sensor Stream Stopped", "Sensors returned to low-power idle");
      fetchSensorData();
      return;
    } catch (e) {}
  }

  try {
    const r = await fetch("api/phone/tool/call", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({
        tool: "phone_sensor_stream",
        args: { action: "stop" }
      })
    });
    const res = await r.json();
    if (typeof toast === "function") {
      toast("info", "Sensor Stream Stopped", res.result || "Sensors returned to low-power idle");
    }
    fetchSensorData();
  } catch (err) {}
}

if ($("code-sensors-btn")) $("code-sensors-btn").onclick = () => openSensors(true);
if ($("sensor-close-btn")) $("sensor-close-btn").onclick = () => openSensors(false);
if ($("sensor-refresh-btn")) $("sensor-refresh-btn").onclick = () => {
  if (typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.refreshAllSensors === "function") {
    window.RayAndroid.refreshAllSensors();
  }
  fetchSensorData();
};

if ($("sensor-start-custom-btn")) {
  $("sensor-start-custom-btn").onclick = () => {
    const inp = $("sensor-duration-input");
    const sec = inp ? Math.max(1, parseInt(inp.value, 10) || 15) : 15;
    startLiveSensorStream(sec);
  };
}

if ($("sensor-start-indefinite-btn")) {
  $("sensor-start-indefinite-btn").onclick = () => {
    startLiveSensorStream(0); // 0 = indefinite until stopped
  };
}

if ($("sensor-stop-btn")) $("sensor-stop-btn").onclick = () => stopLiveSensorStream();

// Filter chips handling
const filterChips = document.querySelectorAll(".sensor-filter-chip");
filterChips.forEach(chip => {
  chip.addEventListener("click", () => {
    sensorActiveFilter = chip.getAttribute("data-filter") || "all";
    filterChips.forEach(c => {
      c.className = "st-btn st-btn--sm " + (c === chip ? "st-btn--primary" : "st-btn--secondary") + " sensor-filter-chip";
    });
    renderSensorsTable();
  });
});

// Search input handling
if ($("sensor-search-input")) {
  $("sensor-search-input").addEventListener("input", (e) => {
    sensorSearchQuery = e.target.value || "";
    renderSensorsTable();
  });
}

const sensorsDlg = $("sensors-dialog");
if (sensorsDlg) {
  sensorsDlg.addEventListener("click", (e) => {
    const rect = sensorsDlg.getBoundingClientRect();
    const isInDialog = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height
      && rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
    if (!isInDialog) openSensors(false);
  });
}

function openSensorInfo(open = true) {
  const dlg = $("sensor-info-modal");
  if (!dlg) return;
  if (open) {
    if (typeof dlg.showModal === "function") {
      try { dlg.showModal(); } catch (e) { dlg.setAttribute("open", ""); }
    } else {
      dlg.setAttribute("open", "");
    }
  } else {
    if (typeof dlg.close === "function") dlg.close();
    else dlg.removeAttribute("open");
  }
}

if ($("sensor-info-btn")) $("sensor-info-btn").onclick = () => openSensorInfo(true);
if ($("sensor-info-close-btn")) $("sensor-info-close-btn").onclick = () => openSensorInfo(false);
if ($("sensor-info-ok-btn")) $("sensor-info-ok-btn").onclick = () => openSensorInfo(false);

const sensorInfoModal = $("sensor-info-modal");
if (sensorInfoModal) {
  sensorInfoModal.addEventListener("click", (e) => {
    const rect = sensorInfoModal.getBoundingClientRect();
    const isInDialog = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height
      && rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
    if (!isInDialog) openSensorInfo(false);
  });
}

// Window-level drop handler: prevents accidental browser file navigation and ingests files (#3838)
window.addEventListener("dragover", (e) => {
  if (Array.from(e.dataTransfer?.types || []).includes("Files")) {
    e.preventDefault();
  }
});
window.addEventListener("drop", async (e) => {
  if (Array.from(e.dataTransfer?.types || []).includes("Files")) {
    if (wsDropzone && (e.target === wsDropzone || wsDropzone.contains(e.target))) return;
    if (wsDialog && (e.target === wsDialog || wsDialog.contains(e.target))) return;
    e.preventDefault();
    const files = await extractFilesFromDataTransfer(e.dataTransfer);
    if (files.length) {
      const stored = await uploadFilesToWorkspace(files, "uploads/");
      const input = $("code-mobile-input");
      if (input && stored.length) {
        const refs = stored.map(p => `@${p}`).join(" ");
        input.value = input.value ? `${input.value.trimEnd()} ${refs} ` : `${refs} `;
        input.focus();
        input.dispatchEvent(new Event("input"));
      }
      toast("success", "Files added to workspace", files.map(f => f.name).join(", "), 3000);
    }
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (typeof STTController !== "undefined") STTController.cancelAutoSendTimer();
    if ($("drawer") && $("drawer").dataset.open === "true") openDrawer(false);
    if ($("workspace-dialog") && ($("workspace-dialog").hasAttribute("open") || $("workspace-dialog").open)) openWorkspace(false);
    if ($("sensors-dialog") && ($("sensors-dialog").hasAttribute("open") || $("sensors-dialog").open)) openSensors(false);
    if ($("sensor-info-modal") && ($("sensor-info-modal").hasAttribute("open") || $("sensor-info-modal").open)) openSensorInfo(false);
    if ($("brave-stt-dialog") && ($("brave-stt-dialog").hasAttribute("open") || $("brave-stt-dialog").open)) STTController.closeBraveGuide();
  }
});

if ($("code-sampling-btn")) $("code-sampling-btn").onclick = () => { lastDrawerTrigger = $("code-sampling-btn"); openDrawer(true); };   // the same settings drive the CLI
syncShared();                                            // the server's Chat settings, or publish this browser's
$("drawer-close").onclick = () => openDrawer(false);
$("scrim").onclick = () => openDrawer(false);

function hasOpenDrawer() {
  if (typeof document === "undefined") return false;
  const s = document.getElementById("sessions-drawer");
  const d = document.getElementById("drawer");
  return Boolean((s && s.dataset && s.dataset.open === "true") || (d && d.dataset && d.dataset.open === "true"));
}

function closeOpenDrawer() {
  if (typeof document === "undefined") return false;
  const s = document.getElementById("sessions-drawer");
  if (s && s.dataset && s.dataset.open === "true") {
    if (typeof openSessions === "function") openSessions(false);
    else s.dataset.open = "false";
    return true;
  }
  const d = document.getElementById("drawer");
  if (d && d.dataset && d.dataset.open === "true") {
    if (typeof openDrawer === "function") openDrawer(false);
    else d.dataset.open = "false";
    return true;
  }
  return false;
}

let phoneBridgePollerRunning = false;
function startPhoneCompanionBridge() {
  if (phoneBridgePollerRunning) return;
  phoneBridgePollerRunning = true;
  let heartbeatTick = 0;

  async function pollLoop() {
    if (typeof window === "undefined" || !window.RayAndroid) {
      phoneBridgePollerRunning = false;
      return;
    }
    try {
      if (++heartbeatTick % 10 === 1) {
        fetch("api/phone/status", { method: "POST", headers: headers(true), body: "{}" }).catch(() => {});
      }
      const r = await fetch("api/phone/tool/pending", { headers: headers() });
      if (r.ok) {
        const data = await r.json();
        if (data && data.pending) {
          const p = data.pending;
          let toolRes = "";
          try {
            if (typeof window.RayAndroid.executeTool === "function") {
              toolRes = window.RayAndroid.executeTool(p.tool, JSON.stringify(p.args || {}), p.id);
            } else {
              toolRes = "Error: RayAndroid.executeTool unavailable";
            }
          } catch (e) {
            toolRes = "Error executing tool: " + (e && e.message ? e.message : String(e));
          }
          let resVal = toolRes;
          try {
            const parsed = JSON.parse(toolRes);
            if (parsed && parsed.result !== undefined) resVal = parsed.result;
          } catch (_) {}
          await fetch("api/phone/tool/result", {
            method: "POST",
            headers: headers(true),
            body: JSON.stringify({ id: p.id, result: resVal })
          }).catch(() => {});
        }
      }
    } catch (_) {}
    setTimeout(pollLoop, 1500);
  }
  pollLoop();
}

function checkRayAndroidCompanion() {
  if (typeof window === "undefined" || !window.RayAndroid) return;
  if (window._rayAndroidCompanionInitialized) return;
  window._rayAndroidCompanionInitialized = true;
  if (typeof document !== "undefined" && document.body) {
    document.body.classList.add("is-android-companion");
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) logoutBtn.style.display = "none";
    const fullscreenBtn = document.getElementById("code-fullscreen-btn");
    if (fullscreenBtn) fullscreenBtn.style.display = "none";
    // the phone's setup screen (permissions) as the first card in About; an older app without openSetup keeps it hidden
    const settingsCard = document.getElementById("android-settings-card");
    if (settingsCard && typeof window.RayAndroid.openSetup === "function") {
      settingsCard.hidden = false;
      document.getElementById("android-settings-btn").addEventListener("click", () => {
        try { window.RayAndroid.openSetup(); } catch (_) {}
      });
    }
    // "Ok Ray" on the phone (an app with the wake word only)
    const wakeRow = document.getElementById("wake-word-row"), wakeBtn = document.getElementById("wake-word-toggle");
    if (wakeRow && typeof window.RayAndroid.setWakeWord === "function") {
      const show = (on) => wakeBtn.setAttribute("aria-checked", String(on));
      try { show(!!window.RayAndroid.isWakeWordOn()); } catch (_) {}
      wakeRow.hidden = false;
      wakeBtn.addEventListener("click", () => {
        const on = wakeBtn.getAttribute("aria-checked") !== "true";
        try { window.RayAndroid.setWakeWord(on); show(on); } catch (_) {}
        toast(on ? "success" : "info", on ? "Listening for “Ok Ray”" : "“Ok Ray” is off",
              on ? "Say it near the phone to open the voice drawer" : "", 3000);
      });
    }
  }
  if (typeof showTab === "function") {
    showTab("code");
  }
  if (typeof window.RayAndroid.getApiKey === "function") {
    try {
      const bridgeKey = window.RayAndroid.getApiKey();
      if (bridgeKey) {
        store.set("apikey", bridgeKey);
        const apiInput = document.getElementById("api-key");
        if (apiInput) apiInput.value = bridgeKey;
      }
    } catch (_) {}
  }
  window.onRayAndroidSpeechResult = (text, isFinal) => {
    if (typeof STTController !== "undefined" && typeof STTController.handleNativeSpeechResult === "function") {
      STTController.handleNativeSpeechResult(text, isFinal);
    }
  };
  // the phone heard nothing or its recognizer failed: the mic button and the keyboard come back
  window.onRayAndroidSpeechError = (message) => {
    if (typeof STTController === "undefined") return;
    STTController.isRecording = false;
    STTController.updateMicUI(false);
    STTController.restoreKeyboard(STTController.currentTarget);
    if (!/no speech|didn't catch|no match|timeout/i.test(String(message || ""))) {
      toast("warn", "Voice input stopped", String(message || ""), 3000);
    }
  };
  startPhoneCompanionBridge();
}

if (typeof window !== "undefined") {
  window.hasOpenDrawer = hasOpenDrawer;
  window.closeOpenDrawer = closeOpenDrawer;
  window.checkRayAndroidCompanion = checkRayAndroidCompanion;
}

