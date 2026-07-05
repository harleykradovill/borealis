(function () {
  const container = document.getElementById("table-section");
  const empty = document.getElementById("libraries-empty");
  const tableContainer = document.getElementById("libraries-table-container");
  const tbody = document.getElementById("libraries-tbody");

  async function loadLibraries() {
    try {
      const result = await globalThis.helpers.fetchJson(
        "/api/analytics/stats/libraries",
      );
      if (!result?.ok) throw new Error(result?.message || "Unknown error");

      const libs = Array.isArray(result.data) ? result.data : [];
      renderLibraries(libs);

      if (
        globalThis.updateLibrariesChart &&
        typeof globalThis.updateLibrariesChart === "function"
      ) {
        updateLibrariesChart(libs);
      }

      if (
        globalThis.updateItemsAddedChart &&
        typeof globalThis.updateItemsAddedChart === "function"
      ) {
        updateItemsAddedChart(libs);
      }
    } catch (error) {
      globalThis.helpers.handleError("Failed to load libraries", error);

      if (empty) empty.hidden = false;
      if (container) container.hidden = true;
      if (tableContainer) tableContainer.hidden = true;
    }
  }

  function renderLibraries(libs) {
    if (!libs || libs.length === 0) {
      if (empty) empty.hidden = false;
      if (container) container.hidden = true;
      if (tableContainer) tableContainer.hidden = true;
      return;
    }

    if (empty) empty.hidden = true;
    if (container) container.hidden = false;
    if (tableContainer) tableContainer.hidden = false;

    tbody.innerHTML = "";

    libs.forEach((lib) => {
      const tr = document.createElement("tr");

      let typeText = "";

      if (lib.type === "movies") {
        typeText = "Movies";
      } else if (lib.type === "tvshows") {
        typeText = "TV Shows";
      } else {
        typeText = lib.type || "";
      }

      const attrs = [
        { label: "Name", value: lib.name || "(unnamed)", isName: true },
        { label: "Type", value: typeText },
        {
          label: "Total Time",
          value: globalThis.helpers.humanTime(lib.total_time_seconds || 0),
        },
        { label: "Size", value: globalThis.helpers.humanBytes(lib.size_bytes || 0) },
        {
          label: "Total Playback",
          value: globalThis.helpers.humanTime(lib.total_playback_seconds || 0),
        },
        { label: "Last Played", value: lib.last_played_item_name || "-" },
      ];

      attrs.forEach((attr) => {
        const td = document.createElement("td");
        if (attr.isName) {
          td.className = "libraries-table-name";
          td.textContent = attr.value;
        } else {
          td.textContent = attr.value;
        }
        tr.appendChild(td);
      });

      tbody.appendChild(tr);
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
      const result = await globalThis.helpers.fetchJson(
        "/api/analytics/items/added-last-30-days",
      );
      if (!result?.ok) throw new Error(result?.message || "API error");

      const data = result.data || {};
      const dates = Array.isArray(data.dates)
        ? data.dates.map((d) => globalThis.helpers.toLocalMD(new Date(d)))
        : globalThis.helpers
            .generateDateLabels(start, days)
            .map(globalThis.helpers.toLocalMD);

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
        "#b3b3b3";
      const bgColor =
        getComputedStyle(document.documentElement).getPropertyValue("--bg") ||
        "#121212";

      const colors = globalThis.helpers.getPalette(libs.length);
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
                color: textColor.trim() || "#b3b3b3",
                boxWidth: 12,
                padding: 8,
                usePointStyle: true,
              },
            },
            tooltip: {
              bodyColor: textColor.trim() || "#b3b3b3",
              titleColor: textColor.trim() || "#b3b3b3",
              backgroundColor: bgColor || "#121212",
              borderColor: borderColor.trim() || "#333",
              borderWidth: 1,
            },
          },
          scales: {
            x: {
              grid: { color: borderColor.trim() || "#333", drawBorder: true },
              ticks: {
                color: textColor.trim() || "#b3b3b3",
                maxRotation: 45,
                minRotation: 0,
              },
            },
            y: {
              beginAtZero: true,
              grid: { color: borderColor.trim() || "#333", drawBorder: true },
              ticks: { color: textColor.trim() || "#b3b3b3", stepSize: 1 },
            },
          },
        },
      });
    } catch (error) {
      globalThis.helpers.handleError("Failed to load items added", error);
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
      const bgColors = globalThis.helpers.getPalette(labels.length);
      const borderColor =
        getComputedStyle(document.documentElement).getPropertyValue("--border") ||
        "#333";
      const textColor =
        getComputedStyle(document.documentElement).getPropertyValue("--text") ||
        "#b3b3b3";
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
              position: "right",
              labels: {
                color: textColor.trim() || "#b3b3b3",
                boxWidth: 12,
                padding: 8,
              },
            },
            tooltip: {
              bodyColor: textColor.trim() || "#b3b3b3",
              titleColor: textColor.trim() || "#b3b3b3",
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
    const bgColors2 = globalThis.helpers.getPalette(labels.length);
    const borderColor2 =
      getComputedStyle(document.documentElement).getPropertyValue("--border") || "#333";
    const textColor2 =
      getComputedStyle(document.documentElement).getPropertyValue("--text") ||
      "#b3b3b3";
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
            position: "right",
            labels: {
              color: textColor2.trim() || "#b3b3b3",
              boxWidth: 12,
              padding: 8,
            },
          },
          tooltip: {
            bodyColor: textColor2.trim() || "#b3b3b3",
            titleColor: textColor2.trim() || "#b3b3b3",
            backgroundColor:
              getComputedStyle(document.documentElement).getPropertyValue("--bg") ||
              "#121212",
          },
        },
      },
    });
  }
  globalThis.updateLibrariesChart = updateLibrariesChart;

  document.addEventListener("syncComplete", () => {
    loadLibraries();
  });
})();
