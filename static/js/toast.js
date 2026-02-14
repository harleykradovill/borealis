(function () {
  let nextId = 0;
  const toasts = new Map();

  /**
   * Get or create the toast container.
   * @returns {HTMLElement} The container element used to host toasts
   */
  function getContainer() {
    let el = document.getElementById("toast-container");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast-container";
      el.className = "toast-container";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    return el;
  }

  /**
   * Generate a unique toast id.
   * @returns {string} A unique toast identifier
   */
  function makeId() {
    nextId += 1;
    return `toast-${nextId}`;
  }

  /**
   * Show a toast message.
   * @param {any} message Message content to display
   * @param {string} [type="success"] Visual class for the toast
   * @param {number} [ttl=5000] Time in ms the toast should show
   * @returns {string} The generated toast ID
   */
  function showToast(message, type = "success", ttl = 5000) {
    const container = getContainer();

    const id = makeId();
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.setAttribute("role", "status");
    el.dataset.toastId = id;
    el.textContent = String(message);

    container.appendChild(el);

    let timeoutId;
    if (typeof ttl === "number" && ttl > 0) {
      timeoutId = setTimeout(() => removeToast(id), ttl);
    }

    toasts.set(id, { el, timeoutId });
    return id;
  }

  /**
   * Update an existing toast.
   * @param {string} id The toast ID to update
   * @param {string} message New message text to set
   * @param {string} type New type/class to set on the toast
   * @returns {boolean} True if the toast was found and updated, false otherwise
   */
  function updateToast(id, message, type) {
    const entry = toasts.get(id);
    if (!entry) return false;

    if (typeof message === "string") {
      entry.el.textContent = message;
    }

    if (typeof type === "string" && type.length) {
      entry.el.className = `toast ${type}`;
    }

    return true;
  }

  /**
   * Remove a toast.
   * @param {string} id The toast ID to remove
   * @returns {boolean} True if toast is removed, false if it doesn't exist
   */
  function removeToast(id) {
    const entry = toasts.get(id);
    if (!entry) return false;

    if (entry.timeoutId) {
      clearTimeout(entry.timeoutId);
    }

    entry.el.remove();
    toasts.delete(id);
    return true;
  }

  function showSyncToast(message = "Syncing...") {
    const container = getContainer();

    const id = makeId();
    const el = document.createElement("div");
    el.className = "toast sync";
    el.setAttribute("role", "status");
    el.dataset.toastId = id;
    el.textContent = String(message);

    container.appendChild(el);

    toasts.set(id, { el, timeoutId: null });
    return id;
  }

  function updateSyncToast(toastId, message) {
    const toast = toasts.get(toastId);
    if (toast && toast.el) {
      toast.el.textContent = String(message);
    }
  }

  function hideSyncToast(toastId) {
    removeToast(toastId);
  }

  window.Toast = {
    showToast,
    updateToast,
    removeToast,
    showSyncToast,
    updateSyncToast,
    hideSyncToast,
  };
})();
