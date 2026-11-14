/**
 * Grouping X posts into readable sections: by day (default), by theme, or by tag.
 * Pure functions so the stream component stays presentational and tests are simple.
 */
import type { XPost } from "./types";

export type Grouping = "date" | "theme" | "tag";

export interface PostGroup {
  key: string;
  label: string;
  posts: XPost[];
}

export const UNSORTED = "Not yet sorted";
export const UNTAGGED = "Untagged";

/** A post's timestamp as a Date (server stores UTC without a zone suffix). */
export function postDate(p: XPost): Date {
  const raw = p.published_at ?? p.date_saved;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : raw.replace(" ", "T") + "Z");
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function dayLabel(d: Date, now: Date = new Date()): string {
  const today = dayKey(now);
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  const key = dayKey(d);
  if (key === today) return "Today";
  if (key === dayKey(y)) return "Yesterday";
  const opts: Intl.DateTimeFormatOptions = { weekday: "long", month: "short", day: "numeric" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(undefined, opts);
}

/** Posts are expected newest-first; groups keep that order internally. */
export function groupPosts(posts: XPost[], by: Grouping, now: Date = new Date()): PostGroup[] {
  const groups = new Map<string, PostGroup>();
  const add = (key: string, label: string, p: XPost) => {
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { key, label, posts: [] }));
    g.posts.push(p);
  };

  for (const p of posts) {
    if (by === "date") {
      const d = postDate(p);
      add(dayKey(d), dayLabel(d, now), p);
    } else if (by === "theme") {
      add(p.theme ?? UNSORTED, p.theme ?? UNSORTED, p);
    } else if (p.topics.length === 0) {
      add(UNTAGGED, UNTAGGED, p);
    } else {
      for (const t of p.topics) add(t, t, p); // a post with two tags appears under both
    }
  }

  const out = [...groups.values()];
  if (by === "date") return out; // already newest day first
  const fallback = by === "theme" ? UNSORTED : UNTAGGED;
  return out.sort((a, b) => {
    if (a.key === fallback) return 1;
    if (b.key === fallback) return -1;
    return b.posts.length - a.posts.length || a.label.localeCompare(b.label);
  });
}

export function timeLabel(p: XPost, by: Grouping): string {
  const d = postDate(p);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  // Under a date heading the day is implied; elsewhere show it.
  return by === "date" ? time : `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${time}`;
}
