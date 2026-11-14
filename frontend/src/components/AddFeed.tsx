import { useState } from "react";

interface Props {
  onAddFeed: (url: string) => Promise<void>;
  /** Labels — defaults are for RSS feeds; the X section reuses this for handles. */
  openLabel?: string;
  openAria?: string;
  placeholder?: string;
  submitLabel?: string;
  busyLabel?: string;
  inputType?: "url" | "text";
}

export function AddFeed({
  onAddFeed,
  openLabel = "+ Feed",
  openAria = "Add a feed",
  placeholder = "Feed or site URL",
  submitLabel = "Add feed",
  busyLabel = "Adding…",
  inputType = "url",
}: Props) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await onAddFeed(url.trim());
      setUrl("");
      setOpen(false);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="add-sm" onClick={() => setOpen(true)} aria-label={openAria}>
        {openLabel}
      </button>
    );
  }

  return (
    <form className="capture feed-capture" onSubmit={submit}>
      <input
        autoFocus
        type={inputType}
        inputMode={inputType === "url" ? "url" : "text"}
        autoCapitalize="off"
        autoCorrect="off"
        placeholder={placeholder}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label={placeholder}
      />
      <div className="capture-row">
        <button type="submit" disabled={busy}>
          {busy ? busyLabel : submitLabel}
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {err && <p className="capture-err">{err}</p>}
    </form>
  );
}
