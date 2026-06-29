(function () {
  if (globalThis.__syncToastBridgeInitialized) return;
  globalThis.__syncToastBridgeInitialized = true;

  let syncToastId = null;
  let source = null;
  let fallbackTimer = null;
  const fallbackIntervalMs = 45000;

  /**
   * Builds a user-facing sync progress message from the payload.
   * @param {Object} payload Sync payload from the server
   * @returns {string} A formatted message, including progress counts when available
   */
  function getSyncMessage(payload) {
    const message = String(payload?.message || "Sync in progress");
    const step = Number(payload?.step || payload?.processed_events || 0);
    const total = Number(payload?.step_total || payload?.total_events || 0);

    if (step > 0 && total > 0) {
      return `${message} (${Math.min(step, total)}/${total})`;
    }
    return message;
  }

  /**
   * Updates the sync toast UI based on the latest payload.
   * @param {Object} payload Sync state payload from the server or stream
   * @returns {void}
   */
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
      Toast.removeToast(syncToastId);
      syncToastId = null;
      globalThis.Toast.showToast("Sync complete");
    }
  }

  /**
   * Fetches the current sync progress snapshot from the server.
   * @returns {Promise<void>} Resolves after the snapshot has been fetched and rendered
   */
  async function fetchSyncSnapshot() {
    try {
      const resp = await fetch("/api/analytics/server/sync-progress");
      if (!resp.ok) return;
      const payload = await resp.json();
      renderSyncState(payload);
    } catch (error) {
      globalThis.helpers.handleError("Failed to fetch sync progress snapshot", error);
    }
  }

  /**
   * Starts fallback polling for sync progress when server-send events are unavailable.
   * @returns {void}
   */
  function startFallbackPolling() {
    if (fallbackTimer) return;
    fallbackTimer = setInterval(fetchSyncSnapshot, fallbackIntervalMs);
    fetchSyncSnapshot();
  }

  /**
   * Disconnects the current sync event stream and stops fallback polling.
   * @returns {void}
   */
  function disconnectSyncStream() {
    stopFallbackPolling();

    if (source) {
      source.close();
      source = null;
    }
  }

  /**
   * Stops the fallback polling timer if it is active.
   * @returns {void}
   */
  function stopFallbackPolling() {
    if (!fallbackTimer) return;
    clearInterval(fallbackTimer);
    fallbackTimer = null;
  }

  /**
   * Opens the server-send events stream for sync progress and falls back to polling on error.
   * @returns {void}
   */
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

        if (payload.sync_complete && payload.syncing === false) {
          const syncCompleteEvent = new CustomEvent("syncComplete", {
            detail: payload,
          });
          document.dispatchEvent(syncCompleteEvent);
        }

        renderSyncState(payload);
      } catch (error) {
        globalThis.helpers.handleError("Failed to fetch sync progress", error);
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

globalThis.helpers = (function () {
  /**
   * Fetches JSON from the given path.
   * @param {string} path The URL to request
   * @returns {Promise<Object>} Resolves with an object containing 'ok', 'status', and 'data' or error details.
   */
  async function fetchJson(path) {
    try {
      const resp = await fetch(path, { method: "GET" });
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
      globalThis.helpers.handleError("Network error", error);
      return {
        ok: false,
        status: 0,
        message: error?.message || "Network error",
        data: null,
      };
    }
  }

  /**
   * Sends a JSON payload via POST to the given path.
   * @param {string} path The URL to send the request to
   * @param {Object} body The JS object to serialize as JSON
   * @param {string} method HTTP method to use
   * @returns {Promise<Object>} Resolves with the parsed response or error details
   */
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
      globalThis.helpers.handleError("Network error", error);
      return {
        ok: false,
        status: 0,
        message: error?.message || "Network error",
        data: null,
      };
    }
  }

  /**
   * Escapes special HTML characters in a string for safe insertion into DOM.
   * @param {(string|null|undefined)} s The input string to escape
   * @returns {string} The escaped string, emptry if input is null/undefined
   */
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

  /**
   * Converts a duration in ms to a human-readable string.
   * @param {number} ms Duration in milliseconds
   * @returns {string} Human-readable representation (e.g., "1h 5m")
   */
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

  /**
   * Converts a byte count into a readable unit string.
   * @param {number} bytes Number of bytes
   * @returns {string} Human-readable representation (e.g., "12.34 MB")
   */
  function humanBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${units[i]}`;
  }

  /**
   * Converts seconds into a human-readable string.
   * @param {number} seconds Time in seconds
   * @returns {string} Human-readable representation (e.g., "2h 30m")
   */
  function humanTime(seconds) {
    if (!seconds || seconds === 0) return "0s";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  }

  /**
   * Masks a key, showing only the first four characters and replacing the rest with dots.
   * @param {string} key The key to mask
   * @returns {string} Masked key string
   */
  function maskKey(key) {
    if (!key) return "";
    if (key.length <= 4) return "•".repeat(key.length);
    return `${key.slice(0, 4)}${"•".repeat(Math.max(8, key.length - 4))}`;
  }

  /**
   * Converts a Date object into an ISO-8601 date string (YYYY-MM-DD)
   * @param {Date} date The date to format
   * @returns {string} ISO date string
   */
  function toLocalISO(date) {
    const yr = date.getFullYear();
    const mo = String(date.getMonth() + 1).padStart(2, "0");
    const da = String(date.getDate()).padStart(2, "0");
    return `${yr}-${mo}-${da}`;
  }

  /**
   * Adds a specified number of days to a Date object and returns the new date.
   * @param {Date} date Original date
   * @param {number} days Number of days to add
   * @returns {Date} New date with added days
   */
  function addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }

  /**
   * Sends a toast, as well as a console error for user-facing errors.
   * @param {string} message Message to display
   * @param {string} error Raw error for console
   */
  function handleError(message, error) {
    globalThis.Toast.showToast(message, "error");
    console.error(`${message}: `, error);
  }

  /**
   * Gets a color palette, optionally generating interpolated colors.
   * @param {number} count Number of colors to generate/return
   * @param {boolean} reverse Reverse palette order
   * @returns {Array<string>} Array of hex color strings
   */
  function getPalette(count = null, reverse = false) {
    const palette = [
      "#1f2b31",
      "#193842",
      "#114751",
      "#0a5962",
      "#19646a",
      "#0b7b68",
      "#078f63",
      "#10aa4d",
      "#00df96",
    ];

    const colors = reverse ? [...palette].reverse() : [...palette];

    if (count === null || count >= colors.length) return colors;

    if (count === 1) {
      return [colors[Math.floor((colors.length - 1) / 2)]];
    }

    const lastIndex = colors.length - 1;
    return Array.from({ length: count }, (_, i) => {
      const index = Math.round((i * lastIndex) / (count - 1));
      return colors[index];
    });
  }

  /**
   * Generates an array of ISO date strings for a date range.
   * @param {Date} startDate Starting date
   * @param {number} days Number of days to include
   * @returns {Array<string>} Array of ISO date strings (YYYY-MM-DD)
   */
  function generateDateLabels(startDate, days = 14) {
    const dates = [];
    for (let i = 0; i < days; i++) {
      const d = addDays(startDate, i);
      dates.push(toLocalISO(d));
    }
    return dates;
  }

  /**
   * Extract media item title from a playback event string
   * @param {string} eventName Full event text
   * @param {string} playbackType Playback event type (e.g, "VideoPlayback", "VideoPlaybackStopped")
   * @returns {string} Extracted media title, or empty string when not available
   */
  function extractMediaItemName(eventName, playbackType) {
    if (!eventName) return "";
    let name = eventName;
    if (playbackType === "VideoPlayback") {
      const match = new RegExp(/is playing (.+)$/).exec(name);
      name = match ? match[1] : name;
    } else if (playbackType === "VideoPlaybackStopped") {
      const match = new RegExp(/has finished playing (.+)$/).exec(name);
      name = match ? match[1] : name;
    }
    return name.replace(/ on .+$/, "");
  }

  /**
   * Converts a Date object into an M/D format string (e.g., "5/22")
   * @param {Date} date The date to format
   * @returns {string} Formatted date string
   */
  function toLocalMD(date) {
    const mo = String(date.getMonth() + 1);
    const da = String(date.getDate());
    return `${mo}/${da}`;
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
    handleError,
    getPalette,
    generateDateLabels,
    extractMediaItemName,
    toLocalMD,
  };
})();
