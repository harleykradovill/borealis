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
    const WEEKS = Math.ceil(days / 7);
    const buckets = Array.from({ length: WEEKS }, () => Array(7).fill(0));
    const msPerDay = 24 * 60 * 60 * 1000;

    items.forEach((it) => {
      const ts = Number(it.activity_at || 0) * 1000;
      if (!ts) return;
      const d = new Date(ts);
      const dayDiff = Math.floor(
        (Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) -
          Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())) /
          msPerDay,
      );
      const index = days - 1 - dayDiff;
      if (index < 0 || index >= days) return;
      const weekIdx = Math.floor(index / 7);
      const weekday = d.getUTCDay();
      if (weekIdx < 0 || weekIdx >= WEEKS) return;
      buckets[weekIdx][weekday] = (buckets[weekIdx][weekday] || 0) + 1;
    });

    let maxV = 0;
    const data = [];
    for (let w = 0; w < WEEKS; w++) {
      for (let wd = 0; wd < 7; wd++) {
        const v = buckets[w][wd] || 0;
        if (v > maxV) maxV = v;

        const index = w * 7 + wd;
        const dayOffset = days - 1 - index;
        const d = new Date(
          Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
        );
        d.setUTCDate(d.getUTCDate() - dayOffset);
        const iso = d.toISOString().slice(0, 10);

        data.push({ x: w + 1, y: wd + 1, v, date: iso });
      }
    }

    return { data, maxV, weeks: WEEKS };
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

    const ctx = canvas.getContext("2d");

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
