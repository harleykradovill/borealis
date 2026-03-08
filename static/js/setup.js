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
      return {
        ok: false,
        status: 0,
        message: err?.message || "Network error",
      };
    }
  }

  const state = {
    hourFormat: "12",
    language: "en",
    syncInterval: 1800,
    jfHost: "",
    jfPort: "",
    jfApiKey: "",
    serverName: "",
    serverVersion: "",
  };

  let currentPage = 1;
  let testConnectionOk = false;
  let availableLibraries = [];

  const pageElements = {
    1: document.querySelector('.setup-page[data-page="1"]'),
    2: document.querySelector('.setup-page[data-page="2"]'),
    3: document.querySelector('.setup-page[data-page="3"]'),
    sync: document.querySelector('.setup-page[data-page="sync"]'),
  };

  const formFields = {
    hourFormat: document.getElementById("hour-format"),
    language: document.getElementById("language"),
    syncInterval: document.getElementById("sync-interval"),
    jfHost: document.getElementById("jf-first-host"),
    jfPort: document.getElementById("jf-first-port"),
    jfApiKey: document.getElementById("jf-first-api-key"),
  };

  const buttons = {
    page1Next: document.getElementById("page1-next"),
    page2Prev: document.getElementById("page2-prev"),
    page2Next: document.getElementById("page2-next"),
    page2Test: document.getElementById("jf-first-test-btn"),
    page3Prev: document.getElementById("page3-prev"),
    page3Finish: document.getElementById("page3-finish"),
  };

  function updateProgressIndicator() {
    const progressIndicator = document.getElementById("progress-indicator");
    if (progressIndicator && progressIndicator.hidden) {
      return;
    }

    const dots = document.querySelectorAll(".progress-dot");
    dots.forEach((dot) => {
      const page = parseInt(dot.dataset.page);
      dot.classList.remove("active", "completed");
      if (page === currentPage) {
        dot.classList.add("active");
      } else if (page < currentPage) {
        dot.classList.add("completed");
      }
    });
  }

  function showPage(pageNum) {
    Object.values(pageElements).forEach((el) => {
      if (el) el.classList.remove("active");
    });
    if (pageElements[pageNum]) {
      pageElements[pageNum].classList.add("active");
    }
    currentPage = pageNum;

    const progressIndicator = document.getElementById("progress-indicator");
    if (progressIndicator) {
      progressIndicator.hidden = pageNum === "sync";
    }

    updateProgressIndicator();
    window.scrollTo(0, 0);
  }

  function savePage1() {
    state.hourFormat = formFields.hourFormat?.value || "12";
    state.language = formFields.language?.value || "en";
    state.syncInterval = parseInt(formFields.syncInterval?.value || "1800");
  }

  function loadPage1() {
    if (formFields.hourFormat) formFields.hourFormat.value = state.hourFormat;
    if (formFields.language) formFields.language.value = state.language;
    if (formFields.syncInterval)
      formFields.syncInterval.value = state.syncInterval;
  }

  function loadPage2() {
    if (formFields.jfHost) formFields.jfHost.value = state.jfHost;
    if (formFields.jfPort) formFields.jfPort.value = state.jfPort;
    if (formFields.jfApiKey) formFields.jfApiKey.value = state.jfApiKey;
    updatePage2NextButton();
  }

  function updatePage2NextButton() {
    if (buttons.page2Next) {
      buttons.page2Next.disabled = !testConnectionOk;
    }
  }

  async function loadPage3() {
    const serverNameDisplay = document.getElementById("server-name-display");
    const serverVersionDisplay = document.getElementById(
      "server-version-display",
    );

    if (serverNameDisplay) {
      serverNameDisplay.textContent = state.serverName || "Unknown";
    }
    if (serverVersionDisplay) {
      serverVersionDisplay.textContent = state.serverVersion || "Unknown";
    }

    await loadLibraries();
  }

  async function loadLibraries() {
    const librariesList = document.getElementById("libraries-list");
    const librariesEmpty = document.getElementById("libraries-empty");

    if (!librariesList) return;

    librariesList.innerHTML = "";

    try {
      const resp = await fetch("/api/jellyfin/libraries", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jf_host: state.jfHost,
          jf_port: state.jfPort,
          jf_api_key: state.jfApiKey,
        }),
      });

      if (!resp.ok) throw new Error("Failed to fetch libraries");
      const result = await resp.json();

      if (!result.ok || !Array.isArray(result.data)) {
        if (librariesEmpty) librariesEmpty.hidden = false;
        return;
      }

      availableLibraries = result.data || [];

      if (availableLibraries.length === 0) {
        if (librariesEmpty) librariesEmpty.hidden = false;
        return;
      }

      if (librariesEmpty) librariesEmpty.hidden = true;

      availableLibraries.forEach((lib) => {
        const libName = lib.Name || lib.name || "Unknown";
        const libType = lib.CollectionType || lib.type || "unknown";

        const item = document.createElement("div");
        item.className = "library-item";

        const label = document.createElement("div");

        const nameSpan = document.createElement("span");
        nameSpan.className = "library-name";
        nameSpan.textContent = libName;

        const typeSpan = document.createElement("span");
        typeSpan.className = "library-type";
        typeSpan.textContent = libType;

        label.appendChild(nameSpan);
        label.appendChild(typeSpan);

        item.appendChild(label);
        librariesList.appendChild(item);
      });
    } catch (err) {
      if (librariesEmpty) librariesEmpty.hidden = false;
      showToast(`Failed to load libraries: ${err.message}`, "error");
    }
  }

  if (buttons.page1Next) {
    buttons.page1Next.addEventListener("click", () => {
      savePage1();
      loadPage2();
      showPage(2);
    });
  }

  if (buttons.page2Prev) {
    buttons.page2Prev.addEventListener("click", () => {
      showPage(1);
    });
  }

  if (buttons.page2Test) {
    buttons.page2Test.addEventListener("click", async () => {
      const host = (formFields.jfHost?.value || "").trim();
      const port = (formFields.jfPort?.value || "").trim();
      const apiKey = (formFields.jfApiKey?.value || "").trim();

      if (!host || !port || !apiKey) {
        showToast("Please fill in all fields", "error");
        return;
      }

      if (!/^\d+$/.test(port)) {
        showToast("Port must be a valid number", "error");
        return;
      }

      buttons.page2Test.disabled = true;
      const original = buttons.page2Test.textContent;
      buttons.page2Test.textContent = "Testing...";

      const result = await postJson(
        "/api/test-connection-with-credentials",
        { jf_host: host, jf_port: port, jf_api_key: apiKey },
        "POST",
      );

      if (result && result.ok) {
        testConnectionOk = true;
        state.jfHost = host;
        state.jfPort = port;
        state.jfApiKey = apiKey;
        state.serverName = result.server_name || "";
        state.serverVersion = result.server_version || "";
        showToast("Connection successful", "success");
        updatePage2NextButton();
      } else {
        testConnectionOk = false;
        const msg =
          result?.message || `Failed (status: ${result?.status ?? "n/a"})`;
        showToast(msg, "error");
        updatePage2NextButton();
      }

      buttons.page2Test.textContent = original;
      setTimeout(() => {
        buttons.page2Test.disabled = false;
      }, 3000);
    });
  }

  if (buttons.page2Next) {
    buttons.page2Next.addEventListener("click", () => {
      if (!testConnectionOk) {
        showToast("Please test connection first", "error");
        return;
      }
      loadPage3();
      showPage(3);
    });
  }

  if (buttons.page3Prev) {
    buttons.page3Prev.addEventListener("click", () => {
      showPage(2);
    });
  }

  if (buttons.page3Finish) {
    buttons.page3Finish.addEventListener("click", async () => {
      buttons.page3Finish.disabled = true;
      const original = buttons.page3Finish.textContent;
      buttons.page3Finish.textContent = "Saving...";

      const payload = {
        jf_host: state.jfHost,
        jf_port: state.jfPort,
        jf_api_key: state.jfApiKey,
        jf_server_name: state.serverName,
        jf_server_version: state.serverVersion,
        hour_format: state.hourFormat,
        language: state.language,
        sync_interval: state.syncInterval,
      };

      try {
        const resp = await fetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!resp.ok) {
          showToast("Failed to save settings", "error");
          buttons.page3Finish.textContent = original;
          buttons.page3Finish.disabled = false;
          return;
        }

        showToast("Settings saved", "success");
        showPage("sync");

        const syncText = document.getElementById("jf-first-sync-text");
        const POLL_INTERVAL = 1000;
        const TIMEOUT_MS = 10 * 60 * 1000;
        const startTs = Date.now();

        async function pollProgress() {
          if (Date.now() - startTs > TIMEOUT_MS) {
            if (syncText) {
              syncText.textContent = "Sync timeout. Please refresh the page.";
            }
            return;
          }

          try {
            const progressResp = await fetch(
              "/api/analytics/server/sync-progress",
            );
            const progressData = await progressResp.json();

            if (progressData && progressData.ok && !progressData.syncing) {
              if (syncText) {
                syncText.textContent = "Setup complete";
              }
              setTimeout(() => {
                window.location.href = "/";
              }, 1500);
              return;
            }

            setTimeout(pollProgress, POLL_INTERVAL);
          } catch (err) {
            setTimeout(pollProgress, POLL_INTERVAL);
          }
        }

        setTimeout(pollProgress, 500);
      } catch (err) {
        showToast("Network error while saving", "error");
        buttons.page3Finish.textContent = original;
        buttons.page3Finish.disabled = false;
      }
    });
  }

  loadPage1();
})();
