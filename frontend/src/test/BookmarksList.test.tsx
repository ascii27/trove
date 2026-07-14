import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BookmarksList } from "../components/BookmarksList";
import { bookmark } from "./factory";

function renderList(over = {}) {
  const props = {
    bookmarks: [
      bookmark({ id: 1, title: "ripgrep", topics: ["CLI", "search"] }),
      bookmark({ id: 2, title: "Postgres docs", source: "postgresql.org", topics: ["docs"], original_url: "https://www.postgresql.org/docs/" }),
    ],
    loaded: true,
    onDelete: vi.fn(),
    onAddTag: vi.fn(),
    onRemoveTag: vi.fn(),
    onBackToNav: vi.fn(),
    ...over,
  };
  render(<BookmarksList {...props} />);
  return props;
}

describe("BookmarksList", () => {
  it("renders bookmark titles as external links to the original URL", () => {
    renderList();
    const link = screen.getByRole("link", { name: "ripgrep" });
    expect(link).toHaveAttribute("href", "https://github.com/BurntSushi/ripgrep");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("filters bookmarks by a tag", async () => {
    renderList();
    expect(screen.getByRole("link", { name: "ripgrep" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Postgres docs" })).toBeInTheDocument();

    // the filter chip carries its count; clicking narrows the list
    await userEvent.click(screen.getByRole("button", { name: /^docs/ }));
    expect(screen.queryByRole("link", { name: "ripgrep" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Postgres docs" })).toBeInTheDocument();
  });

  it("adds and removes tags", async () => {
    const props = renderList();
    const card = screen.getByRole("link", { name: "ripgrep" }).closest(".bm-card") as HTMLElement;

    await userEvent.click(within(card).getByRole("button", { name: /remove tag cli/i }));
    expect(props.onRemoveTag).toHaveBeenCalledWith(1, "CLI");

    await userEvent.click(within(card).getByRole("button", { name: /\+ tag/i }));
    await userEvent.type(within(card).getByLabelText(/new tag/i), "rust{Enter}");
    expect(props.onAddTag).toHaveBeenCalledWith(1, "rust");
  });

  it("shows a fetching state while a bookmark is still pending", () => {
    renderList({ bookmarks: [bookmark({ id: 3, summary: null, extraction_status: "extracting" })] });
    expect(screen.getByText(/fetching details/i)).toBeInTheDocument();
  });

  it("invites the user when there are no bookmarks", () => {
    renderList({ bookmarks: [] });
    expect(screen.getByText(/no bookmarks yet/i)).toBeInTheDocument();
  });
});
