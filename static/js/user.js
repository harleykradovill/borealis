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
        dateTd.textContent = date.toLocaleDateString();
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

document.addEventListener("DOMContentLoaded", () => {
  populateGlanceSection();
  populateRecentActivity();
});
