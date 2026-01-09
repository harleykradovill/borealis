(function () {
  function showToast(message, kind = "success", ttl = 5000) {
    if (window.Toast && typeof window.Toast.showToast === "function") {
      return window.Toast.showToast(message, kind, ttl);
    }
    const container = document.getElementById("toast-container");
    if (!container) return null;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.setAttribute("role", "status");
    el.textContent = message;
    container.appendChild(el);
    if (typeof ttl === "number" && ttl > 0) {
      setTimeout(() => el.remove(), ttl);
    }
    return null;
  }

  async function postJson(path, body, method = "POST") {
    try {
      const resp = await fetch(path, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return await resp.json();
    } catch (err) {
      return { ok: false, status: 0, message: err?.message || "Network error" };
    }
  }

  function maskKey(key) {
    if (!key) return "";
    if (key.length <= 8) return "•".repeat(Math.max(4, key.length));
    return `${key.slice(0, 4)}…${key.slice(-4)}`;
  }

  // Elements
  const hostInput = document.getElementById("jf-first-host");
  const portInput = document.getElementById("jf-first-port");
  const keyInput = document.getElementById("jf-first-api-key");
  const testBtn = document.getElementById("jf-first-test-btn");
  const addBtn = document.getElementById("jf-first-add-btn");
  const form = document.getElementById("first-start-form");
  const noServerDiv = document.getElementById("jf-first-no-server");

  let lastTestOk = false;
  let testingConnection = false;
  let capturedServerName = "";
  let capturedServerVersion = "";

  if (addBtn) {
    addBtn.disabled = true;
  }

  [hostInput, portInput, keyInput].forEach((el) => {
    if (!el) return;
    el.addEventListener("input", () => {
      lastTestOk = false;
      if (addBtn) {
        addBtn.disabled = true;
      }
    });
  });

  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      const host = (hostInput?.value || "").trim();
      const port = (portInput?.value || "").trim();
      const apiKey = (keyInput?.value || "").trim();

      if (!host || !port || !apiKey) {
        showToast("Please fill in host, port and API key", "error");
        return;
      }

      if (testingConnection) return;
      testingConnection = true;
      testBtn.disabled = true;

      if (addBtn) {
        addBtn.disabled = true;
      }

      const original = testBtn.textContent;
      testBtn.textContent = "Testing...";

      const result = await postJson(
        "/api/test-connection-with-credentials",
        { jf_host: host, jf_port: port, jf_api_key: apiKey },
        "POST"
      );

      testingConnection = false;

      if (result && result.ok) {
        lastTestOk = true;
        capturedServerName = result.server_name || "";
        capturedServerVersion = result.server_version || "";
        showToast("Connection successful", "success");
        if (addBtn) {
          addBtn.disabled = false;
          addBtn.focus();
        }
      } else {
        lastTestOk = false;
        const msg =
          result?.message || `Failed (status: ${result?.status ?? "n/a"})`;
        showToast(msg, "error");

        if (addBtn) {
          addBtn.disabled = true;
        }
      }

      testBtn.textContent = original;
      setTimeout(() => (testBtn.disabled = false), 3000);
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      const host = (hostInput?.value || "").trim();
      const port = (portInput?.value || "").trim();
      const apiKey = (keyInput?.value || "").trim();
      const hourFormat = document.getElementById("hour-format")?.value || "12";
      const language = document.getElementById("language")?.value || "en";

      if (!host || !port || !apiKey) {
        showToast("Please fill in host, port and API key", "error");
        return;
      }

      if (!lastTestOk) {
        showToast(
          "Please test the connection and ensure it's successful before adding the server",
          "error"
        );
        return;
      }

      addBtn.disabled = true;
      testBtn.disabled = true;
      hostInput.disabled = true;
      portInput.disabled = true;
      keyInput.disabled = true;
      const original = addBtn.textContent;
      addBtn.textContent = "Saving...";

      const resp = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jf_host: host,
          jf_port: port,
          jf_api_key: apiKey,
          jf_server_name: capturedServerName,
          jf_server_version: capturedServerVersion,
          hour_format: hourFormat,
          language: language,
        }),
      });

      if (!resp.ok) {
        showToast("Failed to save settings", "error");
        addBtn.textContent = original;
        addBtn.disabled = false;
        testBtn.disabled = false;
        hostInput.disabled = false;
        portInput.disabled = false;
        keyInput.disabled = false;
        return;
      }

      try {
        const data = await resp.json();
        showToast("Server added successfully", "success");

        if (noServerDiv) noServerDiv.hidden = true;

        const syncInfo = document.querySelector(".jf-sync-info");
        const syncText = document.getElementById("jf-first-sync-text");
        const placeholder = document.querySelector(".first-start-placeholder");
        const serverBox = document.getElementById("server-box");
        const firstStartForm = document.querySelector(".form-grid");

        if (placeholder) placeholder.hidden = true;
        if (form) form.hidden = true;
        if (serverBox) serverBox.hidden = true;
        if (firstStartForm) firstStartForm.hidden = true;
        if (syncInfo) syncInfo.hidden = false;
        if (syncText) syncText.textContent = "Performing initial sync";

        const POLL_INTERVAL = 1000;
        const TIMEOUT_MS = 10 * 60 * 1000;
        const startTs = Date.now();

        async function pollProgress() {
          try {
            const r = await fetch("/api/analytics/server/sync-progress", {
              cache: "no-store",
            });
            if (!r.ok) {
              if (r.status === 500) {
                console.error("Server error checking sync progress", r.status);
                if (Date.now() - startTs > TIMEOUT_MS) {
                  showToast(
                    "Initial sync is taking longer than expected. You " +
                      "can continue to the app; background sync will finish " +
                      "automatically.",
                    "error"
                  );
                  setTimeout(() => {
                    window.location.href = "/";
                  }, 1200);
                  return;
                }
                setTimeout(pollProgress, POLL_INTERVAL);
                return;
              }
              throw new Error("Network");
            }
            const j = await r.json();
            if (!j || !j.ok) {
              throw new Error(j?.message || "Bad response");
            }

            const syncing = Boolean(j.syncing);

            if (!syncing) {
              setTimeout(() => {
                window.location.href = "/";
              }, 800);
              return;
            }

            if (Date.now() - startTs > TIMEOUT_MS) {
              showToast(
                "Initial sync is taking longer than expected. You can " +
                  "continue to the app; background sync will finish " +
                  "automatically.",
                "error"
              );
              setTimeout(() => {
                window.location.href = "/";
              }, 1200);
              return;
            }

            setTimeout(pollProgress, POLL_INTERVAL);
          } catch (err) {
            console.error("Sync progress fetch error", err);
            if (Date.now() - startTs > TIMEOUT_MS) {
              showToast(
                "Unable to determine sync progress - continuing",
                "error"
              );
              window.location.href = "/";
              return;
            }
            setTimeout(pollProgress, POLL_INTERVAL);
          }
        }

        // Start polling loop
        setTimeout(pollProgress, 500);
      } catch (err) {
        showToast("Saved but failed to parse response", "error");
        console.error(err);
        addBtn.textContent = original;
        addBtn.disabled = false;
        testBtn.disabled = false;
        hostInput.disabled = false;
        portInput.disabled = false;
        keyInput.disabled = false;
      }
    });
  }
})();
