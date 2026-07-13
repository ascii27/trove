import { useState } from "react";
import type { HighlightArchiveEntry } from "../types";

interface Props {
  highlights: HighlightArchiveEntry[];
  loaded: boolean;
  selectedItemId: number | null;
  onOpen: (itemId: number) => void;
  onRemove: (hid: number) => void;
  onBackToNav: () => void;
}

const TrashIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M3 6h18M8 6V4h8v2m-9 0v14a1 1 0 001 1h8a1 1 0 001-1V6M10 11v6M14 11v6" />
  </svg>
);

export function HighlightsList({ highlights, loaded, selectedItemId, onOpen, onRemove, onBackToNav }: Props) {
  const [confirmId, setConfirmId] = useState<number | null>(null);

  return (
    <section className="list">
      <div className="list-head">
        <button className="list-back" onClick={onBackToNav} aria-label="Back to menu">
          ← Menu
        </button>
        <h2>Highlights</h2>
        <div className="sub">Passages you saved while reading</div>
      </div>

      {loaded && highlights.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No highlights yet.</p>
          <p className="empty-sub">Select text while reading an article and tap “✦ Highlight” to save it here.</p>
        </div>
      ) : (
        <div className="cards">
          {highlights.map((h) => (
            <div key={h.id} className={`card quote-card ${selectedItemId === h.item_id ? "selected" : ""}`}>
              <button className="card-open" onClick={() => onOpen(h.item_id)} aria-label={`Open ${h.title ?? "the source"}`}>
                <span className="card-main">
                  <blockquote className="quote">{h.quote}</blockquote>
                  <span className="meta">
                    <span className="quote-source">{h.title ?? h.original_url}</span>
                    <span>{new Date(h.created_at + "Z").toLocaleDateString()}</span>
                  </span>
                </span>
              </button>
              <div className="card-actions">
                {confirmId === h.id ? (
                  <>
                    <button
                      className="danger"
                      onClick={() => {
                        onRemove(h.id);
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
                  <button className="card-delete" aria-label="Delete highlight" onClick={() => setConfirmId(h.id)}>
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
