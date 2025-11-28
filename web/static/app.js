"use strict";

const SECRET_KEYS = ["DISCORD_TOKEN", "JELLYFIN_API_KEY"];
const initialSecrets = {};

function isRedactedFormat(v) {
  return !!v && (/^[*]+$/.test(v) || /^.{1,10}…\*+$/.test(v));
}

// Refresh bot connection status badge
async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const j = await res.json();
    const el = document.getElementById("bot-status");
    if (j.bot_connected) {
      el.innerHTML = "Bot status: <strong class=\"ok\">connected</strong>";
    } else {
      el.innerHTML = "Bot status: <strong class=\"bad\">not connected</strong>";
    }
  } catch (e) {
    document.getElementById("bot-status").textContent = "Bot status: error";
  }
}

// Load redacted config values into form fields
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const j = await res.json();
    ["DISCORD_TOKEN", "JELLYFIN_URL", "JELLYFIN_API_KEY"].forEach(k => {
      const el = document.getElementById(k);
      if (!el) return;
      el.value = j[k] || "";
      if (SECRET_KEYS.includes(k) && isRedactedFormat(el.value)) {
        initialSecrets[k] = el.value;
      }
    });
  } catch (e) {
    // Silent
  }
}

function initSecretClearButtons() {
  SECRET_KEYS.forEach(k => {
    const btn = document.getElementById(k + "_clear");
    const input = document.getElementById(k);
    if (btn && input) {
      btn.addEventListener("click", () => {
        input.value = "";
        input.dataset.cleared = "true";
      });
    }
  });
}

// Handle config form submission
document.getElementById("config-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const payload = new FormData();

    ["DISCORD_TOKEN", "JELLYFIN_URL", "JELLYFIN_API_KEY"].forEach(k => {
        const el = document.getElementById(k);
        if (!el) return;
        const val = el.value;
        const wasRedacted = initialSecrets[k] && val === initialSecrets[k];
        const cleared = el.dataset.cleared === "true";
    if (SECRET_KEYS.includes(k)) {
      if (cleared) {
        payload.append(k, "");
      } else if (wasRedacted) {
        return;
      } else {
        payload.append(k, val);
      }
    } else {
      payload.append(k, val);
    }
  });

  const res = await fetch("/api/config", { method: "POST", body: payload });
  const j = await res.json();
  document.getElementById("save-result").textContent =
    j.updated?.length ? "Saved." : "No changes.";
  refreshStatus();
});

// Handle test notification form
document.getElementById("notify-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = {
    channel_id: document.getElementById("channel_id").value,
    message: document.getElementById("message").value
  };
  const res = await fetch("/api/notify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const j = await res.json();
  document.getElementById("notify-result").textContent =
    j.ok ? "Sent (stub)." : ("Error: " + (j.error || "unknown"));
});

// Jellyfin auth test
document.getElementById("jellyfin-test-btn").addEventListener("click", async () => {
  const btn = document.getElementById("jellyfin-test-btn");
  const out = document.getElementById("jellyfin-test-result");
  const url = document.getElementById("JELLYFIN_URL").value.trim();
  const apiInput = document.getElementById("JELLYFIN_API_KEY");
  const apiValRaw = apiInput.value.trim();
  const useStored = initialSecrets["JELLYFIN_API_KEY"] &&
                     apiValRaw === initialSecrets["JELLYFIN_API_KEY"];
  const apiKey = useStored ? "" : apiValRaw;

  out.textContent = "";
  out.className = "";
  btn.disabled = true;

  try {
    const res = await fetch("/api/jellyfin/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, api_key: apiKey })
    });
    const j = await res.json();
    if (j.ok) {
      const name = j.user?.name || "unknown";
      out.textContent = `OK: authenticated as ${name}`;
      out.className = "ok";
    } else {
      out.textContent = `Error: ${j.error || "unknown"}`;
      out.className = "bad";
    }
  } catch (e) {
    out.textContent = "Error: network or server issue";
    out.className = "bad";
  } finally {
    btn.disabled = false;
  }
});

loadConfig().then(() => initSecretClearButtons());
refreshStatus();