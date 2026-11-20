import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Discover, runOutcome } from "../components/Discover";
import type { DiscoverRun, DiscoverState, Suggestion } from "../types";

function sug(over: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 1, run_id: 2, kind: "x", name: "Jancis Robinson", url: "https://x.com/jancisrobinson", feed_url: null,
    handle: "jancisrobinson", description: "Wine critic.", reason: "You asked about wine.", topics: ["wine"],
    status: "new", created_at: "", ...over,
  };
}

function run(over: Partial<DiscoverRun> = {}): DiscoverRun {
  return {
    id: 2, context: "wine", kinds: "all", status: "done", error: null, found: 2, proposed: 22, passed: 16,
    input_tokens: 2200, output_tokens: 4300, created_at: "2026-11-14 06:00:00", finished_at: "2026-11-14 06:00:30",
    to_review: 2, total: 2, ...over,
  };
}

function state(over: Partial<DiscoverState> = {}): DiscoverState {
  return {
    run: null, runs: [], to_review: 0, profile: { topics: [], feed_count: 0, x_count: 0, collections: [] },
    x_configured: true, ...over,
  };
}

const WINE = run();
const INTERESTS = run({ id: 1, context: null, found: 1, to_review: 0, total: 1, created_at: "2026-11-13 06:00:00" });
const RESULTS: Record<number, Suggestion[]> = {
  2: [
    sug({ id: 10, kind: "blog", handle: null, name: "Wine Folly", url: "https://winefolly.com" }),
    sug({ id: 11 }),
  ],
  1: [sug({ id: 12, run_id: 1, kind: "blog", handle: null, name: "Martin Fowler", url: "https://martinfowler.com", status: "followed" })],
};

function renderIt(s: DiscoverState, over: Record<string, unknown> = {}) {
  const runs = Object.fromEntries(s.runs.map((r) => [r.id, r]));
  const props = {
    state: s, notice: null,
    onStart: vi.fn().mockResolvedValue(undefined),
    onLoadRun: vi.fn(async (id: number) => ({ run: runs[id], suggestions: RESULTS[id] ?? [] })),
    onFollow: vi.fn(async (x: Suggestion) => ({ ...x, status: "followed" as const })),
    onDismiss: vi.fn(async (x: Suggestion) => ({ ...x, status: "dismissed" as const })),
    onRestore: vi.fn(async (x: Suggestion) => ({ ...x, status: "new" as const })),
    onBackToNav: vi.fn(),
    ...over,
  };
  render(<Discover {...props} />);
  return props;
}

describe("Discover", () => {
  it("invites a first search when there's nothing yet", () => {
    renderIt(state());
    expect(screen.getByText("No searches yet")).toBeInTheDocument();
    expect(screen.getByText(/Tell Trove what you're into/)).toBeInTheDocument();
  });

  it("starts a search for people only", async () => {
    const p = renderIt(state());
    await userEvent.click(screen.getByRole("button", { name: "People on X" }));
    await userEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(p.onStart).toHaveBeenCalledWith("", "x");
  });

  it("lists searches and opens the newest one's results", async () => {
    const p = renderIt(state({ runs: [WINE, INTERESTS], run: WINE }));
    const list = screen.getByRole("navigation", { name: "Your searches" });
    expect(within(list).getByRole("button", { name: /“wine”/ })).toHaveAttribute("aria-current", "true");
    expect(within(list).getByRole("button", { name: /From your interests/ })).toBeInTheDocument();
    await waitFor(() => expect(p.onLoadRun).toHaveBeenCalledWith(2));
    expect(await screen.findByText("Wine Folly")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "To review (2)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switches to another search and shows what you did with its results", async () => {
    const p = renderIt(state({ runs: [WINE, INTERESTS], run: WINE }));
    await screen.findByText("Wine Folly");
    await userEvent.click(screen.getByRole("button", { name: /From your interests/ }));
    await waitFor(() => expect(p.onLoadRun).toHaveBeenCalledWith(1));
    // Nothing left to review there, so it opens on "All".
    expect(await screen.findByText("Martin Fowler")).toBeInTheDocument();
    expect(screen.getByText("✓ Subscribed")).toBeInTheDocument();
    expect(screen.queryByText("Wine Folly")).not.toBeInTheDocument();
  });

  it("follows, dismisses and undoes in place", async () => {
    const p = renderIt(state({ runs: [WINE], run: WINE }));
    await screen.findByText("Wine Folly");
    // Stays on "To review": acted-on cards remain visible until you switch.
    await userEvent.click(screen.getByRole("button", { name: "Subscribe" }));
    expect(p.onFollow).toHaveBeenCalledWith(expect.objectContaining({ id: 10 }));
    expect(await screen.findByText("✓ Subscribed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Not for me" }));
    expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(p.onRestore).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }));
    expect(await screen.findByRole("button", { name: "Follow" })).toBeInTheDocument();
    expect(screen.getByText("✓ Subscribed")).toBeInTheDocument();
    // Re-picking the filter drops what's been reviewed.
    await userEvent.click(screen.getByRole("button", { name: /^To review/ }));
    expect(screen.queryByText("Wine Folly")).not.toBeInTheDocument();
    expect(screen.getByText("Jancis Robinson")).toBeInTheDocument();
  });

  it("shows a running search and a failed one", async () => {
    const running = run({ id: 3, status: "running", found: 0, proposed: null, passed: null, to_review: 0, total: 0 });
    const p = renderIt(state({ runs: [running], run: running }));
    expect(screen.getByRole("status")).toHaveTextContent("Finding writers");
    expect(p.onLoadRun).not.toHaveBeenCalled();

    const failed = run({ id: 4, status: "failed", error: "Claude is busy right now.", to_review: 0, total: 0 });
    renderIt(state({ runs: [failed], run: failed }));
    expect(screen.getAllByText(/Claude is busy right now/).length).toBeGreaterThan(0);
  });

  it("can't follow people when X isn't connected", async () => {
    renderIt(state({ runs: [WINE], run: WINE, x_configured: false }));
    expect(await screen.findByRole("button", { name: "Follow" })).toBeDisabled();
    expect(screen.getByText(/X isn't connected/)).toBeInTheDocument();
  });

  it("shows a follow error on the card", async () => {
    renderIt(state({ runs: [WINE], run: WINE }), {
      onFollow: vi.fn().mockRejectedValue(new Error("Couldn't reach that URL.")),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Subscribe" }));
    expect(await screen.findByText("Couldn't reach that URL.")).toBeInTheDocument();
  });

  it("explains every way a search can come back empty", () => {
    expect(runOutcome(run({ status: "running" }))).toBe("Finding…");
    expect(runOutcome(run({ found: 16 }))).toBe("Found 16 new suggestions");
    expect(runOutcome(run({ found: 0, proposed: 0, passed: 0 }))).toMatch(/didn't suggest anything/);
    expect(runOutcome(run({ found: 0, proposed: 22, passed: 0 }))).toMatch(/None of the 22/);
    expect(runOutcome(run({ found: 0, proposed: 22, passed: 16 }))).toMatch(/all 16 were already suggested/);
    expect(runOutcome(run({ found: 0, proposed: null, passed: null }))).toBe("Nothing new");
  });
});
