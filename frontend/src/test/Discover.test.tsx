import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Discover, runOutcome } from "../components/Discover";
import type { DiscoverRun, DiscoverState, Suggestion } from "../types";

function sug(over: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 1, run_id: 1, kind: "x", name: "Jancis Robinson", url: "https://x.com/jancisrobinson", feed_url: null,
    handle: "jancisrobinson", description: "Wine critic.", reason: "You asked about wine.", topics: ["wine"],
    status: "new", created_at: "", ...over,
  };
}

function run(over: Partial<DiscoverRun> = {}): DiscoverRun {
  return {
    id: 1, context: null, kinds: "all", status: "done", error: null, found: 0, proposed: 22, passed: 16,
    input_tokens: 2200, output_tokens: 4300, created_at: "2026-11-14 06:00:00", finished_at: "2026-11-14 06:00:30",
    ...over,
  };
}

function state(over: Partial<DiscoverState> = {}): DiscoverState {
  return {
    run: null, runs: [], suggestions: [], profile: { topics: [], feed_count: 0, x_count: 0, collections: [] },
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
    expect(screen.getByText("No suggestions waiting")).toBeInTheDocument();
    expect(screen.getByText(/Tell Trove what you're into/)).toBeInTheDocument();
  });

  it("starts a search for people only", async () => {
    const p = renderIt(state());
    await userEvent.click(screen.getByRole("button", { name: "People on X" }));
    await userEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(p.onStart).toHaveBeenCalledWith("", "x");
  });

  it("shows a failed run's error", () => {
    const failed = run({ status: "failed", error: "Claude is busy right now." });
    renderIt(state({ run: failed, runs: [failed] }));
    // In the banner and in the history row.
    expect(screen.getAllByText("Claude is busy right now.")).toHaveLength(2);
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

  it("explains every way a search can come back empty", () => {
    expect(runOutcome(run({ status: "running" }))).toBe("Finding…");
    expect(runOutcome(run({ found: 16 }))).toBe("16 new suggestions");
    expect(runOutcome(run({ proposed: 0, passed: 0 }))).toMatch(/didn't suggest anything/);
    expect(runOutcome(run({ proposed: 22, passed: 0 }))).toMatch(/None of the 22/);
    expect(runOutcome(run({ proposed: 22, passed: 16, found: 0 }))).toMatch(/all 16 were already suggested/);
    expect(runOutcome(run({ proposed: null, passed: null }))).toBe("Nothing new");
  });

  it("lists recent searches and filters to one search's results", async () => {
    const runs = [
      run({ id: 2, context: "wine", found: 1 }),
      run({ id: 1, context: null, found: 0, proposed: 22, passed: 16 }),
    ];
    renderIt(state({ runs, run: runs[0], suggestions: [sug({ run_id: 2 }), sug({ id: 5, run_id: 9, handle: "x", name: "Other" })] }));
    expect(screen.getByText("“wine”")).toBeInTheDocument();
    expect(screen.getByText("From your interests")).toBeInTheDocument();
    expect(screen.getByText(/all 16 were already suggested/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show 1 to review" }));
    expect(screen.getByText("Jancis Robinson")).toBeInTheDocument();
    expect(screen.queryByText("Other")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByText("Other")).toBeInTheDocument();
  });
});
