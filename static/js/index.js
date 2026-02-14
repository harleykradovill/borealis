(function () {
  let syncToastId = null;

  async function checkSyncStatus() {
    try {
      const resp = await fetch("/api/analytics/server/sync-progress");
      if (!resp.ok) return;

      const data = await resp.json();
      if (!data.ok) return;

      if (data.syncing) {
        if (!syncToastId) {
          syncToastId = Toast.showSyncToast("Syncing...");
        }
      } else {
        if (syncToastId) {
          Toast.hideSyncToast(syncToastId);
          syncToastId = null;
        }
      }
    } catch (err) {
      console.error("Failed to check sync status:", err);
    }
  }

  checkSyncStatus();
  setInterval(checkSyncStatus, 2000);
})();

document.addEventListener("DOMContentLoaded", () => {
  const canvas = document.getElementById("plays-matrix");
  const emptyEl = document.getElementById("matrix-chart-empty-files");
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
      "#c3d1dd",
      "#adbfce",
      "#98aec0",
      "#829cb2",
      "#6d8ca3",
      "#577b95",
      "#416b88",
      "#285b7a",
      "#004c6d",
    ];
    if (!v) return "#333";
    const t = Math.min(1, v / Math.max(1, maxV));
    const idx = Math.max(
      0,
      Math.min(palette.length - 1, Math.round(t * (palette.length - 1))),
    );
    return palette[idx];
  }

  async function render() {
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

  render();
});

(function () {
  const container = document.getElementById("sessions-container");
  const empty = document.getElementById("sessions-empty");
  const cardsContainer = document.getElementById("sessions-cards");

  if (!container || !cardsContainer) return;

  const REFRESH_INTERVAL = 5000;
  let refreshTimer = null;

  function formatTranscodeStatus(isTranscoding, transcodeReason) {
    if (!isTranscoding) return "Direct Playing";
    return `Transcoding (${transcodeReason || "unknown"})`;
  }

  function formatProgress(progressTicks, runtimeTicks) {
    if (!progressTicks || !runtimeTicks) return "-";
    const percent = Math.round((progressTicks / runtimeTicks) * 100);
    return `${percent}%`;
  }

  function formatETA(progressTicks, runtimeTicks, playbackRate) {
    if (!progressTicks || !runtimeTicks || !playbackRate) return "-";
    const remainingTicks = runtimeTicks - progressTicks;
    const remainingMs = remainingTicks / 10000;
    const remainingSec = Math.round(remainingMs / 1000);

    if (remainingSec < 0) return "-";
    if (remainingSec < 60) return `${remainingSec}s`;

    const minutes = Math.floor(remainingSec / 60);
    const seconds = remainingSec % 60;
    return `${minutes}m ${seconds}s`;
  }

  function renderSessions(sessions) {
    if (!sessions || sessions.length === 0) {
      container.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }

    container.hidden = false;
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
      const itemName = nowPlayingItem.Name || "Unknown Item";

      const playState = session.PlayState || {};
      const progressTicks = playState.PositionTicks || 0;
      const runtimeTicks = nowPlayingItem.RunTimeTicks || 0;
      const playbackRate = playState.PlaybackRate || 1;

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
        {
          label: "Progress",
          value: formatProgress(progressTicks, runtimeTicks),
        },
        {
          label: "ETA",
          value: formatETA(progressTicks, runtimeTicks, playbackRate),
        },
        { label: "Now Playing", value: itemName },
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
