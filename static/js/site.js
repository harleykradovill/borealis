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
