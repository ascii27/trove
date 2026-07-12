import { useState, type ReactNode } from "react";
import type { Feed } from "../types";
import { AddFeed } from "./AddFeed";

interface Props {
  view: "all" | "unread" | "feed";
  feedId: number | null;
  feeds: Feed[];
  unreadCount: number;
  savedCount: number;
  onSelectSaved: (v: "all" | "unread") => void;
  onSelectFeed: (id: number) => void;
  onAddFeed: (url: string) => Promise<void>;
  onDeleteFeed: (id: number) => void;
  captureSlot: ReactNode;
}

export function Nav({
  view,
  feedId,
  feeds,
  unreadCount,
  savedCount,
  onSelectSaved,
  onSelectFeed,
  onAddFeed,
  onDeleteFeed,
  captureSlot,
}: Props) {
  const [confirmFeed, setConfirmFeed] = useState<number | null>(null);

  return (
    <aside className="nav">
      <div className="brand">
        <h1>Trove</h1>
        {captureSlot}
      </div>

      <div className="lane-label">Saved</div>
      <button
        className={`nav-item ${view === "all" ? "active" : ""}`}
        onClick={() => onSelectSaved("all")}
        aria-current={view === "all"}
      >
        <span>All saved</span>
        <span className="count">{savedCount}</span>
      </button>
      <button
        className={`nav-item ${view === "unread" ? "active" : ""}`}
        onClick={() => onSelectSaved("unread")}
        aria-current={view === "unread"}
      >
        <span>Unread</span>
        {unreadCount > 0 && <span className="count unread">{unreadCount}</span>}
      </button>

      <div className="lane-label feeds-label">
        <span>Feeds</span>
        <AddFeed onAddFeed={onAddFeed} />
      </div>
      {feeds.length === 0 && <div className="nav-hint">Add an RSS feed or a site URL.</div>}
      {feeds.map((f) => (
        <div key={f.id} className={`nav-feed ${view === "feed" && feedId === f.id ? "active" : ""}`}>
          <button
            className="nav-item nav-feed-open"
            onClick={() => onSelectFeed(f.id)}
            aria-current={view === "feed" && feedId === f.id}
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
