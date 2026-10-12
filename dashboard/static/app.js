/* SPDX-License-Identifier: GPL-2.0-only */
"use strict";
(() => {
  const counters = ["read_requests", "write_requests", "read_bytes", "write_bytes", "integrity_failures"];
  const actions = ["load-random", "lock", "unlock", "destroy"];
  const descriptions = {
    0: "No key is installed. Load a random key to create an empty medium.",
    1: "The kernel is preparing authenticated encrypted storage.",
    2: "I/O is enabled. Reads authenticate ciphertext before decryption.",
    3: "I/O is blocked. The resident keys and medium are retained.",
    4: "Authentication failed. Destructive recovery is required before I/O."
  };
  function bytes(value) {
    const n = BigInt(value);
    const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"];
    let divisor = 1n, unit = 0;
    while (n >= divisor * 1024n && unit < units.length - 1) { divisor *= 1024n; unit++; }
    return unit === 0 ? `${n} B` : `${n / divisor}.${((n % divisor) * 100n / divisor).toString().padStart(2, "0")} ${units[unit]}`;
  }
  function enabled(state, compatible, fresh, busy) {
    if (!compatible || !fresh || busy) return [];
    return ({0: ["load-random"], 2: ["lock", "destroy"], 3: ["unlock", "destroy"], 4: ["destroy"]})[state] || [];
  }
  function sample(previous, current, elapsed) {
    if (!previous || elapsed <= 0 || elapsed > 5000 || counters.some(k => current[k] < previous[k])) return null;
    // Subtract exactly before converting diagnostic rates to floating point.
    return {read: Number(current.read_bytes - previous.read_bytes) * 1000 / elapsed,
            write: Number(current.write_bytes - previous.write_bytes) * 1000 / elapsed};
  }
  function parseStats(data) {
    const result = {};
    for (const key of counters) {
      if (typeof data[key] !== "string" || !/^(0|[1-9][0-9]{0,19})$/.test(data[key])) throw new Error("Invalid statistics response.");
      result[key] = BigInt(data[key]);
      if (result[key] > 18446744073709551615n) throw new Error("Counter outside u64 range.");
    }
    return result;
  }
  // Pure display helpers are tested with the existing Node runtime, no packages.
  if (typeof module !== "undefined" && module.exports) module.exports = {bytes, enabled, sample, parseStats};
  if (typeof document === "undefined") return;

  const el = id => document.getElementById(id);
  const text = (id, value) => { el(id).textContent = value; };
  const fragment = new URLSearchParams(location.hash.slice(1));
  let token = fragment.get("token") || "";
  fragment.delete("token");
  history.replaceState(null, "", location.pathname); // Never retain in URL/history or storage.
  let current = null, fresh = false, busy = false, polling = false, timer = null;
  let previous = null, previousTime = 0, samples = [], connected = null;
  let lastState = null, lastGeneration = null, lastFailures = null;
  const activity = [];
  const validToken = /^[A-Za-z0-9_-]{43}$/.test(token);
  if (!validToken) token = "";

  function event(message) {
    activity.unshift({time: new Date().toLocaleTimeString([], {hour12: false}), message});
    activity.splice(40);
    el("activity-list").replaceChildren(...activity.map(item => {
      const li = document.createElement("li"), time = document.createElement("time"), label = document.createElement("span");
      time.textContent = item.time; label.textContent = item.message; li.append(time, label); return li;
    }));
  }
  function updateButtons() {
    const allowed = enabled(current?.state, current?.compatible, fresh, busy);
    for (const action of actions) el(action).disabled = !allowed.includes(action);
    el("confirm-destroy").disabled = el("destroy-confirm").value !== "DESTROY" || !allowed.includes("destroy");
  }
  function showError(title, message) {
    text("error-title", title); text("error-message", message); el("error-panel").hidden = false;
  }
  function stale() {
    fresh = false; previous = null; samples = [];
    el("data-panels").dataset.stale = "true";
    el("stale-label").hidden = !current;
    drawChart(); updateButtons();
  }
  async function api(path, actionBody) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 18000);
    try {
      const response = await fetch(path, {
        method: actionBody === undefined ? "GET" : "POST",
        headers: {Authorization: `Bearer ${token}`, ...(actionBody === undefined ? {} : {"Content-Type": "application/json"})},
        body: actionBody === undefined ? undefined : JSON.stringify(actionBody),
        cache: "no-store", credentials: "omit", mode: "same-origin", redirect: "error", signal: controller.signal
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error?.message || "Request rejected.");
        error.code = data.error?.code || "http_error";
        throw error;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }
  function renderStatus(data) {
    if (current === null) text("action-result", "Choose an available lifecycle action.");
    if (lastState !== data.state) event(`State observed: ${data.state_name} (${data.state}).`);
    if (lastGeneration !== null && BigInt(data.generation) < BigInt(lastGeneration)) {
      previous = null; samples = []; event("Generation reset observed; module may have reloaded.");
    }
    lastState = data.state; lastGeneration = data.generation;
    current = data;
    el("state-card").dataset.state = String(data.state);
    text("state-name", data.state_name); text("state-number", `STATE ${data.state}`);
    text("state-description", descriptions[data.state] || "Unknown kernel state. Lifecycle controls are disabled.");
    el("integrity-warning").hidden = data.state !== 4;
    text("capacity", bytes(data.capacity_bytes)); text("capacity-raw", data.capacity_bytes);
    text("generation", data.generation); text("driver-version", data.version || "Unavailable");
    text("cli-version", data.cli_version); text("abi", data.abi); text("unit-bytes", `${data.unit_bytes} bytes`);
    text("features", `${data.features} / 0x${data.features.toString(16)}`);
    text("confidentiality", data.xts ? "AES-256-XTS" : "Not advertised");
    text("integrity", data.integrity ? "HMAC-SHA-256" : "Not advertised");
    text("footer-version", `Driver ${data.version || "unavailable"}`);
    const features = ["xts", "lock", "integrity", "stats"].filter(k => data[k]);
    el("feature-list").replaceChildren(...features.map(name => {
      const tag = document.createElement("span"); tag.textContent = name.toUpperCase(); return tag;
    }));
  }
  function drawChart() {
    const maximum = Math.max(1, ...samples.flatMap(p => [p.read, p.write]));
    for (const key of ["read", "write"]) {
      const points = samples.map((p, i) => `${680 * i / Math.max(1, samples.length - 1)},${130 - p[key] * 110 / maximum}`).join(" ");
      el(`${key}-line`).setAttribute("points", points);
      const latest = samples.at(-1);
      text(`${key}-rate`, latest ? `${bytes(BigInt(Math.round(latest[key])))}/s` : "—");
    }
    text("chart-scale", samples.length ? `SCALE ${bytes(BigInt(Math.ceil(maximum)))}/s · ${samples.length} SAMPLES` : "Awaiting two fresh samples");
  }
  function renderStats(data) {
    const values = parseStats(data), now = performance.now();
    for (const key of counters) {
      text(key, key.endsWith("bytes") ? bytes(values[key]) : values[key].toString());
      if (key.endsWith("bytes")) text(`${key}-raw`, `${values[key]} bytes`);
    }
    el("integrity_failures").closest("article").dataset.failed = String(values.integrity_failures > 0n);
    if (lastFailures !== null && values.integrity_failures > lastFailures) event("Integrity authentication failure count increased.");
    lastFailures = values.integrity_failures;
    const point = sample(previous, values, now - previousTime);
    if (point) { samples.push(point); if (samples.length > 60) samples.shift(); }
    else samples = [];
    previous = values; previousTime = now; drawChart();
  }
  async function refresh() {
    if (polling || !token || document.hidden) return;
    polling = true;
    try {
      const status = await api("/api/status");
      renderStatus(status); // Show a failure latch even if the following stats request fails.
      const stats = await api("/api/stats");
      renderStats(stats);
      if (connected === false) event("Backend reconnected; fresh observations received.");
      connected = true; fresh = true;
      el("data-panels").dataset.stale = "false"; el("stale-label").hidden = true;
      text("connection", "Backend healthy"); el("connection").dataset.health = "healthy";
      text("updated", `Observed ${new Date().toLocaleTimeString([], {hour12: false})}`);
      el("error-panel").hidden = true;
      if (!status.compatible) showError("Compatibility mismatch", status.compatibility_message);
    } catch (error) {
      stale();
      if (!error.code) {
        if (connected !== false) event("Backend disconnected; displayed values are stale.");
        connected = false;
        text("connection", "Connection lost");
        showError("Backend unavailable", "Last observations are stale. Check the local server and reopen its startup URL if it restarted.");
      } else {
        text("connection", "Backend reached · device unavailable");
        showError(error.code.replaceAll("_", " "), error.message);
      }
      el("connection").dataset.health = "error";
    } finally {
      polling = false; el("data-panels").setAttribute("aria-busy", "false"); updateButtons();
    }
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => { if (!busy) await refresh(); schedule(); }, 1000);
  }
  async function act(action) {
    if (busy || !enabled(current?.state, current?.compatible, fresh, false).includes(action)) return;
    busy = true; updateButtons(); text("action-result", "Operation running…");
    clearTimeout(timer);
    // Polling runs sequentially, but an already pending observation can still finish.
    while (polling) await new Promise(resolve => setTimeout(resolve, 25));
    stale();
    try {
      await api(`/api/actions/${action}`, action === "destroy" ? {confirm: "DESTROY"} : {});
      const message = ({"load-random": "Key loaded", lock: "Device locked", unlock: "Device unlocked", destroy: "Key and data destroyed"})[action];
      event(`${message}. Refreshing kernel state.`); text("action-result", `${message}.`);
    } catch (error) {
      const message = error.code ? error.message : "Connection lost during action; outcome unknown. Check state before retrying.";
      event(`Action ${action}: ${message}`); text("action-result", message);
    } finally {
      await refresh(); busy = false; updateButtons(); schedule();
    }
  }
  for (const action of actions) el(action).addEventListener("click", () => {
    if (action !== "destroy") { void act(action); return; }
    el("destroy-confirm").value = ""; updateButtons(); el("destroy-dialog").showModal(); el("destroy-confirm").focus();
  });
  el("destroy-confirm").addEventListener("input", updateButtons);
  el("destroy-dialog").querySelector("form").addEventListener("submit", e => e.preventDefault());
  el("cancel-destroy").addEventListener("click", () => el("destroy-dialog").close());
  el("confirm-destroy").addEventListener("click", () => {
    if (el("destroy-confirm").value === "DESTROY") { el("destroy-dialog").close(); void act("destroy"); }
  });
  document.addEventListener("visibilitychange", () => {
    stale();
    if (!document.hidden && !busy) void refresh();
  });
  window.addEventListener("pagehide", () => { clearTimeout(timer); token = ""; stale(); });
  // Pasting the startup URL into this same tab is otherwise only a fragment
  // navigation, which would leave the old page's missing/expired token in use.
  window.addEventListener("hashchange", () => {
    if (new URLSearchParams(location.hash.slice(1)).has("token")) location.reload();
  });
  if (!token) {
    text("connection", "Authorization required"); el("connection").dataset.health = "error";
    showError("Open the startup access URL", "Use the full URL printed by the local backend. The token stays in memory; a page reload requires that URL again.");
    stale();
  } else { void refresh(); schedule(); }
})();
