(function () {
  const userArrow = document.getElementById("user-arrow");
  const usersList = document.getElementById("sidebar-users-list");

  if (!userArrow || !usersList) return;

  // Toggle users list visibility when clicking Users menu
  userArrow.closest("a").addEventListener("click", (e) => {
    e.preventDefault();
    usersList.style.display = usersList.style.display === "none" ? "" : "none";
  });
})();
