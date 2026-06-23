(function () {
  const glanceTotal = document.querySelector(".glance-card:nth-child(1) .glance-value");
  const glanceStart = document.querySelector(".glance-card:nth-child(2) .glance-value");
  const glanceStop = document.querySelector(".glance-card:nth-child(3) .glance-value");
  const searchInput = document.getElementById("activity-search");

  const container = document.getElementById("activitylog-section");
  const empty = document.getElementById("activitylog-empty");
  const tbody = document.getElementById("activitylog-tbody");

  const firstBtn = document.getElementById("activitylog-first");
  const prevBtn = document.getElementById("activitylog-prev");
  const nextBtn = document.getElementById("activitylog-next");
  const lastBtn = document.getElementById("activitylog-last");
  const pagesDiv = document.getElementById("activitylog-pages");
  const pageNumEl = document.getElementById("activitylog-page-num");
  const metaEl = document.getElementById("activitylog-meta");

  const filterBtn = document.getElementById("activitylog-user-filter-btn");
  const filterMenu = document.getElementById("activitylog-user-filter-menu");
  const filterOptions = document.getElementById("activitylog-user-filter-options");

  const PER_PAGE = 25;
  const MAX_PAGE_BUTTONS = 5;

  let lastKnownTotalPages = 1;
  let allUsers = [];
  let selectedUserIds = null;

  /**
   * Parse page from URL hash.
   * @returns {number} Parsed page number (at least 1)
   */
  function parseHashPage() {
    const match = new RegExp(/page=(\d+)/).exec(location.hash);
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
   * Disable pagination navigation.
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

  function getSelectedUserIdsArray() {
    if (!(selectedUserIds instanceof Set)) return [];
    return Array.from(selectedUserIds).filter(Boolean);
  }

  function updateFilterButtonState() {
    if (!filterBtn) return;

    const selectedCount = getSelectedUserIdsArray().length;
    const totalCount = allUsers.length;
    const hasFilter = totalCount > 0 && selectedCount !== totalCount;

    filterBtn.title = hasFilter
      ? `Filter by User (${selectedCount}/${totalCount} selected)`
      : "Filter by User";

    filterBtn.classList.toggle("active", hasFilter);

    const icon = filterBtn.querySelector(".activitylog-filter-icon");
    if (icon) {
      icon.src = hasFilter
        ? "/assets/icons/filter.svg"
        : "/assets/icons/filter_off.svg";
    }
  }

  function renderFilterOptions() {
    if (!filterOptions) return;

    filterOptions.innerHTML = "";
    const selected = selectedUserIds instanceof Set ? selectedUserIds : new Set();

    for (const user of allUsers) {
      const userId = String(user.user_id || "").trim();
      if (!userId) continue;

      const label = document.createElement("label");
      label.className = "activitylog-filter-option";

      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = userId;
      input.checked = selected.has(userId);

      input.addEventListener("change", () => {
        if (!(selectedUserIds instanceof Set)) selectedUserIds = new Set();

        if (input.checked) {
          selectedUserIds.add(userId);
        } else {
          selectedUserIds.delete(userId);
        }

        updateFilterButtonState();

        if (parseHashPage() === 1) {
          loadPage(1);
        } else {
          gotoPage(1);
        }
      });

      const nameSpan = document.createElement("span");
      nameSpan.textContent = user.username || user.user_id || "(unknown)";

      label.appendChild(input);
      label.appendChild(nameSpan);
      filterOptions.appendChild(label);
    }

    updateFilterButtonState();
  }

  function openFilterMenu() {
    if (!filterBtn || !filterMenu || !container) return;

    const containerRect = container.getBoundingClientRect();
    const btnRect = filterBtn.getBoundingClientRect();

    filterMenu.style.left = `${btnRect.left - containerRect.left}px`;
    filterMenu.style.top = `${btnRect.bottom - containerRect.top + 6}px`;
    filterMenu.hidden = false;
  }

  function closeFilterMenu() {
    if (!filterBtn || !filterMenu) return;
    filterMenu.hidden = true;
  }

  function syncUsersFromPayload(data) {
    const users = Array.isArray(data.users) ? data.users : [];
    const byUserId = new Map();

    for (const raw of users) {
      const userId = String(raw?.user_id || "").trim();
      if (!userId) continue;

      const username = String(raw?.username || "").trim();
      const existing = byUserId.get(userId);

      if (!existing) {
        byUserId.set(userId, {
          user_id: userId,
          username: username,
        });
        continue;
      }

      if (!existing.username && username) {
        existing.username = username;
      }
    }

    allUsers = Array.from(byUserId.values()).sort((a, b) => {
      const left = (a.username || a.user_id).toLowerCase();
      const right = (b.username || b.user_id).toLowerCase();
      return left.localeCompare(right);
    });

    if (selectedUserIds instanceof Set) {
      const validUserIds = new Set(allUsers.map((u) => u.user_id));
      selectedUserIds = new Set(
        Array.from(selectedUserIds).filter((id) => validUserIds.has(id)),
      );
    } else {
      selectedUserIds = new Set(allUsers.map((u) => u.user_id));
    }

    renderFilterOptions();
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

  function renderFilteredEmpty() {
    tbody.innerHTML = "";
    pagesDiv.innerHTML = "";
    pageNumEl.textContent = "1";
    metaEl.textContent = "Page 1 of 1";
    lastKnownTotalPages = 1;
    empty.hidden = true;
    container.hidden = false;
    setNavigationDisabled(true);
  }

  function formatPlaybackType(playbackType) {
    const typeMap = {
      VideoPlayback: "Start Playback",
      VideoPlaybackStopped: "Stop Playback",
    };
    return typeMap[playbackType] || playbackType || "";
  }

  /**
   * Render table and pagination.
   * @param {*} data
   * @returns
   */
  function render(data) {
    syncUsersFromPayload(data);

    const items = Array.isArray(data.items) ? data.items : [];
    const page = Number(data.page) || 1;
    const perPage = Number(data.per_page) || PER_PAGE;
    const total = Number(data.total) || 0;
    const totalPages = Math.max(1, Math.ceil(total / perPage));

    if (!allUsers.length) {
      renderEmpty();
      return;
    }

    if (page > totalPages) {
      gotoPage(totalPages);
      return;
    }

    tbody.innerHTML = "";

    const currentNameById = new Map(
      allUsers.map((u) => [u.user_id, u.username || u.user_id]),
    );

    for (const it of items) {
      const tr = document.createElement("tr");

      const userTd = document.createElement("td");
      userTd.textContent =
        currentNameById.get(it.user_id) || it.username || "Deleted User";
      tr.appendChild(userTd);

      const typeTd = document.createElement("td");
      const typeSpan = document.createElement("span");
      typeSpan.className = "playback-chip";

      const iconImg = document.createElement("img");
      iconImg.className = "playback-chip-icon";
      if (it.playback_type === "VideoPlayback") {
        iconImg.src = "/assets/icons/playbackactivity/play.svg";
      } else if (it.playback_type === "VideoPlaybackStopped") {
        iconImg.src = "/assets/icons/playbackactivity/stop.svg";
      }
      typeSpan.appendChild(iconImg);

      const textNode = document.createTextNode(
        " " + formatPlaybackType(it.playback_type),
      );
      typeSpan.appendChild(textNode);

      if (it.playback_type === "VideoPlayback") {
        typeSpan.classList.add("playback-start");
      } else if (it.playback_type === "VideoPlaybackStopped") {
        typeSpan.classList.add("playback-stop");
      }

      typeTd.appendChild(typeSpan);
      tr.appendChild(typeTd);

      const eventTd = document.createElement("td");
      eventTd.textContent = globalThis.helpers.extractMediaItemName(
        it.event_name,
        it.playback_type,
      );
      tr.appendChild(eventTd);

      const dateTd = document.createElement("td");
      dateTd.style.textAlign = "right";
      dateTd.textContent = it.activity_at
        ? new Date(Number(it.activity_at) * 1000).toLocaleString()
        : "";
      tr.appendChild(dateTd);

      tbody.appendChild(tr);
    }

    lastKnownTotalPages = totalPages;
    empty.hidden = true;
    container.hidden = false;
    pageNumEl.textContent = String(page);
    metaEl.textContent = `Page ${page} of ${totalPages}`;

    glanceTotal.textContent = total.toLocaleString();
    loadGlanceTotals();
    renderPaginationControls(page, totalPages);
  }

  async function loadGlanceTotals() {
    try {
      const resp = await fetch("/api/analytics/activity-summary");
      if (!resp.ok) throw new Error("Network error");
      const payload = await resp.json();
      if (!payload.ok) throw new Error(payload.message || "API error");

      const { start, stop } = payload.data;
      if (glanceStart) glanceStart.textContent = start.toLocaleString();
      if (glanceStop) glanceStop.textContent = stop.toLocaleString();
    } catch (error) {
      globalThis.helpers.handleError("Could not load start/stop totals:", error);
    }
  }

  /**
   * Render pagination buttons.
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
      btn.style.borderRadius = "100px";
      btn.textContent = String(p);
      btn.dataset.page = String(p);

      if (p === current) btn.classList.add("active");

      btn.addEventListener("click", () => gotoPage(p));
      pagesDiv.appendChild(btn);
    }
  }

  function debounce(func, wait) {
    let timeout;
    return function (...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  }

  /**
   * Load a page of PlaybackActivity from the database.
   * @param {number | string} page Page number to load
   * @returns {void}
   */
  async function loadPage(page) {
    const selectedIds = getSelectedUserIdsArray();

    if (selectedUserIds instanceof Set && selectedIds.length === 0) {
      renderFilteredEmpty();
      return;
    }

    setNavigationDisabled(true);

    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(PER_PAGE));

      const searchQuery = searchInput?.value || "";
      if (searchQuery.trim()) {
        params.set("search", searchQuery.trim());
      }

      if (selectedIds.length) {
        params.set("user_ids", selectedIds.join(","));
      }

      if (selectedIds.length) {
        params.set("user_ids", selectedIds.join(","));
      }

      const resp = await fetch(`/api/analytics/activitylog?${params.toString()}`);
      if (!resp.ok) throw new Error("Network error");

      const payload = await resp.json();
      if (!payload?.ok) {
        throw new Error(payload?.message || "API error");
      }

      render(payload.data || {});
    } catch (error) {
      globalThis.helpers.handleError("Failed to load playback activity", error);
      renderEmpty();
    } finally {
      setNavigationDisabled(false);
    }
  }

  firstBtn?.addEventListener("click", () => gotoPage(1));
  prevBtn?.addEventListener("click", () => gotoPage(parseHashPage() - 1));
  nextBtn?.addEventListener("click", () => gotoPage(parseHashPage() + 1));
  lastBtn?.addEventListener("click", () => gotoPage(lastKnownTotalPages));

  filterBtn?.addEventListener("click", (event) => {
    event.stopPropagation();
    if (filterMenu?.hidden) {
      openFilterMenu();
    } else {
      closeFilterMenu();
    }
  });

  filterMenu?.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  document.addEventListener("click", (event) => {
    if (!filterMenu || filterMenu.hidden) return;
    if (event.target === filterBtn || filterBtn?.contains(event.target)) return;
    if (filterMenu.contains(event.target)) return;
    closeFilterMenu();
  });

  window.addEventListener("resize", () => {
    if (!filterMenu?.hidden) openFilterMenu();
  });

  globalThis.addEventListener("hashchange", () => {
    loadPage(parseHashPage());
  });

  loadPage(parseHashPage());

  document.addEventListener("syncComplete", () => {
    const currentPage = parseHashPage();
    loadPage(currentPage);
  });

  searchInput?.addEventListener(
    "input",
    debounce(() => {
      if (parseHashPage() === 1) {
        loadPage(1);
      } else {
        gotoPage(1);
      }
    }, 300),
  );
})();
