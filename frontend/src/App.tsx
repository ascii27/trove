import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Capture } from "./components/Capture";
import { Nav } from "./components/Nav";
import { List } from "./components/List";
import { Reader } from "./components/Reader";
import { isPending, type Feed, type ItemFull, type ItemSummary } from "./types";

type View = "all" | "unread" | "feed";

export default function App() {
  const [view, setView] = useState<View>("all");
  const [feedId, setFeedId] = useState<number | null>(null);
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [items, setItems] = useState<ItemSummary[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<ItemFull | null>(null);
  // Mobile drills nav → list → reader; listOpen tracks the first step (desktop ignores it).
  const [listOpen, setListOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const loadFeeds = useCallback(async () => {
    try {
      setFeeds((await api.feeds()).feeds);
    } catch {
      /* ignore */
    }
  }, []);

  const loadList = useCallback(async (v: View, fid: number | null) => {
    try {
      const res = await api.list(v, fid ?? undefined);
      setItems(res.items);
      setUnreadCount(res.unread_count);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadFeeds();
  }, [loadFeeds]);
  useEffect(() => {
    setLoaded(false);
    loadList(view, feedId);
  }, [view, feedId, loadList]);

  // Poll while anything visible is still extracting/enriching.
  const anyPending = items.some(isPending) || (selected != null && isPending(selected));
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => {
    if (!anyPending) return;
    const id = setInterval(async () => {
      await loadList(view, feedId);
      await loadFeeds();
      const cur = selectedRef.current;
      if (cur && isPending(cur)) {
        try {
          setSelected((await api.get(cur.id)).item);
        } catch {
          /* ignore transient */
        }
      }
    }, 2500);
    return () => clearInterval(id);
  }, [anyPending, view, feedId, loadList, loadFeeds]);

  const openItem = useCallback(
    async (id: number) => {
      setSelectedId(id);
      setNotice(null);
      try {
        const { item } = await api.get(id); // GET also triggers lazy-load for deferred feed items
        if (item.read_state === "unread") {
          const res = await api.markRead(id);
          setSelected(res.item);
          setUnreadCount(res.unread_count);
          setItems((prev) => prev.map((i) => (i.id === id ? { ...i, read_state: "read" } : i)));
          loadFeeds();
        } else {
          setSelected(item);
        }
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [loadFeeds]
  );

  const onCapture = useCallback(
    async (url: string) => {
      setNotice(null);
      const res = await api.capture(url);
      setView("all");
      setFeedId(null);
      await loadList("all", null);
      if (res.duplicate) setNotice("You've already saved that — here it is.");
      openItem(res.item.id);
    },
    [loadList, openItem]
  );

  const onAddFeed = useCallback(
    async (url: string) => {
      const res = await api.addFeed(url);
      await loadFeeds();
      setNotice(res.duplicate ? "You already follow that feed." : `Following ${res.feed.title ?? "the feed"}.`);
      setView("feed");
      setFeedId(res.feed.id);
    },
    [loadFeeds]
  );

  const onDeleteFeed = useCallback(
    async (id: number) => {
      await api.removeFeed(id);
      await loadFeeds();
      if (view === "feed" && feedId === id) {
        setView("all");
        setFeedId(null);
      }
    },
    [view, feedId, loadFeeds]
  );

  const onMarkUnread = useCallback(
    async (id: number) => {
      const res = await api.markUnread(id);
      setSelected(res.item);
      setUnreadCount(res.unread_count);
      setItems((prev) => prev.map((i) => (i.id === id ? { ...i, read_state: "unread" } : i)));
      loadFeeds();
    },
    [loadFeeds]
  );

  const onRetry = useCallback(
    async (id: number) => {
      const { item } = await api.retry(id);
      setSelected(item);
      await loadList(view, feedId);
    },
    [view, feedId, loadList]
  );

  const onSave = useCallback(
    async (id: number) => {
      const { item } = await api.save(id);
      setSelected(item);
      setNotice("Saved to your library.");
      await loadList(view, feedId);
      loadFeeds();
    },
    [view, feedId, loadList, loadFeeds]
  );

  const onDelete = useCallback(
    async (id: number) => {
      await api.remove(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
      setSelectedId((cur) => (cur === id ? null : cur));
      setSelected((cur) => (cur && cur.id === id ? null : cur));
      await loadList(view, feedId);
      loadFeeds();
    },
    [view, feedId, loadList, loadFeeds]
  );

  const onBack = useCallback(() => {
    setSelectedId(null);
    setSelected(null);
  }, []);

  const onBackToNav = useCallback(() => {
    setListOpen(false);
    setSelectedId(null);
    setSelected(null);
  }, []);

  // onCapture opens a reader item; make sure the mobile list is "entered" too.
  useEffect(() => {
    if (selectedId != null) setListOpen(true);
  }, [selectedId]);

  return (
    <div className={`app${listOpen ? " list-open" : ""}${selectedId != null ? " reading" : ""}`}>
      <Nav
        view={view}
        feedId={feedId}
        feeds={feeds}
        unreadCount={unreadCount}
        savedCount={view === "feed" ? feeds.find((f) => f.id === feedId)?.unread_count ?? 0 : items.length}
        onSelectSaved={(v) => {
          setView(v);
          setFeedId(null);
          setListOpen(true);
        }}
        onSelectFeed={(id) => {
          setView("feed");
          setFeedId(id);
          setListOpen(true);
        }}
        onAddFeed={onAddFeed}
        onDeleteFeed={onDeleteFeed}
        captureSlot={<Capture onCapture={onCapture} />}
      />
      <List
        items={items}
        view={view}
        feedTitle={view === "feed" ? feeds.find((f) => f.id === feedId)?.title ?? "Feed" : null}
        loaded={loaded}
        selectedId={selectedId}
        notice={notice}
        error={error}
        onSelect={openItem}
        onDelete={onDelete}
        onBackToNav={onBackToNav}
      />
      <Reader item={selected} onMarkUnread={onMarkUnread} onRetry={onRetry} onBack={onBack} onSave={onSave} />
    </div>
  );
}
