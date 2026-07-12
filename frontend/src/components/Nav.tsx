import type { ReactNode } from "react";

interface Props {
  view: "all" | "unread";
  unreadCount: number;
  savedCount: number;
  onSelectView: (v: "all" | "unread") => void;
  captureSlot: ReactNode;
}

export function Nav({ view, unreadCount, savedCount, onSelectView, captureSlot }: Props) {
  return (
    <aside className="nav">
      <div className="brand">
        <h1>Trove</h1>
        {captureSlot}
      </div>
      <div className="lane-label">Saved</div>
      <button
        className={`nav-item ${view === "all" ? "active" : ""}`}
        onClick={() => onSelectView("all")}
        aria-current={view === "all"}
      >
        <span>All saved</span>
        <span className="count">{savedCount}</span>
      </button>
      <button
        className={`nav-item ${view === "unread" ? "active" : ""}`}
        onClick={() => onSelectView("unread")}
        aria-current={view === "unread"}
      >
        <span>Unread</span>
        {unreadCount > 0 && <span className="count unread">{unreadCount}</span>}
      </button>
    </aside>
  );
}
