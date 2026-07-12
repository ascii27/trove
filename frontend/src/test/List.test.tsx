import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { List } from "../components/List";
import { summary } from "./factory";

const noop = vi.fn();

describe("List", () => {
  it("shows the empty-library invitation when nothing is saved", () => {
    render(<List items={[]} view="all" feedTitle={null} loaded selectedId={null} notice={null} error={null} onSelect={noop} onDelete={noop} />);
    expect(screen.getByText(/library is empty/i)).toBeInTheDocument();
    expect(screen.getByText(/save your first article/i)).toBeInTheDocument();
  });

  it("says you're caught up when there are no unread items", () => {
    render(<List items={[]} view="unread" feedTitle={null} loaded selectedId={null} notice={null} error={null} onSelect={noop} onDelete={noop} />);
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
        error={null}
        onSelect={noop} onDelete={noop}
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
        error={null}
        onSelect={vi.fn()}
        onDelete={onDelete}
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
        error={null}
        onSelect={noop} onDelete={noop}
      />
    );
    expect(screen.getByText(/extracting the article/i)).toBeInTheDocument();
  });
});
