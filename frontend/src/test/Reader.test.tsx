import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Reader } from "../components/Reader";
import { full } from "./factory";

describe("Reader", () => {
  it("prompts to select when nothing is open", () => {
    render(<Reader item={null} onMarkUnread={vi.fn()} onRetry={vi.fn()} onBack={vi.fn()} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />);
    expect(screen.getByText(/select something to read/i)).toBeInTheDocument();
  });

  it("renders the article, metadata, and a working Mark unread", async () => {
    const onMarkUnread = vi.fn();
    render(<Reader item={full({ read_state: "read" })} onMarkUnread={onMarkUnread} onRetry={vi.fn()} onBack={vi.fn()} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/internal developer platform/i);
    expect(screen.getByText(/adoption is voluntary/i)).toBeInTheDocument(); // summary
    expect(screen.getByText("Analysis")).toBeInTheDocument(); // source-type pill
    expect(screen.getByText("Mandated platforms rot.")).toBeInTheDocument(); // claim
    expect(screen.getByText("platform engineering")).toBeInTheDocument(); // topic

    await userEvent.click(screen.getByRole("button", { name: /mark unread/i }));
    expect(onMarkUnread).toHaveBeenCalledWith(full().id);
  });

  it("shows the analyzing state while enrichment is pending", () => {
    render(
      <Reader
        item={full({ enrichment_status: "enriching", summary: null, topics: [], claims: [] })}
        onMarkUnread={vi.fn()}
        onRetry={vi.fn()} onBack={vi.fn()} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()}
      />
    );
    expect(screen.getByText(/analyzing/i)).toBeInTheDocument();
  });

  it("shows the failed state with a retry that fires onRetry", async () => {
    const onRetry = vi.fn();
    render(
      <Reader
        item={full({ extraction_status: "failed", error_message: "Could not reach the page." })}
        onMarkUnread={vi.fn()}
        onRetry={onRetry} onBack={vi.fn()} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()}
      />
    );
    expect(screen.getByText(/couldn't extract this page/i)).toBeInTheDocument();
    expect(screen.getByText(/could not reach the page/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry extraction/i }));
    expect(onRetry).toHaveBeenCalledWith(full().id);
  });

  it("flags a partial capture", () => {
    render(<Reader item={full({ extraction_status: "partial" })} onMarkUnread={vi.fn()} onRetry={vi.fn()} onBack={vi.fn()} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />);
    expect(screen.getByText(/looks partial/i)).toBeInTheDocument();
  });

  it("offers a back control that fires onBack (mobile navigation)", async () => {
    const onBack = vi.fn();
    render(<Reader item={full()} onMarkUnread={vi.fn()} onRetry={vi.fn()} onBack={onBack} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /back to the list/i }));
    expect(onBack).toHaveBeenCalled();
  });

  it("shows no back control when nothing is open", () => {
    render(<Reader item={null} onMarkUnread={vi.fn()} onRetry={vi.fn()} onBack={vi.fn()} onSave={vi.fn()} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /back to the list/i })).not.toBeInTheDocument();
  });

  it("adds the open item to a collection via the picker", async () => {
    const onToggleCollection = vi.fn();
    render(
      <Reader
        item={full({ id: 7, read_state: "read", collection_ids: [] })}
        onMarkUnread={vi.fn()}
        onRetry={vi.fn()}
        onBack={vi.fn()}
        onSave={vi.fn()}
        highlightTopics={[]}
        collections={[{ id: 3, name: "AI research", query: "AI", item_count: 2 }]}
        onToggleCollection={onToggleCollection}
        onCreateCollectionForItem={vi.fn()}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: /add to collection/i }));
    await userEvent.click(screen.getByRole("menuitemcheckbox", { name: /ai research/i }));
    expect(onToggleCollection).toHaveBeenCalledWith(3, 7, false);
  });

  it("shows Save to library only for feed items and fires onSave", async () => {
    const onSave = vi.fn();
    const { rerender } = render(
      <Reader item={full({ lane: "saved" })} onMarkUnread={vi.fn()} onRetry={vi.fn()} onBack={vi.fn()} onSave={onSave} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />
    );
    expect(screen.queryByRole("button", { name: /save to library/i })).not.toBeInTheDocument();

    rerender(
      <Reader item={full({ id: 3, lane: "feed" })} onMarkUnread={vi.fn()} onRetry={vi.fn()} onBack={vi.fn()} onSave={onSave} highlightTopics={[]} collections={[]} onToggleCollection={vi.fn()} onCreateCollectionForItem={vi.fn()} />
    );
    await userEvent.click(screen.getByRole("button", { name: /save to library/i }));
    expect(onSave).toHaveBeenCalledWith(3);
  });
});
