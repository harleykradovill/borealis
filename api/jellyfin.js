export async function getSystemInfo() {
  return fetchJson("/api/jellyfin/system-info");
}

export async function getUsers() {
  return fetchJson("/api/jellyfin/users");
}

export async function getLibraries() {
  return fetchJson("/api/jellyfin/libraries");
}

async function fetchJson(path) {
  try {
    const resp = await fetch(path, { method: "GET" });
    const body = await resp.json();
    if (!resp.ok) {
      return { ok: false, status: resp.status, message: "HTTP error", data: null };
    }
    return body;
  } catch (err) {
    return { ok: false, status: 0, message: err?.message || "Network error" };
  }
}