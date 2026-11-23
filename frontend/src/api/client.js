import axios from "axios";
export { errorMessage } from "./errorMessages";

/**
 * Central HTTP client.
 *
 * - Base URL defaults to the Vite proxy (`/api/`); set VITE_API_URL to call a
 *   backend on another origin (for example http://localhost:8001/api/).
 * - Attaches the JWT access token to every request.
 * - On a 401 it refreshes the access token once (sharing a single refresh
 *   request between concurrent calls) and retries the original request.
 *   If refreshing fails the session is cleared and listeners are notified.
 */

const ACCESS_KEY = "access_token";
const REFRESH_KEY = "refresh_token";

export const API_BASE = import.meta.env.VITE_API_URL || "/api/";

export const tokens = {
  get access() {
    try { return localStorage.getItem(ACCESS_KEY) || ""; } catch { return ""; }
  },
  get refresh() {
    try { return localStorage.getItem(REFRESH_KEY) || ""; } catch { return ""; }
  },
  set({ access, refresh }) {
    try {
      if (access) localStorage.setItem(ACCESS_KEY, access);
      if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    } catch { /* storage unavailable (private mode) */ }
  },
  clear() {
    try {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
    } catch { /* storage unavailable */ }
  },
};

const sessionListeners = new Set();
/** Subscribe to "session expired" events. Returns an unsubscribe function. */
export function onSessionExpired(listener) {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

const api = axios.create({ baseURL: API_BASE });

api.interceptors.request.use((config) => {
  const access = tokens.access;
  if (access && !config.skipAuth) config.headers.Authorization = `Bearer ${access}`;
  return config;
});

let refreshPromise = null;

/** Refresh the access token. Concurrent callers share one network request. */
export function refreshAccessToken() {
  if (!tokens.refresh) return Promise.reject(new Error("No refresh token"));
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE.replace(/\/$/, "")}/accounts/token/refresh/`, { refresh: tokens.refresh })
      .then((response) => {
        tokens.set({ access: response.data.access, refresh: response.data.refresh });
        return response.data.access;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config || {};
    const status = error.response?.status;
    const isAuthCall = /accounts\/(login|register|token\/refresh)\//.test(original.url || "");
    if (status === 401 && !original._retried && !isAuthCall && tokens.refresh) {
      original._retried = true;
      try {
        const access = await refreshAccessToken();
        original.headers = { ...(original.headers || {}), Authorization: `Bearer ${access}` };
        return api(original);
      } catch {
        tokens.clear();
        sessionListeners.forEach((listener) => listener());
      }
    } else if (status === 401 && !isAuthCall) {
      tokens.clear();
      sessionListeners.forEach((listener) => listener());
    }
    return Promise.reject(error);
  },
);

/** Normalise list endpoints that may return arrays or paginated envelopes. */
export function asList(data) {
  if (Array.isArray(data)) return data;
  for (const key of ["results", "data", "items"]) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

/** Absolute URL for media paths such as /media/chat/x.jpg. */
export function mediaUrl(path) {
  if (!path || typeof path !== "string") return "";
  if (/^(https?:|data:|blob:)/i.test(path)) return path;
  try {
    const base = new URL(API_BASE, window.location.origin);
    return `${base.origin}${path.startsWith("/") ? path : `/${path}`}`;
  } catch {
    return path;
  }
}

/** WebSocket URL for a path such as /ws/chat/inbox/. */
export function socketUrl(path) {
  const configured = import.meta.env.VITE_WS_URL;
  let origin;
  if (configured) {
    origin = configured.replace(/\/$/, "");
  } else {
    const base = new URL(API_BASE, window.location.origin);
    origin = `${base.protocol === "https:" ? "wss:" : "ws:"}//${base.host}`;
  }
  return `${origin}${path}?token=${encodeURIComponent(tokens.access)}`;
}

export default api;
