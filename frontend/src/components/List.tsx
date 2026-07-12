import { useState } from "react";
import type { ItemSummary } from "../types";

interface Props {
  items: ItemSummary[];
  view: "all" | "unread" | "feed";
  feedTitle: string | null;
  loaded: boolean;
  selectedId: number | null;
  notice: string | null;
  error: string | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onBackToNav: () => void;
}

function metaBits(i: ItemSummary): string[] {
  const bits: string[] = [];
  if (i.source) bits.push(i.source);
  if (i.publish_date) bits.push(i.publish_date);
  else bits.push(new Date(i.date_saved + "Z").toLocaleDateString());
  if (i.reading_minutes) bits.push(`${i.reading_minutes} min`);
  return bits;
}

function cardBody(i: ItemSummary) {
  if (i.extraction_status === "failed") {
    return <span className="snippet failed">Couldn't extract this page — open it to retry.</span>;
  }
  if (i.extraction_status === "pending" || i.extraction_status === "extracting") {
    return <span className="snippet muted">Extracting the article…</span>;
  }
  if (i.summary) {
    return <span className="snippet">{i.summary}</span>;
  }
  if (i.extraction_status === "deferred") {
    return <span className="snippet muted">Open to load the full article.</span>;
  }
  return <span className="snippet muted">Analyzing…</span>;
}

const TrashIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M3 6h18M8 6V4h8v2m-9 0v14a1 1 0 001 1h8a1 1 0 001-1V6M10 11v6M14 11v6" />
  </svg>
);

export function List({ items, view, feedTitle, loaded, selectedId, notice, error, onSelect, onDelete, onBackToNav }: Props) {
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const title = view === "feed" ? feedTitle ?? "Feed" : view === "unread" ? "Unread" : "All saved";
  const subtitle =
    view === "feed" ? "Streamed in" : view === "unread" ? "Saved and not yet read" : "Things you chose to keep";

  return (
    <section className="list">
      <div className="list-head">
        <button className="list-back" onClick={onBackToNav} aria-label="Back to menu">
          ← Menu
        </button>
        <h2>{title}</h2>
        <div className="sub">{subtitle}</div>
        {notice && <div className="notice">{notice}</div>}
        {error && <div className="banner-error">{error}</div>}
      </div>

      {loaded && items.length === 0 ? (
        view === "unread" ? (
          <div className="empty-state">
            <p className="empty-title">You're all caught up.</p>
            <p className="empty-sub">Nothing unread. Nicely done.</p>
          </div>
        ) : view === "feed" ? (
          <div className="empty-state">
            <p className="empty-title">Nothing here yet.</p>
            <p className="empty-sub">New items will stream in as this feed publishes.</p>
          </div>
        ) : (
          <div className="empty-state">
            <p className="empty-title">Your library is empty.</p>
            <p className="empty-sub">Paste a URL with “+ URL” to save your first article.</p>
          </div>
        )
      ) : (
        <div className="cards">
          {items.map((i) => (
            <div key={i.id} className={`card ${i.read_state === "read" ? "read" : ""} ${selectedId === i.id ? "selected" : ""}`}>
              <button className="card-open" onClick={() => onSelect(i.id)} aria-label={i.title ?? "Untitled item"}>
                <span className="status" aria-hidden="true">
                  <span className="u" />
                </span>
                <span className="card-main">
                  <span className="card-title">{i.title ?? i.original_url}</span>
                  <span className="meta">
                    {metaBits(i).map((b, idx) => (
                      <span key={idx}>{b}</span>
                    ))}
                    {i.read_state === "unread" && <span className="unread-tag">Unread</span>}
                  </span>
                  {cardBody(i)}
                </span>
              </button>
              <div className="card-actions">
                {confirmId === i.id ? (
                  <>
                    <button
                      className="danger"
                      onClick={() => {
                        onDelete(i.id);
                        setConfirmId(null);
                      }}
                    >
                      Delete
                    </button>
                    <button className="ghost-sm" onClick={() => setConfirmId(null)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button className="card-delete" aria-label={`Delete ${i.title ?? "item"}`} onClick={() => setConfirmId(i.id)}>
                    <TrashIcon />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
