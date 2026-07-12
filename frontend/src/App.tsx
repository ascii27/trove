import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Capture } from "./components/Capture";
import { Nav } from "./components/Nav";
import { List } from "./components/List";
import { Reader } from "./components/Reader";
import { isPending, type ItemFull, type ItemSummary } from "./types";

type View = "all" | "unread";

export default function App() {
  const [view, setView] = useState<View>("all");
  const [items, setItems] = useState<ItemSummary[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<ItemFull | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const loadList = useCallback(async (v: View) => {
    try {
      const res = await api.list(v);
      setItems(res.items);
      setUnreadCount(res.unread_count);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadList(view);
  }, [view, loadList]);

  // Poll while anything visible is still extracting/enriching, so content and
  // metadata appear without a manual refresh.
  const anyPending = items.some(isPending) || (selected != null && isPending(selected));
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  useEffect(() => {
    if (!anyPending) return;
    const id = setInterval(async () => {
      await loadList(view);
      const cur = selectedRef.current;
      if (cur && isPending(cur)) {
        try {
          const { item } = await api.get(cur.id);
          setSelected(item);
        } catch {
          /* ignore transient */
        }
      }
    }, 2500);
    return () => clearInterval(id);
  }, [anyPending, view, loadList]);

  const openItem = useCallback(async (id: number) => {
    setSelectedId(id);
    setNotice(null);
    try {
      const { item } = await api.get(id);
      // Auto-mark-read on open (PRD O-2), with an easy "mark unread" in the reader.
      if (item.read_state === "unread") {
        const res = await api.markRead(id);
        setSelected(res.item);
        setUnreadCount(res.unread_count);
        setItems((prev) => prev.map((i) => (i.id === id ? { ...i, read_state: "read" } : i)));
      } else {
        setSelected(item);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const onCapture = useCallback(
    async (url: string) => {
      setNotice(null);
      const res = await api.capture(url);
      await loadList(view);
      if (res.duplicate) {
        setNotice("You've already saved that — here it is.");
        openItem(res.item.id);
      } else {
        setSelectedId(res.item.id);
        openItem(res.item.id);
      }
    },
    [view, loadList, openItem]
  );

  const onMarkUnread = useCallback(async (id: number) => {
    const res = await api.markUnread(id);
    setSelected(res.item);
    setUnreadCount(res.unread_count);
    setItems((prev) => prev.map((i) => (i.id === id ? { ...i, read_state: "unread" } : i)));
  }, []);

  const onRetry = useCallback(
    async (id: number) => {
      const { item } = await api.retry(id);
      setSelected(item);
      await loadList(view);
    },
    [view, loadList]
  );

  const onDelete = useCallback(
    async (id: number) => {
      await api.remove(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
      setSelectedId((cur) => (cur === id ? null : cur));
      setSelected((cur) => (cur && cur.id === id ? null : cur));
      await loadList(view);
    },
    [view, loadList]
  );

  const onBack = useCallback(() => {
    setSelectedId(null);
    setSelected(null);
  }, []);

  return (
    <div className={`app${selectedId != null ? " reading" : ""}`}>
      <Nav
        view={view}
        unreadCount={unreadCount}
        savedCount={items.length}
        onSelectView={setView}
        captureSlot={<Capture onCapture={onCapture} />}
      />
      <List
        items={items}
        view={view}
        loaded={loaded}
        selectedId={selectedId}
        notice={notice}
        error={error}
        onSelect={openItem}
        onDelete={onDelete}
      />
      <Reader item={selected} onMarkUnread={onMarkUnread} onRetry={onRetry} onBack={onBack} />
    </div>
  );
}
