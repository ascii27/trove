import { useEffect, useRef, useState, type ReactNode } from "react";
import { offsetsOf, paintHighlights } from "../highlights";
import { renderMarkdown } from "../render";
import type { Collection, ItemFull } from "../types";
import { CollectionPicker } from "./CollectionPicker";

interface Props {
  item: ItemFull | null;
  highlightTopics: string[];
  collections: Collection[];
  onMarkUnread: (id: number) => void;
  onRetry: (id: number) => void;
  onBack: () => void;
  onSave: (id: number) => void;
  onToggleCollection: (collectionId: number, itemId: number, isMember: boolean) => void;
  onCreateCollectionForItem: (name: string, itemId: number) => void;
  onAddHighlight: (itemId: number, sel: { quote: string; start: number; end: number }) => void;
  onRemoveHighlight: (hid: number) => void;
}

// Keep floating popovers clear of the sticky mobile back-bar.
const TOP_CLAMP = 52;

type Pending = { quote: string; start: number; end: number; x: number; y: number };
type Removing = { id: number; x: number; y: number };

const SOURCE_LABEL: Record<string, string> = {
  primary: "Primary",
  secondary: "Secondary",
  analysis: "Analysis",
};

function MetaPanel({ item, highlightTopics }: { item: ItemFull; highlightTopics: string[] }) {
  const en = item.enrichment_status;
  return (
    <aside className="side">
      {en === "pending" || en === "enriching" ? (
        <div className="side-analyzing">
          <span className="ai-badge">✦ Analyzing…</span>
          <p className="muted">Generating summary, topics, and key claims.</p>
        </div>
      ) : en === "failed" ? (
        <p className="muted">Couldn't generate metadata for this one. The article is still readable.</p>
      ) : (
        <>
          <div className="ai-badge">✦ Auto-generated</div>
          {item.summary && <p className="summary">{item.summary}</p>}
          {item.source_type && (
            <div className="field">
              <div className="k">Source type</div>
              <div className="v">
                <span className={`src-pill src-${item.source_type}`}>{SOURCE_LABEL[item.source_type]}</span>
              </div>
            </div>
          )}
          {item.claims.length > 0 && (
            <div className="field">
              <div className="k">Key claims</div>
              <ul className="claims">
                {item.claims.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          {item.topics.length > 0 && (
            <div className="field">
              <div className="k">Topics</div>
              <div className="tags">
                {item.topics.map((t) => (
                  <span key={t} className={highlightTopics.includes(t) ? "hit" : ""}>
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      <div className="divider" />
      {item.reading_minutes ? (
        <div className="field">
          <div className="k">Reading time</div>
          <div className="v">{item.reading_minutes} minutes</div>
        </div>
      ) : null}
      <div className="field">
        <div className="k">Original</div>
        <div className="v">
          <a href={item.original_url} target="_blank" rel="noopener noreferrer">
            {item.source ?? item.original_url}
          </a>
        </div>
      </div>
    </aside>
  );
}

export function Reader({
  item,
  highlightTopics,
  collections,
  onMarkUnread,
  onRetry,
  onBack,
  onSave,
  onToggleCollection,
  onCreateCollectionForItem,
  onAddHighlight,
  onRemoveHighlight,
}: Props) {
  const proseRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [removing, setRemoving] = useState<Removing | null>(null);

  const highlightsKey = (item?.highlights ?? [])
    .map((h) => `${h.id}:${h.start_offset}:${h.end_offset}`)
    .join(",");

  // Repaint highlights after each render. React leaves the prose DOM alone
  // while content_text is unchanged, so the marks persist between renders;
  // they get wiped (and repainted here) only when content or highlights change.
  useEffect(() => {
    const root = proseRef.current;
    if (root) paintHighlights(root, item?.highlights ?? []);
  }, [item?.id, item?.content_text, highlightsKey]);

  // Capture a text selection inside the article → offer to save it.
  useEffect(() => {
    const root = proseRef.current;
    if (!root) return;
    const onUp = (e: Event) => {
      if (popoverRef.current?.contains(e.target as Node)) return; // ignore taps on our button
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        setPending(null);
        setRemoving(null);
        return;
      }
      const range = sel.getRangeAt(0);
      const offs = offsetsOf(root, range);
      const quote = sel.toString();
      if (!offs || !quote.trim()) {
        setPending(null);
        setRemoving(null);
        return;
      }
      const rect = range.getBoundingClientRect();
      setRemoving(null);
      setPending({ ...offs, quote, x: rect.left + rect.width / 2, y: rect.top });
    };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchend", onUp);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchend", onUp);
    };
  }, [item?.id]);

  const savePending = () => {
    if (pending && item) onAddHighlight(item.id, { quote: pending.quote, start: pending.start, end: pending.end });
    setPending(null);
    window.getSelection()?.removeAllRanges();
  };

  // Clicking a painted highlight offers to remove it.
  const onProseClick = (e: React.MouseEvent) => {
    const mark = (e.target as HTMLElement).closest?.("mark.hl") as HTMLElement | null;
    if (!mark?.dataset.hlId) return;
    setPending(null);
    setRemoving({ id: Number(mark.dataset.hlId), x: e.clientX, y: e.clientY });
  };

  let content: ReactNode;

  if (!item) {
    content = <div className="reader-empty">Select something to read.</div>;
  } else if (item.extraction_status === "pending" || item.extraction_status === "extracting") {
    content = (
      <div className="reader-empty">
        <p>Extracting the article…</p>
        <p className="muted">This usually takes a moment.</p>
      </div>
    );
  } else if (item.extraction_status === "failed") {
    content = (
      <div className="reader-empty reader-failed">
        <p className="empty-title">We couldn't extract this page.</p>
        <p className="muted">{item.error_message ?? "The page couldn't be read."}</p>
        <div className="failed-actions">
          <button onClick={() => onRetry(item.id)}>Retry extraction</button>
          <a className="button-link" href={item.original_url} target="_blank" rel="noopener noreferrer">
            Open the original
          </a>
        </div>
      </div>
    );
  } else {
    content = (
      <>
        <article className="article">
          <div className="article-head">
            {item.category && <div className="eyebrow">{item.category}</div>}
            <div className="article-actions">
              {item.lane === "feed" && (
                <button className="save-btn" onClick={() => onSave(item.id)}>
                  Save to library
                </button>
              )}
              <CollectionPicker
                collections={collections}
                memberIds={item.collection_ids}
                onToggle={(cid, isMember) => onToggleCollection(cid, item.id, isMember)}
                onCreate={(name) => onCreateCollectionForItem(name, item.id)}
              />
              <button className="ghost mark-unread" onClick={() => onMarkUnread(item.id)}>
                Mark unread
              </button>
            </div>
          </div>
          <h1>{item.title ?? item.original_url}</h1>
          <div className="byline">
            {[
              item.author,
              item.source,
              item.publish_date,
              item.reading_minutes ? `${item.reading_minutes} min read` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
          {item.extraction_status === "partial" && (
            <div className="partial-banner">
              This capture looks partial (the page may be paywalled). Showing what we got —{" "}
              <a href={item.original_url} target="_blank" rel="noopener noreferrer">
                open the original
              </a>
              .
            </div>
          )}
          {item.content_text && (
            <div
              ref={proseRef}
              className="prose"
              onClick={onProseClick}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(item.content_text) }}
            />
          )}
        </article>
        <MetaPanel item={item} highlightTopics={highlightTopics} />
      </>
    );
  }

  return (
    <section className="reader">
      {item && (
        <button className="reader-back" onClick={onBack} aria-label="Back to the list">
          ← Back
        </button>
      )}
      {content}
      {pending && (
        <div
          ref={popoverRef}
          className="hl-pop"
          style={{ top: Math.max(pending.y - 44, TOP_CLAMP), left: pending.x }}
        >
          {/* preventDefault keeps the selection alive through the tap */}
          <button onPointerDown={(e) => e.preventDefault()} onClick={savePending}>
            ✦ Highlight
          </button>
        </div>
      )}
      {removing && (
        <div
          ref={popoverRef}
          className="hl-pop"
          style={{ top: Math.max(removing.y - 44, TOP_CLAMP), left: removing.x }}
        >
          <button
            className="danger"
            onClick={() => {
              onRemoveHighlight(removing.id);
              setRemoving(null);
            }}
          >
            Remove highlight
          </button>
        </div>
      )}
    </section>
  );
}
