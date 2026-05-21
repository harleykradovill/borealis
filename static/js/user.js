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

document.addEventListener("DOMContentLoaded", populateGlanceSection);
