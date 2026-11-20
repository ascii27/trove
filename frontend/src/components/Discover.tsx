import { useEffect, useState } from "react";
import type { DiscoverKinds, DiscoverRun, DiscoverState, Suggestion } from "../types";

export interface RunResults {
  run: DiscoverRun;
  suggestions: Suggestion[];
}

interface Props {
  state: DiscoverState | null;
  notice: string | null;
  onStart: (context: string, kinds: DiscoverKinds) => Promise<void>;
  onLoadRun: (id: number) => Promise<RunResults>;
  /** Each returns the suggestion as it now stands (followed / dismissed / new again). */
  onFollow: (s: Suggestion) => Promise<Suggestion>;
  onDismiss: (s: Suggestion) => Promise<Suggestion>;
  onRestore: (s: Suggestion) => Promise<Suggestion>;
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
  return new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** What a finished search did, in words — including why it found nothing. */
export function runOutcome(run: DiscoverRun): string {
  if (run.status === "running") return "Finding…";
  if (run.status === "failed") return run.error ?? "Failed. Try again.";
  if (run.found > 0) return `Found ${plural(run.found, "new suggestion")}`;
  if (run.proposed == null) return "Nothing new";
  if (run.proposed === 0) return "Claude didn't suggest anything. Try different wording.";
  if (!run.passed) return `None of the ${run.proposed} suggested had a working, recent feed or a valid handle.`;
  return `Nothing new: all ${run.passed} were already suggested or followed.`;
}

export function runLabel(run: DiscoverRun): string {
  return run.context ? `“${run.context}”` : "From your interests";
}

function kindsLabel(run: DiscoverRun): string | null {
  return run.kinds === "blogs" ? "Blogs" : run.kinds === "x" ? "People on X" : null;
}

function SuggestionCard({
  s,
  xConfigured,
  onFollow,
  onDismiss,
  onRestore,
}: {
  s: Suggestion;
  xConfigured: boolean;
  onFollow: (s: Suggestion) => Promise<void>;
  onDismiss: (s: Suggestion) => Promise<void>;
  onRestore: (s: Suggestion) => Promise<void>;
}) {
  const [busy, setBusy] = useState<"follow" | "dismiss" | "restore" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const isX = s.kind === "x";
  const followDisabled = isX && !xConfigured;

  async function act(kind: "follow" | "dismiss" | "restore") {
    setBusy(kind);
    setErr(null);
    try {
      await (kind === "follow" ? onFollow(s) : kind === "dismiss" ? onDismiss(s) : onRestore(s));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className={`disc-card disc-card--${s.status}`}>
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
          {s.status === "new" && (
            <>
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
            </>
          )}
          {s.status === "followed" && <span className="disc-badge">✓ {isX ? "Following" : "Subscribed"}</span>}
          {s.status === "dismissed" && (
            <>
              <span className="disc-badge disc-badge--muted">Not for me</span>
              <button className="ghost-sm" disabled={busy != null} onClick={() => act("restore")}>
                Undo
              </button>
            </>
          )}
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

type Filter = "review" | "all";

function Results({
  run,
  results,
  loading,
  xConfigured,
  onFollow,
  onDismiss,
  onRestore,
  onBack,
}: {
  run: DiscoverRun;
  results: RunResults | null;
  loading: boolean;
  xConfigured: boolean;
  onFollow: (s: Suggestion) => Promise<void>;
  onDismiss: (s: Suggestion) => Promise<void>;
  onRestore: (s: Suggestion) => Promise<void>;
  onBack: () => void;
}) {
  const all = results?.run.id === run.id ? results.suggestions : [];
  const toReview = all.filter((s) => s.status === "new");
  const [filter, setFilter] = useState<Filter>("review");
  // Cards you just followed or passed on stay put (showing their new status, with Undo)
  // until you switch filter or search, rather than vanishing from "To review".
  const [acted, setActed] = useState<Set<number>>(new Set());
  // Start on "To review" when there's something to review, otherwise show everything.
  // Re-pick when a running search finishes (it had nothing to review while running).
  useEffect(() => {
    setFilter(run.to_review > 0 ? "review" : "all");
    setActed(new Set());
  }, [run.id, run.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (f: Filter) => {
    setFilter(f);
    setActed(new Set());
  };
  const track =
    (fn: (s: Suggestion) => Promise<void>) =>
    async (s: Suggestion): Promise<void> => {
      await fn(s);
      setActed((prev) => new Set(prev).add(s.id));
    };
  const follow = track(onFollow);
  const dismiss = track(onDismiss);

  const shown = filter === "review" ? all.filter((s) => s.status === "new" || acted.has(s.id)) : all;
  const blogs = shown.filter((s) => s.kind === "blog");
  const people = shown.filter((s) => s.kind === "x");
  const card = (s: Suggestion) => (
    <SuggestionCard key={s.id} s={s} xConfigured={xConfigured} onFollow={follow} onDismiss={dismiss} onRestore={onRestore} />
  );

  return (
    <div className="disc-results" aria-label="Search results">
      <button className="disc-back" onClick={onBack}>
        ← All searches
      </button>
      <div className="disc-results-head">
        <h3 className="disc-results-title">{runLabel(run)}</h3>
        <p className="disc-results-meta">
          {kindsLabel(run) && <>{kindsLabel(run)} · </>}
          {ago(run.created_at, Date.now())} · {runOutcome(run)}
        </p>
        {all.length > 0 && (
          <div className="seg disc-filter-seg" role="group" aria-label="Show">
            <button className={filter === "review" ? "on" : ""} aria-pressed={filter === "review"} onClick={() => pick("review")}>
              To review ({toReview.length})
            </button>
            <button className={filter === "all" ? "on" : ""} aria-pressed={filter === "all"} onClick={() => pick("all")}>
              All ({all.length})
            </button>
          </div>
        )}
      </div>

      {run.status === "running" ? (
        <p className="disc-progress" role="status">
          Finding writers and checking their feeds. This takes about half a minute; you can keep reading meanwhile.
        </p>
      ) : run.status === "failed" ? (
        <div className="banner-error">{run.error ?? "This search failed. Try again."}</div>
      ) : loading && all.length === 0 ? (
        <p className="disc-hint">Loading…</p>
      ) : all.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing to show</p>
          <p className="empty-sub">{runOutcome(run)}</p>
        </div>
      ) : shown.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">All reviewed</p>
          <p className="empty-sub">
            You've followed or passed on everything from this search.{" "}
            <button className="disc-run-show" onClick={() => pick("all")}>
              Show all {all.length}
            </button>
          </p>
        </div>
      ) : (
        <>
          {blogs.length > 0 && (
            <div className="disc-group">
              <h4 className="x-group-head">
                Blogs <span className="x-group-count">{blogs.length}</span>
              </h4>
              <ul className="disc-list">{blogs.map(card)}</ul>
            </div>
          )}
          {people.length > 0 && (
            <div className="disc-group">
              <h4 className="x-group-head">
                People on X <span className="x-group-count">{people.length}</span>
              </h4>
              {!xConfigured && (
                <p className="disc-hint">X isn't connected, so you can open these profiles but not follow them here.</p>
              )}
              <ul className="disc-list">{people.map(card)}</ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function Discover({ state, notice, onStart, onLoadRun, onFollow, onDismiss, onRestore, onBackToNav }: Props) {
  const [context, setContext] = useState("");
  const [kinds, setKinds] = useState<DiscoverKinds>("all");
  const [startErr, setStartErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  // The search whose results are open. null → the newest (desktop) / the list (phone).
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [openOnPhone, setOpenOnPhone] = useState(false);
  const [results, setResults] = useState<RunResults | null>(null);
  const [loading, setLoading] = useState(false);

  const runs = state?.runs ?? [];
  const running = starting || state?.run?.status === "running";
  const selected = runs.find((r) => r.id === selectedId) ?? runs[0] ?? null;
  const profile = state?.profile;
  const xConfigured = state?.x_configured ?? false;

  // Load the selected search's results; reload when it finishes or its counts change.
  const selKey = selected ? `${selected.id}:${selected.status}:${selected.to_review}:${selected.total}` : "";
  useEffect(() => {
    if (!selected || selected.status === "running") return;
    let live = true;
    setLoading(true);
    onLoadRun(selected.id)
      .then((r) => live && setResults(r))
      .catch(() => {})
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [selKey]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStartErr(null);
    setStarting(true);
    try {
      await onStart(context.trim(), kinds);
      setSelectedId(null); // follow the new search
      setOpenOnPhone(true);
      setContext("");
    } catch (e2) {
      setStartErr((e2 as Error).message);
    } finally {
      setStarting(false);
    }
  }

  // Card actions update the open results in place.
  const replace = (s: Suggestion) =>
    setResults((prev) => (prev ? { ...prev, suggestions: prev.suggestions.map((x) => (x.id === s.id ? s : x)) } : prev));
  const follow = async (s: Suggestion) => replace(await onFollow(s));
  const dismiss = async (s: Suggestion) => replace(await onDismiss(s));
  const restore = async (s: Suggestion) => replace(await onRestore(s));

  const basis =
    profile && (profile.topics.length > 0 || profile.feed_count > 0 || profile.x_count > 0)
      ? [
          profile.topics.length > 0 ? profile.topics.slice(0, 6).join(", ") : null,
          profile.feed_count > 0 ? plural(profile.feed_count, "feed") : null,
          profile.x_count > 0 ? `${profile.x_count} ${profile.x_count === 1 ? "person" : "people"} on X` : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  const now = Date.now();

  return (
    <section className={`list disc${openOnPhone ? " disc--results-open" : ""}`}>
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
        {startErr && <div className="banner-error">{startErr}</div>}
        {notice && <div className="notice">{notice}</div>}
      </div>

      {state != null && runs.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No searches yet</p>
          <p className="empty-sub">Find suggestions to see blogs and people picked for you. Your last 25 searches are kept here.</p>
        </div>
      ) : (
        <div className="disc-layout">
          <nav className="disc-searches" aria-label="Your searches">
            <h3 className="disc-searches-title">Searches</h3>
            <ul className="disc-runs">
              {runs.map((r) => {
                const active = selected?.id === r.id;
                return (
                  <li key={r.id}>
                    <button
                      className={`disc-run disc-run--${r.status}${active ? " active" : ""}`}
                      aria-current={active}
                      onClick={() => {
                        setSelectedId(r.id);
                        setOpenOnPhone(true);
                      }}
                    >
                      <span className="disc-run-main">
                        <span className="disc-run-label">{runLabel(r)}</span>
                        {r.to_review > 0 && <span className="count unread">{r.to_review}</span>}
                      </span>
                      <span className="disc-run-outcome">
                        {r.status === "running" && <span className="disc-dot" aria-hidden="true" />}
                        {kindsLabel(r) && <>{kindsLabel(r)} · </>}
                        {ago(r.created_at, now)} ·{" "}
                        {r.status === "done" && r.total > 0 ? plural(r.total, "result") : runOutcome(r)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          {selected && (
            <Results
              run={selected}
              results={results}
              loading={loading}
              xConfigured={xConfigured}
              onFollow={follow}
              onDismiss={dismiss}
              onRestore={restore}
              onBack={() => setOpenOnPhone(false)}
            />
          )}
        </div>
      )}
    </section>
  );
}
