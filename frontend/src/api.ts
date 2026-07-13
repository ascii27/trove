import type { Collection, Feed, ItemFull, ItemSummary } from "./types";

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

export interface LensResponse {
  query: string;
  items: ItemSummary[];
  saved_count: number;
  feed_count: number;
}
export interface FeedsResponse {
  feeds: Feed[];
}
export interface AddFeedResponse {
  feed: Feed;
  duplicate: boolean;
}

export const api = {
  list: (view: "all" | "unread" | "feed", feedId?: number) =>
    req<ListResponse>(`/api/items?view=${view}${feedId != null ? `&feed_id=${feedId}` : ""}`),
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
  save: (id: number) => req<{ item: ItemFull }>(`/api/items/${id}/save`, { method: "POST" }),

  lens: (q: string) => req<LensResponse>(`/api/lens?q=${encodeURIComponent(q)}`),

  feeds: () => req<FeedsResponse>("/api/feeds"),
  addFeed: (url: string) =>
    req<AddFeedResponse>("/api/feeds", { method: "POST", body: JSON.stringify({ url }) }),
  removeFeed: (id: number) => req<{ deleted: boolean }>(`/api/feeds/${id}`, { method: "DELETE" }),

  collections: () => req<{ collections: Collection[] }>("/api/collections"),
  getCollection: (id: number) =>
    req<{ collection: Collection; items: ItemSummary[] }>(`/api/collections/${id}`),
  createCollection: (name: string, query: string | null, itemIds: number[]) =>
    req<{ collection: Collection }>("/api/collections", {
      method: "POST",
      body: JSON.stringify({ name, query, item_ids: itemIds }),
    }),
  removeCollection: (id: number) => req<{ deleted: boolean }>(`/api/collections/${id}`, { method: "DELETE" }),
  addToCollection: (cid: number, itemId: number) =>
    req<{ collection: Collection }>(`/api/collections/${cid}/items`, {
      method: "POST",
      body: JSON.stringify({ item_id: itemId }),
    }),
  removeFromCollection: (cid: number, itemId: number) =>
    req<{ collection: Collection }>(`/api/collections/${cid}/items/${itemId}`, { method: "DELETE" }),
};
