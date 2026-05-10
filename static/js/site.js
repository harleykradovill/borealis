(function () {
  if (globalThis.__syncToastBridgeInitialized) return;
  globalThis.__syncToastBridgeInitialized = true;

  let syncToastId = null;
  let source = null;
  let fallbackTimer = null;
  const fallbackIntervalMs = 45000;

  function getSyncMessage(payload) {
    const message = String(payload?.message || "Sync in progress");
    const processed = Number(payload?.processed_events || 0);
    const total = Number(payload?.total_events || 0);

    if (total > 0) {
      return `${message} (${Math.min(processed, total)}/${total})`;
    }
    return message;
  }

  function renderSyncState(payload) {
    if (!payload || payload.ok === false) return;
    const syncing = Boolean(payload.syncing);

    if (syncing) {
      const message = getSyncMessage(payload);
      if (syncToastId) {
        Toast.updateSyncToast(syncToastId, message);
      } else {
        syncToastId = Toast.showSyncToast(message);
      }
      return;
    }

    if (syncToastId) {
      Toast.hideSyncToast(syncToastId);
      syncToastId = null;
      globalThis.Toast.showToast("Sync complete");
    }
  }

  async function fetchSyncSnapshot() {
    try {
      const resp = await fetch("/api/analytics/server/sync-progress");
      if (!resp.ok) return;
      const payload = await resp.json();
      renderSyncState(payload);
    } catch (error) {
      globalThis.Toast.showToast("Failed to fetch sync progress snapshot", "error");
      console.error("Failed to fetch sync progress snapshot: ", error);
    }
  }

  function startFallbackPolling() {
    if (fallbackTimer) return;
    fallbackTimer = setInterval(fetchSyncSnapshot, fallbackIntervalMs);
    fetchSyncSnapshot();
  }

  function disconnectSyncStream() {
    stopFallbackPolling();

    if (source) {
      source.close();
      source = null;
    }
  }

  function stopFallbackPolling() {
    if (!fallbackTimer) return;
    clearInterval(fallbackTimer);
    fallbackTimer = null;
  }

  function connectSyncStream() {
    disconnectSyncStream();

    if (!globalThis.EventSource) {
      startFallbackPolling();
      return;
    }

    source = new EventSource("/api/analytics/server/sync-progress/stream");

    source.addEventListener("sync_progress", (event) => {
      try {
        const payload = JSON.parse(event.data);
        renderSyncState(payload);
      } catch (error) {
        globalThis.Toast.showToast("Failed to fetch sync progress", "error");
        console.error("Invalid sync_progress payload: ", error);
      }
    });

    source.onopen = () => {
      stopFallbackPolling();
    };

    source.onerror = () => {
      startFallbackPolling();
    };
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      fetchSyncSnapshot();
    }
  });

  window.addEventListener("pagehide", disconnectSyncStream);
  window.addEventListener("beforeunload", disconnectSyncStream);

  connectSyncStream();
  fetchSyncSnapshot();
})();

globalThis.jf_helpers = (function () {
  async function fetchJson(path, opts = {}) {
    try {
      const resp = await fetch(path, opts.method ? opts : { method: "GET" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          message: data?.message || "HTTP error",
          data: null,
        };
      }
      if (data && typeof data === "object" && ("ok" in data || "data" in data)) {
        return data;
      }
      return { ok: true, status: resp.status, data };
    } catch (error) {
      globalThis.Toast.showToast("Network error", "error");
      return {
        ok: false,
        status: 0,
        message: error?.message || "Network error",
        data: null,
      };
    }
  }

  async function postJson(path, body, method = "POST") {
    try {
      const resp = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        return {
          ok: false,
          status: resp.status,
          message: data?.message || "HTTP error",
          data: null,
        };
      }
      if (data && typeof data === "object" && ("ok" in data || "data" in data)) {
        return data;
      }
      return { ok: true, status: resp.status, data };
    } catch (error) {
      globalThis.Toast.showToast("Network error", "error");
      return {
        ok: false,
        status: 0,
        message: error?.message || "Network error",
        data: null,
      };
    }
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s).replaceAll(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  }

  function humanDuration(ms) {
    if (!ms || ms <= 0) return "0s";
    let s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    s = s % 3600;
    const m = Math.floor(s / 60);
    const sec = s % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${sec}s`;
    return `${sec}s`;
  }

  function humanBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${units[i]}`;
  }

  function humanTime(seconds) {
    if (!seconds || seconds === 0) return "0s";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function maskKey(key) {
    if (!key) return "";
    if (key.length <= 4) return "•".repeat(key.length);
    return `${key.slice(0, 4)}${"•".repeat(Math.max(8, key.length - 4))}`;
  }

  function toLocalISO(date) {
    const yr = date.getFullYear();
    const mo = String(date.getMonth() + 1).padStart(2, "0");
    const da = String(date.getDate()).padStart(2, "0");
    return `${yr}-${mo}-${da}`;
  }

  function addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }

  return {
    fetchJson,
    postJson,
    escapeHtml,
    humanDuration,
    humanBytes,
    humanTime,
    maskKey,
    toLocalISO,
    addDays,
  };
})();
