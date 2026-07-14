import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Capture } from "../components/Capture";

describe("Capture", () => {
  it("defaults to read-later and passes the chosen kind", async () => {
    const onCapture = vi.fn().mockResolvedValue(undefined);
    render(<Capture onCapture={onCapture} />);

    await userEvent.click(screen.getByRole("button", { name: /save a url/i }));
    await userEvent.type(screen.getByLabelText(/url to save/i), "https://ex.com/a");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onCapture).toHaveBeenCalledWith("https://ex.com/a", "saved");
  });

  it("captures as a bookmark when the toggle is set", async () => {
    const onCapture = vi.fn().mockResolvedValue(undefined);
    render(<Capture onCapture={onCapture} />);

    await userEvent.click(screen.getByRole("button", { name: /save a url/i }));
    await userEvent.type(screen.getByLabelText(/url to save/i), "https://ex.com/tool");
    await userEvent.click(screen.getByRole("radio", { name: /bookmark/i }));
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onCapture).toHaveBeenCalledWith("https://ex.com/tool", "bookmark");
  });
});
