(function () {
  /**
   * Refresh user page data when sync completes.
   * @returns {void}
   */
  function refreshUserData() {
    try {
      populateGlanceSection();
      populateRecentActivity();
    } catch (error) {
      globalThis.helpers.handleError("Error refreshing user data:", error);
    }
  }

  document.addEventListener("syncComplete", () => {
    refreshUserData();
  });
})();

function populateGlanceSection() {
  const data = document.getElementById("user-data");
  if (!data) return;

  const user = JSON.parse(data.textContent);

  document.getElementById("glance-total-plays").textContent = user.total_plays;
  document.getElementById("glance-total-watch-time").textContent =
    globalThis.helpers.humanTime(user.total_watch_time_seconds);
  document.getElementById("glance-last-activity").textContent = user.last_seen_at
    ? new Date(user.last_seen_at * 1000).toLocaleDateString()
    : "-";
}

function populateRecentActivity() {
  const userIdMatch = new RegExp(/\/user\/([^/]+)$/).exec(globalThis.location.pathname);
  if (!userIdMatch) return;

  const userId = userIdMatch[1];
  const container = document.getElementById("recent-activity-container");
  const empty = document.getElementById("recent-activity-empty");
  const tbody = document.getElementById("recent-activity-tbody");

  fetch(`/api/analytics/user/${encodeURIComponent(userId)}/recent-activity?limit=18`)
    .then((res) => {
      if (!res.ok) throw new Error("Failed to fetch recent activity");
      return res.json();
    })
    .then((result) => {
      if (!result.ok || !Array.isArray(result.data)) {
        empty.hidden = false;
        container.hidden = true;
        return;
      }

      if (result.data.length === 0) {
        empty.hidden = false;
        container.hidden = true;
        return;
      }

      tbody.innerHTML = "";

      for (const activity of result.data) {
        const tr = document.createElement("tr");

        const dateTd = document.createElement("td");
        const date = new Date((activity.activity_at || 0) * 1000);
        dateTd.textContent = globalThis.helpers.formatDateTime(date);
        tr.appendChild(dateTd);

        const displayName = globalThis.helpers.extractMediaItemName(
          activity.event_name,
          activity.playback_type,
        );

        const nameTd = document.createElement("td");
        nameTd.textContent = displayName || activity.item_name || "Unknown";
        nameTd.className = "recent-activity-name";
        tr.appendChild(nameTd);

        const durationTd = document.createElement("td");
        durationTd.textContent = globalThis.helpers.humanTime(
          activity.duration_watched_seconds || 0,
        );
        durationTd.className = "align-right";
        tr.appendChild(durationTd);

        tbody.appendChild(tr);
      }

      container.hidden = false;
      empty.hidden = true;
    })
    .catch((error) => {
      globalThis.helpers.handleError("Failed to load recent activity", error);
      empty.hidden = false;
      container.hidden = true;
    });
}

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
      key: "libraries",
      labelField: "name",
      valueKey: "plays",
      format: (v) => String(Number(v)),
    },
    {
      key: "items",
      labelField: "name",
      valueKey: "plays",
      format: (v) => String(Number(v)),
    },
    {
      key: "genres",
      labelField: "genre",
      valueKey: "plays",
      format: (v) => String(Number(v)),
    },
  ];

  let cachedData = null;

  async function fetchStatsData() {
    const userIdMatch = /\/user\/([^/]+)$/.exec(globalThis.location.pathname);
    if (!userIdMatch) return null;

    const userId = userIdMatch[1];

    try {
      const libResp = await fetch(
        `/api/analytics/user/${encodeURIComponent(userId)}/stats/libraries`,
      );
      if (!libResp.ok) return null;

      const libPayload = await libResp.json();
      if (!libPayload?.ok) return null;

      const itemResp = await fetch(
        `/api/analytics/user/${encodeURIComponent(userId)}/stats/items`,
      );
      if (!itemResp.ok) return null;

      const itemPayload = await itemResp.json();
      if (!itemPayload?.ok) return null;

      const genreResp = await fetch(`/api/analytics/stats/dashboard`);
      if (!genreResp.ok) return null;

      const genrePayload = await genreResp.json();
      if (!genrePayload.ok) return null;

      const rawGenres = genrePayload.data?.sections?.most_popular_genres || [];
      const genres = rawGenres
        .map((g) => ({
          genre: g.genre,
          plays: g.user_breakdown?.[userId] ?? 0,
        }))
        .sort((a, b) => b.plays - a.plays);

      return {
        libraries: libPayload.data?.libraries || [],
        items: itemPayload.data?.items || [],
        genres: genres,
      };
    } catch (error) {
      globalThis.helpers.handleError("Failed to fetch statistics data:", error);
      return null;
    }
  }

  function renderChart(data, typeIndex) {
    if (!data) return;

    const stat = statTypes[typeIndex];
    const rows = (Array.isArray(data[stat.key]) ? data[stat.key] : []).slice(0, 5);

    const labels = rows.map((r) => r?.[stat.labelField] ?? "");
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

    const xTicks = {
      color: "#b3b3b3",
      precision: 0,
      padding: 6,
    };

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
        animation: { duration: 0 },
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
            ticks: xTicks,
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

    if (globalThis.__userStatsChart) {
      globalThis.__userStatsChart.destroy();
      globalThis.__userStatsChart = null;
    }
    globalThis.__userStatsChart = new Chart(ctx, config);
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
  const trendLoading = document.getElementById("plays-trend-loading");
  const trendCanvas = document.getElementById("plays-trend-chart");
  if (!trendCanvas) return;

  /**
   * Load activity for a specific user over N days.
   * @param {string} userId The Jellyfin user ID
   * @param {number} days Number of days to look back
   * @returns {Promise<Array>} Filtered stop events
   */
  async function loadUserActivity(userId, days = 14) {
    try {
      const perPage = 1000;
      const maxPages = 20;
      let page = 1;
      const all = [];
      const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;

      while (page <= maxPages) {
        const resp = await fetch(
          `/api/analytics/activitylog?page=${page}&per_page=${perPage}&user_ids=${encodeURIComponent(userId)}`,
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

        const minTsSec = Math.min(
          ...pageItems.map((it) => Number(it.activity_at || 0)),
        );
        if (Number.isFinite(minTsSec) && minTsSec * 1000 <= cutoff) break;

        if (pageItems.length < perPage) break;
        page += 1;
      }

      return all;
    } catch (error) {
      globalThis.helpers.handleError("Failed to load user activity", error);
      return [];
    }
  }

  async function renderUserTrend(days = 14) {
    const userIdMatch = /\/user\/([^/]+)$/.exec(globalThis.location.pathname);
    if (!userIdMatch) return;

    const userId = userIdMatch[1];
    const totalCountEl = document.getElementById("plays-trend-total");
    const trendLabelEl = document.querySelector(".plays-trend-card-label");
    const numberFmt = new Intl.NumberFormat();

    if (trendLoading) trendLoading.hidden = false;
    trendCanvas.style.display = "none";

    try {
      const items = await loadUserActivity(userId, days);

      let labels, values;
      if (days === 1) {
        const now = new Date();
        const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const todayEnd = new Date(todayStart);
        todayEnd.setDate(todayEnd.getDate() + 1);

        const counts = new Array(24).fill(0);
        items.forEach((it) => {
          const ts = Number(it.activity_at || 0) * 1000;
          if (!ts) return;
          const d = new Date(ts);
          if (d >= todayStart && d < todayEnd) {
            counts[d.getHours()] += 1;
          }
        });

        labels = [];
        values = [];
        for (let h = 0; h < 24; h++) {
          const d = new Date(todayStart);
          d.setHours(h);
          labels.push(globalThis.helpers.formatHour(d));
          values.push(counts[h]);
        }
      } else {
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

        labels = [];
        values = [];
        const start = globalThis.helpers.addDays(now, -(days - 1));

        const dateLabels = globalThis.helpers.generateDateLabels(start, days);
        dateLabels.forEach((iso) => {
          const date = new Date(iso + "T00:00:00Z");
          labels.push(globalThis.helpers.toLocalMD(date));
          values.push(counts[iso] || 0);
        });
      }

      const totalPlays = values.reduce((sum, v) => sum + Number(v || 0), 0);
      if (totalCountEl) {
        totalCountEl.textContent = numberFmt.format(totalPlays);
      }
      if (trendLabelEl) {
        trendLabelEl.textContent =
          days === 1 ? "Plays today by the hour" : `Plays in the last ${days} days`;
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
              borderColor: "#000000cc",
              backgroundColor: "#056d4ccc",
              fill: true,
              tension: 0.5,
              pointRadius: 3,
              pointHoverRadius: 4,
              pointBackgroundColor: "#000000cc",
              pointBorderColor: "#000000cc",
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
                autoSkip: true,
                maxRotation: 0,
                minRotation: 0,
                padding: 6,
              },
              grid: { display: true },
            },
            y: {
              display: true,
              title: { display: false },
              ticks: {
                color: "#000000",
                precision: 0,
              },
              grid: { display: true },
              min: yMin,
              max: yMax,
            },
          },
          maintainAspectRatio: false,
          responsive: true,
        },
      };

      if (globalThis.__userTrendChart) {
        globalThis.__userTrendChart.destroy();
      }
      globalThis.__userTrendChart = new Chart(ctx, config);
      trendCanvas.style.display = "";

      const cardHeader = document.getElementById("plays-trend-card-header");
      if (cardHeader) {
        cardHeader.removeAttribute("hidden");
      }
    } finally {
      if (trendLoading) trendLoading.hidden = true;
    }
  }

  const run = () => {
    renderUserTrend().catch((error) => {
      globalThis.helpers.handleError("Failed to render user trend:", error);
    });
  };
  if (typeof globalThis.requestIdleCallback === "function") {
    globalThis.requestIdleCallback(run, { timeout: 100 });
  } else {
    globalThis.setTimeout(run, 0);
  }

  const trendDayMap = [1, 7, 14, 30, 90];
  const trendNavs = document.querySelectorAll(".plays-trend-nav li");

  trendNavs.forEach((item, index) => {
    item.addEventListener("click", () => {
      const days = trendDayMap[index];
      if (days === null) return;

      trendNavs.forEach((nav) => nav.classList.remove("active"));
      item.classList.add("active");
      renderUserTrend(days);
    });
  });

  document.addEventListener("syncComplete", () => {
    renderUserTrend().catch((error) => {
      globalThis.helpers.handleError("Failed to refresh user trend:", error);
    });
  });
})();

document.addEventListener("DOMContentLoaded", () => {
  populateGlanceSection();
  populateRecentActivity();
});
