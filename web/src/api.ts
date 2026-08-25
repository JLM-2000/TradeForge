import type { Dashboard } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };
const apiBase = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://127.0.0.1:8001" : "");

function apiUrl(path: string) {
  return `${apiBase}${path}`;
}

export async function fetchDashboard(signal?: AbortSignal): Promise<Dashboard> {
  const response = await fetch(apiUrl("/api/v1/dashboard"), { signal });
  if (!response.ok) throw new Error(`Dashboard unavailable (${response.status})`);
  return response.json() as Promise<Dashboard>;
}

export async function postAction<T = Dashboard>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(body ?? {}),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : payload.detail?.message ?? "Action rejected";
    throw new Error(detail);
  }
  return payload as T;
}

export function dashboardFromAction(payload: Dashboard | { dashboard: Dashboard }): Dashboard {
  return "dashboard" in payload ? payload.dashboard : payload;
}

export async function searchUniverse(query: string): Promise<{ matches: Array<{ symbol: string; name: string; exchange: string; assetClass: string; fractionable: boolean; watchlisted: boolean }>; error: string | null }> {
  const response = await fetch(apiUrl(`/api/v1/universe/search?q=${encodeURIComponent(query)}`));
  if (!response.ok) throw new Error(`Universe search failed (${response.status})`);
  return response.json();
}
