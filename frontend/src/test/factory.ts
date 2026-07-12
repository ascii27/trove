import type { ItemFull, ItemSummary } from "../types";

export function summary(over: Partial<ItemSummary> = {}): ItemSummary {
  return {
    id: 1,
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
    ...over,
  };
}
