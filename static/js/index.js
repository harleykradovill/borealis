document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("plays-matrix");
  const emptyEl = document.getElementById("matrix-chart-empty-files");
  const matrixLoading = document.getElementById("matrix-loading");
  if (!canvas) return;

  async function loadActivity(days = 365) {
    try {
      const perPage = 1000;
      const maxPages = 20;
      let page = 1;
      const all = [];
      const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;

      while (page <= maxPages) {
        const resp = await fetch(
          `/api/analytics/activitylog?page=${page}&per_page=${perPage}`,
        );
        if (!resp.ok) break;
        const payload = await resp.json();
        if (!payload?.ok) break;

        const pageItems = Array.isArray(payload.data?.items)
          ? payload.data.items
          : [];
        if (!pageItems.length) break;

        all.push(...pageItems);

        const minTsSec = Math.min(
          ...pageItems.map((it) => Number(it.activity_at || 0)),
        );
        if (isFinite(minTsSec) && minTsSec * 1000 <= cutoff) break;

        if (pageItems.length < perPage) break;
        page++;
      }

      return all;
    } catch (err) {
      console.error("Failed to load activity", err);
      return [];
    }
  }

  function buildMatrix(items, days = 365) {
    const now = new Date();
    now.setHours(0, 0, 0, 0);

    const startDate = new Date(now);
    startDate.setDate(startDate.getDate() - (days - 1));
    startDate.setDate(startDate.getDate() - startDate.getDay());

    const toLocalISO = (d) => {
      const yr = d.getFullYear();
      const mo = String(d.getMonth() + 1).padStart(2, "0");
      const da = String(d.getDate()).padStart(2, "0");
      return `${yr}-${mo}-${da}`;
    };

    const counts = {};
    items.forEach((it) => {
      const ts = Number(it.activity_at || 0) * 1000;
      if (!ts) return;
      const d = new Date(ts);
      const iso = toLocalISO(d);
      counts[iso] = (counts[iso] || 0) + 1;
    });

    const data = [];
    let maxV = 0;
    let weekIdx = 0;
    const curr = new Date(startDate);

    while (curr <= now) {
      const iso = toLocalISO(curr);
      const v = counts[iso] || 0;
      if (v > maxV) maxV = v;

      const weekday = curr.getDay();
      data.push({
        x: weekIdx + 1,
        y: weekday + 1,
        v,
        date: iso,
      });

      if (weekday === 6) weekIdx++;
      curr.setDate(curr.getDate() + 1);
    }

    return { data, maxV, weeks: weekIdx + 1 };
  }

  function colorFor(v, maxV) {
    const palette = [
      "#2b313d",
      "#2d3647",
      "#2f3c52",
      "#364c6d",
      "#35537a",
      "#3869a5",
      "#346daf",
      "#2a73c7",
      "#187ddb",
    ];
    if (!v) return "#191e27";
    const t = Math.min(1, v / Math.max(1, maxV));
    const idx = Math.max(
      0,
      Math.min(palette.length - 1, Math.round(t * (palette.length - 1))),
    );
    return palette[idx];
  }

  async function render() {
    try {
      const items = await loadActivity(365);
      const { data, maxV, weeks } = buildMatrix(items, 365);
      if (!data.length || maxV === 0) {
        if (emptyEl) emptyEl.hidden = false;
        canvas.style.display = "none";
        return;
      } else {
        if (emptyEl) emptyEl.hidden = true;
        canvas.style.display = "";
      }

      const monthLabels = generateMonthLabels(data, weeks);
      const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

      const canvasContainer = canvas.parentElement;
      const labelsWrapper = document.createElement("div");
      labelsWrapper.className = "matrix-labels-wrapper";

      const topLabels = document.createElement("div");
      topLabels.className = "matrix-top-labels";
      monthLabels.forEach((label) => {
        const div = document.createElement("div");
        div.className = "matrix-month-label";
        div.textContent = label;
        topLabels.appendChild(div);
      });

      const contentWrapper = document.createElement("div");
      contentWrapper.className = "matrix-content";

      const leftLabels = document.createElement("div");
      leftLabels.className = "matrix-left-labels";
      dayLabels.forEach((day) => {
        const div = document.createElement("div");
        div.className = "matrix-day-label";
        div.textContent = day;
        leftLabels.appendChild(div);
      });

      const canvasWrapper = document.createElement("div");
      canvasWrapper.className = "matrix-canvas-wrapper";
      canvasWrapper.appendChild(canvas.cloneNode(true));
      const newCanvas = canvasWrapper.querySelector("canvas");

      contentWrapper.appendChild(leftLabels);
      contentWrapper.appendChild(canvasWrapper);

      labelsWrapper.appendChild(topLabels);
      labelsWrapper.appendChild(contentWrapper);

      canvasContainer.replaceChild(labelsWrapper, canvas);

      const ctx = newCanvas.getContext("2d");

      const config = {
        type: "matrix",
        data: {
          datasets: [
            {
              data,
              borderWidth: 0,
              borderRadius: 5,
              backgroundColor: (ctxArg) => {
                const v = ctxArg.raw.v || 0;
                return colorFor(v, maxV);
              },
              width: ({ chart }) => {
                const areaW = (chart.chartArea || {}).width || canvas.width;
                const areaH = (chart.chartArea || {}).height || canvas.height;
                const cellW = Math.max(2, Math.floor(areaW / weeks) - 1);
                const cellH = Math.max(2, Math.floor(areaH / 7) - 1);
                return Math.max(2, Math.min(cellW, cellH));
              },
              height: ({ chart }) => {
                const areaW = (chart.chartArea || {}).width || canvas.width;
                const areaH = (chart.chartArea || {}).height || canvas.height;
                const cellW = Math.max(2, Math.floor(areaW / weeks) - 1);
                const cellH = Math.max(2, Math.floor(areaH / 7) - 1);
                return Math.max(2, Math.min(cellW, cellH));
              },
            },
          ],
        },
        options: {
          animation: {
            x: { duration: 0 },
            y: { duration: 0 },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: () => "",
                label: (ctx) => {
                  const r = ctx.raw;
                  return `${r.date} - ${r.v} plays`;
                },
              },
            },
          },
          scales: {
            x: {
              display: false,
              min: 0.5,
              max: weeks + 0.5,
              offset: false,
              grid: { display: false },
            },
            y: {
              display: false,
              min: 0.5,
              max: 7.5,
              grid: { display: false },
            },
          },
          maintainAspectRatio: false,
          responsive: true,
        },
      };

      if (window.__playsMatrixChart) {
        try {
          window.__playsMatrixChart.destroy();
        } catch (e) {}
        window.__playsMatrixChart = null;
      }
      window.__playsMatrixChart = new Chart(ctx, config);
    } finally {
      if (matrixLoading) {
        matrixLoading.classList.remove("skeleton");
        matrixLoading.style.display = "none";
      }
    }
  }

  function generateMonthLabels(data, weeks) {
    const shortMonths = [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
    ];
    const labels = Array(weeks).fill("");
    const seenMonths = new Set();

    data.forEach((point) => {
      const dateStr = point.date;
      const date = new Date(dateStr + "T00:00:00Z");
      const month = shortMonths[date.getUTCMonth()];
      const weekIdx = point.x - 1;

      const monthKey = `${date.getUTCFullYear()}-${date.getUTCMonth()}`;
      if (!seenMonths.has(monthKey) && weekIdx < weeks) {
        labels[weekIdx] = month;
        seenMonths.add(monthKey);
      }
    });

    return labels;
  }

  function scheduleHeatmapRender() {
    const run = () => {
      render().catch((err) => {
        console.error("Failed to render plays heatmap:", err);
      });
    };

    if (typeof window.requestIdleCallback === "function") {
      window.requestIdleCallback(run, { timeout: 100 });
      return;
    }

    window.setTimeout(run, 0);
  }

  scheduleHeatmapRender();
});

(function () {
  const container = document.getElementById("sessions-container");
  const empty = document.getElementById("sessions-empty");
  const cardsContainer = document.getElementById("sessions-cards");
  const loading = document.getElementById("sessions-loading");
  let firstLoadDone = false;

  if (!container || !cardsContainer) return;

  const REFRESH_INTERVAL = 5000;
  let refreshTimer = null;

  function formatTranscodeStatus(isTranscoding, transcodeReason) {
    if (!isTranscoding) return "Direct Playing";
    return `Transcoding (${transcodeReason || "unknown"})`;
  }

  function getSessionPlaybackState(playState) {
    const isPaused = !!playState?.IsPaused;
    return {
      isPaused,
      iconUrl: isPaused ? "/assets/icons/pause.png" : "/assets/icons/play.png",
      iconAlt: isPaused ? "Paused" : "Playing",
    };
  }

  function renderSessions(sessions) {
    if (!firstLoadDone) {
      firstLoadDone = true;
      if (loading) {
        loading.classList.remove("skeleton");
        loading.style.display = "none";
      }
    }

    if (!sessions || sessions.length === 0) {
      if (cardsContainer) cardsContainer.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }

    if (cardsContainer) cardsContainer.hidden = false;
    if (empty) empty.hidden = true;
    cardsContainer.innerHTML = "";

    sessions.forEach((session) => {
      const card = document.createElement("div");
      card.className = "session-card";

      const deviceName = session.DeviceName || "Unknown Device";
      const clientName = session.Client || "Unknown Client";
      const userName = session.UserName || "Unknown User";
      const ipAddr = session.RemoteEndPoint || "-";

      const nowPlayingItem = session.NowPlayingItem || {};
      const itemId = nowPlayingItem.Id || "";

      const primaryTag =
        nowPlayingItem.PrimaryImageTag ||
        nowPlayingItem.ImageTags?.Primary ||
        "";

      if (itemId) {
        const imageUrl = primaryTag
          ? `/api/jellyfin/items/${encodeURIComponent(itemId)}/images/primary?tag=${encodeURIComponent(primaryTag)}`
          : `/api/jellyfin/items/${encodeURIComponent(itemId)}/images/primary`;

        card.style.setProperty("--session-bg-image", `url("${imageUrl}")`);
        card.classList.add("session-card-has-bg");
      }

      const itemName = nowPlayingItem.Name || "Unknown Item";

      const playState = session.PlayState || {};
      const progressTicks = playState.PositionTicks || 0;
      const runtimeTicks = nowPlayingItem.RunTimeTicks || 0;
      const playbackState = getSessionPlaybackState(playState);

      const mediaSource = (session.NowPlayingSessions || [{}])[0] || {};
      const videoCodec = mediaSource.VideoCodec || "unknown";
      const audioCodec = mediaSource.AudioCodec || "unknown";
      const videoIsTranscoding = !!mediaSource.TranscodingInfo?.VideoCodec;
      const audioIsTranscoding = !!mediaSource.TranscodingInfo?.AudioCodec;

      const attrs = [
        { label: "Device", value: deviceName },
        { label: "Client", value: clientName },
        { label: "User", value: userName },
        { label: "IP Address", value: ipAddr },
        {
          label: "Video",
          value: formatTranscodeStatus(videoIsTranscoding, videoCodec),
        },
        {
          label: "Audio",
          value: formatTranscodeStatus(audioIsTranscoding, audioCodec),
        },
      ];

      attrs.forEach((attr) => {
        const div = document.createElement("div");
        div.className = "session-card-attr";

        const label = document.createElement("span");
        label.className = "session-card-attr-label";
        label.textContent = attr.label;

        const value = document.createElement("span");
        value.className = "session-card-attr-value";
        value.textContent = attr.value;

        div.appendChild(label);
        div.appendChild(value);
        card.appendChild(div);
      });

      const safeProgressTicks = Number(progressTicks) || 0;
      const safeRuntimeTicks = Number(runtimeTicks) || 0;
      const rawPercent =
        safeRuntimeTicks > 0 ? (safeProgressTicks / safeRuntimeTicks) * 100 : 0;
      const progressPercent = Math.max(
        0,
        Math.min(100, Math.round(rawPercent)),
      );
      const progressDiv = document.createElement("div");
      progressDiv.className = "session-card-progress";

      const progressTitle = document.createElement("div");
      progressTitle.className = "session-card-progress-title";
      progressTitle.textContent = itemName;

      const progressMeta = document.createElement("div");
      progressMeta.className = "session-card-progress-meta";

      const progressIcon = document.createElement("img");
      progressIcon.className = "session-card-progress-icon";
      progressIcon.src = playbackState.iconUrl;
      progressIcon.alt = playbackState.iconAlt;
      progressIcon.loading = "lazy";
      progressIcon.decoding = "async";

      const progressBar = document.createElement("div");
      progressBar.className = "session-card-progress-bar";

      const progressFill = document.createElement("div");
      progressFill.className = "session-card-progress-fill";
      progressFill.style.width = `${progressPercent}%`;

      progressBar.appendChild(progressFill);

      const progressLabel = document.createElement("div");
      progressLabel.className = "session-card-progress-label";
      progressLabel.textContent = `${progressPercent}%`;

      progressMeta.appendChild(progressIcon);
      progressMeta.appendChild(progressBar);
      progressMeta.appendChild(progressLabel);

      progressDiv.appendChild(progressTitle);
      progressDiv.appendChild(progressMeta);
      card.appendChild(progressDiv);

      cardsContainer.appendChild(card);
    });
  }

  async function loadSessions() {
    try {
      const resp = await fetch("/api/analytics/sessions");
      if (!resp.ok) {
        renderSessions([]);
        return;
      }

      const result = await resp.json();
      if (!result.ok || !Array.isArray(result.data)) {
        renderSessions([]);
        return;
      }

      renderSessions(result.data);
    } catch (err) {
      console.error("Failed to load sessions:", err);
      renderSessions([]);
    }
  }

  function startRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    loadSessions();
    refreshTimer = setInterval(loadSessions, REFRESH_INTERVAL);
  }

  function stopRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopRefresh();
    } else {
      startRefresh();
    }
  });

  startRefresh();
})();

(function () {
  const LIMIT = 5;
  const statLists = document.querySelectorAll(
    ".statistics-item.skeleton, .statistics-value.skeleton",
  );

  function clearStatsSkeleton() {
    statLists.forEach((el) => el.classList.remove("skeleton"));
  }

  function fmtHours(seconds) {
    if (seconds === null || seconds === undefined || seconds === "") return "";
    const sec = Number(seconds);
    if (!Number.isFinite(sec)) return "";
    return `${Math.round(sec / 3600)}h`;
  }

  function fmtDate(tsSec) {
    const ts = Number(tsSec);
    if (!Number.isFinite(ts) || ts <= 0) return "";
    const d = new Date(ts * 1000);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleDateString();
  }

  function renderRows(nameListId, valueListId, rows, nameFn, valueFn) {
    const nameList = document.getElementById(nameListId);
    const valueList = document.getElementById(valueListId);
    if (!nameList || !valueList) return;

    const safeRows = Array.isArray(rows) ? rows.slice(0, LIMIT) : [];
    while (safeRows.length < LIMIT) safeRows.push(null);

    nameList.innerHTML = safeRows
      .map((row) => `<li class="statistics-item">${nameFn(row)}</li>`)
      .join("");

    valueList.innerHTML = safeRows
      .map((row) => `<li class="statistics-value">${valueFn(row)}</li>`)
      .join("");
  }

  async function loadWatchStatistics() {
    try {
      const resp = await fetch("/api/analytics/stats/dashboard");
      if (!resp.ok) return;

      const payload = await resp.json();
      if (!payload?.ok) return;

      const sections = payload.data?.sections || {};

      renderRows(
        "stat-top-users-names",
        "stat-top-users-values",
        sections.top_users_by_plays,
        (r) => r?.name ?? "",
        (r) =>
          r?.plays === null || r?.plays === undefined
            ? ""
            : String(Number(r.plays)),
      );

      renderRows(
        "stat-top-items-names",
        "stat-top-items-values",
        sections.top_items_by_plays,
        (r) => r?.name ?? "",
        (r) =>
          r?.plays === null || r?.plays === undefined
            ? ""
            : String(Number(r.plays)),
      );

      renderRows(
        "stat-top-libraries-names",
        "stat-top-libraries-values",
        sections.top_libraries_by_plays,
        (r) => r?.name ?? "",
        (r) =>
          r?.plays === null || r?.plays === undefined
            ? ""
            : String(Number(r.plays)),
      );

      renderRows(
        "stat-watch-time-names",
        "stat-watch-time-values",
        sections.top_users_by_watch_time,
        (r) => r?.name ?? "",
        (r) => fmtHours(r?.watch_seconds),
      );

      renderRows(
        "stat-active-day-names",
        "stat-active-day-values",
        sections.most_active_weekdays,
        (r) => r?.weekday ?? "",
        (r) =>
          r?.plays === null || r?.plays === undefined
            ? ""
            : String(Number(r.plays)),
      );

      renderRows(
        "stat-recent-names",
        "stat-recent-values",
        sections.recently_watched,
        (r) => r?.name ?? "",
        (r) => fmtDate(r?.last_watched_at),
      );
    } catch (err) {
      console.error("Failed to load watch statistics:", err);
    } finally {
      clearStatsSkeleton();
    }
  }

  document.addEventListener("DOMContentLoaded", loadWatchStatistics);
})();

(function () {
  const group = document.querySelector(".statistics-section");
  if (!group) return;

  const track = group.querySelector("[data-carousel-track]");
  const prevBtn = group.querySelector('[data-carousel-action="prev"]');
  const nextBtn = group.querySelector('[data-carousel-action="next"]');

  if (!track || !prevBtn || !nextBtn) return;

  const listCards = () =>
    Array.from(track.children).filter((el) =>
      el.classList.contains("statistics-card"),
    );

  let pageIndex = 0;

  function updateCarousel() {
    const cards = listCards();
    if (!cards.length) return;

    const perView = 3;
    const pages = Math.max(1, Math.ceil(cards.length / perView));
    pageIndex = Math.max(0, Math.min(pageIndex, pages - 1));

    const cardWidth = cards[0].getBoundingClientRect().width;
    const gap = parseFloat(getComputedStyle(track).gap || "0");
    const offset = (cardWidth + gap) * pageIndex * perView;

    track.style.transform = `translateX(-${offset}px)`;
    prevBtn.disabled = pageIndex === 0;
    nextBtn.disabled = pageIndex >= pages - 1;
  }

  prevBtn.addEventListener("click", () => {
    pageIndex -= 1;
    updateCarousel();
  });

  nextBtn.addEventListener("click", () => {
    pageIndex += 1;
    updateCarousel();
  });

  window.addEventListener("resize", updateCarousel);
  updateCarousel();
})();
