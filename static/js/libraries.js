(function () {
  const container = document.getElementById("libraries-container");
  const empty = document.getElementById("libraries-empty");
  const cardsContainer = document.getElementById("libraries-cards");

  async function loadLibraries() {
    try {
      const resp = await fetch("/api/analytics/stats/libraries");
      if (!resp.ok) throw new Error("Network error");
      const data = await resp.json();
      if (!data?.ok) throw new Error(data?.message || "API error");

      const libs = Array.isArray(data.data) ? data.data : [];
      renderLibraries(libs);

      if (
        globalThis.updateLibrariesChart &&
        typeof globalThis.updateLibrariesChart === "function"
      ) {
        try {
          globalThis.updateLibrariesChart(libs);
        } catch (error) {
          globalThis.jf_helpers.handleError("Failed to load chart", error);
        }
      }

      if (
        globalThis.updateItemsAddedChart &&
        typeof globalThis.updateItemsAddedChart === "function"
      ) {
        try {
          globalThis.updateItemsAddedChart(libs);
        } catch (error) {
          globalThis.jf_helpers.handleError("Failed to load items added", error);
        }
      }
    } catch (error) {
      globalThis.jf_helpers.handleError("Failed to load libraries", error);
      if (empty) empty.hidden = false;
      if (container) container.hidden = true;
    }
  }

  function renderLibraries(libs) {
    if (!libs || libs.length === 0) {
      if (empty) empty.hidden = false;
      if (container) container.hidden = true;
      return;
    }
    empty.hidden = true;
    container.hidden = false;
    cardsContainer.innerHTML = "";

    libs.forEach((lib) => {
      const card = document.createElement("div");
      card.className = "library-card";

      const typeText =
        lib.type === "movies"
          ? "Movies"
          : lib.type === "tvshows"
            ? "TV Shows"
            : lib.type || "";

      const attrs = [
        { label: "Name", value: lib.name || "(unnamed)", isName: true },
        { label: "Type", value: typeText },
        {
          label: "Total Time",
          value: globalThis.jf_helpers.humanTime(lib.total_time_seconds || 0),
        },
        { label: "Size", value: globalThis.jf_helpers.humanBytes(lib.size_bytes || 0) },
        {
          label: "Total Playback",
          value: globalThis.jf_helpers.humanTime(lib.total_playback_seconds || 0),
        },
        { label: "Last Played", value: lib.last_played_item_name || "-" },
      ];

      attrs.forEach((attr) => {
        const div = document.createElement("div");
        div.className = "library-card-attr";

        const label = document.createElement("span");
        label.className = "library-card-attr-label";
        label.textContent = attr.label;

        const value = document.createElement("span");
        value.className = `library-card-attr-value ${attr.isName ? "name" : ""}`;
        value.textContent = attr.value;

        div.appendChild(label);
        div.appendChild(value);
        card.appendChild(div);
      });

      cardsContainer.appendChild(card);
    });
  }

  loadLibraries();

  setInterval(loadLibraries, 60 * 1000);
})();

/**
 * Charts
 */

(function () {
  let filesChart = null;
  let playsChart = null;
  let itemLineChart = null;

  function paletteFor(n) {
    const palette = [
      "#9bbfe0",
      "#82b0db",
      "#69a1d6",
      "#5092d1",
      "#3783cc",
      "#1f75c6",
      "#1567b3",
      "#0b5990",
      "#004c6d",
    ];
    if (!n || n <= 0) return [];

    if (n <= palette.length) {
      const colors = [];
      for (let i = 0; i < n; i++) {
        const idx = Math.round((i * (palette.length - 1)) / (n - 1));
        colors.push(palette[idx]);
      }
      return colors;
    }

    const colors = [];
    const hue = 198;
    const sat = 52;
    const minL = 32;
    const maxL = 76;
    for (let i = 0; i < n; i++) {
      const t = n === 1 ? 0.5 : i / (n - 1);
      const l = Math.round(minL + (maxL - minL) * t);
      colors.push(`hsl(${hue} ${sat}% ${l}%)`);
    }
    return colors;
  }

  function generateDateRange(days = 30) {
    const dates = [];
    const now = new Date();
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const iso = d.toISOString().slice(0, 10);
      dates.push(iso);
    }
    return dates;
  }

  function initializeItemsByDatePerLibrary(libraries, dates) {
    const result = {};
    libraries.forEach((lib) => {
      result[lib.jellyfin_id] = {};
      dates.forEach((date) => {
        result[lib.jellyfin_id][date] = 0;
      });
    });
    return result;
  }

  async function updateItemsAddedChart(libs) {
    const itemLineCanvas = document.getElementById("item-line");
    if (!itemLineCanvas || !libs || libs.length === 0) return;

    try {
      const resp = await fetch("/api/analytics/items/added-last-30-days");
      if (!resp.ok) throw new Error("Network error");
      const payload = await resp.json();
      if (!payload?.ok) throw new Error(payload?.message || "API error");

      const data = payload.data || {};
      const dates = Array.isArray(data.dates) ? data.dates : generateDateRange(30);

      const itemsByDate = initializeItemsByDatePerLibrary(libs, dates);

      const serverLibs = Array.isArray(data.libraries) ? data.libraries : [];
      serverLibs.forEach((sLib) => {
        if (!sLib?.jellyfin_id || !Array.isArray(sLib.counts)) return;
        const jfId = sLib.jellyfin_id;
        const counts = sLib.counts;
        if (!itemsByDate[jfId]) return;
        for (let i = 0; i < dates.length; i++) {
          const date = dates[i];
          itemsByDate[jfId][date] = Number(counts[i] || 0);
        }
      });

      const borderColor =
        getComputedStyle(document.documentElement).getPropertyValue("--border") ||
        "#333";
      const textColor =
        getComputedStyle(document.documentElement).getPropertyValue("--text") ||
        "#f0f0f0";
      const bgColor =
        getComputedStyle(document.documentElement).getPropertyValue("--bg") ||
        "#121212";

      const colors = paletteFor(libs.length);
      const datasets = libs.map((lib, idx) => {
        const libData = itemsByDate[lib.jellyfin_id] || {};
        const values = dates.map((date) => libData[date] || 0);

        return {
          label: lib.name || "(unnamed)",
          data: values,
          borderColor: colors[idx],
          backgroundColor: colors[idx] + "33",
          fill: true,
          tension: 0.3,
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          pointBackgroundColor: colors[idx],
          pointBorderColor: bgColor,
          pointBorderWidth: 2,
        };
      });

      const ctx = itemLineCanvas.getContext("2d");
      if (itemLineChart) itemLineChart.destroy();

      itemLineChart = new Chart(ctx, {
        type: "line",
        data: {
          labels: dates,
          datasets,
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "bottom",
              labels: {
                color: textColor.trim() || "#f0f0f0",
                boxWidth: 12,
                padding: 8,
                usePointStyle: true,
              },
            },
            tooltip: {
              bodyColor: textColor.trim() || "#f0f0f0",
              titleColor: textColor.trim() || "#f0f0f0",
              backgroundColor: bgColor || "#121212",
              borderColor: borderColor.trim() || "#333",
              borderWidth: 1,
            },
          },
          scales: {
            x: {
              grid: { color: borderColor.trim() || "#333", drawBorder: true },
              ticks: {
                color: textColor.trim() || "#f0f0f0",
                maxRotation: 45,
                minRotation: 0,
              },
            },
            y: {
              beginAtZero: true,
              grid: { color: borderColor.trim() || "#333", drawBorder: true },
              ticks: { color: textColor.trim() || "#f0f0f0", stepSize: 1 },
            },
          },
        },
      });
    } catch (error) {
      globalThis.jf_helpers.handleError("Failed to load items added", error);
      return;
    }
  }

  globalThis.updateItemsAddedChart = updateItemsAddedChart;

  async function updateLibrariesChart(libs) {
    const filesChartCanvas = document.getElementById("files-doughnut");
    const playsChartCanvas = document.getElementById("plays-doughnut");
    const emptyElFiles = document.getElementById("libraries-chart-empty-files");
    const emptyElPlays = document.getElementById("libraries-chart-empty-plays");
    if (!filesChartCanvas) return;
    if (!playsChartCanvas) return;

    const labels = (libs || []).map((l) => l.name || "(unnamed)");
    const filesData = (libs || []).map((l) => Number(l.total_files || 0));
    const playsData = (libs || []).map((l) => Number(l.total_plays || 0));

    const totalFiles = filesData.reduce((a, b) => a + b, 0);
    const totalPlays = playsData.reduce((a, b) => a + b, 0);

    // Files chart
    if (totalFiles) {
      if (emptyElFiles) emptyElFiles.hidden = true;
      filesChartCanvas.style.display = "";
      const bgColors = paletteFor(labels.length);
      const borderColor =
        getComputedStyle(document.documentElement).getPropertyValue("--border") ||
        "#333";
      const textColor =
        getComputedStyle(document.documentElement).getPropertyValue("--text") ||
        "#f0f0f0";
      const ctx = filesChartCanvas.getContext("2d");
      if (filesChart) filesChart.destroy();
      filesChart = new Chart(ctx, {
        type: "doughnut",
        data: {
          labels,
          datasets: [
            {
              data: filesData,
              backgroundColor: bgColors,
              borderColor: new Array(labels.length).fill(borderColor.trim()),
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "bottom",
              labels: {
                color: textColor.trim() || "#f0f0f0",
                boxWidth: 12,
                padding: 8,
              },
            },
            tooltip: {
              bodyColor: textColor.trim() || "#f0f0f0",
              titleColor: textColor.trim() || "#f0f0f0",
              backgroundColor:
                getComputedStyle(document.documentElement).getPropertyValue("--bg") ||
                "#121212",
            },
          },
        },
      });
    } else {
      if (emptyElFiles) emptyElFiles.hidden = false;
      filesChartCanvas.style.display = "none";
      if (filesChart) {
        filesChart.destroy();
        filesChart = null;
      }
    }

    // Plays chart
    if (!totalPlays) {
      if (emptyElPlays) emptyElPlays.hidden = false;
      playsChartCanvas.style.display = "none";
      if (playsChart) {
        playsChart.destroy();
        playsChart = null;
      }
      return;
    }

    if (emptyElPlays) emptyElPlays.hidden = true;
    playsChartCanvas.style.display = "";
    const bgColors2 = paletteFor(labels.length);
    const borderColor2 =
      getComputedStyle(document.documentElement).getPropertyValue("--border") || "#333";
    const textColor2 =
      getComputedStyle(document.documentElement).getPropertyValue("--text") ||
      "#f0f0f0";
    const ctx2 = playsChartCanvas.getContext("2d");
    if (playsChart) playsChart.destroy();
    playsChart = new Chart(ctx2, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data: playsData,
            backgroundColor: bgColors2,
            borderColor: new Array(labels.length).fill(borderColor2.trim()),
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: {
              color: textColor2.trim() || "#f0f0f0",
              boxWidth: 12,
              padding: 8,
            },
          },
          tooltip: {
            bodyColor: textColor2.trim() || "#f0f0f0",
            titleColor: textColor2.trim() || "#f0f0f0",
            backgroundColor:
              getComputedStyle(document.documentElement).getPropertyValue("--bg") ||
              "#121212",
          },
        },
      },
    });
  }
  globalThis.updateLibrariesChart = updateLibrariesChart;
})();
