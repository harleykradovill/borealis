(function () {
  const tabs = Array.from(document.querySelectorAll(".settings-link"));
  const panels = Array.from(
    document.querySelectorAll('.settings-content[role="tabpanel"]'),
  );

  const fieldConfig = {
    hour_format: { element: "hour-format", type: "value", default: "12" },
    language: { element: "language", type: "value", default: "en" },
    sync_interval: { element: "sync-interval", type: "value", default: "1800" },
    sync_enabled: { element: "sync-enabled", type: "checked", default: true },
    play_threshold: { element: "play-threshold", type: "value", default: "120" },
    discord_enabled: { element: "discord-enabled", type: "checked", default: false },
    discord_url: { element: "discord-url", type: "value", default: "" },
    discord_username: { element: "discord-username", type: "value", default: "" },
    discord_avatar: { element: "discord-avatar", type: "value", default: "" },
  };

  const fields = {};
  const lastKnown = {};

  Object.entries(fieldConfig).forEach(([key, config]) => {
    fields[key] = document.getElementById(config.element);
    lastKnown[key] = null;
  });

  fields.sync_next_at = document.getElementById("sync-next-at");
  fields.manual_periodic_sync_btn = document.getElementById("manual-periodic-sync-btn");
  fields.discord_playback_start = document.getElementById("discord-playback-start");
  fields.discord_playback_stop = document.getElementById("discord-playback-stop");
  fields.discord_sync_complete = document.getElementById("discord-sync-complete");
  fields.discord_sync_error = document.getElementById("discord-sync-error");

  const discordTriggerKeys = [
    "discord_playback_start",
    "discord_playback_stop",
    "discord_sync_complete",
    "discord_sync_error",
  ];

  function collectDiscordTriggers() {
    return {
      playback_start: !!fields.discord_playback_start?.checked,
      playback_stop: !!fields.discord_playback_stop?.checked,
      sync_complete: !!fields.discord_sync_complete?.checked,
      sync_error: !!fields.discord_sync_error?.checked,
    };
  }

  let syncStatusTimer = null;

  function formatRelativeTime(ts, emptyLabel) {
    if (!ts) return emptyLabel;

    let targetSec = Number(ts);
    if (!Number.isFinite(targetSec)) return emptyLabel;

    let nowSec = Math.floor(Date.now() / 1000);
    let diff = targetSec - nowSec;
    let absDiff = Math.abs(diff);

    if (absDiff < 10) {
      return diff >= 0 ? "in a few seconds" : "just now";
    }

    let value = 0;
    let unit = "";

    if (absDiff < 3600) {
      value = Math.floor(absDiff / 60) || 1;
      unit = value === 1 ? "minute" : "minutes";
    } else if (absDiff < 86400) {
      value = Math.floor(absDiff / 3600);
      unit = value === 1 ? "hour" : "hours";
    } else {
      value = Math.floor(absDiff / 86400);
      unit = value === 1 ? "day" : "days";
    }

    return diff >= 0 ? "in " + value + " " + unit : value + " " + unit + " ago";
  }

  function renderSyncStatus(payload) {
    if (!payload || !fields.sync_next_at) return;

    const nextAt = payload.next_scheduled_sync_at;
    fields.sync_next_at.textContent = nextAt
      ? formatRelativeTime(nextAt, "Not scheduled")
      : "Not scheduled";
  }

  async function refreshSyncStatus() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/settings/sync-status");
      if (result?.ok) {
        const payload =
          result.data && typeof result.data === "object" ? result.data : result;
        renderSyncStatus(payload);
      }
    } catch (error) {
      console.warn("Failed to refresh sync status:", error);
    }
  }

  function startSyncStatusPolling() {
    refreshSyncStatus();
    if (syncStatusTimer) clearInterval(syncStatusTimer);
    syncStatusTimer = setInterval(refreshSyncStatus, 60000);
  }

  async function loadSettings() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/settings");
      if (!result?.ok) throw new Error(result?.message || "GET failed");
      const data = result.data || {};

      Object.entries(fieldConfig).forEach(([key, config]) => {
        if (!fields[key]) return;

        const value = data[key] ?? config.default;
        if (config.type === "checked") {
          fields[key].checked = Boolean(value);
          lastKnown[key] = fields[key].checked;
        } else {
          fields[key].value =
            config.type === "value" && key === "sync_interval" ? String(value) : value;
          lastKnown[key] = fields[key].value;
        }
      });

      const triggers = data.discord_triggers || {};
      discordTriggerKeys.forEach((key) => {
        if (fields[key]) {
          const triggerKey = key.replace("discord_", "");
          fields[key].checked = !!triggers[triggerKey];
        }
      });
      lastKnown.discord_triggers = collectDiscordTriggers();
    } catch (error) {
      globalThis.helpers.handleError("Failed to load settings", error);
    }
  }

  let saveTimer = null;
  let pendingPayload = {};

  function scheduleSave(payload) {
    pendingPayload = { ...pendingPayload, ...payload };
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const toSend = pendingPayload;
      pendingPayload = {};
      saveTimer = null;
      saveSettings(toSend);
    }, 200);
  }

  async function saveSettings(payload) {
    try {
      const result = await globalThis.helpers.postJson("/api/settings", payload, "PUT");
      if (!result?.ok) {
        globalThis.helpers.handleError("Failed to save settings", result?.message);
        return;
      }

      const updated = typeof result?.data === "object" ? result.data : result;

      Object.entries(fieldConfig).forEach(([key, config]) => {
        if (!fields[key] || !(key in updated)) return;

        if (config.type === "checked") {
          fields[key].checked = Boolean(updated[key] ?? config.default);
          lastKnown[key] = fields[key].checked;
        } else {
          const value =
            key === "sync_interval" ? String(updated[key] || "") : updated[key];
          fields[key].value = value;
          lastKnown[key] = value;
        }
      });

      globalThis.Toast.showToast("Settings saved");
    } catch (error) {
      globalThis.helpers.handleError("Failed to save settings", error);
    }
  }

  function bindAutosave() {
    Object.entries(fieldConfig).forEach(([key, config]) => {
      if (!fields[key]) return;

      fields[key].addEventListener("change", () => {
        const value =
          config.type === "checked" ? fields[key].checked : fields[key].value;
        if (value !== lastKnown[key]) {
          const saveValue = key === "sync_interval" ? Number(value) : value;
          scheduleSave({ [key]: saveValue });
        }
      });
    });

    discordTriggerKeys.forEach((key) => {
      if (fields[key]) {
        fields[key].addEventListener("change", () => {
          scheduleSave({ discord_triggers: collectDiscordTriggers() });
        });
      }
    });
  }

  let manualSyncPollTimer = null;

  function setManualSyncButtonState(syncing) {
    const btn = fields.manual_periodic_sync_btn;
    if (!btn) return;

    btn.disabled = syncing;
    btn.textContent = syncing ? "Sync Running..." : "Sync Now";
  }

  async function refreshManualSyncButtonState() {
    try {
      const result = await globalThis.helpers.fetchJson(
        "/api/analytics/server/sync-progress",
      );
      if (result?.ok) {
        const syncing = result.syncing === true || result.data?.syncing === true;
        setManualSyncButtonState(!!syncing);
      }
    } catch (error) {
      console.warn("Failed to refresh manual sync button state:", error);
    }
  }

  function startManualSyncButtonPolling() {
    if (manualSyncPollTimer) return;
    manualSyncPollTimer = setInterval(refreshManualSyncButtonState, 10000);
  }

  function bindManualPeriodicSync() {
    const btn = fields.manual_periodic_sync_btn;
    if (!btn) return;

    refreshManualSyncButtonState();
    startManualSyncButtonPolling();

    btn.addEventListener("click", async () => {
      if (btn.disabled) return;

      btn.disabled = true;
      btn.textContent = "Starting...";

      try {
        const result = await globalThis.helpers.postJson(
          "/api/sync/periodic",
          {},
          "POST",
        );
        if (!result?.ok) {
          globalThis.helpers.handleError(
            "Failed to start manual sync",
            result?.message,
          );
        }
      } catch (error) {
        globalThis.helpers.handleError("Failed to start manual sync", error);
      } finally {
        setTimeout(() => {
          refreshManualSyncButtonState();
          refreshSyncStatus();
        }, 300);
      }
    });
  }

  function activate(id) {
    tabs.forEach((t) => {
      const isActive = t.getAttribute("href") === `#${id}`;
      t.classList.toggle("active", isActive);
      t.setAttribute("tabindex", isActive ? "0" : "-1");
    });
    panels.forEach((p) => {
      p.hidden = p.id !== id;
    });

    const header = document.getElementById("header");
    if (header) {
      const activeTab = tabs.find((t) => t.getAttribute("href") === `#${id}`);
      if (activeTab) header.textContent = activeTab.textContent.trim();
    }
  }

  function fromHash() {
    const id = (location.hash || "#display").slice(1);
    const known = panels.some((p) => p.id === id);
    activate(known ? id : "display");
  }

  tabs.forEach((t) => {
    t.addEventListener("click", (e) => {
      e.preventDefault();
      const id = t.getAttribute("href").slice(1);
      history.replaceState(null, "", `#${id}`);
      activate(id);
    });
  });

  globalThis.addEventListener("hashchange", fromHash);
  fromHash();
  loadSettings().then(() => {
    bindAutosave();
    bindManualPeriodicSync();
    startSyncStatusPolling();
  });
})();

(function () {
  const displayElements = {
    btn: document.getElementById("jf-remove-server-btn"),
    name: document.getElementById("jf-server-name-display"),
    host: document.getElementById("jf-server-host-display"),
    key: document.getElementById("jf-server-key-display"),
  };

  const emptyServerConfig = {
    jf_host: "",
    jf_port: "",
    jf_api_key: "",
    jf_server_name: "",
    jf_server_version: "",
  };

  function displayServer(data) {
    if (displayElements.name)
      displayElements.name.textContent = data.jf_server_name || "Unknown Name";
    if (displayElements.host)
      displayElements.host.textContent = `${data.jf_host}:${data.jf_port}`;
    if (displayElements.key) {
      const masked = globalThis.helpers.maskKey(data.jf_api_key);
      displayElements.key.textContent = `API Key: ${masked}`;
    }
  }

  async function checkServerState() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/settings");
      const data = result.data || {};

      if (data.jf_host && data.jf_port && data.jf_api_key) {
        displayServer(data);
      }
    } catch (error) {
      globalThis.helpers.handleError("Failed to check server state", error);
    }
  }

  if (displayElements.btn) {
    displayElements.btn.addEventListener("click", async () => {
      if (!confirm("Remove Jellyfin server configuration?")) return;

      try {
        const result = await globalThis.helpers.postJson(
          "/api/settings",
          emptyServerConfig,
          "PUT",
        );
        if (!result?.ok) {
          globalThis.helpers.handleError("Failed to remove server", result?.message);
          return;
        }
        globalThis.Toast.showToast("Server removed");
      } catch (error) {
        globalThis.helpers.handleError("Failed to remove server", error);
      }
    });
  }

  checkServerState();
})();

(function () {
  const elements = {
    panel: document.getElementById("sync"),
    list: document.getElementById("synclog-list"),
    empty: document.getElementById("synclog-empty"),
    tab: document.getElementById("sync-tab"),
  };

  function setVisibility(showList) {
    if (elements.list) elements.list.hidden = !showList;
    if (elements.empty) elements.empty.hidden = showList;
  }

  function createSyncLogItem(log) {
    const li = document.createElement("li");
    li.classList.add("sync-log-item");

    const res = (log.result || "").toString().toUpperCase();
    if (res === "SUCCESS") li.classList.add("success");
    else if (res === "FAILED" || res === "ERROR") li.classList.add("failed");

    const started = log.started_at ? new Date(Number(log.started_at) * 1000) : null;
    const icon =
      res === "SUCCESS"
        ? "/assets/icons/synclog-success.svg"
        : "/assets/icons/synclog-failed.svg";

    li.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:0.75rem;align-items:center;">
        <div>
          <div style="font-weight:600;color:var(--text);">${globalThis.helpers.escapeHtml(
            log.name || "(unnamed)",
          )}</div>
          <div style="font-size:0.9rem;color:var(--text-muted);">
            ${started ? globalThis.helpers.formatDateTime(started) : ""}
            ${log.type ? " • " + globalThis.helpers.escapeHtml(log.type) : ""}
          </div>
        </div>
        <div style="text-align:right;">
          <img src="${icon}" alt="${res}" style="width:25px;height:25px;flex-shrink:0;">
          <div style="font-weight:600;color:var(--text);">${globalThis.helpers.humanDuration(
            Number(log.duration_ms || 0),
          )}</div>
        </div>
      </div>
    `;
    return li;
  }

  async function loadSyncLogs() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/analytics/sync-logs");
      if (!result?.ok) {
        globalThis.helpers.handleError("Failed to load sync logs", result?.message);
        setVisibility(false);
        return;
      }

      const logs = Array.isArray(result.data) ? result.data : [];
      if (!logs.length) {
        setVisibility(false);
        return;
      }

      if (elements.list) {
        elements.list.innerHTML = "";
        logs.forEach((log) => elements.list.appendChild(createSyncLogItem(log)));
      }
      setVisibility(true);
    } catch (error) {
      globalThis.helpers.handleError("Failed to load sync logs", error);
      setVisibility(false);
    }
  }

  function loadIfVisible() {
    if (elements.panel && !elements.panel.hidden) loadSyncLogs();
  }

  if (location.hash === "#sync") setTimeout(loadIfVisible, 0);
  if (elements.tab)
    elements.tab.addEventListener("click", () => setTimeout(loadIfVisible, 0));
})();

(function () {
  const elements = {
    grid: document.getElementById("db-info-grid"),
    version: document.getElementById("db-version"),
    size: document.getElementById("db-size"),
    created: document.getElementById("db-created"),
    modified: document.getElementById("db-modified"),
  };

  const fieldMap = {
    alembic_version: elements.version,
    size: elements.size,
    created_at: elements.created,
    modified_at: elements.modified,
  };

  async function loadDatabaseInfo() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/database/info");
      if (!result?.ok) {
        globalThis.helpers.handleError("Failed to load database info", result?.message);
        return;
      }

      const data =
        result.data && typeof result.data === "object" ? result.data : result;

      Object.entries(fieldMap).forEach(([dataKey, el]) => {
        if (el && data[dataKey]) {
          el.textContent = data[dataKey];
        }
      });
    } catch (error) {
      globalThis.helpers.handleError("Failed to load database info", error);
    }
  }

  if (elements.grid) {
    loadDatabaseInfo();
  }
})();
