export type ReadState = "unread" | "reading" | "read" | "archived";
export type Lane = "saved" | "feed";
export type ExtractionStatus = "pending" | "extracting" | "extracted" | "partial" | "failed" | "deferred";
export type EnrichmentStatus = "pending" | "enriching" | "done" | "failed";

export interface ItemSummary {
  id: number;
  lane: Lane;
  feed_id: number | null;
  title: string | null;
  author: string | null;
  source: string | null;
  publish_date: string | null;
  word_count: number | null;
  reading_minutes: number | null;
  original_url: string;
  date_saved: string;
  read_state: ReadState;
  extraction_status: ExtractionStatus;
  enrichment_status: EnrichmentStatus;
  summary: string | null;
  category: string | null;
  source_type: "primary" | "secondary" | "analysis" | null;
  error_message: string | null;
}

export interface Feed {
  id: number;
  url: string;
  site_url: string | null;
  title: string | null;
  last_polled_at: string | null;
  last_error: string | null;
  unread_count: number;
}

export interface ItemFull extends ItemSummary {
  content_text: string | null;
  topics: string[];
  claims: string[];
}

/** True while an item is actively being fetched/extracted/enriched — drives polling.
 * 'deferred' feed items are idle (they load on open), so they don't poll. */
export function isPending(i: ItemSummary): boolean {
  const ex = i.extraction_status;
  if (ex === "deferred") return false;
  const en = i.enrichment_status;
  const extracting = ex === "pending" || ex === "extracting";
  const enriching = ex !== "failed" && (en === "pending" || en === "enriching");
  return extracting || enriching;
}
