import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { List } from "../components/List";
import { summary } from "./factory";

const noop = vi.fn();

describe("List", () => {
  it("shows the empty-library invitation when nothing is saved", () => {
    render(<List items={[]} view="all" feedTitle={null} loaded selectedId={null} notice={null} error={null} lensQuery="" onLensChange={noop} lensFocusTick={0} lensInfo={null} onSelect={noop} onDelete={noop} onBackToNav={noop} />);
    expect(screen.getByText(/library is empty/i)).toBeInTheDocument();
    expect(screen.getByText(/save your first article/i)).toBeInTheDocument();
  });

  it("says you're caught up when there are no unread items", () => {
    render(<List items={[]} view="unread" feedTitle={null} loaded selectedId={null} notice={null} error={null} lensQuery="" onLensChange={noop} lensFocusTick={0} lensInfo={null} onSelect={noop} onDelete={noop} onBackToNav={noop} />);
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });

  it("marks unread items with the Unread tag and read items without", () => {
    render(
      <List
        items={[summary({ id: 1, read_state: "unread" }), summary({ id: 2, read_state: "read", title: "Read one" })]}
        view="all" feedTitle={null}
        loaded
        selectedId={null}
        notice={null}
        error={null} lensQuery="" onLensChange={noop} lensFocusTick={0} lensInfo={null}
        onSelect={noop} onDelete={noop} onBackToNav={noop}
      />
    );
    // exactly one Unread tag (the unread card)
    expect(screen.getAllByText("Unread")).toHaveLength(1);
    const readOpen = screen.getByRole("button", { name: "Read one" });
    expect(readOpen.closest(".card")).toHaveClass("read");
  });

  it("deletes an item after an inline confirm", async () => {
    const onDelete = vi.fn();
    render(
      <List
        items={[summary({ id: 7, title: "Doomed" })]}
        view="all" feedTitle={null}
        loaded
        selectedId={null}
        notice={null}
        error={null} lensQuery="" onLensChange={noop} lensFocusTick={0} lensInfo={null}
        onSelect={vi.fn()}
        onDelete={onDelete} onBackToNav={noop}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /delete doomed/i }));
    // opening the card must not have fired; a confirm appears
    await userEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(onDelete).toHaveBeenCalledWith(7);
  });

  it("shows an extracting hint while a capture is in progress", () => {
    render(
      <List
        items={[summary({ extraction_status: "extracting", enrichment_status: "pending", summary: null, title: null })]}
        view="all" feedTitle={null}
        loaded
        selectedId={null}
        notice={null}
        error={null} lensQuery="" onLensChange={noop} lensFocusTick={0} lensInfo={null}
        onSelect={noop} onDelete={noop} onBackToNav={noop}
      />
    );
    expect(screen.getByText(/extracting the article/i)).toBeInTheDocument();
  });

  it("offers a back-to-menu control (mobile) that fires onBackToNav", async () => {
    const onBackToNav = vi.fn();
    render(
      <List
        items={[summary()]}
        view="feed"
        feedTitle="Pragmatic Engineer"
        loaded
        selectedId={null}
        notice={null}
        error={null} lensQuery="" onLensChange={noop} lensFocusTick={0} lensInfo={null}
        onSelect={noop}
        onDelete={noop}
        onBackToNav={onBackToNav}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /back to menu/i }));
    expect(onBackToNav).toHaveBeenCalled();
  });

  it("renders lens results with a 'reading about' header and cross-lane tags", () => {
    render(
      <List
        items={[summary({ id: 1, lane: "saved" }), summary({ id: 2, lane: "feed", title: "Feed item" })]}
        view="all"
        feedTitle={null}
        loaded
        selectedId={null}
        notice={null}
        error={null}
        lensQuery="AI"
        onLensChange={noop}
        lensFocusTick={0}
        lensInfo={{ savedCount: 1, feedCount: 1 }}
        onSelect={noop}
        onDelete={noop}
        onBackToNav={noop}
      />
    );
    expect(screen.getByText(/reading about/i)).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument(); // the lens term
    expect(screen.getByText("Saved")).toBeInTheDocument(); // cross-lane origin tag
    expect(screen.getByText("Feed")).toBeInTheDocument();
  });
});
