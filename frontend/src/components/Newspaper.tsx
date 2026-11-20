import { useState } from "react";
import type { Edition, PaperSchedule, PaperState, PaperStory } from "../types";

interface Props {
  state: PaperState | null;
  edition: Edition | null; // the issue on screen
  loadingEdition: boolean;
  onSelectEdition: (id: number) => void;
  onPrint: () => Promise<void>;
  onSaveSchedule: (schedule: PaperSchedule, hour: number) => Promise<void>;
  onOpenStory: (story: PaperStory) => void;
  onBackToNav: () => void;
}

const SCHEDULES: { key: PaperSchedule; label: string }[] = [
  { key: "off", label: "Off" },
  { key: "daily", label: "Daily" },
  { key: "weekdays", label: "Weekdays" },
  { key: "weekends", label: "Weekends" },
];

function utc(ts: string): Date {
  return new Date(ts.includes("T") ? (ts.endsWith("Z") ? ts : ts + "Z") : ts.replace(" ", "T") + "Z");
}

export function longDate(ts: string): string {
  return utc(ts).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

function shortDate(ts: string): string {
  return utc(ts).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function hourLabel(h: number): string {
  const d = new Date(2000, 0, 1, h);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function ago(ts: string | null): string | null {
  if (!ts) return null;
  const t = utc(ts).getTime();
  if (Number.isNaN(t)) return null;
  const h = Math.round((Date.now() - t) / 3600000);
  if (h < 1) return "just now";
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

function scheduleLabel(schedule: PaperSchedule, hour: number): string {
  if (schedule === "off") return "Not scheduled";
  const days = schedule === "daily" ? "Every day" : schedule === "weekdays" ? "Weekdays" : "Weekends";
  return `${days} at ${hourLabel(hour)}`;
}

function Picture({ src, className }: { src: string | null; className: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  return (
    <img
      className={className}
      src={src}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

function Byline({ story }: { story: PaperStory }) {
  const when = ago(story.published_at);
  return (
    <div className="np-byline">
      {story.source ?? story.author}
      {when && <span> · {when}</span>}
    </div>
  );
}

function StoryLink({ story, onOpen, children }: { story: PaperStory; onOpen: (s: PaperStory) => void; children: React.ReactNode }) {
  return (
    <a
      className="np-story-link"
      href={story.url}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return; // let modified clicks open the original
        e.preventDefault();
        onOpen(story);
      }}
    >
      {children}
    </a>
  );
}

function ScheduleControl({
  schedule,
  hour,
  onSave,
}: {
  schedule: PaperSchedule;
  hour: number;
  onSave: (schedule: PaperSchedule, hour: number) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  async function save(s: PaperSchedule, h: number) {
    setErr(null);
    try {
      await onSave(s, h);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="np-schedule">
      <button className="np-tool" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {scheduleLabel(schedule, hour)}
      </button>
      {open && (
        <div className="np-schedule-panel" role="group" aria-label="Print schedule">
          <div className="seg">
            {SCHEDULES.map((s) => (
              <button
                key={s.key}
                type="button"
                className={schedule === s.key ? "on" : ""}
                aria-pressed={schedule === s.key}
                onClick={() => save(s.key, hour)}
              >
                {s.label}
              </button>
            ))}
          </div>
          {schedule !== "off" && (
            <label className="np-hour">
              Ready by{" "}
              <select value={hour} onChange={(e) => save(schedule, Number(e.target.value))} aria-label="Ready by">
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {hourLabel(h)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <p className="np-hint">Times are in {tz.replace(/_/g, " ")}. A scheduled edition is skipped if there's too little new to print.</p>
          {err && <p className="capture-err">{err}</p>}
        </div>
      )}
    </div>
  );
}

function Lead({ story, onOpen }: { story: PaperStory; onOpen: (s: PaperStory) => void }) {
  return (
    <article className={`np-lead${story.image ? " has-image" : ""}`}>
      {story.image && (
        <StoryLink story={story} onOpen={onOpen}>
          <Picture src={story.image} className="np-lead-img" />
        </StoryLink>
      )}
      <div className="np-lead-text">
        <h2 className="np-lead-head">
          <StoryLink story={story} onOpen={onOpen}>
            {story.headline}
          </StoryLink>
        </h2>
        {story.summary && <p className="np-lead-summary">{story.summary}</p>}
        <Byline story={story} />
      </div>
    </article>
  );
}

function Section({ name, stories, onOpen }: { name: string; stories: PaperStory[]; onOpen: (s: PaperStory) => void }) {
  const [top, ...rest] = stories;
  return (
    <section className="np-section" aria-label={name}>
      <h3 className="np-section-name">{name}</h3>
      <article className="np-story np-story--top">
        {top.image && (
          <StoryLink story={top} onOpen={onOpen}>
            <Picture src={top.image} className="np-story-img" />
          </StoryLink>
        )}
        <h4 className="np-head">
          <StoryLink story={top} onOpen={onOpen}>
            {top.headline}
          </StoryLink>
        </h4>
        {top.summary && <p className="np-summary">{top.summary}</p>}
        <Byline story={top} />
      </article>
      {rest.map((s) => (
        <article key={s.item_id} className="np-story">
          <h4 className="np-head np-head--small">
            <StoryLink story={s} onOpen={onOpen}>
              {s.headline}
            </StoryLink>
          </h4>
          {s.summary && <p className="np-summary">{s.summary}</p>}
          <Byline story={s} />
        </article>
      ))}
    </section>
  );
}

export function Newspaper({
  state,
  edition,
  loadingEdition,
  onSelectEdition,
  onPrint,
  onSaveSchedule,
  onOpenStory,
  onBackToNav,
}: Props) {
  const [printErr, setPrintErr] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);
  const running = printing || state?.running != null;
  const done = (state?.editions ?? []).filter((e) => e.status === "done");
  // The most recent attempt failed (and nothing newer printed): say why.
  const lastAttempt = state?.editions[0];
  const failed = lastAttempt?.status === "failed" ? lastAttempt : null;
  const layout = edition?.layout ?? null;

  async function print() {
    setPrintErr(null);
    setPrinting(true);
    try {
      await onPrint();
    } catch (e) {
      setPrintErr((e as Error).message);
    } finally {
      setPrinting(false);
    }
  }

  const toolbar = (
    <div className="np-toolbar">
      <button className="list-back" onClick={onBackToNav} aria-label="Back to menu">
        ← Menu
      </button>
      {done.length > 0 && (
        <label className="np-issues">
          <span className="np-visually-hidden">Back issues</span>
          <select
            value={edition?.id ?? ""}
            onChange={(e) => onSelectEdition(Number(e.target.value))}
            aria-label="Back issues"
          >
            {done.map((e) => (
              <option key={e.id} value={e.id}>
                No. {e.number} · {shortDate(e.created_at)}
              </option>
            ))}
          </select>
        </label>
      )}
      <span className="np-toolbar-spacer" />
      {state && (
        <ScheduleControl schedule={state.settings.schedule} hour={state.settings.hour} onSave={onSaveSchedule} />
      )}
      <button className="np-tool np-print" onClick={print} disabled={running}>
        {running ? "Printing…" : "Print a new edition"}
      </button>
    </div>
  );

  const banners = (
    <>
      {running && (
        <p className="np-banner np-banner--busy" role="status">
          <span className="disc-dot" aria-hidden="true" />
          Printing a new edition from what's come in since the last one. It takes about half a minute.
        </p>
      )}
      {!running && failed && (
        <p className="np-banner np-banner--error">
          {failed.trigger === "schedule" ? "The scheduled edition" : "The last edition"} ({shortDate(failed.created_at)})
          wasn't printed: {failed.error}
        </p>
      )}
      {printErr && <p className="np-banner np-banner--error">{printErr}</p>}
    </>
  );

  if (state != null && done.length === 0) {
    return (
      <section className="list np">
        {toolbar}
        {banners}
        <div className="np-empty">
          <p className="np-masthead-title">The Trove</p>
          <p className="np-empty-sub">
            Your own morning paper, edited from your feeds, the people you follow on X and your reading list.
          </p>
          {!running && (
            <button className="np-tool np-print" onClick={print}>
              Print the first edition
            </button>
          )}
        </div>
      </section>
    );
  }

  return (
    <section className="list np">
      {toolbar}
      {banners}
      {edition && layout && (
        <div className={`np-paper${loadingEdition ? " is-loading" : ""}`}>
          <header className="np-masthead">
            <div className="np-masthead-meta">
              <span>No. {edition.number}</span>
              <span>{longDate(edition.created_at)}</span>
              <span>
                {edition.story_count} stories · {layout.source_count} sources
              </span>
            </div>
            <h1 className="np-masthead-title">The Trove</h1>
            {layout.editors_note && <p className="np-note">{layout.editors_note}</p>}
          </header>

          {layout.lead && <Lead story={layout.lead} onOpen={onOpenStory} />}

          {layout.sections.length > 0 && (
            <div className="np-sections">
              {layout.sections.map((sec) => (
                <Section key={sec.name} name={sec.name} stories={sec.stories} onOpen={onOpenStory} />
              ))}
            </div>
          )}

          {(layout.from_x.length > 0 || layout.from_shelf.length > 0) && (
            <div className="np-extras">
              {layout.from_x.length > 0 && (
                <aside className="np-box" aria-label="Overheard on X">
                  <h3 className="np-box-title">Overheard on X</h3>
                  {layout.from_x.map((s) => (
                    <div key={s.item_id} className="np-post">
                      <StoryLink story={s} onOpen={onOpenStory}>
                        <span className="np-post-who">{s.author ?? s.source}</span>
                      </StoryLink>
                      <p className="np-post-text">{s.summary}</p>
                    </div>
                  ))}
                </aside>
              )}
              {layout.from_shelf.length > 0 && (
                <aside className="np-box np-box--shelf" aria-label="From your reading list">
                  <h3 className="np-box-title">From your reading list</h3>
                  {layout.from_shelf.map((s) => (
                    <div key={s.item_id} className="np-post">
                      <h4 className="np-head np-head--small">
                        <StoryLink story={s} onOpen={onOpenStory}>
                          {s.headline}
                        </StoryLink>
                      </h4>
                      {s.summary && <p className="np-summary">{s.summary}</p>}
                      <Byline story={s} />
                    </div>
                  ))}
                </aside>
              )}
            </div>
          )}
          <footer className="np-footer">Edited for you by Trove · tap a headline to read it</footer>
        </div>
      )}
    </section>
  );
}
