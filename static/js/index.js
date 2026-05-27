(function () {
  /**
   * Refresh all dashboard data when sync completes.
   * @returns {void}
   */
  function refreshAllData() {
    try {
      const glanceLoading = document.getElementById("glance-loading");
      if (glanceLoading && !glanceLoading.classList.contains("skeleton")) {
        loadGlance().catch((err) => {
          console.error("Failed to refresh glance data:", err);
        });
      }

      const sessionsCard = document.getElementById("sessions-cards");
      if (sessionsCard && sessionsCard.children.length > 0) {
        loadSessions().catch((err) => {
          console.error("Failed to refresh sessions:", err);
        });
      }

      const playCanvas = document.getElementById("plays-matrix");
      if (playCanvas && playCanvas.style.display !== "none") {
        loadActivity(182)
          .then(() => {
            const render = globalThis.__indexRenderHeatmap;
            if (typeof render === "function") {
              render().catch((err) => {
                console.error("Failed to refresh heatmap:", err);
              });
            }
          })
          .catch((err) => {
            console.error("Failed to refresh activity data:", err);
          });
      }

      const statsCards = document.querySelectorAll("[data-stat-key]");
      if (statsCards.length > 0) {
        fetchStatsData().catch((err) => {
          console.error("Failed to refresh stats:", err);
        });
      }

      const codecCards = document.querySelectorAll("[data-codec-key]");
      if (codecCards.length > 0) {
        fetchCodecsData().catch((err) => {
          console.error("Failed to refresh codecs:", err);
        });
      }
    } catch (error) {
      console.error("Error refreshing dashboard data:", error);
    }
  }

  document.addEventListener("syncComplete", () => {
    refreshAllData();
  });
})();

function updateRowLayout() {
  const sessionCards = document.querySelectorAll(
    "#sessions-cards .session-card",
  ).length;
  const sessionsSection = document.getElementById("sessions-section");
  const trendSection = document.querySelector(".plays-trend-section");

  if (sessionCards <= 1) {
    sessionsSection.style.flex = "2.1 1 0";
    trendSection.style.flex = "7.9 1 0";
  } else if (sessionCards === 2) {
    sessionsSection.style.flex = "4.1 1 0";
    trendSection.style.flex = "5.9 1 0";
  } else {
    sessionsSection.style.flex = "7 1 0";
    trendSection.style.flex = "3 1 0";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const sessionsCards = document.getElementById("sessions-cards");
  if (sessionsCards) {
    const observer = new MutationObserver(updateRowLayout);
    observer.observe(sessionsCards, { childList: true });
  }
});

async function loadActivity(days = 182) {
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

      const pageItems = Array.isArray(payload.data?.items) ? payload.data.items : [];
      if (!pageItems.length) break;

      const stopOnlyItems = pageItems.filter(
        (it) => it.playback_type === "VideoPlaybackStopped",
      );

      all.push(...stopOnlyItems);

      const minTsSec = Math.min(...pageItems.map((it) => Number(it.activity_at || 0)));
      if (Number.isFinite(minTsSec) && minTsSec * 1000 <= cutoff) break;

      if (pageItems.length < perPage) break;
      page += 1;
    }

    return all;
  } catch (error) {
    globalThis.helpers.handleError("Failed to load activity", error);
    return [];
  }
}

function buildMatrix(items, days = 182) {
  const now = new Date();
  now.setHours(0, 0, 0, 0);

  const startDate = new Date(now);
  startDate.setDate(startDate.getDate() - (days - 1));
  startDate.setDate(startDate.getDate() - startDate.getDay());

  const counts = {};
  items.forEach((it) => {
    const ts = Number(it.activity_at || 0) * 1000;
    if (!ts) return;
    const d = new Date(ts);
    const iso = globalThis.helpers.toLocalISO(d);
    counts[iso] = (counts[iso] || 0) + 1;
  });

  const data = [];
  let maxV = 0;
  let weekIdx = 0;

  const dateLabels = globalThis.helpers.generateDateLabels(startDate, days);
  dateLabels.forEach((iso) => {
    const v = counts[iso] || 0;
    if (v > maxV) maxV = v;

    const date = new Date(iso + "T00:00:00Z");
    const weekday = date.getUTCDay();
    data.push({
      x: weekIdx + 1,
      y: weekday + 1,
      v,
      date: iso,
    });

    if (weekday === 6) weekIdx += 1;
  });

  return { data, maxV, weeks: weekIdx + 1 };
}

function colorFor(v, maxV) {
  const palette = globalThis.helpers.getPalette();
  if (!v) return "#2b313d";
  const t = Math.min(1, v / Math.max(1, maxV));
  const idx = Math.max(
    0,
    Math.min(palette.length - 1, Math.round(t * (palette.length - 1))),
  );
  return palette[idx];
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
  const labels = new Array(weeks).fill("");
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

function buildTrendSeries(items, days = 14) {
  const now = new Date();
  now.setHours(0, 0, 0, 0);

  const counts = {};
  items.forEach((it) => {
    const ts = Number(it.activity_at || 0) * 1000;
    if (!ts) return;
    const d = new Date(ts);
    const iso = globalThis.helpers.toLocalISO(d);
    counts[iso] = (counts[iso] || 0) + 1;
  });

  const labels = [];
  const values = [];
  const start = globalThis.helpers.addDays(now, -(days - 1));

  const dateLabels = globalThis.helpers.generateDateLabels(start, days);
  dateLabels.forEach((iso) => {
    const date = new Date(iso + "T00:00:00Z");
    const label = `${date.getUTCMonth() + 1}/${date.getUTCDate()}`;
    labels.push(label);
    values.push(counts[iso] || 0);
  });

  return { labels, values };
}

document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("plays-matrix");
  const emptyEl = document.getElementById("matrix-chart-empty-files");
  const matrixLoading = document.getElementById("matrix-loading");
  const trendLoading = document.getElementById("plays-trend-loading");
  if (!canvas) return;

  async function render() {
    try {
      const items = await loadActivity(182);
      const { data, maxV, weeks } = buildMatrix(items, 182);
      if (!data.length || maxV === 0) {
        if (emptyEl) emptyEl.hidden = false;
        canvas.style.display = "none";
        return;
      }

      if (emptyEl) emptyEl.hidden = true;
      canvas.style.display = "";

      const monthLabels = generateMonthLabels(data, weeks);
      const dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

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

      canvas.replaceWith(labelsWrapper);

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
                const areaW = chart.chartArea?.width || canvas.width;
                const areaH = chart.chartArea?.height || canvas.height;
                const cellW = Math.max(2, Math.floor(areaW / weeks) - 1);
                const cellH = Math.max(2, Math.floor(areaH / 7) - 1);
                return Math.max(2, Math.min(cellW, cellH));
              },
              height: ({ chart }) => {
                const areaW = chart.chartArea?.width || canvas.width;
                const areaH = chart.chartArea?.height || canvas.height;
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
                label: (ctxArg) => {
                  const r = ctxArg.raw;
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

      if (globalThis.__playsMatrixChart) {
        globalThis.__playsMatrixChart.destroy();
        globalThis.__playsMatrixChart = null;
      }
      globalThis.__playsMatrixChart = new Chart(ctx, config);
    } finally {
      if (matrixLoading) {
        matrixLoading.classList.remove("skeleton");
        matrixLoading.style.display = "none";
      }
    }
  }

  function scheduleHeatmapRender() {
    const run = () => {
      render().catch((err) => {
        console.error("Failed to render plays heatmap:", err);
      });
    };

    if (typeof globalThis.requestIdleCallback === "function") {
      globalThis.requestIdleCallback(run, { timeout: 100 });
      return;
    }

    globalThis.setTimeout(run, 0);
  }

  scheduleHeatmapRender();

  async function renderTrend() {
    const trendCanvas = document.getElementById("plays-trend-chart");
    const totalCountEl = document.getElementById("plays-trend-total");
    const numberFmt = new Intl.NumberFormat();

    if (!trendCanvas) return;

    if (trendLoading) trendLoading.hidden = false;
    trendCanvas.style.display = "none";

    try {
      const items = await loadActivity(14);
      const { labels, values } = buildTrendSeries(items, 14);

      const totalPlays = values.reduce((sum, value) => sum + Number(value || 0), 0);
      if (totalCountEl) {
        totalCountEl.textContent = numberFmt.format(totalPlays);
      }

      const minV = Math.min(...values);
      const maxV = Math.max(...values);
      const span = Math.max(1, maxV - minV);
      const pad = Math.max(1, Math.round(span * 0.2));
      const yMin = Math.max(0, minV - pad);
      const yMax = maxV + pad;

      const ctx = trendCanvas.getContext("2d");

      const config = {
        type: "line",
        data: {
          labels,
          datasets: [
            {
              data: values,
              borderColor: "#0c1310",
              backgroundColor: "#198544cc",
              fill: true,
              tension: 0.5,
              pointRadius: 3,
              pointHoverRadius: 4,
              pointBackgroundColor: "#0c1310",
              pointBorderColor: "#0c1310",
              borderWidth: 2,
            },
          ],
        },
        options: {
          animation: { duration: 200 },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctxArg) => `Plays: ${ctxArg.raw}`,
              },
            },
          },
          scales: {
            x: {
              display: true,
              title: { display: false },
              ticks: {
                color: "#000000",
                autoSkip: false,
                maxRotation: 0,
                minRotation: 0,
                padding: 6,
              },
              grid: { display: false },
            },
            y: {
              display: true,
              title: { display: false },
              ticks: {
                color: "#000000",
                precision: 0,
              },
              grid: { display: false },
              min: yMin,
              max: yMax,
            },
          },
          maintainAspectRatio: false,
          responsive: true,
        },
      };

      if (globalThis.__playsTrendChart) {
        globalThis.__playsTrendChart.destroy();
        globalThis.__playsTrendChart = null;
      }
      globalThis.__playsTrendChart = new Chart(ctx, config);
      trendCanvas.style.display = "";
      const cardHeader = document.getElementById("plays-trend-card-header");
      if (cardHeader) {
        cardHeader.removeAttribute("hidden");
      }
    } finally {
      if (trendLoading) trendLoading.hidden = true;
    }
  }

  function scheduleTrendRender() {
    const run = () => {
      renderTrend().catch((err) => {
        console.error("Failed to render plays trend:", err);
      });
    };

    if (typeof globalThis.requestIdleCallback === "function") {
      globalThis.requestIdleCallback(run, { timeout: 100 });
      return;
    }

    globalThis.setTimeout(run, 0);
  }

  scheduleTrendRender();
});

(function () {
  const loading = document.getElementById("glance-loading");
  const grid = document.getElementById("glance-grid");

  const elActiveSessions = document.getElementById("glance-active-sessions");
  const elTotalPlays = document.getElementById("glance-total-plays");
  const elTotalItems = document.getElementById("glance-total-items");
  const elTotalSize = document.getElementById("glance-total-size");
  const elTotalUsers = document.getElementById("glance-total-users");

  if (!grid) return;

  const numberFmt = new Intl.NumberFormat();

  function setText(el, value) {
    if (!el) return;
    el.textContent = value;
  }

  async function loadGlance() {
    if (loading) loading.hidden = false;
    if (grid) grid.hidden = true;

    try {
      const resp = await fetch("/api/analytics/stats/glance");
      if (!resp.ok) throw new Error("Network error");

      const payload = await resp.json();
      if (!payload?.ok) throw new Error(payload?.message || "API error");

      const data = payload.data || {};

      setText(elActiveSessions, numberFmt.format(Number(data.active_sessions || 0)));
      setText(elTotalPlays, numberFmt.format(Number(data.total_plays || 0)));
      setText(elTotalItems, numberFmt.format(Number(data.total_items || 0)));
      setText(
        elTotalSize,
        globalThis.helpers.humanBytes(Number(data.total_size_bytes || 0)),
      );
      setText(elTotalUsers, numberFmt.format(Number(data.total_users || 0)));

      if (grid) grid.hidden = false;
    } catch (error) {
      globalThis.helpers.handleError("Failed to load glance", error);
      setText(elActiveSessions, "-");
      setText(elTotalPlays, "-");
      setText(elTotalItems, "-");
      setText(elTotalSize, "-");
      setText(elTotalUsers, "-");
    } finally {
      if (loading) loading.hidden = true;
    }
  }

  loadGlance();
})();

(function () {
  const container = document.getElementById("sessions-container");
  const empty = document.getElementById("sessions-empty");
  const cardsContainer = document.getElementById("sessions-cards");
  const loading = document.getElementById("sessions-loading");
  const elGlanceActiveSessions = document.getElementById("glance-active-sessions");
  const glanceNumberFmt = new Intl.NumberFormat();
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
      iconUrl: isPaused ? "/assets/icons/pause.svg" : "/assets/icons/play.svg",
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
      if (cardsContainer) {
        cardsContainer.hidden = true;
        cardsContainer.innerHTML = "";
      }
      if (empty) empty.hidden = false;
      updateRowLayout();
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
        nowPlayingItem.PrimaryImageTag || nowPlayingItem.ImageTags?.Primary || "";

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
        { label: "Client", value: `${clientName} on ${deviceName}` },
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
      const progressPercent = Math.max(0, Math.min(100, Math.round(rawPercent)));
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
    requestAnimationFrame(() => {
      updateRowLayout();
    });
  }

  async function loadSessions() {
    try {
      const resp = await fetch("/api/analytics/sessions");
      if (!resp.ok) {
        if (elGlanceActiveSessions) elGlanceActiveSessions.textContent = "-";
        renderSessions([]);
        return;
      }

      const result = await resp.json();
      if (!result.ok || !Array.isArray(result.data)) {
        if (elGlanceActiveSessions) elGlanceActiveSessions.textContent = "-";
        renderSessions([]);
        return;
      }

      if (elGlanceActiveSessions) {
        elGlanceActiveSessions.textContent = glanceNumberFmt.format(
          Number(result.data.length || 0),
        );
      }

      renderSessions(result.data);
    } catch (error) {
      globalThis.helpers.handleError("Failed to load sessions", error);
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
  const statisticsSection = document.querySelector(".statistics-section");
  if (!statisticsSection) return;

  const statsCanvas = document.getElementById("watch-statistics-chart");
  const statsLoading = document.getElementById("watch-statistics-loading");
  if (!statsCanvas) return;

  const navItems = statisticsSection.querySelectorAll(".statistics-nav li");
  const palette = globalThis.helpers.getPalette(null, true);

  const statTypes = [
    {
      key: "top_users_by_plays",
      valueKey: "plays",
      format: (v) => String(Number(v)),
    },
    {
      key: "top_items_by_plays",
      valueKey: "plays",
      format: (v) => String(Number(v)),
    },
    {
      key: "top_libraries_by_plays",
      valueKey: "plays",
      format: (v) => String(Number(v)),
    },
    {
      key: "top_users_by_watch_time",
      valueKey: "watch_seconds",
      format: (v) => globalThis.helpers.humanTime(Number(v)),
    },
  ];

  let cachedData = null;

  async function fetchStatsData() {
    try {
      const resp = await fetch("/api/analytics/stats/dashboard");
      if (!resp.ok) return null;

      const payload = await resp.json();
      return payload?.ok ? payload.data?.sections : null;
    } catch (error) {
      console.error("Failed to fetch statistics data:", error);
      return null;
    }
  }

  function renderChart(data, typeIndex) {
    if (!data) return;

    const stat = statTypes[typeIndex];
    const rows = (Array.isArray(data[stat.key]) ? data[stat.key] : []).slice(0, 5);

    const labels = rows.map((r) => r?.name ?? "");
    const values = rows.map((r) => Number(r?.[stat.valueKey] || 0));

    const maxV = values.length ? Math.max(...values) : 0;
    if (!maxV) {
      statsCanvas.style.display = "none";
      return;
    }

    const span = Math.max(1, maxV);
    const pad = Math.max(1, Math.round(span * 0.05));
    const xMax = maxV + pad;

    const ctx = statsCanvas.getContext("2d");

    const config = {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: values.map(
              (_, idx) => palette[Math.min(idx, palette.length - 1)],
            ),
            borderRadius: 100,
            barThickness: 22,
          },
        ],
      },
      options: {
        indexAxis: "y",
        animation: { duration: 200 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctxArg) => stat.format(rows[ctxArg.dataIndex]?.[stat.valueKey]),
            },
          },
        },
        scales: {
          x: {
            display: true,
            title: { display: false },
            ticks: { color: "#b3b3b3", precision: 0, padding: 6 },
            grid: { display: false },
            min: 0,
            max: xMax,
          },
          y: {
            display: true,
            title: { display: false },
            ticks: { color: "#b3b3b3" },
            grid: { display: false },
          },
        },
        maintainAspectRatio: false,
        responsive: true,
      },
    };

    if (globalThis.__statsChart) {
      globalThis.__statsChart.destroy();
      globalThis.__statsChart = null;
    }
    globalThis.__statsChart = new Chart(ctx, config);
    statsCanvas.style.display = "";
  }

  async function switchStatistic(index) {
    navItems.forEach((item, i) => {
      item.classList.toggle("active", i === index);
    });

    if (!cachedData) {
      if (statsLoading) statsLoading.hidden = false;
      statsCanvas.style.display = "none";
      cachedData = await fetchStatsData();
      if (statsLoading) statsLoading.hidden = true;
    }

    renderChart(cachedData, index);
  }

  navItems.forEach((item, index) => {
    item.addEventListener("click", () => switchStatistic(index));
  });

  switchStatistic(0);
})();

(function () {
  const resolutionCanvas = document.getElementById("resolutions-chart");
  const resolutionLoading = document.getElementById("resolutions-loading");
  const resolutionEmpty = document.getElementById("resolutions-empty");

  if (!resolutionCanvas) return;

  const resolutionPalette = globalThis.helpers.getPalette(null, true);

  function renderResolutionsChart(rows) {
    const safeRows = Array.isArray(rows) ? rows : [];
    const labels = safeRows.map((r) => r?.resolution ?? "");
    const values = safeRows.map((r) => Number(r?.count || 0));

    const maxV = values.length ? Math.max(...values) : 0;
    if (!values.length || maxV === 0) {
      if (resolutionEmpty) resolutionEmpty.hidden = false;
      resolutionCanvas.style.display = "none";
      return;
    }

    if (resolutionEmpty) resolutionEmpty.hidden = true;

    const span = Math.max(1, maxV);
    const pad = Math.max(1, Math.round(span * 0.2));
    const xMax = maxV + pad;

    const ctx = resolutionCanvas.getContext("2d");

    const config = {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: values.map(
              (_, idx) =>
                resolutionPalette[Math.min(idx, resolutionPalette.length - 1)],
            ),
            borderRadius: 100,
            barThickness: 18,
          },
        ],
      },
      options: {
        indexAxis: "y",
        animation: { duration: 200 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctxArg) => `Items: ${ctxArg.raw}`,
            },
          },
        },
        scales: {
          x: {
            display: true,
            title: { display: false },
            ticks: {
              color: "#b3b3b3",
              precision: 0,
              padding: 6,
            },
            grid: { display: false },
            min: 0,
            max: xMax,
          },
          y: {
            display: true,
            title: { display: false },
            ticks: { color: "#b3b3b3" },
            grid: { display: false },
          },
        },
        maintainAspectRatio: false,
        responsive: true,
      },
    };

    if (globalThis.__resolutionsChart) {
      globalThis.__resolutionsChart.destroy();
      globalThis.__resolutionsChart = null;
    }
    globalThis.__resolutionsChart = new Chart(ctx, config);
    resolutionCanvas.style.display = "";
  }

  async function loadResolutions() {
    try {
      if (resolutionLoading) resolutionLoading.hidden = false;
      resolutionCanvas.style.display = "none";

      const resp = await fetch("/api/analytics/stats/dashboard");
      if (!resp.ok) return;

      const payload = await resp.json();
      if (!payload?.ok) return;

      renderResolutionsChart(payload.data?.sections?.resolutions || []);
    } catch (error) {
      globalThis.helpers.handleError("Failed to load resolutions", error);
    } finally {
      if (resolutionLoading) resolutionLoading.hidden = true;
    }
  }

  loadResolutions();
})();

(function () {
  const codecsCanvas = document.getElementById("codecs-chart");
  const codecsLoading = document.getElementById("codecs-loading");
  if (!codecsCanvas) return;

  const codecsNav = document.querySelectorAll(".codecs-nav li");
  let cachedData = null;

  async function fetchCodecsData() {
    try {
      if (codecsLoading) codecsLoading.hidden = false;
      codecsCanvas.style.display = "none";

      const resp = await fetch("/api/analytics/stats/dashboard");
      if (!resp.ok) return;

      const payload = await resp.json();
      if (!payload?.ok) return;

      cachedData = payload.data?.sections || {};
    } catch (error) {
      globalThis.helpers.handleError("Failed to load codecs data", error);
    } finally {
      if (codecsLoading) codecsLoading.hidden = true;
    }
  }

  function renderChart(codecType) {
    if (!cachedData) return;

    const dataArray =
      codecType === 0 ? cachedData.video_codecs : cachedData.audio_codecs;
    if (!Array.isArray(dataArray) || !dataArray.length) return;

    const codecKey = codecType === 0 ? "video_codec" : "audio_codec";
    const labels = dataArray.map((r) => r?.[codecKey] || "");
    const values = dataArray.map((r) => Number(r?.count || 0));

    const palette = globalThis.helpers.getPalette(values.length, true);

    const ctx = codecsCanvas.getContext("2d");
    const config = {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: values,
            backgroundColor: palette,
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: {
          legend: {
            display: true,
            position: "right",
            labels: {
              color: "#b3b3b3",
              font: { size: 12 },
              padding: 12,
            },
          },
          tooltip: {
            callbacks: {
              label: (ctxArg) => `${ctxArg.label}: ${ctxArg.raw}`,
            },
          },
        },
      },
    };

    if (globalThis.__codecsChart) {
      globalThis.__codecsChart.destroy();
    }
    globalThis.__codecsChart = new Chart(ctx, config);
    codecsCanvas.style.display = "";
  }

  async function switchCodec(index) {
    codecsNav.forEach((item, i) => {
      item.classList.toggle("active", i === index);
    });

    if (!cachedData) {
      await fetchCodecsData();
    }

    renderChart(index);
  }

  codecsNav.forEach((item, index) => {
    item.addEventListener("click", () => switchCodec(index));
  });

  switchCodec(0);
})();
