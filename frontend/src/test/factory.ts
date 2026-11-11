import type { Bookmark, Feed, ItemFull, ItemSummary, XAccount, XPost } from "../types";

export function bookmark(over: Partial<Bookmark> = {}): Bookmark {
  return {
    id: 1,
    title: "ripgrep — fast recursive search",
    source: "github.com",
    original_url: "https://github.com/BurntSushi/ripgrep",
    date_saved: "2026-07-14 10:00:00",
    publish_date: null,
    favicon_url: "https://github.com/favicon.ico",
    summary: "A line-oriented search tool that respects gitignore.",
    topics: ["CLI", "search"],
    extraction_status: "extracted",
    enrichment_status: "done",
    ...over,
  };
}

export function feed(over: Partial<Feed> = {}): Feed {
  return {
    id: 1,
    url: "https://blog.pragmaticengineer.com/rss",
    site_url: "https://blog.pragmaticengineer.com",
    title: "Pragmatic Engineer",
    last_polled_at: "2026-07-12 10:00:00",
    last_error: null,
    unread_count: 3,
    ...over,
  };
}

export function summary(over: Partial<ItemSummary> = {}): ItemSummary {
  return {
    id: 1,
    lane: "saved",
    feed_id: null,
    title: "The anatomy of an internal developer platform",
    author: "Susanne Kaiser",
    source: "martinfowler.com",
    publish_date: "Mar 2026",
    word_count: 1200,
    reading_minutes: 6,
    original_url: "https://martinfowler.com/idp",
    date_saved: "2026-07-12 10:00:00",
    read_state: "unread",
    extraction_status: "extracted",
    enrichment_status: "done",
    summary: "Argues an IDP succeeds only when adoption is voluntary.",
    category: "essay",
    source_type: "analysis",
    error_message: null,
    ...over,
  };
}

export function full(over: Partial<ItemFull> = {}): ItemFull {
  return {
    ...summary(over),
    content_text: "## Section\n\nA platform is a product whose customers are engineers.",
    topics: ["AI", "platform engineering"],
    claims: ["Mandated platforms rot.", "Cognitive load predicts uptake."],
    collection_ids: [],
    highlights: [],
    ...over,
  };
}

export function xAccount(over: Partial<XAccount> = {}): XAccount {
  return {
    id: 1,
    handle: "jane",
    name: "Jane Doe",
    avatar_url: null,
    last_polled_at: "2026-11-11 10:00:00",
    last_error: null,
    unread_count: 2,
    ...over,
  };
}

export function xPost(over: Partial<XPost> = {}): XPost {
  return {
    id: 1,
    x_account_id: 1,
    post_id: "100",
    thread_len: 1,
    theme: "AI agents",
    title: "Agents need better evals",
    author: "Jane Doe",
    handle: "jane",
    avatar_url: null,
    original_url: "https://x.com/jane/status/100",
    published_at: "2026-11-11T09:00:00",
    date_saved: "2026-11-11 09:05:00",
    read_state: "unread",
    content_text: "Agents need better evals.",
    topics: [],
    highlights: [],
    ...over,
  };
}
