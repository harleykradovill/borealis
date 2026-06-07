(function () {
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

  /**
   * Update the visible progress indicator for the setup wizard. Marks the
   * current page as active and any prior pages as completed.
   * @returns {void}
   */
  function updateProgressIndicator() {
    const progressIndicator = document.getElementById("progress-indicator");
    if (progressIndicator?.hidden) {
      return;
    }

    const dots = document.querySelectorAll(".progress-dot");
    dots.forEach((dot) => {
      const page = Number.parseInt(dot.dataset.page);
      dot.classList.remove("active", "completed");
      if (page === currentPage) {
        dot.classList.add("active");
      } else if (page < currentPage) {
        dot.classList.add("completed");
      }
    });
  }

  /**
   * Show the requested setup page and hide the others.
   * @param {number|string} pageNum Page identifier to show
   * @returns {void}
   */
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

  /**
   * Persist page 1 settings from the form into the local setup state.
   * @returns {void}
   */
  function savePage1() {
    state.hourFormat = formFields.hourFormat?.value || "12";
    state.language = formFields.language?.value || "en";
    state.syncInterval = Number.parseInt(formFields.syncInterval?.value || "1800");
  }

  /**
   * Populate page 1 form fields from the current setup state.
   * @returns {void}
   */
  function loadPage1() {
    if (formFields.hourFormat) formFields.hourFormat.value = state.hourFormat;
    if (formFields.language) formFields.language.value = state.language;
    if (formFields.syncInterval) formFields.syncInterval.value = state.syncInterval;
  }

  /**
   * Populate page 2 form fields from the current setup state.
   * @returns {void}
   */
  function loadPage2() {
    if (formFields.jfHost) formFields.jfHost.value = state.jfHost;
    if (formFields.jfPort) formFields.jfPort.value = state.jfPort;
    if (formFields.jfApiKey) formFields.jfApiKey.value = state.jfApiKey;
    updatePage2NextButton();
  }

  /**
   * Enable or disable the page 2 "Next" button based on connection test state.
   * @returns {void}
   */
  function updatePage2NextButton() {
    if (buttons.page2Next) {
      buttons.page2Next.disabled = !testConnectionOk;
    }
  }

  /**
   * Populate page 3 summary fields and load the available Jellyfin libraries.
   * @returns {Promise<void>}
   */
  async function loadPage3() {
    const serverNameDisplay = document.getElementById("server-name-display");
    const serverVersionDisplay = document.getElementById("server-version-display");

    if (serverNameDisplay) {
      serverNameDisplay.textContent = state.serverName || "Unknown";
    }
    if (serverVersionDisplay) {
      serverVersionDisplay.textContent = state.serverVersion || "Unknown";
    }

    await loadLibraries();
  }

  /**
   * Fetch Jellyfin libraries for the current connection and render them.
   * @returns {Promise<void>}
   */
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

      if (!resp.ok) {
        globalThis.helpers.handleError("Failed to fetch libraries", resp?.message);
      }

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

        const item = document.createElement("div");
        item.className = "library-item";

        const label = document.createElement("div");

        const nameSpan = document.createElement("span");
        nameSpan.className = "library-name";
        nameSpan.textContent = libName;

        label.appendChild(nameSpan);

        item.appendChild(label);
        librariesList.appendChild(item);
      });
    } catch (error) {
      globalThis.helpers.handleError("Failed to load libraries", error);
      if (librariesEmpty) librariesEmpty.hidden = false;
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
        globalThis.helpers.handleError(
          "Please fill in all fields",
          "Please fill in all fields",
        );
        return;
      }

      if (!/^\d+$/.test(port)) {
        globalThis.helpers.handleError(
          "Port must be a valid number",
          "Port must be a valid number",
        );
        return;
      }

      buttons.page2Test.disabled = true;
      const original = buttons.page2Test.textContent;
      buttons.page2Test.textContent = "Testing...";

      const result = await globalThis.helpers.postJson(
        "/api/test-connection-with-credentials",
        { jf_host: host, jf_port: port, jf_api_key: apiKey },
      );

      if (result?.ok) {
        testConnectionOk = true;
        state.jfHost = host;
        state.jfPort = port;
        state.jfApiKey = apiKey;
        state.serverName = result.server_name || "";
        state.serverVersion = result.server_version || "";
        globalThis.Toast.showToast("Connection successful");
        updatePage2NextButton();
      } else {
        testConnectionOk = false;
        const msg = result?.message || `Failed (status: ${result?.status ?? "n/a"})`;
        globalThis.helpers.handleError("Failed to connect to Jellyfin server", msg);
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
        globalThis.helpers.handleError(
          "Test connection before continuing",
          "Test connection before continuing",
        );
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
          globalThis.helpers.handleError("Failed to save settings", resp?.message);
          buttons.page3Finish.textContent = original;
          buttons.page3Finish.disabled = false;
          return;
        }

        globalThis.Toast.showToast("Settings saved");
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
            const progressResp = await fetch("/api/analytics/server/sync-progress");
            const progressData = await progressResp.json();

            if (progressData?.ok && !progressData.syncing) {
              if (syncText) {
                syncText.textContent = "Setup complete";
              }
              setTimeout(() => {
                globalThis.location.href = "/";
              }, 1500);
              return;
            }

            setTimeout(pollProgress, POLL_INTERVAL);
          } catch (error) {
            globalThis.helpers.handleError("Failed to poll sync progress", error);
            setTimeout(pollProgress, POLL_INTERVAL);
          }
        }

        setTimeout(pollProgress, 500);
      } catch (error) {
        globalThis.helpers.handleError("Network error while syncing", error);
        buttons.page3Finish.textContent = original;
        buttons.page3Finish.disabled = false;
      }
    });
  }

  loadPage1();
})();
