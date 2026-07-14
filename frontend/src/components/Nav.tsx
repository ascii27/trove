import { useState, type ReactNode } from "react";
import type { Collection, Feed } from "../types";
import { AddFeed } from "./AddFeed";

interface Props {
  view: "all" | "unread" | "feed" | "collection" | "highlights" | "bookmarks";
  feedId: number | null;
  feeds: Feed[];
  collections: Collection[];
  collectionId: number | null;
  unreadCount: number;
  savedCount: number;
  lensActive: boolean;
  onSelectSaved: (v: "all" | "unread") => void;
  onSelectFeed: (id: number) => void;
  onSelectCollection: (id: number) => void;
  onDeleteCollection: (id: number) => void;
  onSelectHighlights: () => void;
  highlightCount: number;
  onSelectBookmarks: () => void;
  bookmarkCount: number;
  onSearch: () => void;
  onAddFeed: (url: string) => Promise<void>;
  onDeleteFeed: (id: number) => void;
  captureSlot: ReactNode;
}

export function Nav({
  view,
  feedId,
  feeds,
  collections,
  collectionId,
  unreadCount,
  savedCount,
  lensActive,
  onSelectSaved,
  onSelectFeed,
  onSelectCollection,
  onDeleteCollection,
  onSelectHighlights,
  highlightCount,
  onSelectBookmarks,
  bookmarkCount,
  onSearch,
  onAddFeed,
  onDeleteFeed,
  captureSlot,
}: Props) {
  const [confirmFeed, setConfirmFeed] = useState<number | null>(null);
  const [confirmCol, setConfirmCol] = useState<number | null>(null);
  const isActive = (v: "all" | "unread") => !lensActive && view === v;

  return (
    <aside className="nav">
      <div className="brand">
        <h1>Trove</h1>
        {captureSlot}
      </div>

      <button className={`nav-item nav-search ${lensActive ? "active" : ""}`} onClick={onSearch}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M21 21l-4.3-4.3" />
        </svg>
        <span>Search</span>
      </button>

      <div className="lane-label">Saved</div>
      <button
        className={`nav-item ${isActive("all") ? "active" : ""}`}
        onClick={() => onSelectSaved("all")}
        aria-current={isActive("all")}
      >
        <span>All saved</span>
        <span className="count">{savedCount}</span>
      </button>
      <button
        className={`nav-item ${isActive("unread") ? "active" : ""}`}
        onClick={() => onSelectSaved("unread")}
        aria-current={isActive("unread")}
      >
        <span>Unread</span>
        {unreadCount > 0 && <span className="count unread">{unreadCount}</span>}
      </button>
      <button
        className={`nav-item ${!lensActive && view === "highlights" ? "active" : ""}`}
        onClick={onSelectHighlights}
        aria-current={!lensActive && view === "highlights"}
      >
        <span>Highlights</span>
        {highlightCount > 0 && <span className="count">{highlightCount}</span>}
      </button>
      <button
        className={`nav-item ${!lensActive && view === "bookmarks" ? "active" : ""}`}
        onClick={onSelectBookmarks}
        aria-current={!lensActive && view === "bookmarks"}
      >
        <span>Bookmarks</span>
        {bookmarkCount > 0 && <span className="count">{bookmarkCount}</span>}
      </button>

      {collections.length > 0 && <div className="lane-label">Research collections</div>}
      {collections.map((c) => {
        const active = !lensActive && view === "collection" && collectionId === c.id;
        return (
          <div key={c.id} className={`nav-feed nav-sub ${active ? "active" : ""}`}>
            <button className="nav-item nav-feed-open" onClick={() => onSelectCollection(c.id)} aria-current={active}>
              <span className="dot research" aria-hidden="true" />
              <span className="nav-feed-title">{c.name}</span>
              <span className="count">{c.item_count}</span>
            </button>
            {confirmCol === c.id ? (
              <span className="feed-confirm">
                <button
                  className="danger"
                  onClick={() => {
                    onDeleteCollection(c.id);
                    setConfirmCol(null);
                  }}
                >
                  Delete
                </button>
                <button className="ghost-sm" onClick={() => setConfirmCol(null)}>
                  Cancel
                </button>
              </span>
            ) : (
              <button
                className="nav-feed-remove"
                aria-label={`Delete collection ${c.name}`}
                title="Delete collection"
                onClick={() => setConfirmCol(c.id)}
              >
                ×
              </button>
            )}
          </div>
        );
      })}

      <div className="lane-label feeds-label">
        <span>Feeds</span>
        <AddFeed onAddFeed={onAddFeed} />
      </div>
      {feeds.length === 0 && <div className="nav-hint">Add an RSS feed or a site URL.</div>}
      {feeds.map((f) => (
        <div key={f.id} className={`nav-feed ${!lensActive && view === "feed" && feedId === f.id ? "active" : ""}`}>
          <button
            className="nav-item nav-feed-open"
            onClick={() => onSelectFeed(f.id)}
            aria-current={!lensActive && view === "feed" && feedId === f.id}
          >
            <span className="dot" aria-hidden="true" />
            <span className="nav-feed-title">{f.title ?? f.url}</span>
            {f.unread_count > 0 && <span className="count unread">{f.unread_count}</span>}
          </button>
          {confirmFeed === f.id ? (
            <span className="feed-confirm">
              <button
                className="danger"
                onClick={() => {
                  onDeleteFeed(f.id);
                  setConfirmFeed(null);
                }}
              >
                Remove
              </button>
              <button className="ghost-sm" onClick={() => setConfirmFeed(null)}>
                Cancel
              </button>
            </span>
          ) : (
            <button
              className="nav-feed-remove"
              aria-label={`Unsubscribe from ${f.title ?? "feed"}`}
              title="Unsubscribe"
              onClick={() => setConfirmFeed(f.id)}
            >
              ×
            </button>
          )}
        </div>
      ))}
    </aside>
  );
}
