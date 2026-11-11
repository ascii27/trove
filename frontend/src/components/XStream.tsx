import { useEffect, useMemo, useRef, useState } from "react";
import { offsetsOf, paintHighlights } from "../highlights";
import { renderMarkdown } from "../render";
import type { XAccount, XPost, XStatus } from "../types";
import { groupPosts, timeLabel, type Grouping } from "../xgroup";

interface Props {
  posts: XPost[];
  account: XAccount | null; // null → all followed accounts
  status: XStatus | null;
  loaded: boolean;
  error: string | null;
  grouping: Grouping;
  onGroupingChange: (g: Grouping) => void;
  onMark: (ids: number[], state: "read" | "unread") => void;
  onAddTag: (id: number, name: string) => void;
  onRemoveTag: (id: number, name: string) => void;
  onSetTheme: (id: number, theme: string | null) => void;
  onAddHighlight: (id: number, sel: { quote: string; start: number; end: number }) => void;
  onRemoveHighlight: (hid: number) => void;
  onRefresh: (accountId: number) => Promise<void>;
  onBackToNav: () => void;
}

const GROUPINGS: { key: Grouping; label: string }[] = [
  { key: "date", label: "Date" },
  { key: "theme", label: "Theme" },
  { key: "tag", label: "Tag" },
];

const TOP_CLAMP = 52;

function Avatar({ src, name }: { src: string | null; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <span className="x-avatar x-avatar-fallback">{name.charAt(0).toUpperCase() || "•"}</span>;
  return <img className="x-avatar" src={src} alt="" onError={() => setFailed(true)} />;
}

function Prose({ post }: { post: XPost }) {
  const ref = useRef<HTMLDivElement>(null);
  const key = post.highlights.map((h) => `${h.id}:${h.start_offset}:${h.end_offset}`).join(",");
  const html = useMemo(() => renderMarkdown(post.content_text ?? ""), [post.content_text]);
  useEffect(() => {
    if (ref.current) paintHighlights(ref.current, post.highlights);
  }, [html, key, post.highlights]);
  return <div ref={ref} className="prose x-prose" data-item-id={post.id} dangerouslySetInnerHTML={{ __html: html }} />;
}

function TagRow({ post, onAdd, onRemove }: { post: XPost; onAdd: (n: string) => void; onRemove: (n: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [tag, setTag] = useState("");
  return (
    <div className="bm-tags">
      {post.topics.map((t) => (
        <span key={t} className="bm-tag">
          {t}
          <button className="bm-tag-x" aria-label={`Remove tag ${t}`} onClick={() => onRemove(t)}>
            ×
          </button>
        </span>
      ))}
      {adding ? (
        <form
          className="bm-tag-add"
          onSubmit={(e) => {
            e.preventDefault();
            if (tag.trim()) onAdd(tag.trim());
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
  );
}

function ThemePill({ post, themes, onSet }: { post: XPost; themes: string[]; onSet: (t: string | null) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(post.theme ?? "");
  if (editing) {
    return (
      <form
        className="x-theme-edit"
        onSubmit={(e) => {
          e.preventDefault();
          onSet(value.trim() || null);
          setEditing(false);
        }}
      >
        <input autoFocus list="x-themes" value={value} onChange={(e) => setValue(e.target.value)}
          onBlur={() => setEditing(false)} aria-label="Theme" placeholder="Theme (blank = auto)" />
        <datalist id="x-themes">
          {themes.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
      </form>
    );
  }
  return (
    <button
      className={`x-theme ${post.theme ? "" : "muted"}`}
      title="Change theme"
      onClick={() => {
        setValue(post.theme ?? "");
        setEditing(true);
      }}
    >
      {post.theme ?? "Sorting…"}
    </button>
  );
}

function PostCard(props: {
  post: XPost;
  grouping: Grouping;
  themes: string[];
  onMark: Props["onMark"];
  onAddTag: Props["onAddTag"];
  onRemoveTag: Props["onRemoveTag"];
  onSetTheme: Props["onSetTheme"];
}) {
  const { post, grouping, themes } = props;
  const unread = post.read_state === "unread";
  const name = post.author ?? `@${post.handle ?? ""}`;
  return (
    <article className={`x-post ${unread ? "unread" : ""}`}>
      <header className="x-post-head">
        <Avatar src={post.avatar_url} name={name} />
        <div className="x-post-who">
          <span className="x-name">{name}</span>
          <span className="meta">
            {post.handle && <span>@{post.handle}</span>}
            <a href={post.original_url} target="_blank" rel="noopener noreferrer" title="Open on X">
              {timeLabel(post, grouping)}
            </a>
            {(post.thread_len ?? 1) > 1 && <span className="x-thread">Thread · {post.thread_len} posts</span>}
          </span>
        </div>
        {grouping !== "theme" && (
          <ThemePill post={post} themes={themes} onSet={(t) => props.onSetTheme(post.id, t)} />
        )}
        <button
          className={`x-read-toggle ${unread ? "is-unread" : ""}`}
          aria-label={unread ? "Mark read" : "Mark unread"}
          title={unread ? "Mark read" : "Mark unread"}
          onClick={() => props.onMark([post.id], unread ? "read" : "unread")}
        />
      </header>
      <Prose post={post} />
      <TagRow post={post} onAdd={(n) => props.onAddTag(post.id, n)} onRemove={(n) => props.onRemoveTag(post.id, n)} />
    </article>
  );
}

type Pending = { itemId: number; quote: string; start: number; end: number; x: number; y: number };
type Removing = { id: number; x: number; y: number };

export function XStream(props: Props) {
  const { posts, account, status, loaded, error, grouping } = props;
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [removing, setRemoving] = useState<Removing | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const allTags = useMemo(() => {
    const counts = new Map<string, number>();
    for (const p of posts) for (const t of p.topics) counts.set(t, (counts.get(t) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [posts]);
  const themes = useMemo(() => [...new Set(posts.map((p) => p.theme).filter(Boolean) as string[])].sort(), [posts]);

  const shown = posts.filter(
    (p) => (!activeTag || p.topics.includes(activeTag)) && (!unreadOnly || p.read_state === "unread")
  );
  const groups = useMemo(() => groupPosts(shown, grouping), [shown, grouping]);
  const unreadIds = shown.filter((p) => p.read_state === "unread").map((p) => p.id);

  // A selection inside any post's prose offers "Highlight"; offsets are per post.
  useEffect(() => {
    const onUp = (e: Event) => {
      if (popRef.current?.contains(e.target as Node)) return;
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        setPending(null);
        setRemoving(null);
        return;
      }
      const range = sel.getRangeAt(0);
      const start = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement;
      const prose = start?.closest<HTMLElement>(".x-prose");
      if (!prose || !rootRef.current?.contains(prose)) return setPending(null);
      const offs = offsetsOf(prose, range);
      const quote = sel.toString();
      if (!offs || !quote.trim()) return setPending(null);
      const rect = range.getBoundingClientRect();
      setRemoving(null);
      setPending({ itemId: Number(prose.dataset.itemId), quote, ...offs, x: rect.left + rect.width / 2, y: rect.top });
    };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchend", onUp);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchend", onUp);
    };
  }, []);

  const onClick = (e: React.MouseEvent) => {
    const mark = (e.target as HTMLElement).closest?.("mark.hl") as HTMLElement | null;
    if (!mark?.dataset.hlId) return;
    setPending(null);
    setRemoving({ id: Number(mark.dataset.hlId), x: e.clientX, y: e.clientY });
  };

  const title = account ? account.name ?? `@${account.handle}` : "X";
  const notConfigured = status != null && !status.configured;

  return (
    <section className="list x-stream" ref={rootRef} onClick={onClick}>
      <div className="list-head">
        <button className="list-back" onClick={props.onBackToNav} aria-label="Back to menu">
          ← Menu
        </button>
        <div className="x-head-row">
          <div>
            <h2>{title}</h2>
            <div className="sub">
              {account ? `@${account.handle}` : "Posts from people you follow"}
              {unreadIds.length > 0 && ` · ${unreadIds.length} unread`}
            </div>
          </div>
          <div className="x-head-actions">
            {account && (
              <button
                className="ghost-sm"
                disabled={refreshing}
                onClick={async () => {
                  setRefreshing(true);
                  try {
                    await props.onRefresh(account.id);
                  } finally {
                    setRefreshing(false);
                  }
                }}
              >
                {refreshing ? "Checking…" : "Check for new posts"}
              </button>
            )}
            {unreadIds.length > 0 && (
              <button className="ghost-sm" onClick={() => props.onMark(unreadIds, "read")}>
                Mark all read
              </button>
            )}
          </div>
        </div>
        <div className="x-controls">
          <div className="seg" role="group" aria-label="Group posts by">
            {GROUPINGS.map((g) => (
              <button key={g.key} className={grouping === g.key ? "on" : ""} aria-pressed={grouping === g.key}
                onClick={() => props.onGroupingChange(g.key)}>
                {g.label}
              </button>
            ))}
          </div>
          <label className="x-unread-only">
            <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
            Unread only
          </label>
        </div>
        {allTags.length > 0 && (
          <div className="bm-filter">
            <button className={`bm-filter-tag ${activeTag === null ? "on" : ""}`} onClick={() => setActiveTag(null)}>
              All
            </button>
            {allTags.map(([t, n]) => (
              <button key={t} className={`bm-filter-tag ${activeTag === t ? "on" : ""}`}
                onClick={() => setActiveTag(activeTag === t ? null : t)}>
                {t} <span className="bm-filter-count">{n}</span>
              </button>
            ))}
          </div>
        )}
        {account?.last_error && <div className="banner-error">Last check failed: {account.last_error}</div>}
        {error && <div className="banner-error">{error}</div>}
      </div>

      {notConfigured ? (
        <div className="empty-state">
          <p className="empty-title">Connect X to start following people.</p>
          <p className="empty-sub">{status?.message}</p>
        </div>
      ) : loaded && posts.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No posts yet.</p>
          <p className="empty-sub">
            {account ? "New posts appear here as they're published." : "Follow someone with “+ Follow” to read their posts here."}
          </p>
        </div>
      ) : loaded && shown.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">Nothing matches.</p>
          <p className="empty-sub">Clear the tag filter or turn off “Unread only.”</p>
        </div>
      ) : (
        <div className="x-groups">
          {groups.map((g) => {
            const groupUnread = g.posts.filter((p) => p.read_state === "unread").map((p) => p.id);
            return (
              <section key={g.key} className="x-group" aria-label={g.label}>
                <h3 className="x-group-head">
                  <span>{g.label}</span>
                  <span className="x-group-count">{g.posts.length}</span>
                  {groupUnread.length > 0 && (
                    <button className="x-group-read" onClick={() => props.onMark(groupUnread, "read")}>
                      Mark read
                    </button>
                  )}
                </h3>
                {g.posts.map((p) => (
                  <PostCard key={`${g.key}:${p.id}`} post={p} grouping={grouping} themes={themes}
                    onMark={props.onMark} onAddTag={props.onAddTag} onRemoveTag={props.onRemoveTag}
                    onSetTheme={props.onSetTheme} />
                ))}
              </section>
            );
          })}
        </div>
      )}

      {pending && (
        <div ref={popRef} className="hl-pop" style={{ top: Math.max(pending.y - 44, TOP_CLAMP), left: pending.x }}>
          <button
            onPointerDown={(e) => e.preventDefault()}
            onClick={() => {
              props.onAddHighlight(pending.itemId, { quote: pending.quote, start: pending.start, end: pending.end });
              setPending(null);
              window.getSelection()?.removeAllRanges();
            }}
          >
            ✦ Highlight
          </button>
        </div>
      )}
      {removing && (
        <div ref={popRef} className="hl-pop" style={{ top: Math.max(removing.y - 44, TOP_CLAMP), left: removing.x }}>
          <button
            className="danger"
            onClick={(e) => {
              e.stopPropagation();
              props.onRemoveHighlight(removing.id);
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
