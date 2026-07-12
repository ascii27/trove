import type { ItemSummary } from "../types";

interface Props {
  items: ItemSummary[];
  view: "all" | "unread";
  loaded: boolean;
  selectedId: number | null;
  notice: string | null;
  error: string | null;
  onSelect: (id: number) => void;
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
    return <div className="snippet failed">Couldn't extract this page — open it to retry.</div>;
  }
  if (i.extraction_status === "pending" || i.extraction_status === "extracting") {
    return <div className="snippet muted">Extracting the article…</div>;
  }
  if (i.summary) {
    return <div className="snippet">{i.summary}</div>;
  }
  return <div className="snippet muted">Analyzing…</div>;
}

export function List({ items, view, loaded, selectedId, notice, error, onSelect }: Props) {
  const title = view === "unread" ? "Unread" : "All saved";
  const subtitle = view === "unread" ? "Saved and not yet read" : "Things you chose to keep";

  return (
    <section className="list">
      <div className="list-head">
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
        ) : (
          <div className="empty-state">
            <p className="empty-title">Your library is empty.</p>
            <p className="empty-sub">Paste a URL with “+ URL” to save your first article.</p>
          </div>
        )
      ) : (
        <div className="cards">
          {items.map((i) => (
            <button
              key={i.id}
              className={`card ${i.read_state === "read" ? "read" : ""} ${selectedId === i.id ? "selected" : ""}`}
              onClick={() => onSelect(i.id)}
              aria-label={i.title ?? "Untitled item"}
            >
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
          ))}
        </div>
      )}
    </section>
  );
}
