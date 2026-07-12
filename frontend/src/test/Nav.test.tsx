import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Nav } from "../components/Nav";
import { feed } from "./factory";

function renderNav(over: Partial<React.ComponentProps<typeof Nav>> = {}) {
  const props = {
    view: "all" as const,
    feedId: null,
    feeds: [feed({ id: 1, title: "Pragmatic Engineer", unread_count: 3 })],
    unreadCount: 2,
    savedCount: 6,
    lensActive: false,
    onSelectSaved: vi.fn(),
    onSelectFeed: vi.fn(),
    onSearch: vi.fn(),
    onAddFeed: vi.fn().mockResolvedValue(undefined),
    onDeleteFeed: vi.fn(),
    captureSlot: <button>+ URL</button>,
    ...over,
  };
  render(<Nav {...props} />);
  return props;
}

describe("Nav", () => {
  it("lists feeds with their unread counts and selects one", async () => {
    const props = renderNav();
    expect(screen.getByText("Pragmatic Engineer")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Pragmatic Engineer/ }));
    expect(props.onSelectFeed).toHaveBeenCalledWith(1);
  });

  it("adds a feed", async () => {
    const props = renderNav();
    await userEvent.click(screen.getByRole("button", { name: /add a feed/i }));
    await userEvent.type(screen.getByLabelText(/feed or site url/i), "https://example.com");
    await userEvent.click(screen.getByRole("button", { name: /^add feed$/i }));
    expect(props.onAddFeed).toHaveBeenCalledWith("https://example.com");
  });

  it("unsubscribes after confirm", async () => {
    const props = renderNav();
    await userEvent.click(screen.getByRole("button", { name: /unsubscribe from pragmatic engineer/i }));
    await userEvent.click(screen.getByRole("button", { name: /^remove$/i }));
    expect(props.onDeleteFeed).toHaveBeenCalledWith(1);
  });

  it("shows a hint when there are no feeds", () => {
    renderNav({ feeds: [] });
    expect(screen.getByText(/add an rss feed/i)).toBeInTheDocument();
  });
});
