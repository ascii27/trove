import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, type LensResponse } from "./api";
import { Capture } from "./components/Capture";
import { Nav } from "./components/Nav";
import { List } from "./components/List";
import { HighlightsList } from "./components/HighlightsList";
import { BookmarksList } from "./components/BookmarksList";
import { Reader } from "./components/Reader";
import { XStream } from "./components/XStream";
import { Discover } from "./components/Discover";
import type { Grouping } from "./xgroup";
import {
  bookmarkPending,
  isPending,
  type Bookmark,
  type Collection,
  type DiscoverKinds,
  type DiscoverState,
  type Feed,
  type HighlightArchiveEntry,
  type ItemFull,
  type ItemSummary,
  type Suggestion,
  type XAccount,
  type XPost,
  type XStatus,
} from "./types";

type View = "all" | "unread" | "feed" | "collection" | "highlights" | "bookmarks" | "x" | "discover";

const GROUPING_KEY = "trove.x.grouping";
function initialGrouping(): Grouping {
  try {
    const g = localStorage.getItem(GROUPING_KEY);
    if (g === "date" || g === "theme" || g === "tag") return g;
  } catch {
    /* storage unavailable */
  }
  return "date";
}

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
  // Discover's own status line, so its messages never land on another view.
  const [discoverNotice, setDiscoverNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // X lane: followed accounts and their posts, read as a grouped stream.
  const [xStatus, setXStatus] = useState<XStatus | null>(null);
  const [xAccounts, setXAccounts] = useState<XAccount[]>([]);
  const [xUnread, setXUnread] = useState(0);
  const [xAccountId, setXAccountId] = useState<number | null>(null);
  const [xPosts, setXPosts] = useState<XPost[]>([]);
  const [xGrouping, setXGrouping] = useState<Grouping>(initialGrouping);
  // Discover: AI-found blogs and X accounts to follow.
  const [discover, setDiscover] = useState<DiscoverState | null>(null);
  const discoverRunRef = useRef<DiscoverState["run"]>(null);

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

  const loadXAccounts = useCallback(async () => {
    try {
      const res = await api.xAccounts();
      setXAccounts(res.accounts);
      setXUnread(res.unread_count);
    } catch {
      /* ignore */
    }
  }, []);

  const loadXPosts = useCallback(async (accountId: number | null) => {
    try {
      const res = await api.xPosts(accountId);
      setXPosts(res.posts);
      setXUnread(res.unread_count);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const loadDiscover = useCallback(async () => {
    try {
      const next = await api.discover();
      // Announce when a search that was running finishes.
      const prev = discoverRunRef.current;
      if (prev?.status === "running" && next.run?.id === prev.id && next.run.status === "done") {
        const n = next.run.found;
        setDiscoverNotice(n > 0 ? `Found ${n} new suggestion${n === 1 ? "" : "s"}.` : "Nothing new turned up this time.");
      }
      discoverRunRef.current = next.run;
      setDiscover(next);
    } catch {
      /* ignore */
    }
  }, []);

  const loadCurrent = useCallback(
    async (v: View, fid: number | null, cid: number | null) => {
      // Highlights/Bookmarks are their own lanes with dedicated loaders — never
      // hit the item list endpoint for them (it rejects those view names, and
      // polling calls their loaders separately).
      if (v === "highlights" || v === "bookmarks" || v === "x" || v === "discover") return;
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
    loadXAccounts();
    loadDiscover();
    api.xStatus().then(setXStatus).catch(() => {});
  }, [loadFeeds, loadCollections, loadHighlights, loadBookmarks, loadXAccounts, loadDiscover]);
  useEffect(() => {
    setLoaded(false);
    if (view === "highlights") {
      loadHighlights().then(() => setLoaded(true));
    } else if (view === "bookmarks") {
      loadBookmarks().then(() => setLoaded(true));
    } else if (view === "x") {
      loadXPosts(xAccountId).then(() => setLoaded(true));
    } else if (view === "discover") {
      loadDiscover().then(() => setLoaded(true));
    } else {
      loadCurrent(view, feedId, collectionId);
    }
  }, [view, feedId, collectionId, xAccountId, loadCurrent, loadHighlights, loadBookmarks, loadXPosts, loadDiscover]);

  // A discovery search runs in the background for a minute or two; poll until it lands.
  const discoverRunning = discover?.run?.status === "running";
  useEffect(() => {
    if (!discoverRunning) return;
    const id = setInterval(loadDiscover, 4000);
    return () => clearInterval(id);
  }, [discoverRunning, loadDiscover]);

  // While reading X, quietly pick up new posts and themes as the worker lands them.
  useEffect(() => {
    if (view !== "x") return;
    const id = setInterval(() => {
      loadXPosts(xAccountId);
      loadXAccounts();
    }, 60000);
    return () => clearInterval(id);
  }, [view, xAccountId, loadXPosts, loadXAccounts]);

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
    // The search bar lives in the item list; leave the X stream to show it.
    setView((v) => (v === "x" || v === "discover" ? "all" : v));
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

  // --- X ---
  const onSelectX = useCallback((accountId: number | null) => {
    setView("x");
    setXAccountId(accountId);
    setFeedId(null);
    setCollectionId(null);
    setListOpen(true);
    setLensQuery("");
    setSelectedId(null);
    setSelected(null);
  }, []);

  const onFollowX = useCallback(
    async (handle: string) => {
      const res = await api.followX(handle);
      await loadXAccounts();
      const who = res.account.name ?? `@${res.account.handle}`;
      setNotice(res.duplicate ? `You already follow ${who}.` : `Following ${who}.`);
      onSelectX(res.account.id);
    },
    [loadXAccounts, onSelectX]
  );

  const onUnfollowX = useCallback(
    async (id: number) => {
      await api.unfollowX(id);
      await loadXAccounts();
      if (view === "x") {
        if (xAccountId === id) setXAccountId(null);
        else loadXPosts(xAccountId);
      }
    },
    [view, xAccountId, loadXAccounts, loadXPosts]
  );

  const onRefreshX = useCallback(
    async (id: number) => {
      await api.refreshX(id);
      await Promise.all([loadXPosts(xAccountId), loadXAccounts()]);
    },
    [xAccountId, loadXPosts, loadXAccounts]
  );

  // --- discover ---
  const onSelectDiscover = useCallback(() => {
    setView("discover");
    setFeedId(null);
    setCollectionId(null);
    setListOpen(true);
    setLensQuery("");
    setSelectedId(null);
    setSelected(null);
    setNotice(null);
  }, []);

  const onStartDiscover = useCallback(async (context: string, kinds: DiscoverKinds) => {
    setDiscoverNotice(null);
    const { run } = await api.startDiscover(context, kinds);
    discoverRunRef.current = run;
    setDiscover((prev) => (prev ? { ...prev, run } : prev));
  }, []);

  const dropSuggestion = useCallback((id: number) => {
    setDiscover((prev) => (prev ? { ...prev, suggestions: prev.suggestions.filter((x) => x.id !== id) } : prev));
  }, []);

  const onFollowSuggestion = useCallback(
    async (s: Suggestion) => {
      const res = await api.followSuggestion(s.id);
      dropSuggestion(s.id);
      if (s.kind === "blog") {
        await loadFeeds();
        setDiscoverNotice(res.duplicate ? `You already follow ${s.name}.` : `Subscribed to ${s.name}.`);
      } else {
        await loadXAccounts();
        setDiscoverNotice(res.duplicate ? `You already follow ${s.name}.` : `Following ${s.name}.`);
      }
    },
    [dropSuggestion, loadFeeds, loadXAccounts]
  );

  const onDismissSuggestion = useCallback(
    async (s: Suggestion) => {
      await api.dismissSuggestion(s.id);
      dropSuggestion(s.id);
    },
    [dropSuggestion]
  );

  const onGroupingChange = useCallback((g: Grouping) => {
    setXGrouping(g);
    try {
      localStorage.setItem(GROUPING_KEY, g);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const patchPost = useCallback((id: number, patch: Partial<XPost>) => {
    setXPosts((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }, []);

  const onMarkX = useCallback(
    async (ids: number[], state: "read" | "unread") => {
      const set = new Set(ids);
      setXPosts((prev) => prev.map((p) => (set.has(p.id) ? { ...p, read_state: state } : p)));
      try {
        const res = await api.markXPosts(ids, state);
        setXUnread(res.unread_count);
        loadXAccounts();
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [loadXAccounts]
  );

  const onAddXTag = useCallback(
    async (id: number, name: string) => patchPost(id, { topics: (await api.addTag(id, name)).topics }),
    [patchPost]
  );
  const onRemoveXTag = useCallback(
    async (id: number, name: string) => patchPost(id, { topics: (await api.removeTag(id, name)).topics }),
    [patchPost]
  );
  const onSetXTheme = useCallback(
    async (id: number, theme: string | null) => patchPost(id, { theme: (await api.setXTheme(id, theme)).post.theme }),
    [patchPost]
  );
  const onAddXHighlight = useCallback(
    async (id: number, sel: { quote: string; start: number; end: number }) => {
      const { highlight } = await api.addHighlight(id, sel);
      setXPosts((prev) =>
        prev.map((p) =>
          p.id === id
            ? { ...p, highlights: [...p.highlights, highlight].sort((a, b) => a.start_offset - b.start_offset) }
            : p
        )
      );
      loadHighlights();
    },
    [loadHighlights]
  );
  const onRemoveXHighlight = useCallback(
    async (hid: number) => {
      await api.removeHighlight(hid);
      setXPosts((prev) => prev.map((p) => ({ ...p, highlights: p.highlights.filter((h) => h.id !== hid) })));
      loadHighlights();
    },
    [loadHighlights]
  );

  // onCapture opens a reader item; make sure the mobile list is "entered" too.
  useEffect(() => {
    if (selectedId != null) setListOpen(true);
  }, [selectedId]);

  // Phones scroll the window, one level (menu / list / reader) at a time, so give
  // each new screen its own scroll: start at the top, except coming back from the
  // reader, which returns to where you were in the list.
  const mobileLevel = selectedId != null ? "reader" : listOpen ? "list" : "nav";
  const paneKey = `${view}|${feedId}|${collectionId}|${xAccountId}`;
  const listScrollY = useRef(0);
  const levelRef = useRef(mobileLevel);
  const prevScreen = useRef({ pane: paneKey, level: mobileLevel, item: selectedId });
  useEffect(() => {
    const onScroll = () => {
      if (levelRef.current === "list") listScrollY.current = window.scrollY;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useLayoutEffect(() => {
    const prev = prevScreen.current;
    prevScreen.current = { pane: paneKey, level: mobileLevel, item: selectedId };
    levelRef.current = mobileLevel;
    const same = prev.pane === paneKey && prev.level === mobileLevel && prev.item === selectedId;
    if (same || !window.matchMedia?.("(max-width: 820px)").matches) return;
    const backToList = prev.level === "reader" && mobileLevel === "list" && prev.pane === paneKey;
    window.scrollTo(0, backToList ? listScrollY.current : 0);
  }, [paneKey, mobileLevel, selectedId]);

  const lensActive = lensQuery.trim() !== "";
  const displayItems = lensActive ? lensResults?.items ?? [] : items;
  const collectionInfo =
    view === "collection" && collectionId != null
      ? { id: collectionId, name: collectionName, count: items.length }
      : null;

  return (
    <div
      className={`app${listOpen ? " list-open" : ""}${selectedId != null ? " reading" : ""}${
        (view === "x" || view === "discover") && !lensActive ? " wide" : ""
      }`}
    >
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
        xAccounts={xAccounts}
        xAccountId={xAccountId}
        xUnreadCount={xUnread}
        onSelectX={onSelectX}
        onFollowX={onFollowX}
        onUnfollowX={onUnfollowX}
        onSelectDiscover={onSelectDiscover}
        discoverCount={discover?.suggestions.length ?? 0}
      />
      {view === "discover" && !lensActive ? (
        <Discover
          state={discover}
          notice={discoverNotice}
          onStart={onStartDiscover}
          onFollow={onFollowSuggestion}
          onDismiss={onDismissSuggestion}
          onBackToNav={onBackToNav}
        />
      ) : view === "x" && !lensActive ? (
        <XStream
          posts={xPosts}
          account={xAccounts.find((a) => a.id === xAccountId) ?? null}
          status={xStatus}
          loaded={loaded}
          error={error}
          grouping={xGrouping}
          onGroupingChange={onGroupingChange}
          onMark={onMarkX}
          onAddTag={onAddXTag}
          onRemoveTag={onRemoveXTag}
          onSetTheme={onSetXTheme}
          onAddHighlight={onAddXHighlight}
          onRemoveHighlight={onRemoveXHighlight}
          onRefresh={onRefreshX}
          onBackToNav={onBackToNav}
        />
      ) : view === "highlights" ? (
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
          view={view === "x" || view === "discover" ? "all" : view}
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
