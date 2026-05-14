(function () {
  /**
   * Load and render sidebar user entries.
   * @returns {Promise<void>} Resolves when sidebar rendering is complete.
   */
  async function loadSidebarUsers() {
    const list = document.getElementById("sidebar-users-list");
    if (!list) return;

    const result = await helpers.fetchJson("/api/analytics/stats/users");

    if (!result.ok || !result.data) {
      console.error("Failed to load users:", result.message);
      return;
    }

    const users = result.data;
    if (!users.length) return;

    users.forEach((user) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = `/users/${user.id}`;

      const img = document.createElement("img");
      img.alt = "";
      img.className = "sidebar-user-icon";
      img.src = user.image_url || "/assets/icons/profile_small.png";
      img.onerror = () => {
        img.src = "/assets/icons/profile_small.png";
      };

      const span = document.createElement("span");
      span.textContent = user.name;
      span.title = user.name;

      link.appendChild(img);
      link.appendChild(span);

      if (globalThis.location.pathname === `/users/${user.id}`) {
        link.classList.add("active");
      }

      li.appendChild(link);
      list.appendChild(li);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadSidebarUsers);
  } else {
    loadSidebarUsers();
  }
})();
