import { useMemo, useState } from "react";
import { bookmarkPending, type Bookmark } from "../types";

interface Props {
  bookmarks: Bookmark[];
  loaded: boolean;
  onDelete: (id: number) => void;
  onAddTag: (id: number, name: string) => void;
  onRemoveTag: (id: number, name: string) => void;
  onBackToNav: () => void;
}

const TrashIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M3 6h18M8 6V4h8v2m-9 0v14a1 1 0 001 1h8a1 1 0 001-1V6M10 11v6M14 11v6" />
  </svg>
);

function Favicon({ bm }: { bm: Bookmark }) {
  const [failed, setFailed] = useState(false);
  const letter = (bm.source ?? bm.title ?? bm.original_url).replace(/^https?:\/\//, "").charAt(0).toUpperCase();
  if (failed || !bm.favicon_url) return <span className="bm-favicon bm-favicon-fallback">{letter || "•"}</span>;
  return <img className="bm-favicon" src={bm.favicon_url} alt="" onError={() => setFailed(true)} />;
}

function BookmarkCard({ bm, onDelete, onAddTag, onRemoveTag }: {
  bm: Bookmark;
  onDelete: (id: number) => void;
  onAddTag: (id: number, name: string) => void;
  onRemoveTag: (id: number, name: string) => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const [adding, setAdding] = useState(false);
  const [tag, setTag] = useState("");
  const host = bm.source ?? bm.original_url.replace(/^https?:\/\//, "").split("/")[0];

  return (
    <div className="card bm-card">
      <div className="bm-main">
        <Favicon bm={bm} />
        <div className="bm-body">
          <a className="bm-title" href={bm.original_url} target="_blank" rel="noopener noreferrer">
            {bm.title ?? bm.original_url}
          </a>
          <span className="meta">
            <span className="bm-site">{host}</span>
            <span>{new Date(bm.date_saved + "Z").toLocaleDateString()}</span>
          </span>
          {bookmarkPending(bm) ? (
            <span className="snippet muted">Fetching details…</span>
          ) : (
            bm.summary && <span className="snippet">{bm.summary}</span>
          )}
          <div className="bm-tags">
            {bm.topics.map((t) => (
              <span key={t} className="bm-tag">
                {t}
                <button className="bm-tag-x" aria-label={`Remove tag ${t}`} onClick={() => onRemoveTag(bm.id, t)}>
                  ×
                </button>
              </span>
            ))}
            {adding ? (
              <form
                className="bm-tag-add"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (tag.trim()) onAddTag(bm.id, tag.trim());
                  setTag("");
                  setAdding(false);
                }}
              >
                <input autoFocus value={tag} onChange={(e) => setTag(e.target.value)} aria-label="New tag"
                  onBlur={() => setAdding(false)} placeholder="tag…" />
              </form>
            ) : (
              <button className="bm-tag-add-btn" onClick={() => setAdding(true)}>
                + tag
              </button>
            )}
          </div>
        </div>
      </div>
      <div className="card-actions">
        {confirm ? (
          <>
            <button className="danger" onClick={() => { onDelete(bm.id); setConfirm(false); }}>
              Delete
            </button>
            <button className="ghost-sm" onClick={() => setConfirm(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button className="card-delete" aria-label={`Delete bookmark ${bm.title ?? ""}`} onClick={() => setConfirm(true)}>
            <TrashIcon />
          </button>
        )}
      </div>
    </div>
  );
}

export function BookmarksList({ bookmarks, loaded, onDelete, onAddTag, onRemoveTag, onBackToNav }: Props) {
  const [activeTag, setActiveTag] = useState<string | null>(null);

  const allTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const b of bookmarks) for (const t of b.topics) counts.set(t, (counts.get(t) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [bookmarks]);

  const shown = activeTag ? bookmarks.filter((b) => b.topics.includes(activeTag)) : bookmarks;

  return (
    <section className="list">
      <div className="list-head">
        <button className="list-back" onClick={onBackToNav} aria-label="Back to menu">
          ← Menu
        </button>
        <h2>Bookmarks</h2>
        <div className="sub">Links you keep — open in a new tab</div>
        {allTags.length > 0 && (
          <div className="bm-filter">
            <button className={`bm-filter-tag ${activeTag === null ? "on" : ""}`} onClick={() => setActiveTag(null)}>
              All
            </button>
            {allTags.map(([t, n]) => (
              <button
                key={t}
                className={`bm-filter-tag ${activeTag === t ? "on" : ""}`}
                onClick={() => setActiveTag(activeTag === t ? null : t)}
              >
                {t} <span className="bm-filter-count">{n}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {loaded && bookmarks.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No bookmarks yet.</p>
          <p className="empty-sub">Paste a URL with “+ URL” and choose “Bookmark” to keep a link here.</p>
        </div>
      ) : (
        <div className="cards">
          {shown.map((bm) => (
            <BookmarkCard key={bm.id} bm={bm} onDelete={onDelete} onAddTag={onAddTag} onRemoveTag={onRemoveTag} />
          ))}
        </div>
      )}
    </section>
  );
}
