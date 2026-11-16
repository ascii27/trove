import { useEffect, useRef, useState } from "react";
import type { DiscoverKinds, DiscoverRun, DiscoverState, Suggestion } from "../types";

interface Props {
  state: DiscoverState | null;
  notice: string | null;
  onStart: (context: string, kinds: DiscoverKinds) => Promise<void>;
  onFollow: (s: Suggestion) => Promise<void>;
  onDismiss: (s: Suggestion) => Promise<void>;
  onBackToNav: () => void;
}

const KINDS: { key: DiscoverKinds; label: string }[] = [
  { key: "all", label: "Both" },
  { key: "blogs", label: "Blogs" },
  { key: "x", label: "People on X" },
];

function host(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function ago(utc: string, now: number): string {
  const t = Date.parse(utc.replace(" ", "T") + "Z");
  if (Number.isNaN(t)) return "";
  const min = Math.round((now - t) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(t).toLocaleDateString();
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** What a finished search did, in words — including why it found nothing. */
export function runOutcome(run: DiscoverRun): string {
  if (run.status === "running") return "Finding…";
  if (run.status === "failed") return run.error ?? "Failed. Try again.";
  if (run.found > 0) return plural(run.found, "new suggestion");
  if (run.proposed == null) return "Nothing new";
  if (run.proposed === 0) return "Claude didn't suggest anything. Try different wording.";
  if (!run.passed) return `None of the ${run.proposed} suggested had a working, recent feed or a valid handle.`;
  return `Nothing new: all ${run.passed} were already suggested or followed.`;
}

function runLabel(run: DiscoverRun): string {
  const what = run.context ? `“${run.context}”` : "From your interests";
  return run.kinds === "blogs" ? `${what} · Blogs` : run.kinds === "x" ? `${what} · People on X` : what;
}

function SuggestionCard({
  s,
  xConfigured,
  onFollow,
  onDismiss,
}: {
  s: Suggestion;
  xConfigured: boolean;
  onFollow: (s: Suggestion) => Promise<void>;
  onDismiss: (s: Suggestion) => Promise<void>;
}) {
  const [busy, setBusy] = useState<"follow" | "dismiss" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const isX = s.kind === "x";
  const followDisabled = isX && !xConfigured;

  async function act(kind: "follow" | "dismiss") {
    setBusy(kind);
    setErr(null);
    try {
      await (kind === "follow" ? onFollow(s) : onDismiss(s));
    } catch (e) {
      setErr((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <li className="disc-card">
      <div className="disc-card-head">
        <div className="disc-who">
          <span className="disc-name">{s.name}</span>
          {s.url && (
            <a className="disc-link" href={s.url} target="_blank" rel="noreferrer">
              {isX ? `@${s.handle}` : host(s.url)}
            </a>
          )}
        </div>
        <div className="disc-actions">
          <button
            className="disc-follow"
            disabled={busy != null || followDisabled}
            title={followDisabled ? "Connect X in Trove's settings to follow from here" : undefined}
            onClick={() => act("follow")}
          >
            {busy === "follow" ? (isX ? "Following…" : "Subscribing…") : isX ? "Follow" : "Subscribe"}
          </button>
          <button className="ghost-sm" disabled={busy != null} onClick={() => act("dismiss")}>
            Not for me
          </button>
        </div>
      </div>
      {s.description && <p className="disc-desc">{s.description}</p>}
      {s.reason && <p className="disc-reason">{s.reason}</p>}
      {s.topics.length > 0 && (
        <div className="bm-tags">
          {s.topics.map((t) => (
            <span key={t} className="bm-tag disc-topic">
              {t}
            </span>
          ))}
        </div>
      )}
      {err && <p className="capture-err">{err}</p>}
    </li>
  );
}

export function Discover({ state, notice, onStart, onFollow, onDismiss, onBackToNav }: Props) {
  const [context, setContext] = useState("");
  const [kinds, setKinds] = useState<DiscoverKinds>("all");
  const [startErr, setStartErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [onlyRun, setOnlyRun] = useState<number | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  // "Show N to review" sits at the bottom of the history; bring the filtered results into view.
  useEffect(() => {
    if (onlyRun != null) bodyRef.current?.scrollIntoView?.({ block: "start" });
  }, [onlyRun]);

  const run = state?.run ?? null;
  const runs = state?.runs ?? [];
  const running = starting || run?.status === "running";
  const allSuggestions = state?.suggestions ?? [];
  const shownRun = onlyRun != null ? runs.find((r) => r.id === onlyRun) ?? null : null;
  const suggestions = shownRun ? allSuggestions.filter((s) => s.run_id === shownRun.id) : allSuggestions;
  const now = Date.now();
  const blogs = suggestions.filter((s) => s.kind === "blog");
  const people = suggestions.filter((s) => s.kind === "x");
  const profile = state?.profile;
  const xConfigured = state?.x_configured ?? false;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStartErr(null);
    setStarting(true);
    setOnlyRun(null);
    try {
      await onStart(context.trim(), kinds);
    } catch (e2) {
      setStartErr((e2 as Error).message);
    } finally {
      setStarting(false);
    }
  }

  const basis =
    profile && (profile.topics.length > 0 || profile.feed_count > 0 || profile.x_count > 0)
      ? [
          profile.topics.length > 0 ? `${profile.topics.slice(0, 6).join(", ")}` : null,
          profile.feed_count > 0 ? `${profile.feed_count} feed${profile.feed_count === 1 ? "" : "s"}` : null,
          profile.x_count > 0 ? `${profile.x_count} ${profile.x_count === 1 ? "person" : "people"} on X` : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  return (
    <section className="list disc">
      <div className="list-head">
        <button className="list-back" onClick={onBackToNav} aria-label="Back to menu">
          ← Menu
        </button>
        <h2>Discover</h2>
        <div className="sub">
          {basis ? <>Suggestions shaped by {basis}.</> : "Tell Trove what you're into and it'll find writers to follow."}
        </div>

        <form className="disc-form" onSubmit={submit}>
          <label className="disc-label" htmlFor="disc-context">
            Anything specific? <span className="disc-optional">Optional</span>
          </label>
          <input
            id="disc-context"
            className="disc-input"
            type="text"
            maxLength={300}
            placeholder="e.g. I'm interested in natural wine"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            disabled={running}
          />
          <div className="disc-form-row">
            <div className="seg" role="group" aria-label="What to look for">
              {KINDS.map((k) => (
                <button
                  key={k.key}
                  type="button"
                  className={kinds === k.key ? "on" : ""}
                  aria-pressed={kinds === k.key}
                  onClick={() => setKinds(k.key)}
                  disabled={running}
                >
                  {k.label}
                </button>
              ))}
            </div>
            <button type="submit" className="disc-go" disabled={running}>
              {running ? "Finding…" : "Find suggestions"}
            </button>
          </div>
        </form>
        {running && (
          <p className="disc-progress" role="status">
            Finding writers{run?.context ? ` for “${run.context}”` : ""} and checking their feeds. This takes about a
            minute — you can keep reading meanwhile.
          </p>
        )}
        {!running && run?.status === "failed" && run.error && <div className="banner-error">{run.error}</div>}
        {startErr && <div className="banner-error">{startErr}</div>}
        {notice && <div className="notice">{notice}</div>}
      </div>

      <div className="disc-body" ref={bodyRef}>
        {shownRun && (
          <div className="disc-filter">
            <span>
              Showing {runLabel(shownRun)} · {suggestions.length} to review
            </span>
            <button className="ghost-sm" onClick={() => setOnlyRun(null)}>
              Show all
            </button>
          </div>
        )}
        {state == null ? null : suggestions.length === 0 ? (
          !running && (
            <div className="empty-state">
              <p className="empty-title">{shownRun ? "All reviewed" : "No suggestions waiting"}</p>
              <p className="empty-sub">
                {runs.length > 0
                  ? "Your recent searches are below. Try adding something specific above."
                  : "Find suggestions to see blogs and people picked for you."}
              </p>
            </div>
          )
        ) : (
          <>
            {blogs.length > 0 && (
              <div className="disc-group">
                <h3 className="x-group-head">
                  Blogs <span className="x-group-count">{blogs.length}</span>
                </h3>
                <ul className="disc-list">
                  {blogs.map((s) => (
                    <SuggestionCard key={s.id} s={s} xConfigured={xConfigured} onFollow={onFollow} onDismiss={onDismiss} />
                  ))}
                </ul>
              </div>
            )}
            {people.length > 0 && (
              <div className="disc-group">
                <h3 className="x-group-head">
                  People on X <span className="x-group-count">{people.length}</span>
                </h3>
                {!xConfigured && (
                  <p className="disc-hint">X isn't connected, so you can open these profiles but not follow them here.</p>
                )}
                <ul className="disc-list">
                  {people.map((s) => (
                    <SuggestionCard key={s.id} s={s} xConfigured={xConfigured} onFollow={onFollow} onDismiss={onDismiss} />
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        {runs.length > 0 && (
          <div className="disc-group">
            <h3 className="x-group-head">Recent searches</h3>
            <ul className="disc-runs">
              {runs.map((r) => {
                const left = allSuggestions.filter((s) => s.run_id === r.id).length;
                const outcome = runOutcome(r);
                return (
                  <li key={r.id} className={`disc-run disc-run--${r.status}`}>
                    <div className="disc-run-main">
                      <span className="disc-run-label">{runLabel(r)}</span>
                      <span className="disc-run-time">{ago(r.created_at, now)}</span>
                    </div>
                    <div className="disc-run-outcome">
                      {r.status === "running" && <span className="disc-dot" aria-hidden="true" />}
                      {outcome}
                      {r.found > 0 && left > 0 && (
                        <button className="disc-run-show" onClick={() => setOnlyRun(r.id)}>
                          Show {left} to review
                        </button>
                      )}
                      {r.found > 0 && left === 0 && " · all reviewed"}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
