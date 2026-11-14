import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { XStream } from "../components/XStream";
import { xAccount, xPost } from "./factory";

function setup(over: Partial<Parameters<typeof XStream>[0]> = {}) {
  const props = {
    posts: [
      xPost({ id: 1, theme: "AI agents", topics: ["evals"] }),
      xPost({ id: 2, theme: "Climate", title: "Heat pumps", content_text: "Heat pumps are winning.", read_state: "read" as const }),
    ],
    account: null,
    status: { configured: true, mode: "api" as const, message: null },
    loaded: true,
    error: null,
    grouping: "date" as const,
    onGroupingChange: vi.fn(),
    onMark: vi.fn(),
    onAddTag: vi.fn(),
    onRemoveTag: vi.fn(),
    onSetTheme: vi.fn(),
    onAddHighlight: vi.fn(),
    onRemoveHighlight: vi.fn(),
    onRefresh: vi.fn().mockResolvedValue(undefined),
    onBackToNav: vi.fn(),
    ...over,
  };
  render(<XStream {...props} />);
  return props;
}

describe("XStream", () => {
  it("renders posts under group headings and switches grouping", async () => {
    const props = setup({ grouping: "theme" });
    expect(screen.getByRole("region", { name: "AI agents" })).toHaveTextContent("Agents need better evals.");
    expect(screen.getByRole("region", { name: "Climate" })).toHaveTextContent("Heat pumps are winning.");
    await userEvent.click(screen.getByRole("button", { name: "Tag" }));
    expect(props.onGroupingChange).toHaveBeenCalledWith("tag");
  });

  it("marks a group read and filters by tag", async () => {
    const props = setup();
    await userEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    expect(props.onMark).toHaveBeenCalledWith([1], "read");
    await userEvent.click(screen.getByRole("button", { name: /^evals/ }));
    expect(screen.queryByText("Heat pumps are winning.")).not.toBeInTheDocument();
  });

  it("adds a tag to a post", async () => {
    const props = setup({ posts: [xPost({ id: 7 })] });
    await userEvent.click(screen.getByRole("button", { name: "+ tag" }));
    await userEvent.type(screen.getByLabelText("New tag"), "ideas{enter}");
    expect(props.onAddTag).toHaveBeenCalledWith(7, "ideas");
  });

  it("paints saved highlights inside the post", () => {
    setup({
      posts: [xPost({ id: 3, highlights: [{ id: 9, quote: "better evals", start_offset: 12, end_offset: 24, created_at: "" }] })],
    });
    const mark = document.querySelector("mark.hl");
    expect(mark).toHaveTextContent("better evals");
  });

  it("invites setup when X isn't connected", () => {
    setup({ posts: [], status: { configured: false, mode: null, message: "Set TROVE_X_BEARER_TOKEN." } });
    expect(screen.getByText("Connect X to start following people.")).toBeInTheDocument();
  });

  it("checks one account for new posts", async () => {
    const props = setup({ account: xAccount({ id: 4 }) });
    const head = screen.getByRole("heading", { name: "Jane Doe" }).parentElement!.parentElement!;
    await userEvent.click(within(head).getByRole("button", { name: "Check for new posts" }));
    expect(props.onRefresh).toHaveBeenCalledWith(4);
  });
});
