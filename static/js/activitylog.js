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

  const filterBtn = document.getElementById("activitylog-user-filter-btn");
  const filterMenu = document.getElementById("activitylog-user-filter-menu");
  const filterOptions = document.getElementById(
    "activitylog-user-filter-options",
  );

  const PER_PAGE = 25;
  const MAX_PAGE_BUTTONS = 7;

  let lastKnownTotalPages = 1;
  let allUsers = [];
  let selectedUserIds = null;

  function safeShowToast(msg, kind = "error") {
    if (typeof showToast === "function") {
      showToast(msg, kind);
    } else {
      console.error(msg);
    }
  }

  function parseHashPage() {
    const match = location.hash.match(/page=(\d+)/);
    return match ? Math.max(1, Number(match[1])) : 1;
  }

  function gotoPage(page) {
    location.hash = `page=${Math.max(1, Number(page) || 1)}`;
  }

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
    const allSelected = totalCount > 0 && selectedCount === totalCount;
    filterBtn.setAttribute(
      "aria-label",
      allSelected
        ? "Filter by user (all users selected)"
        : `Filter by user (${selectedCount}/${totalCount} selected)`,
    );
  }

  function renderFilterOptions() {
    if (!filterOptions) return;

    filterOptions.innerHTML = "";
    const selected =
      selectedUserIds instanceof Set ? selectedUserIds : new Set();

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
      nameSpan.textContent =
        user.username_denorm || user.user_id || "(unknown)";

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
    filterBtn.setAttribute("aria-expanded", "true");
  }

  function closeFilterMenu() {
    if (!filterBtn || !filterMenu) return;
    filterMenu.hidden = true;
    filterBtn.setAttribute("aria-expanded", "false");
  }

  function syncUsersFromPayload(data) {
    const users = Array.isArray(data.users) ? data.users : [];
    allUsers = users
      .map((u) => ({
        user_id: String(u?.user_id || "").trim(),
        username_denorm: u?.username_denorm || "",
      }))
      .filter((u) => u.user_id);

    if (!(selectedUserIds instanceof Set)) {
      selectedUserIds = new Set(allUsers.map((u) => u.user_id));
    }

    renderFilterOptions();
  }

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

    lastKnownTotalPages = totalPages;
    empty.hidden = true;
    container.hidden = false;
    pageNumEl.textContent = String(page);
    metaEl.textContent = `Page ${page} of ${totalPages}`;

    renderPaginationControls(page, totalPages);
  }

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

      if (selectedIds.length) {
        params.set("user_ids", selectedIds.join(","));
      }

      const resp = await fetch(
        `/api/analytics/activitylog?${params.toString()}`,
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

  window.addEventListener("hashchange", () => {
    loadPage(parseHashPage());
  });

  loadPage(parseHashPage());
})();
