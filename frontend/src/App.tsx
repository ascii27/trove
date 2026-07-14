import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LensResponse } from "./api";
import { Capture } from "./components/Capture";
import { Nav } from "./components/Nav";
import { List } from "./components/List";
import { HighlightsList } from "./components/HighlightsList";
import { BookmarksList } from "./components/BookmarksList";
import { Reader } from "./components/Reader";
import {
  bookmarkPending,
  isPending,
  type Bookmark,
  type Collection,
  type Feed,
  type HighlightArchiveEntry,
  type ItemFull,
  type ItemSummary,
} from "./types";

type View = "all" | "unread" | "feed" | "collection" | "highlights" | "bookmarks";

export default function App() {
  const [view, setView] = useState<View>("all");
  const [feedId, setFeedId] = useState<number | null>(null);
  const [feeds, setFeeds] = useState<Feed[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionId, setCollectionId] = useState<number | null>(null);
  const [collectionName, setCollectionName] = useState<string>("");
  const [highlightsArchive, setHighlightsArchive] = useState<HighlightArchiveEntry[]>([]);
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [items, setItems] = useState<ItemSummary[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<ItemFull | null>(null);
  // Mobile drills nav → list → reader; listOpen tracks the first step (desktop ignores it).
  const [listOpen, setListOpen] = useState(false);
  // Lens: a live "read about X" query that overrides the current view across both lanes.
  const [lensQuery, setLensQuery] = useState("");
  const [lensResults, setLensResults] = useState<LensResponse | null>(null);
  const [matchedTopics, setMatchedTopics] = useState<string[]>([]);
  const [lensFocusTick, setLensFocusTick] = useState(0);
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

  const loadCollections = useCallback(async () => {
    try {
      setCollections((await api.collections()).collections);
    } catch {
      /* ignore */
    }
  }, []);

  const loadHighlights = useCallback(async () => {
    try {
      setHighlightsArchive((await api.highlights()).highlights);
    } catch {
      /* ignore */
    }
  }, []);

  const loadBookmarks = useCallback(async () => {
    try {
      setBookmarks((await api.bookmarks()).bookmarks);
    } catch {
      /* ignore */
    }
  }, []);

  const loadCurrent = useCallback(
    async (v: View, fid: number | null, cid: number | null) => {
      try {
        if (v === "collection" && cid != null) {
          const res = await api.getCollection(cid);
          setItems(res.items);
          setCollectionName(res.collection.name);
        } else {
          const res = await api.list(v as "all" | "unread" | "feed", fid ?? undefined);
          setItems(res.items);
          setUnreadCount(res.unread_count);
        }
        setLoaded(true);
      } catch (e) {
        setError((e as Error).message);
      }
    },
    []
  );

  const reloadCurrent = useCallback(
    () => loadCurrent(view, feedId, collectionId),
    [loadCurrent, view, feedId, collectionId]
  );

  // Debounced lens query. Empty query → no lens (show the current view).
  useEffect(() => {
    const q = lensQuery.trim();
    if (!q) {
      setLensResults(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        setLensResults(await api.lens(q));
      } catch (e) {
        setError((e as Error).message);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [lensQuery]);

  useEffect(() => {
    loadFeeds();
    loadCollections();
    loadHighlights();
    loadBookmarks();
  }, [loadFeeds, loadCollections, loadHighlights, loadBookmarks]);
  useEffect(() => {
    setLoaded(false);
    if (view === "highlights") {
      loadHighlights().then(() => setLoaded(true));
    } else if (view === "bookmarks") {
      loadBookmarks().then(() => setLoaded(true));
    } else {
      loadCurrent(view, feedId, collectionId);
    }
  }, [view, feedId, collectionId, loadCurrent, loadHighlights, loadBookmarks]);

  // Poll while anything visible is still extracting/enriching.
  const anyPending =
    items.some(isPending) || (selected != null && isPending(selected)) || bookmarks.some(bookmarkPending);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => {
    if (!anyPending) return;
    const id = setInterval(async () => {
      await reloadCurrent();
      await loadFeeds();
      await loadBookmarks();
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
  }, [anyPending, reloadCurrent, loadFeeds, loadBookmarks]);

  const openItem = useCallback(
    async (id: number) => {
      setSelectedId(id);
      setNotice(null);
      // Carry the lens's matched topics for this item so the reader can highlight them.
      setMatchedTopics(lensResults?.items.find((i) => i.id === id)?.matched_topics ?? []);
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
    [loadFeeds, lensResults]
  );

  const onSearch = useCallback(() => {
    setListOpen(true);
    setSelectedId(null); // land on the list/search screen, not a lingering reader
    setSelected(null);
    setLensFocusTick((t) => t + 1);
  }, []);

  const onCapture = useCallback(
    async (url: string, kind: "saved" | "bookmark") => {
      setNotice(null);
      const res = await api.capture(url, kind);
      if (kind === "bookmark") {
        setView("bookmarks");
        setFeedId(null);
        setListOpen(true);
        await loadBookmarks();
        if (res.duplicate) setNotice("That URL is already saved.");
        return;
      }
      setView("all");
      setFeedId(null);
      await loadCurrent("all", null, null);
      if (res.duplicate) setNotice("You've already saved that — here it is.");
      openItem(res.item.id);
    },
    [loadCurrent, openItem, loadBookmarks]
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
      await reloadCurrent();
    },
    [reloadCurrent]
  );

  const onSave = useCallback(
    async (id: number) => {
      const { item } = await api.save(id);
      setSelected(item);
      setNotice("Saved to your library.");
      await reloadCurrent();
      loadFeeds();
    },
    [reloadCurrent, loadFeeds]
  );

  const onDelete = useCallback(
    async (id: number) => {
      await api.remove(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
      setSelectedId((cur) => (cur === id ? null : cur));
      setSelected((cur) => (cur && cur.id === id ? null : cur));
      await reloadCurrent();
      loadFeeds();
    },
    [reloadCurrent, loadFeeds]
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

  // --- collections ---
  const onSelectCollection = useCallback((id: number) => {
    setView("collection");
    setCollectionId(id);
    setListOpen(true);
    setLensQuery("");
  }, []);

  const onSaveCollection = useCallback(
    async (name: string) => {
      const ids = (lensResults?.items ?? []).map((i) => i.id);
      const res = await api.createCollection(name, lensQuery.trim() || null, ids);
      await loadCollections();
      setLensQuery(""); // exit the lens
      setNotice(`Saved “${res.collection.name}” with ${res.collection.item_count} sources.`);
      setView("collection");
      setCollectionId(res.collection.id);
    },
    [lensResults, lensQuery, loadCollections]
  );

  const onDeleteCollection = useCallback(
    async (id: number) => {
      await api.removeCollection(id);
      await loadCollections();
      if (view === "collection" && collectionId === id) {
        setView("all");
        setCollectionId(null);
      }
    },
    [view, collectionId, loadCollections]
  );

  const onRemoveFromCollection = useCallback(
    async (cid: number, itemId: number) => {
      await api.removeFromCollection(cid, itemId);
      setItems((prev) => prev.filter((i) => i.id !== itemId));
      loadCollections();
    },
    [loadCollections]
  );

  // Reader "add to collection" popover toggles + create-new.
  const onToggleCollection = useCallback(
    async (cid: number, itemId: number, isMember: boolean) => {
      if (isMember) await api.removeFromCollection(cid, itemId);
      else await api.addToCollection(cid, itemId);
      setSelected((await api.get(itemId)).item);
      loadCollections();
    },
    [loadCollections]
  );

  const onCreateCollectionForItem = useCallback(
    async (name: string, itemId: number) => {
      await api.createCollection(name, null, [itemId]);
      setSelected((await api.get(itemId)).item);
      loadCollections();
    },
    [loadCollections]
  );

  // --- highlights ---
  const onAddHighlight = useCallback(
    async (itemId: number, sel: { quote: string; start: number; end: number }) => {
      await api.addHighlight(itemId, sel);
      setSelected((await api.get(itemId)).item); // refetch → reader repaints the new mark
      loadHighlights();
    },
    [loadHighlights]
  );

  const onRemoveHighlight = useCallback(
    async (hid: number) => {
      await api.removeHighlight(hid);
      const cur = selectedRef.current;
      if (cur) setSelected((await api.get(cur.id)).item);
      loadHighlights();
    },
    [loadHighlights]
  );

  const onSelectHighlights = useCallback(() => {
    setView("highlights");
    setFeedId(null);
    setCollectionId(null);
    setListOpen(true);
    setLensQuery("");
  }, []);

  // --- bookmarks ---
  const onSelectBookmarks = useCallback(() => {
    setView("bookmarks");
    setFeedId(null);
    setCollectionId(null);
    setListOpen(true);
    setLensQuery("");
  }, []);

  const onDeleteBookmark = useCallback(
    async (id: number) => {
      await api.remove(id);
      setBookmarks((prev) => prev.filter((b) => b.id !== id));
    },
    []
  );

  const onAddBookmarkTag = useCallback(async (id: number, name: string) => {
    const { topics } = await api.addTag(id, name);
    setBookmarks((prev) => prev.map((b) => (b.id === id ? { ...b, topics } : b)));
  }, []);

  const onRemoveBookmarkTag = useCallback(async (id: number, name: string) => {
    const { topics } = await api.removeTag(id, name);
    setBookmarks((prev) => prev.map((b) => (b.id === id ? { ...b, topics } : b)));
  }, []);

  // onCapture opens a reader item; make sure the mobile list is "entered" too.
  useEffect(() => {
    if (selectedId != null) setListOpen(true);
  }, [selectedId]);

  const lensActive = lensQuery.trim() !== "";
  const displayItems = lensActive ? lensResults?.items ?? [] : items;
  const collectionInfo =
    view === "collection" && collectionId != null
      ? { id: collectionId, name: collectionName, count: items.length }
      : null;

  return (
    <div className={`app${listOpen ? " list-open" : ""}${selectedId != null ? " reading" : ""}`}>
      <Nav
        view={view}
        feedId={feedId}
        feeds={feeds}
        collections={collections}
        collectionId={collectionId}
        unreadCount={unreadCount}
        lensActive={lensActive}
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
        onSelectCollection={onSelectCollection}
        onDeleteCollection={onDeleteCollection}
        onSelectHighlights={onSelectHighlights}
        highlightCount={highlightsArchive.length}
        onSelectBookmarks={onSelectBookmarks}
        bookmarkCount={bookmarks.length}
        onSearch={onSearch}
        onAddFeed={onAddFeed}
        onDeleteFeed={onDeleteFeed}
        captureSlot={<Capture onCapture={onCapture} />}
      />
      {view === "highlights" ? (
        <HighlightsList
          highlights={highlightsArchive}
          loaded={loaded}
          selectedItemId={selectedId}
          onOpen={openItem}
          onRemove={onRemoveHighlight}
          onBackToNav={onBackToNav}
        />
      ) : view === "bookmarks" ? (
        <BookmarksList
          bookmarks={bookmarks}
          loaded={loaded}
          onDelete={onDeleteBookmark}
          onAddTag={onAddBookmarkTag}
          onRemoveTag={onRemoveBookmarkTag}
          onBackToNav={onBackToNav}
        />
      ) : (
        <List
          items={displayItems}
          view={view}
          feedTitle={view === "feed" ? feeds.find((f) => f.id === feedId)?.title ?? "Feed" : null}
          collectionInfo={collectionInfo}
          loaded={loaded}
          selectedId={selectedId}
          notice={notice}
          error={error}
          lensQuery={lensQuery}
          onLensChange={setLensQuery}
          lensFocusTick={lensFocusTick}
          lensInfo={
            lensActive
              ? { savedCount: lensResults?.saved_count ?? 0, feedCount: lensResults?.feed_count ?? 0 }
              : null
          }
          onSaveAsCollection={onSaveCollection}
          onSelect={openItem}
          onDelete={onDelete}
          onRemoveFromCollection={onRemoveFromCollection}
          onBackToNav={onBackToNav}
        />
      )}
      <Reader
        item={selected}
        highlightTopics={matchedTopics}
        collections={collections}
        onMarkUnread={onMarkUnread}
        onRetry={onRetry}
        onBack={onBack}
        onSave={onSave}
        onToggleCollection={onToggleCollection}
        onCreateCollectionForItem={onCreateCollectionForItem}
        onAddHighlight={onAddHighlight}
        onRemoveHighlight={onRemoveHighlight}
      />
    </div>
  );
}
