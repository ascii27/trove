import { useState } from "react";
import type { ItemSummary } from "../types";
import { LensBar } from "./LensBar";

interface Props {
  items: ItemSummary[];
  view: "all" | "unread" | "feed" | "collection" | "highlights" | "bookmarks";
  feedTitle: string | null;
  collectionInfo: { id: number; name: string; count: number } | null;
  loaded: boolean;
  selectedId: number | null;
  notice: string | null;
  error: string | null;
  lensQuery: string;
  onLensChange: (q: string) => void;
  lensFocusTick: number;
  lensInfo: { savedCount: number; feedCount: number } | null;
  onSaveAsCollection: (name: string) => Promise<void>;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onRemoveFromCollection: (collectionId: number, itemId: number) => void;
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

/** The "＋ Save as collection" control shown while a lens is active. */
function SaveAsCollection({ defaultName, onSave }: { defaultName: string; onSave: (name: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(defaultName);
  const [busy, setBusy] = useState(false);

  if (!open) {
    return (
      <button
        className="savecoll"
        onClick={() => {
          setName(defaultName);
          setOpen(true);
        }}
      >
        ＋ Save as collection
      </button>
    );
  }
  return (
    <form
      className="savecoll-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!name.trim()) return;
        setBusy(true);
        try {
          await onSave(name.trim());
          setOpen(false);
        } finally {
          setBusy(false);
        }
      }}
    >
      <input autoFocus value={name} onChange={(e) => setName(e.target.value)} aria-label="Collection name" />
      <div className="capture-row">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function List({
  items,
  view,
  feedTitle,
  collectionInfo,
  loaded,
  selectedId,
  notice,
  error,
  lensQuery,
  onLensChange,
  lensFocusTick,
  lensInfo,
  onSaveAsCollection,
  onSelect,
  onDelete,
  onRemoveFromCollection,
  onBackToNav,
}: Props) {
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const crossLane = lensInfo != null || collectionInfo != null; // show origin tags

  const viewTitle =
    collectionInfo != null
      ? collectionInfo.name
      : view === "feed"
      ? feedTitle ?? "Feed"
      : view === "unread"
      ? "Unread"
      : "All saved";
  const viewSub =
    collectionInfo != null
      ? `Research collection · ${collectionInfo.count} ${collectionInfo.count === 1 ? "source" : "sources"}`
      : view === "feed"
      ? "Streamed in"
      : view === "unread"
      ? "Saved and not yet read"
      : "Things you chose to keep";

  return (
    <section className="list">
      <div className="list-head">
        <button className="list-back" onClick={onBackToNav} aria-label="Back to menu">
          ← Menu
        </button>
        <LensBar value={lensQuery} onChange={onLensChange} focusTick={lensFocusTick} />
        {lensInfo ? (
          <>
            <h2>
              Reading about <span className="lens-term">{lensQuery.trim()}</span>
            </h2>
            <div className="sub">
              {items.length} across your library · {lensInfo.savedCount} saved, {lensInfo.feedCount} from feeds
            </div>
            <SaveAsCollection defaultName={lensQuery.trim()} onSave={onSaveAsCollection} />
          </>
        ) : (
          <>
            <h2>{viewTitle}</h2>
            <div className="sub">{viewSub}</div>
          </>
        )}
        {notice && <div className="notice">{notice}</div>}
        {error && <div className="banner-error">{error}</div>}
      </div>

      {loaded && items.length === 0 && lensInfo ? (
        <div className="empty-state">
          <p className="empty-title">Nothing matches “{lensQuery.trim()}”.</p>
          <p className="empty-sub">Try a broader interest, or clear the search.</p>
        </div>
      ) : loaded && items.length === 0 && collectionInfo ? (
        <div className="empty-state">
          <p className="empty-title">No sources yet.</p>
          <p className="empty-sub">Open an article and use “Add to collection” to gather sources here.</p>
        </div>
      ) : loaded && items.length === 0 ? (
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
                    {crossLane && (
                      <span className={`lane-tag ${i.lane === "saved" ? "lane-saved" : "lane-feed"}`}>
                        {i.lane === "saved" ? "Saved" : "Feed"}
                      </span>
                    )}
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
                        if (collectionInfo) onRemoveFromCollection(collectionInfo.id, i.id);
                        else onDelete(i.id);
                        setConfirmId(null);
                      }}
                    >
                      {collectionInfo ? "Remove" : "Delete"}
                    </button>
                    <button className="ghost-sm" onClick={() => setConfirmId(null)}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    className="card-delete"
                    aria-label={`${collectionInfo ? "Remove" : "Delete"} ${i.title ?? "item"}`}
                    onClick={() => setConfirmId(i.id)}
                  >
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
