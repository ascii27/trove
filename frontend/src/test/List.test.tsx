import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { List } from "../components/List";
import { summary } from "./factory";

const noop = vi.fn();

describe("List", () => {
  it("shows the empty-library invitation when nothing is saved", () => {
    render(<List items={[]} view="all" loaded selectedId={null} notice={null} error={null} onSelect={noop} />);
    expect(screen.getByText(/library is empty/i)).toBeInTheDocument();
    expect(screen.getByText(/save your first article/i)).toBeInTheDocument();
  });

  it("says you're caught up when there are no unread items", () => {
    render(<List items={[]} view="unread" loaded selectedId={null} notice={null} error={null} onSelect={noop} />);
    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });

  it("marks unread items with the Unread tag and read items without", () => {
    render(
      <List
        items={[summary({ id: 1, read_state: "unread" }), summary({ id: 2, read_state: "read", title: "Read one" })]}
        view="all"
        loaded
        selectedId={null}
        notice={null}
        error={null}
        onSelect={noop}
      />
    );
    // exactly one Unread tag (the unread card)
    expect(screen.getAllByText("Unread")).toHaveLength(1);
    const readCard = screen.getByRole("button", { name: "Read one" });
    expect(readCard).toHaveClass("read");
  });

  it("shows an extracting hint while a capture is in progress", () => {
    render(
      <List
        items={[summary({ extraction_status: "extracting", enrichment_status: "pending", summary: null, title: null })]}
        view="all"
        loaded
        selectedId={null}
        notice={null}
        error={null}
        onSelect={noop}
      />
    );
    expect(screen.getByText(/extracting the article/i)).toBeInTheDocument();
  });
});
