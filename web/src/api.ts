import type { Bar, MetricSpec, PriceZone, ScreenRunResult, Timeframe } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.message ?? detail?.errors?.[0]?.message ?? `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  catalog: () => request<MetricSpec[]>("/api/catalog"),
  runScreen: (payload: object) =>
    request<ScreenRunResult>("/api/screens/run", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  bars: (symbol: string, timeframe: Timeframe, start: string, end: string) =>
    request<Bar[]>(
      `/api/symbols/${encodeURIComponent(symbol)}/bars?${new URLSearchParams({ timeframe, start, end })}`,
    ),
  zones: (symbol: string, timeframe: Timeframe, asOf: string) =>
    request<PriceZone[]>(
      `/api/symbols/${encodeURIComponent(symbol)}/zones?${new URLSearchParams({ timeframe, as_of: asOf, limit_each: "20" })}`,
    ),
  createManualZone: (symbol: string, payload: object) =>
    request<PriceZone>(`/api/symbols/${encodeURIComponent(symbol)}/zones/manual`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteManualZone: (symbol: string, zoneId: string) =>
    request<void>(`/api/symbols/${encodeURIComponent(symbol)}/zones/manual/${zoneId}`, {
      method: "DELETE",
    }),
};
