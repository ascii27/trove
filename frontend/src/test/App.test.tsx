import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api";
import { full, summary } from "./factory";

vi.mock("../api", () => ({
  api: {
    list: vi.fn(),
    get: vi.fn(),
    capture: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    retry: vi.fn(),
    remove: vi.fn(),
  },
}));

const mockApi = api as unknown as {
  list: ReturnType<typeof vi.fn>;
  get: ReturnType<typeof vi.fn>;
  capture: ReturnType<typeof vi.fn>;
  markRead: ReturnType<typeof vi.fn>;
  markUnread: ReturnType<typeof vi.fn>;
  retry: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
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
});
