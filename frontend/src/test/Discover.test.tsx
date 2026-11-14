import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Discover } from "../components/Discover";
import type { DiscoverState, Suggestion } from "../types";

function sug(over: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 1, run_id: 1, kind: "x", name: "Jancis Robinson", url: "https://x.com/jancisrobinson", feed_url: null,
    handle: "jancisrobinson", description: "Wine critic.", reason: "You asked about wine.", topics: ["wine"],
    status: "new", created_at: "", ...over,
  };
}

function state(over: Partial<DiscoverState> = {}): DiscoverState {
  return {
    run: null, suggestions: [], profile: { topics: [], feed_count: 0, x_count: 0, collections: [] },
    x_configured: true, ...over,
  };
}

function renderIt(s: DiscoverState) {
  const props = {
    state: s, notice: null,
    onStart: vi.fn().mockResolvedValue(undefined),
    onFollow: vi.fn().mockResolvedValue(undefined),
    onDismiss: vi.fn().mockResolvedValue(undefined),
    onBackToNav: vi.fn(),
  };
  render(<Discover {...props} />);
  return props;
}

describe("Discover", () => {
  it("invites a first search when there's nothing yet", () => {
    renderIt(state());
    expect(screen.getByText("No suggestions yet")).toBeInTheDocument();
    expect(screen.getByText(/Tell Trove what you're into/)).toBeInTheDocument();
  });

  it("starts a search for people only", async () => {
    const p = renderIt(state());
    await userEvent.click(screen.getByRole("button", { name: "People on X" }));
    await userEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(p.onStart).toHaveBeenCalledWith("", "x");
  });

  it("shows a failed run's error", () => {
    renderIt(state({ run: { id: 1, context: null, kinds: "all", status: "failed", error: "Claude is busy right now.",
      found: 0, created_at: "", finished_at: "" } }));
    expect(screen.getByText("Claude is busy right now.")).toBeInTheDocument();
  });

  it("follows and dismisses suggestions", async () => {
    const p = renderIt(state({ suggestions: [sug(), sug({ id: 2, handle: "other", name: "Other" })] }));
    expect(screen.getByRole("link", { name: "@jancisrobinson" })).toHaveAttribute("href", "https://x.com/jancisrobinson");
    await userEvent.click(screen.getAllByRole("button", { name: "Follow" })[0]);
    expect(p.onFollow).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
    await userEvent.click(screen.getAllByRole("button", { name: "Not for me" })[1]);
    expect(p.onDismiss).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }));
  });

  it("can't follow people when X isn't connected", () => {
    renderIt(state({ x_configured: false, suggestions: [sug()] }));
    expect(screen.getByRole("button", { name: "Follow" })).toBeDisabled();
    expect(screen.getByText(/X isn't connected/)).toBeInTheDocument();
  });

  it("shows a follow error on the card", async () => {
    const p = renderIt(state({ suggestions: [sug({ kind: "blog", handle: null, name: "Wine Folly", url: "https://winefolly.com" })] }));
    p.onFollow.mockRejectedValueOnce(new Error("Couldn't reach that URL."));
    await userEvent.click(screen.getByRole("button", { name: "Subscribe" }));
    expect(await screen.findByText("Couldn't reach that URL.")).toBeInTheDocument();
  });
});
