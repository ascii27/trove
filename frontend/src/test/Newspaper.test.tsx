import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Newspaper } from "../components/Newspaper";
import type { Edition, EditionSummary, PaperState, PaperStory } from "../types";

function story(id: number, headline: string, over: Partial<PaperStory> = {}): PaperStory {
  return {
    item_id: id, lane: "feed", headline, summary: `About ${headline}.`, original_title: headline,
    source: "The Batch", author: null, url: `https://example.com/${id}`, image: null,
    published_at: "2026-11-20T08:00:00", ...over,
  };
}

function summary(over: Partial<EditionSummary> = {}): EditionSummary {
  return {
    id: 2, number: 2, status: "done", trigger: "manual", error: null, window_start: "2026-11-19 00:00:00",
    story_count: 4, created_at: "2026-11-20 14:00:00", finished_at: "2026-11-20 14:00:20", ...over,
  };
}

const EDITION: Edition = {
  ...summary(),
  layout: {
    editors_note: "Big day for AI.",
    lead: story(1, "Lead story", { image: "https://img.example/lead.jpg" }),
    sections: [
      { name: "AI", stories: [story(2, "Top AI story", { image: "https://img.example/ai.jpg" }), story(3, "Second AI story")] },
    ],
    from_x: [story(4, "swyx", { lane: "x", summary: "Netlify refounds for AI." })],
    from_shelf: [story(5, "A saved essay", { lane: "saved" })],
    source_count: 3,
  },
};

function state(over: Partial<PaperState> = {}): PaperState {
  return {
    editions: [summary(), summary({ id: 1, number: 1, created_at: "2026-11-19 14:00:00" })],
    running: null, latest_id: 2,
    settings: { schedule: "off", hour: 6, tz: "UTC", last_scheduled: null },
    ...over,
  };
}

function renderIt(over: Partial<React.ComponentProps<typeof Newspaper>> = {}) {
  const props = {
    state: state(), edition: EDITION, loadingEdition: false,
    onSelectEdition: vi.fn(), onPrint: vi.fn().mockResolvedValue(undefined),
    onSaveSchedule: vi.fn().mockResolvedValue(undefined), onOpenStory: vi.fn(), onBackToNav: vi.fn(),
    ...over,
  };
  render(<Newspaper {...props} />);
  return props;
}

describe("Newspaper", () => {
  it("lays out the masthead, lead, sections and boxes", () => {
    renderIt();
    expect(screen.getByRole("heading", { level: 1, name: "The Trove" })).toBeInTheDocument();
    expect(screen.getByText("No. 2")).toBeInTheDocument();
    expect(screen.getByText("4 stories · 3 sources")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Lead story" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "AI" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Overheard on X" })).toHaveTextContent("Netlify refounds for AI.");
    expect(screen.getByRole("complementary", { name: "From your reading list" })).toHaveTextContent("A saved essay");
    // Pictures only where the edition has them: the lead and the section's top story.
    expect(document.querySelectorAll("img")).toHaveLength(2);
  });

  it("opens a story through the app instead of navigating away", async () => {
    const p = renderIt();
    await userEvent.click(screen.getByRole("link", { name: "Second AI story" }));
    expect(p.onOpenStory).toHaveBeenCalledWith(expect.objectContaining({ item_id: 3 }));
  });

  it("switches back issues and prints a new edition", async () => {
    const p = renderIt();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Back issues" }), "1");
    expect(p.onSelectEdition).toHaveBeenCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "Print a new edition" }));
    expect(p.onPrint).toHaveBeenCalled();
  });

  it("sets a schedule", async () => {
    const p = renderIt();
    await userEvent.click(screen.getByRole("button", { name: "Not scheduled" }));
    await userEvent.click(screen.getByRole("button", { name: "Weekends" }));
    expect(p.onSaveSchedule).toHaveBeenCalledWith("weekends", 6);
  });

  it("explains a skipped scheduled edition", () => {
    const skipped = summary({ id: 3, number: null, status: "failed", trigger: "schedule",
      error: "Not enough new stories since the last edition (1)." });
    renderIt({ state: state({ editions: [skipped, summary()] }) });
    expect(screen.getByText(/The scheduled edition .* wasn't printed: Not enough new stories/)).toBeInTheDocument();
  });

  it("invites the first edition", async () => {
    const p = renderIt({ state: state({ editions: [], latest_id: null }), edition: null });
    await userEvent.click(screen.getByRole("button", { name: "Print the first edition" }));
    expect(p.onPrint).toHaveBeenCalled();
  });
});
