(function () {
  const container = document.getElementById("users-container");
  const empty = document.getElementById("users-empty");
  const tbody = document.getElementById("users-tbody");

  function formatWatchTime(seconds) {
    if (!seconds || seconds === 0) return "0s";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return h ? `${h}h ${m}m` : m ? `${m}m ${s}s` : `${s}s`;
  }

  function formatLastSeen(timestamp) {
    if (!timestamp) return "Never";
    const ts = Number(timestamp);
    if (!ts) return "Never";
    const date = new Date(ts * 1000);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  async function loadUsers() {
    try {
      const resp = await fetch("/api/analytics/stats/users");
      if (!resp.ok) throw new Error("Network error");

      const payload = await resp.json();
      if (!payload || !payload.ok) {
        throw new Error(payload?.message || "API error");
      }

      const users = Array.isArray(payload.data) ? payload.data : [];
      render(users);
    } catch (err) {
      console.error(err);
      renderEmpty();
    }
  }

  function render(users) {
    if (!users || users.length === 0) {
      renderEmpty();
      return;
    }

    container.hidden = false;
    empty.hidden = true;
    tbody.innerHTML = "";

    users.forEach((user) => {
      const row = document.createElement("tr");

      const nameCell = document.createElement("td");
      nameCell.className = "user-name";
      nameCell.textContent = user.name || "Unknown";

      const lastWatchedCell = document.createElement("td");
      lastWatchedCell.className = "cell-muted";
      lastWatchedCell.textContent = user.last_watched_item_name || "(no data)";

      const lastDeviceCell = document.createElement("td");
      lastDeviceCell.className = "cell-muted";
      lastDeviceCell.textContent = user.last_device || "(no data)";

      const totalPlaysCell = document.createElement("td");
      totalPlaysCell.className = "align-right cell-value";
      totalPlaysCell.textContent = String(user.total_plays || 0);

      const watchTimeCell = document.createElement("td");
      watchTimeCell.className = "align-right cell-value";
      watchTimeCell.textContent = formatWatchTime(
        user.total_watch_time_seconds || 0,
      );

      const lastSeenCell = document.createElement("td");
      lastSeenCell.className = "align-right cell-muted";
      lastSeenCell.textContent = formatLastSeen(user.last_seen_at);

      row.appendChild(nameCell);
      row.appendChild(lastWatchedCell);
      row.appendChild(lastDeviceCell);
      row.appendChild(totalPlaysCell);
      row.appendChild(watchTimeCell);
      row.appendChild(lastSeenCell);

      tbody.appendChild(row);
    });
  }

  function renderEmpty() {
    container.hidden = true;
    empty.hidden = false;
    tbody.innerHTML = "";
  }

  loadUsers();
  setInterval(loadUsers, 60000);
})();
