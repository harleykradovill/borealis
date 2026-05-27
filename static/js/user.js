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
      console.error("Error refreshing user data:", error);
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

  fetch(`/api/analytics/user/${encodeURIComponent(userId)}/recent-activity?limit=8`)
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

document.addEventListener("DOMContentLoaded", () => {
  populateGlanceSection();
  populateRecentActivity();
});
