(function () {
  const container = document.getElementById("activitylog-container");
  const empty = document.getElementById("activitylog-empty");
  const tbody = document.getElementById("activitylog-tbody");

  const firstBtn = document.getElementById("activitylog-first");
  const prevBtn = document.getElementById("activitylog-prev");
  const nextBtn = document.getElementById("activitylog-next");
  const lastBtn = document.getElementById("activitylog-last");
  const pagesDiv = document.getElementById("activitylog-pages");
  const pageNumEl = document.getElementById("activitylog-page-num");
  const metaEl = document.getElementById("activitylog-meta");

  const PER_PAGE = 25;
  const MAX_PAGE_BUTTONS = 7;

  let lastKnownTotalPages = 1;

  /**
   * Safe toast wrapper.
   * @param {any} msg Message or Error to display in the toast
   * @param {string} kind Toast type
   * @returns {void}
   */
  function safeShowToast(msg, kind = "error") {
    if (typeof showToast === "function") {
      showToast(msg, kind);
    } else {
      console.error(msg);
    }
  }

  /**
   * Parse page from URL hash.
   * @returns {number} Parsed page number (at least 1)
   */
  function parseHashPage() {
    const match = location.hash.match(/page=(\d+)/);
    return match ? Math.max(1, Number(match[1])) : 1;
  }

  /**
   * Go to the given page.
   * @param {number | string} page Page number to navigate to
   * @returns {void}
   */
  function gotoPage(page) {
    location.hash = `page=${Math.max(1, Number(page) || 1)}`;
  }

  /**
   * Disable pagnation navigation.
   * @param {boolean} disabled True to disable controls, false to enable
   * @returns {void}
   */
  function setNavigationDisabled(disabled) {
    [firstBtn, prevBtn, nextBtn, lastBtn].forEach((btn) => {
      if (btn) btn.disabled = disabled;
    });

    Array.from(pagesDiv.children).forEach((el) => {
      if (el.tagName === "BUTTON") el.disabled = disabled;
    });
  }

  /**
   * Load a page of PlaybackActivity from the database.
   * @param {number | string} page Page number to load
   * @returns {void}
   */
  async function loadPage(page) {
    setNavigationDisabled(true);

    try {
      const resp = await fetch(
        `/api/analytics/activitylog?page=${page}&per_page=${PER_PAGE}`,
      );
      if (!resp.ok) throw new Error("Network error");

      const payload = await resp.json();
      if (!payload?.ok) {
        throw new Error(payload?.message || "API error");
      }

      render(payload.data || {});
    } catch (err) {
      safeShowToast(
        `Failed to load activity log: ${err?.message || err}`,
        "error",
      );
      renderEmpty();
    } finally {
      setNavigationDisabled(false);
    }
  }

  /**
   * Render empty state.
   * @returns {void}
   */
  function renderEmpty() {
    container.hidden = true;
    empty.hidden = false;
    pagesDiv.innerHTML = "";
    pageNumEl.textContent = "1";
    metaEl.textContent = "Page 1";
    lastKnownTotalPages = 1;
  }

  /**
   * Render table and pagnation.
   * @param {*} data
   * @returns
   */
  function render(data) {
    const items = Array.isArray(data.items) ? data.items : [];
    const page = Number(data.page) || 1;
    const perPage = Number(data.per_page) || PER_PAGE;
    const total = Number(data.total) || 0;

    if (!items.length) {
      renderEmpty();
      return;
    }

    tbody.innerHTML = "";

    for (const it of items) {
      const tr = document.createElement("tr");

      const userTd = document.createElement("td");
      userTd.style.padding = "0.5rem";
      userTd.textContent = it.username_denorm || it.user_id || "(unknown)";
      tr.appendChild(userTd);

      const eventTd = document.createElement("td");
      eventTd.style.padding = "0.5rem";
      eventTd.textContent = it.event_name || "";
      tr.appendChild(eventTd);

      const dateTd = document.createElement("td");
      dateTd.style.padding = "0.5rem";
      dateTd.style.textAlign = "right";
      dateTd.textContent = it.activity_at
        ? new Date(Number(it.activity_at) * 1000).toLocaleString()
        : "";
      tr.appendChild(dateTd);

      tbody.appendChild(tr);
    }

    const totalPages = Math.max(1, Math.ceil(total / perPage));
    lastKnownTotalPages = totalPages;

    empty.hidden = true;
    container.hidden = false;

    pageNumEl.textContent = String(page);
    metaEl.textContent = `Page ${page} of ${totalPages}`;

    renderPaginationControls(page, totalPages);
  }

  /**
   * Render pagnation buttons.
   * @param {number} current Current page number
   * @param {number} totalPages Total number of available pages
   * @returns {void}
   */
  function renderPaginationControls(current, totalPages) {
    firstBtn.disabled = current <= 1;
    prevBtn.disabled = current <= 1;
    nextBtn.disabled = current >= totalPages;
    lastBtn.disabled = current >= totalPages;

    pagesDiv.innerHTML = "";

    const half = Math.floor(MAX_PAGE_BUTTONS / 2);
    let start = Math.max(1, current - half);
    let end = Math.min(totalPages, start + MAX_PAGE_BUTTONS - 1);

    if (end - start + 1 < MAX_PAGE_BUTTONS) {
      start = Math.max(1, end - MAX_PAGE_BUTTONS + 1);
    }

    for (let p = start; p <= end; p++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-ghost";
      btn.style.minWidth = "36px";
      btn.textContent = String(p);
      btn.dataset.page = String(p);

      if (p === current) btn.classList.add("active");

      btn.addEventListener("click", () => gotoPage(p));
      pagesDiv.appendChild(btn);
    }
  }

  firstBtn?.addEventListener("click", () => gotoPage(1));
  prevBtn?.addEventListener("click", () => gotoPage(parseHashPage() - 1));
  nextBtn?.addEventListener("click", () => gotoPage(parseHashPage() + 1));
  lastBtn?.addEventListener("click", () => gotoPage(lastKnownTotalPages));

  window.addEventListener("hashchange", () => {
    loadPage(parseHashPage());
  });

  loadPage(parseHashPage());
})();
