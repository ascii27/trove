import type { ItemFull, ItemSummary } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface ListResponse {
  items: ItemSummary[];
  unread_count: number;
}
export interface CaptureResponse {
  item: ItemSummary;
  duplicate: boolean;
}

export const api = {
  list: (view: "all" | "unread") => req<ListResponse>(`/api/items?view=${view}`),
  get: (id: number) => req<{ item: ItemFull }>(`/api/items/${id}`),
  capture: (url: string) =>
    req<CaptureResponse>("/api/items", { method: "POST", body: JSON.stringify({ url }) }),
  markRead: (id: number) =>
    req<{ item: ItemFull; unread_count: number }>(`/api/items/${id}/read`, { method: "POST" }),
  markUnread: (id: number) =>
    req<{ item: ItemFull; unread_count: number }>(`/api/items/${id}/unread`, { method: "POST" }),
  retry: (id: number) => req<{ item: ItemFull }>(`/api/items/${id}/retry`, { method: "POST" }),
  remove: (id: number) =>
    req<{ deleted: boolean; unread_count: number }>(`/api/items/${id}`, { method: "DELETE" }),
};
