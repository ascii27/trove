import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api";
import { bookmark, feed, full, summary, xAccount, xPost } from "./factory";

vi.mock("../api", () => ({
  api: {
    list: vi.fn(),
    get: vi.fn(),
    capture: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    retry: vi.fn(),
    remove: vi.fn(),
    save: vi.fn(),
    lens: vi.fn(),
    feeds: vi.fn(),
    addFeed: vi.fn(),
    removeFeed: vi.fn(),
    collections: vi.fn(),
    getCollection: vi.fn(),
    createCollection: vi.fn(),
    removeCollection: vi.fn(),
    addToCollection: vi.fn(),
    removeFromCollection: vi.fn(),
    highlights: vi.fn(),
    bookmarks: vi.fn(),
    addTag: vi.fn(),
    removeTag: vi.fn(),
    xStatus: vi.fn(),
    xAccounts: vi.fn(),
    xPosts: vi.fn(),
    followX: vi.fn(),
    unfollowX: vi.fn(),
    refreshX: vi.fn(),
    markXPosts: vi.fn(),
    setXTheme: vi.fn(),
    discover: vi.fn(),
    startDiscover: vi.fn(),
    followSuggestion: vi.fn(),
    dismissSuggestion: vi.fn(),
  },
}));

const mockApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.feeds.mockResolvedValue({ feeds: [] });
  mockApi.collections.mockResolvedValue({ collections: [] });
  mockApi.highlights.mockResolvedValue({ highlights: [] });
  mockApi.bookmarks.mockResolvedValue({ bookmarks: [] });
  mockApi.xStatus.mockResolvedValue({ configured: true, mode: "api", message: null });
  mockApi.xAccounts.mockResolvedValue({ accounts: [], unread_count: 0 });
  mockApi.xPosts.mockResolvedValue({ posts: [], unread_count: 0 });
  mockApi.discover.mockResolvedValue(discoverState());
});

function discoverState(over: Record<string, unknown> = {}) {
  return {
    run: null,
    suggestions: [],
    profile: { topics: ["AI"], feed_count: 2, x_count: 0, collections: [] },
    x_configured: true,
    ...over,
  };
}

const wineBlog = {
  id: 11, run_id: 1, kind: "blog", name: "Wine Folly", url: "https://winefolly.com",
  feed_url: "https://winefolly.com/feed", handle: null, description: "Wine basics, beautifully drawn.",
  reason: "Matches your ask about wine.", topics: ["wine"], status: "new", created_at: "2026-11-14 10:00:00",
};

describe("App", () => {
  it("auto-marks an item read when opened and shows the reader", async () => {
    mockApi.list.mockResolvedValue({ items: [summary({ id: 5, read_state: "unread" })], unread_count: 1 });
    mockApi.get.mockResolvedValue({ item: full({ id: 5, read_state: "unread" }) });
    mockApi.markRead.mockResolvedValue({ item: full({ id: 5, read_state: "read" }), unread_count: 0 });

    render(<App />);
    const card = await screen.findByRole("button", { name: "The anatomy of an internal developer platform" });
    await userEvent.click(card);

    await waitFor(() => expect(mockApi.markRead).toHaveBeenCalledWith(5));
    expect(await screen.findByRole("button", { name: /mark unread/i })).toBeInTheDocument();
  });

  it("captures a URL and surfaces the extracting item in the reader", async () => {
    // initial empty library, then a list containing the new pending item
    mockApi.list
      .mockResolvedValueOnce({ items: [], unread_count: 0 })
      .mockResolvedValue({
        items: [summary({ id: 9, extraction_status: "extracting", enrichment_status: "pending", title: null, summary: null })],
        unread_count: 1,
      });
    mockApi.capture.mockResolvedValue({
      item: summary({ id: 9, extraction_status: "pending", enrichment_status: "pending", title: null, summary: null }),
      duplicate: false,
    });
    mockApi.get.mockResolvedValue({
      item: full({ id: 9, extraction_status: "extracting", enrichment_status: "pending", title: null, summary: null, content_text: null }),
    });

    render(<App />);
    await screen.findByText(/library is empty/i);

    await userEvent.click(screen.getByRole("button", { name: /save a url/i }));
    await userEvent.type(screen.getByLabelText(/url to save/i), "https://example.com/post");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(mockApi.capture).toHaveBeenCalledWith("https://example.com/post", "saved"));
    expect(await screen.findByText(/extracting the article/i)).toBeInTheDocument();
  });

  it("opens the Bookmarks view without hitting the item-list endpoint", async () => {
    mockApi.list.mockResolvedValue({ items: [], unread_count: 0 });
    mockApi.bookmarks.mockResolvedValue({ bookmarks: [bookmark({ id: 3, title: "ripgrep" })] });

    render(<App />);
    await screen.findByText(/library is empty/i);

    mockApi.list.mockClear();
    await userEvent.click(screen.getByRole("button", { name: /^Bookmarks/ }));

    // the bookmark's title renders as an external link, not a reader item
    const link = await screen.findByRole("link", { name: "ripgrep" });
    expect(link).toHaveAttribute("target", "_blank");
    // switching to Bookmarks must never query the item list (it rejects that view)
    expect(mockApi.list).not.toHaveBeenCalled();
  });

  it("deletes an item and removes it from the list", async () => {
    mockApi.list
      .mockResolvedValueOnce({ items: [summary({ id: 5, title: "Doomed" })], unread_count: 1 })
      .mockResolvedValue({ items: [], unread_count: 0 });
    mockApi.remove.mockResolvedValue({ deleted: true, unread_count: 0 });

    render(<App />);
    await screen.findByRole("button", { name: "Doomed" });

    await userEvent.click(screen.getByRole("button", { name: /delete doomed/i }));
    await userEvent.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(mockApi.remove).toHaveBeenCalledWith(5));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Doomed" })).not.toBeInTheDocument());
  });

  it("runs a lens query and shows cross-lane results", async () => {
    mockApi.list.mockResolvedValue({ items: [], unread_count: 0 });
    mockApi.lens.mockResolvedValue({
      query: "AI",
      items: [summary({ id: 1, lane: "saved", title: "Saved AI piece" }), summary({ id: 2, lane: "feed", title: "Feed AI piece" })],
      saved_count: 1,
      feed_count: 1,
    });

    render(<App />);
    await screen.findByText(/library is empty/i);

    await userEvent.type(screen.getByLabelText(/search your library/i), "AI");
    await waitFor(() => expect(mockApi.lens).toHaveBeenCalledWith("AI"));
    expect(await screen.findByText(/reading about/i)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Saved AI piece" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Feed AI piece" })).toBeInTheDocument();
  });

  it("saves a lens as a collection", async () => {
    mockApi.list.mockResolvedValue({ items: [], unread_count: 0 });
    mockApi.lens.mockResolvedValue({
      query: "AI",
      items: [summary({ id: 1, lane: "saved" }), summary({ id: 2, lane: "feed" })],
      saved_count: 1,
      feed_count: 1,
    });
    mockApi.createCollection.mockResolvedValue({ collection: { id: 8, name: "AI", query: "AI", item_count: 2 } });
    mockApi.getCollection.mockResolvedValue({ collection: { id: 8, name: "AI", query: "AI", item_count: 2 }, items: [] });

    render(<App />);
    await screen.findByText(/library is empty/i);
    await userEvent.type(screen.getByLabelText(/search your library/i), "AI");
    await waitFor(() => expect(mockApi.lens).toHaveBeenCalledWith("AI"));

    await userEvent.click(await screen.findByRole("button", { name: /save as collection/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(mockApi.createCollection).toHaveBeenCalledWith("AI", "AI", [1, 2]));
  });

  it("adds a feed, shows it in the nav, and opens its items", async () => {
    mockApi.list.mockResolvedValue({ items: [], unread_count: 0 });
    mockApi.feeds
      .mockResolvedValueOnce({ feeds: [] }) // initial
      .mockResolvedValue({ feeds: [feed({ id: 2, title: "Pragmatic Engineer", unread_count: 1 })] });
    mockApi.addFeed.mockResolvedValue({ feed: feed({ id: 2, title: "Pragmatic Engineer" }), duplicate: false });

    render(<App />);
    await screen.findByText(/library is empty/i);

    await userEvent.click(screen.getByRole("button", { name: /add a feed/i }));
    await userEvent.type(screen.getByLabelText(/feed or site url/i), "https://blog.pragmaticengineer.com");
    await userEvent.click(screen.getByRole("button", { name: /^add feed$/i }));

    await waitFor(() => expect(mockApi.addFeed).toHaveBeenCalledWith("https://blog.pragmaticengineer.com"));
    // the feed view is selected and requested from the API
    await waitFor(() => expect(mockApi.list).toHaveBeenCalledWith("feed", 2));
    // the feed appears in the nav (as a selectable button)
    expect(await screen.findByRole("button", { name: /^Pragmatic Engineer/ })).toBeInTheDocument();
  });

  it("follows an X account and shows its posts as a grouped stream", async () => {
    const acct = xAccount({ id: 3 });
    mockApi.list.mockResolvedValue({ items: [], unread_count: 0 });
    mockApi.followX.mockResolvedValue({ account: acct, duplicate: false });
    mockApi.xAccounts.mockResolvedValueOnce({ accounts: [], unread_count: 0 }).mockResolvedValue({ accounts: [acct], unread_count: 1 });
    const now = new Date().toISOString().slice(0, 19);
    mockApi.xPosts.mockResolvedValue({ posts: [xPost({ id: 11, published_at: now })], unread_count: 1 });

    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Follow someone on X" }));
    await userEvent.type(screen.getByLabelText("@handle or profile link"), "@jane");
    await userEvent.click(screen.getByRole("button", { name: "Follow" }));

    await waitFor(() => expect(mockApi.followX).toHaveBeenCalledWith("@jane"));
    await waitFor(() => expect(mockApi.xPosts).toHaveBeenCalledWith(3));
    expect(await screen.findByText("Agents need better evals.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Today" })).toBeInTheDocument();
  });

  it("runs a discovery search with context and subscribes to a suggested blog", async () => {
    mockApi.list.mockResolvedValue({ items: [], unread_count: 0 });
    const running = { id: 1, context: "natural wine", kinds: "all", status: "running", error: null, found: 0,
      created_at: "", finished_at: null };
    mockApi.startDiscover.mockResolvedValue({ run: running });
    mockApi.followSuggestion.mockResolvedValue({ suggestion: { ...wineBlog, status: "followed" }, duplicate: false,
      feed: feed({ id: 4, title: "Wine Folly" }) });

    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /^Discover/ }));
    expect(await screen.findByText(/shaped by AI · 2 feeds/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/anything specific/i), "natural wine");
    await userEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(mockApi.startDiscover).toHaveBeenCalledWith("natural wine", "all");
    expect(await screen.findByRole("status")).toHaveTextContent("for “natural wine”");

    // The poll picks up the finished run.
    mockApi.discover.mockResolvedValue(discoverState({ run: { ...running, status: "done", found: 1 },
      suggestions: [wineBlog] }));
    expect(await screen.findByText("Wine Folly", {}, { timeout: 6000 })).toBeInTheDocument();
    expect(screen.getByText("Found 1 new suggestion.")).toBeInTheDocument();

    mockApi.feeds.mockResolvedValue({ feeds: [feed({ id: 4, title: "Wine Folly" })] });
    await userEvent.click(screen.getByRole("button", { name: "Subscribe" }));
    expect(mockApi.followSuggestion).toHaveBeenCalledWith(11);
    expect(await screen.findByText("Subscribed to Wine Folly.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Wine Folly/ })).toBeInTheDocument(); // now in the nav

    // Discover's messages stay on Discover.
    await userEvent.click(screen.getByRole("button", { name: /^All saved/ }));
    expect(screen.queryByText("Subscribed to Wine Folly.")).not.toBeInTheDocument();
    expect(screen.queryByText("Found 1 new suggestion.")).not.toBeInTheDocument();
  }, 10000);
});
