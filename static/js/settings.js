(function () {
  const tabs = Array.from(document.querySelectorAll(".settings-tab"));
  const panels = Array.from(
    document.querySelectorAll('.settings-content[role="tabpanel"]'),
  );

  const fields = {
    hour_format: document.getElementById("hour-format"),
    language: document.getElementById("language"),
    sync_interval: document.getElementById("sync-interval"),
    manual_periodic_sync_btn: document.getElementById("manual-periodic-sync-btn"),
    sync_next_at: document.getElementById("sync-next-at"),
    sync_next_eta: document.getElementById("sync-next-eta"),
    discord_enabled: document.getElementById("discord-enabled"),
    discord_url: document.getElementById("discord-url"),
    discord_username: document.getElementById("discord-username"),
    discord_avatar: document.getElementById("discord-avatar"),
    discord_playback_start: document.getElementById("discord-playback-start"),
    discord_playback_stop: document.getElementById("discord-playback-stop"),
    discord_sync_complete: document.getElementById("discord-sync-complete"),
    discord_sync_error: document.getElementById("discord-sync-error"),
  };

  const lastKnown = {
    hour_format: null,
    language: null,
    sync_interval: null,
    discord_enabled: null,
    discord_url: null,
    discord_username: null,
    discord_avatar: null,
    discord_triggers: null,
  };

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

    if (diff >= 0) {
      return "in " + value + " " + unit;
    }
    return value + " " + unit + " ago";
  }

  function renderSyncStatus(payload) {
    if (!payload) return;

    let nextAt = payload.next_scheduled_sync_at;
    if (fields.sync_next_at) {
      fields.sync_next_at.textContent = nextAt
        ? formatRelativeTime(nextAt, "Not scheduled")
        : "Not scheduled";
    }

    if (fields.sync_next_eta) {
      fields.sync_next_eta.textContent = "";
    }
  }

  async function refreshSyncStatus() {
    let result = await globalThis.helpers.fetchJson("/api/settings/sync-status");
    if (!result?.ok) return;
    let payload = result.data && typeof result.data === "object" ? result.data : result;
    renderSyncStatus(payload);
  }

  function startSyncStatusPolling() {
    refreshSyncStatus().catch(function () {});
    if (syncStatusTimer) clearInterval(syncStatusTimer);
    syncStatusTimer = setInterval(function () {
      refreshSyncStatus().catch(function () {});
    }, 60000);
  }

  async function loadSettings() {
    try {
      const resp = await fetch("/api/settings");
      if (!resp.ok) throw new Error(`GET failed: ${resp.status}`);
      const data = await resp.json();

      if (fields.hour_format) fields.hour_format.value = data.hour_format || "12";
      if (fields.language) fields.language.value = data.language || "en";
      if (fields.sync_interval)
        fields.sync_interval.value = String(data.sync_interval || "1800");
      if (fields.discord_enabled)
        fields.discord_enabled.checked = data.discord_enabled || false;
      if (fields.discord_url) fields.discord_url.value = data.discord_url || "";
      if (fields.discord_username)
        fields.discord_username.value = data.discord_username || "";
      if (fields.discord_avatar)
        fields.discord_avatar.value = data.discord_avatar || "";

      const triggers = data.discord_triggers || {};
      if (fields.discord_playback_start)
        fields.discord_playback_start.checked = !!triggers.playback_start;
      if (fields.discord_playback_stop)
        fields.discord_playback_stop.checked = !!triggers.playback_stop;
      if (fields.discord_sync_complete)
        fields.discord_sync_complete.checked = !!triggers.sync_complete;
      if (fields.discord_sync_error)
        fields.discord_sync_error.checked = !!triggers.sync_error;

      lastKnown.hour_format = fields.hour_format ? fields.hour_format.value : null;
      lastKnown.language = fields.language ? fields.language.value : null;
      lastKnown.sync_interval = fields.sync_interval
        ? fields.sync_interval.value
        : null;
      lastKnown.discord_enabled = fields.discord_enabled
        ? fields.discord_enabled?.checked
        : null;
      lastKnown.discord_url = fields.discord_url ? fields.discord_url.value : null;
      lastKnown.discord_username = fields.discord_username
        ? fields.discord_username.value
        : null;
      lastKnown.discord_avatar = fields.discord_avatar
        ? fields.discord_avatar.value
        : null;
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

      if (fields.hour_format && "hour_format" in updated) {
        fields.hour_format.value = updated.hour_format;
        lastKnown.hour_format = updated.hour_format;
      }
      if (fields.language && "language" in updated) {
        fields.language.value = updated.language;
        lastKnown.language = updated.language;
      }
      if (fields.sync_interval && "sync_interval" in updated) {
        fields.sync_interval.value = String(updated.sync_interval || "");
        lastKnown.sync_interval = fields.sync_interval.value;
      }

      if (fields.discord_enabled && "discord_enabled" in updated) {
        fields.discord_enabled.checked = Boolean(updated.discord_enabled || false);
        lastKnown.discord_enabled = fields.discord_enabled?.checked;
      }

      if (fields.discord_url && "discord_url" in updated) {
        fields.discord_url.value = String(updated.discord_url || "");
        lastKnown.discord_url = fields.discord_url.value;
      }

      if (fields.discord_username && "discord_username" in updated) {
        fields.discord_username.value = String(updated.discord_username || "");
        lastKnown.discord_username = fields.discord_username.value;
      }

      if (fields.discord_avatar && "discord_avatar" in updated) {
        fields.discord_avatar.value = String(updated.discord_avatar || "");
        lastKnown.discord_avatar = fields.discord_avatar.value;
      }

      globalThis.Toast.showToast("Settings saved");
    } catch (error) {
      globalThis.helpers.handleError("Failed to save settings", error);
    }
  }

  function bindAutosave() {
    if (fields.hour_format) {
      fields.hour_format.addEventListener("blur", () => {
        const v = fields.hour_format.value;
        if (v !== lastKnown.hour_format) scheduleSave({ hour_format: v });
      });
      fields.hour_format.addEventListener("change", () => {
        const v = fields.hour_format.value;
        if (v !== lastKnown.hour_format) scheduleSave({ hour_format: v });
      });
    }
    if (fields.language) {
      fields.language.addEventListener("blur", () => {
        const v = fields.language.value;
        if (v !== lastKnown.language) scheduleSave({ language: v });
      });
      fields.language.addEventListener("change", () => {
        const v = fields.language.value;
        if (v !== lastKnown.language) scheduleSave({ language: v });
      });
    }
    if (fields.sync_interval) {
      fields.sync_interval.addEventListener("blur", () => {
        const v = String(fields.sync_interval.value);
        if (v !== lastKnown.sync_interval) scheduleSave({ sync_interval: Number(v) });
      });
      fields.sync_interval.addEventListener("change", () => {
        const v = String(fields.sync_interval.value);
        if (v !== lastKnown.sync_interval) scheduleSave({ sync_interval: Number(v) });
      });
    }
    if (fields.discord_enabled) {
      fields.discord_enabled.addEventListener("blur", () => {
        const v = Boolean(fields.discord_enabled?.checked);
        if (v !== lastKnown.discord_enabled) scheduleSave({ discord_enabled: v });
      });
      fields.discord_enabled.addEventListener("change", () => {
        const v = Boolean(fields.discord_enabled?.checked);
        if (v !== lastKnown.discord_enabled) scheduleSave({ discord_enabled: v });
      });
    }
    if (fields.discord_url) {
      fields.discord_url.addEventListener("blur", () => {
        const v = String(fields.discord_url.value);
        if (v !== lastKnown.discord_url) scheduleSave({ discord_url: v });
      });
      fields.discord_url.addEventListener("change", () => {
        const v = String(fields.discord_url.value);
        if (v !== lastKnown.discord_url) scheduleSave({ discord_url: v });
      });
    }
    if (fields.discord_username) {
      fields.discord_username.addEventListener("blur", () => {
        const v = String(fields.discord_username.value);
        if (v !== lastKnown.discord_username) scheduleSave({ discord_username: v });
      });
      fields.discord_username.addEventListener("change", () => {
        const v = String(fields.discord_username.value);
        if (v !== lastKnown.discord_username) scheduleSave({ discord_username: v });
      });
    }
    if (fields.discord_avatar) {
      fields.discord_avatar.addEventListener("blur", () => {
        const v = String(fields.discord_avatar.value);
        if (v !== lastKnown.discord_avatar) scheduleSave({ discord_avatar: v });
      });
      fields.discord_avatar.addEventListener("change", () => {
        const v = String(fields.discord_avatar.value);
        if (v !== lastKnown.discord_avatar) scheduleSave({ discord_avatar: v });
      });
    }

    const triggerFields = [
      "discord_playback_start",
      "discord_playback_stop",
      "discord_sync_complete",
      "discord_sync_error",
    ];
    triggerFields.forEach((key) => {
      const el = fields[key];
      if (el) {
        el.addEventListener("change", () => {
          scheduleSave({ discord_triggers: collectDiscordTriggers() });
        });
      }
    });
  }

  let manualSyncPollTimer = null;

  function setManualSyncButtonState(syncing) {
    const btn = fields.manual_periodic_sync_btn;
    if (!btn) return;

    if (syncing) {
      btn.disabled = true;
      btn.textContent = "Sync Running...";
      return;
    }

    btn.disabled = false;
    btn.textContent = "Sync Now";
  }

  async function refreshManualSyncButtonState() {
    const result = await globalThis.helpers.fetchJson(
      "/api/analytics/server/sync-progress",
    );
    if (!result?.ok) return;

    const syncing = result.syncing === true || result.data?.syncing === true;

    setManualSyncButtonState(!!syncing);
  }

  function startManualSyncButtonPolling() {
    if (manualSyncPollTimer) return;
    manualSyncPollTimer = setInterval(() => {
      refreshManualSyncButtonState().catch(() => {});
    }, 10000);
  }

  function bindManualPeriodicSync() {
    const btn = fields.manual_periodic_sync_btn;
    if (!btn) return;

    refreshManualSyncButtonState().catch(() => {});
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
          await refreshManualSyncButtonState();
          return;
        }
      } catch (error) {
        globalThis.helpers.handleError("Failed to start manual sync", error);
      } finally {
        setTimeout(handleSyncComplete, 300);
        refreshSyncStatus().catch(function () {});
      }
    });
  }

  function handleSyncComplete() {
    refreshManualSyncButtonState().catch(() => {});
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
  }

  function fromHash() {
    const id = (location.hash || "#general").slice(1);
    const known = panels.some((p) => p.id === id);
    activate(known ? id : "general");
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
  const removeServerBtn = document.getElementById("jf-remove-server-btn");
  const serverHostDisplay = document.getElementById("jf-server-host-display");
  const serverKeyDisplay = document.getElementById("jf-server-key-display");
  const serverNameDisplay = document.getElementById("jf-server-name-display");

  function displayServer(name, host, port, apiKey) {
    if (serverNameDisplay) {
      serverNameDisplay.textContent = name || "Unknown Name";
    }
    if (serverHostDisplay) {
      serverHostDisplay.textContent = `${host}:${port}`;
    }
    if (serverKeyDisplay) {
      const masked = globalThis.helpers.maskKey(apiKey);
      serverKeyDisplay.textContent = `API Key: ${masked}`;
    }
  }

  async function checkServerState() {
    try {
      const resp = await fetch("/api/settings");
      if (!resp.ok) return;
      const data = await resp.json();

      const hasServer = !!(data.jf_host && data.jf_port && data.jf_api_key);

      if (hasServer) {
        displayServer(data.jf_server_name, data.jf_host, data.jf_port, data.jf_api_key);
      }
    } catch (error) {
      globalThis.helpers.handleError("Failed to check server state", error);
    }
  }

  if (removeServerBtn) {
    removeServerBtn.addEventListener("click", async () => {
      if (!confirm("Remove Jellyfin server configuration?")) return;

      try {
        const resp = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jf_host: "",
            jf_port: "",
            jf_api_key: "",
            jf_server_name: "",
            jf_server_version: "",
          }),
        });

        if (!resp.ok) {
          globalThis.helpers.handleError("Failed to remove server", resp?.message);
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
  const panel = document.getElementById("tasklog");
  const list = document.getElementById("tasklog-list");
  const empty = document.getElementById("tasklog-empty");
  const tab = document.getElementById("task-log-tab");

  async function loadTaskLogs() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/analytics/task-logs");
      if (!result.ok) {
        globalThis.helpers.handleError("Failed to load task logs", result.message);
        if (empty) empty.hidden = false;
        if (list) list.hidden = true;
        return;
      }

      const logs = Array.isArray(result.data) ? result.data : [];
      if (!logs.length) {
        if (empty) empty.hidden = false;
        if (list) list.hidden = true;
        return;
      }

      if (empty) empty.hidden = true;
      if (list) list.hidden = false;
      list.innerHTML = "";

      logs.forEach((l) => {
        const li = document.createElement("li");

        li.classList.add("task-log-item");
        const res = (l.result || "").toString().toUpperCase();
        if (res === "SUCCESS") li.classList.add("success");
        else if (res === "FAILED" || res === "ERROR") li.classList.add("failed");

        const started = l.started_at ? new Date(Number(l.started_at) * 1000) : null;
        const iconSrc =
          res === "SUCCESS"
            ? "/assets/icons/tasklog-success.svg"
            : "/assets/icons/tasklog-failed.svg";

        li.innerHTML = `
          <div style="display:flex;justify-content:space-between;gap:0.75rem;align-items:center;">
            <div>
              <div style="font-weight:600;color:var(--text);">${globalThis.helpers.escapeHtml(
                l.name || "(unnamed)",
              )}</div>
              <div style="font-size:0.9rem;color:var(--text-muted);">
                ${started ? started.toLocaleString() : ""}
                ${l.type ? " • " + globalThis.helpers.escapeHtml(l.type) : ""}
              </div>
            </div>
            <div style="text-align:right;">
              <img src="${iconSrc}" alt="${res}" style="width:25px;height:25px;flex-shrink:0;">
              <div style="font-weight:600;color:var(--text);">${globalThis.helpers.humanDuration(
                Number(l.duration_ms || 0),
              )}</div>
            </div>
          </div>
        `;
        list.appendChild(li);
      });
    } catch (error) {
      globalThis.helpers.handleError("Failed to load task logs", error);
      if (empty) empty.hidden = false;
      if (list) list.hidden = true;
    }
  }

  function loadIfVisible() {
    if (panel && !panel.hidden) loadTaskLogs();
  }

  if (location.hash === "#tasklog") setTimeout(loadIfVisible, 0);
  if (tab) tab.addEventListener("click", () => setTimeout(loadIfVisible, 0));
})();

(function () {
  const dbInfoGrid = document.getElementById("db-info-grid");

  async function loadDatabaseInfo() {
    try {
      const result = await globalThis.helpers.fetchJson("/api/database/info");
      if (!result?.ok) {
        globalThis.helpers.handleError(
          "Failed to load database info:",
          result?.message,
        );
        return;
      }

      const data =
        result.data && typeof result.data === "object" ? result.data : result;

      if (dbInfoGrid) {
        if (data.alembic_version && document.getElementById("db-version")) {
          document.getElementById("db-version").textContent = data.alembic_version;
        }
        if (data.size && document.getElementById("db-size")) {
          document.getElementById("db-size").textContent = data.size;
        }
        if (data.created_at && document.getElementById("db-created")) {
          document.getElementById("db-created").textContent = data.created_at;
        }
        if (data.modified_at && document.getElementById("db-modified")) {
          document.getElementById("db-modified").textContent = data.modified_at;
        }
      }
    } catch (error) {
      globalThis.helpers.handleError("Failed to load database info", error);
    }
  }

  if (dbInfoGrid) {
    loadDatabaseInfo();
  }
})();
