import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api";
import { feed, full, summary } from "./factory";

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
  },
}));

const mockApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.feeds.mockResolvedValue({ feeds: [] });
  mockApi.collections.mockResolvedValue({ collections: [] });
});

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

    await waitFor(() => expect(mockApi.capture).toHaveBeenCalledWith("https://example.com/post"));
    expect(await screen.findByText(/extracting the article/i)).toBeInTheDocument();
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
});
