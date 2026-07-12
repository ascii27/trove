import { useState } from "react";

export function AddFeed({ onAddFeed }: { onAddFeed: (url: string) => Promise<void> }) {
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
      <button className="add-sm" onClick={() => setOpen(true)} aria-label="Add a feed">
        + Feed
      </button>
    );
  }

  return (
    <form className="capture feed-capture" onSubmit={submit}>
      <input
        autoFocus
        type="url"
        inputMode="url"
        placeholder="Feed or site URL"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label="Feed or site URL"
      />
      <div className="capture-row">
        <button type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add feed"}
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {err && <p className="capture-err">{err}</p>}
    </form>
  );
}
