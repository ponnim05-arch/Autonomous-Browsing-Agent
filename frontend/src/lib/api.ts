/**
 * Central API client configuration.
 *
 * - Local dev: leave VITE_API_BASE_URL unset → requests hit the Vite dev proxy
 *   (see vite.config.ts) which forwards /api, /ws and /screenshots to the
 *   FastAPI backend on 127.0.0.1:8000.
 * - Production: set VITE_API_BASE_URL (e.g. https://browser-agent-api.onrender.com)
 *   so the Vercel-hosted frontend talks directly to the Python backend.
 */

const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") ?? "";

/** Build an absolute URL for a REST/static path such as "/api/health". */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** Build a WebSocket URL for a path such as "/ws/agent/<run_id>". */
export function wsUrl(path: string): string {
  if (API_BASE) {
    return `${API_BASE.replace(/^http/, "ws")}${path}`;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}
