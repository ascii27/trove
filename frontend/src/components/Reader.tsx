import type { ReactNode } from "react";
import { renderMarkdown } from "../render";
import type { ItemFull } from "../types";

interface Props {
  item: ItemFull | null;
  highlightTopics: string[];
  onMarkUnread: (id: number) => void;
  onRetry: (id: number) => void;
  onBack: () => void;
  onSave: (id: number) => void;
}

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

export function Reader({ item, highlightTopics, onMarkUnread, onRetry, onBack, onSave }: Props) {
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
            <div className="prose" dangerouslySetInnerHTML={{ __html: renderMarkdown(item.content_text) }} />
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
    </section>
  );
}
