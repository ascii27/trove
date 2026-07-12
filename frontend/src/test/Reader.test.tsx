import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Reader } from "../components/Reader";
import { full } from "./factory";

describe("Reader", () => {
  it("prompts to select when nothing is open", () => {
    render(<Reader item={null} onMarkUnread={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText(/select something to read/i)).toBeInTheDocument();
  });

  it("renders the article, metadata, and a working Mark unread", async () => {
    const onMarkUnread = vi.fn();
    render(<Reader item={full({ read_state: "read" })} onMarkUnread={onMarkUnread} onRetry={vi.fn()} />);

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
        onRetry={vi.fn()}
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
        onRetry={onRetry}
      />
    );
    expect(screen.getByText(/couldn't extract this page/i)).toBeInTheDocument();
    expect(screen.getByText(/could not reach the page/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /retry extraction/i }));
    expect(onRetry).toHaveBeenCalledWith(full().id);
  });

  it("flags a partial capture", () => {
    render(<Reader item={full({ extraction_status: "partial" })} onMarkUnread={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByText(/looks partial/i)).toBeInTheDocument();
  });
});
