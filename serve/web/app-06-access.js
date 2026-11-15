// serve/web/app-06-access.js - part of the web app (see app-01-util.js): server access.
// A classic script, loaded in order by index.html; it shares its globals with the others.
"use strict";

// ------------------------------------------------------------------ server access
const DEFAULT_KEY = "";
function headers(json = false) {
  const h = {};
  let key = store.get("apikey", DEFAULT_KEY);
  if (!key && typeof window !== "undefined" && window.RayAndroid && typeof window.RayAndroid.getApiKey === "function") {
    try { key = window.RayAndroid.getApiKey(); } catch (_) {}
  }
  if (key) h.Authorization = "Bearer " + key;
  if (json) h["Content-Type"] = "application/json";
  return h;
}
$("api-key").value = store.get("apikey", DEFAULT_KEY);
// D.L. AI: behind Cloudflare Access the login is the credential - no key is kept or sent from this browser
(async () => {
  try {
    const r = await fetch("api/whoami", { headers: headers() });
    const who = r.ok ? await r.json() : null;
    if (who && who.auth === "cf-access") {
      store.set("apikey", "");
      const field = $("api-key").closest(".st-field");
      if (field) field.innerHTML = `<span class="st-label">Signed in with Cloudflare Access <output>${(who.email || "").replace(/[<>&"]/g, "")}</output></span>`;
    }
  } catch (e) { /* older server or offline: keep the key field */ }
})();
$("api-key").onchange = () => { store.set("apikey", $("api-key").value.trim()); toast("success", "API key saved", "Kept in this browser only."); };

if ($("force-restart-btn")) {
  $("force-restart-btn").onclick = async () => {
    if (!confirm("Forcefully kill the running engine process and restart/reset?")) return;
    const btn = $("force-restart-btn");
    btn.disabled = true;
    btn.textContent = "Restarting…";
    try {
      const r = await fetch("restart", {method: "POST", headers: headers(true), body: "{}"});
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try { msg = (await r.json()).error.message || msg; } catch (e) {}
        throw new Error(msg);
      }
      const res = await r.json();
      toast("success", "Engine restarted", `Model state: ${res.status || "ready"}`);
    } catch (e) {
      toast("error", "Restart failed", e.message || String(e), 6000);
    } finally {
      btn.disabled = false;
      btn.textContent = "Force Restart";
    }
  };
}

if ($("logout-btn")) {
  $("logout-btn").onclick = () => {
    if (!confirm("Are you sure you want to log out?")) return;
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch (e) {}
    const host = window.location.hostname;
    const domains = [host, "." + host, ""];
    const cookieNames = ["CF_Authorization", "CF_AppSession", "CF_Session", "strata.apikey", "strata.theme"];
    try {
      document.cookie.split(";").forEach(c => {
        const name = c.split("=")[0].trim();
        if (name && !cookieNames.includes(name)) cookieNames.push(name);
      });
    } catch (e) {}
    for (const d of domains) {
      for (const name of cookieNames) {
        document.cookie = `${name}=; Path=/; ${d ? `Domain=${d}; ` : ""}Expires=Thu, 01 Jan 1970 00:00:01 GMT; Max-Age=0;`;
      }
    }
    // Cloudflare Access keeps two sessions: this app's CF_Authorization cookie (HttpOnly, so only Cloudflare's own
    // logout page can clear it) and the session on the team domain, which silently signs the app in again on the next
    // visit. So: end the app's cookie in the background, then open the team logout (site-config.js sets its URL).
    const appLogout = "/cdn-cgi/access/logout";
    const teamLogout = window.STRATA_LOGOUT_URL || "";
    const go = (url) => {
      try { (window.top || window).location.href = url; } catch (e) { window.location.href = url; }
    };
    if (!teamLogout || teamLogout === appLogout) { go(appLogout); return; }
    let left = false;
    const leave = () => { if (!left) { left = true; go(teamLogout); } };
    setTimeout(leave, 3000);                  // never wait longer than this for the app logout
    fetch(appLogout, { credentials: "include", cache: "no-store", redirect: "manual" })
      .catch(() => {})
      .finally(leave);
  };
}

async function loadAvailableModels() {
  if (!$("model-select")) return;
  try {
    const r = await fetch("available_models", {headers: headers()});
    if (r.ok) {
      const data = await r.json();
      if (data.models && data.models.length) {
        $("model-select").innerHTML = data.models.map(m =>
          `<option value="${esc(m.id)}"${m.active ? " selected" : ""}>${esc(m.name || m.id)}</option>`
        ).join("");
      }
    }
  } catch (e) {}
}

if ($("model-select")) {
  $("model-select").onchange = async () => {
    const target = $("model-select").value;
    toast("info", "Switching model…", `Selecting ${target}`);
    try {
      const r = await fetch("switch_model", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({model: target})
      });
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try { msg = (await r.json()).error.message || msg; } catch (e) {}
        throw new Error(msg);
      }
      const res = await r.json();
      if (res.status === "already_loaded") {
        toast("info", "Already Active", `${res.name || target} is already loaded.`);
      } else {
        toast("success", "Model Active", `${res.name || target} (${res.status || "ready"}).`);
      }
      loadHealth();
    } catch (e) {
      toast("error", "Model Switch Failed", e.message || String(e), 6000);
      loadAvailableModels();
    }
  };
}

let health = {model: "Ray", images: false, max_context: 0};
async function loadHealth() {
  try {
    health = await (await fetch("health")).json();
    if ($("model-select") && health.model) {
      $("model-select").value = health.model;
    }
  } catch (e) {
    setTimeout(loadHealth, 2000);
  }
}

