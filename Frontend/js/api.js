async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await parseResponse(response);
  if (!response.ok) {
    const error = new Error(
      payload?.detail || payload?.message || payload?.error || "Ошибка запроса",
    );
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export function formatBackendError(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Неизвестная ошибка";
}

export async function getCurrentUser() {
  return apiFetch("/api/auth/me", { method: "GET" });
}

export async function loginUser(username, password) {
  return apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function registerUser(username, password) {
  return apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logoutUser() {
  return apiFetch("/api/auth/logout", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function listWorlds() {
  return apiFetch("/api/worlds", { method: "GET" });
}

export async function createWorld(world_name, world_seed) {
  return apiFetch("/api/worlds", {
    method: "POST",
    body: JSON.stringify({ world_name, world_seed: world_seed || null }),
  });
}

export async function deleteWorld(worldId) {
  return apiFetch(`/api/worlds/${worldId}`, {
    method: "DELETE",
  });
}

export async function createServer(worldId) {
  return apiFetch("/api/servers", {
    method: "POST",
    body: JSON.stringify({ world_id: worldId }),
  });
}

export async function getServer(serverCode) {
  return apiFetch(`/api/servers/${serverCode}`, {
    method: "GET",
  });
}
