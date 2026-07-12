import { useState } from "react";

export function Capture({ onCapture }: { onCapture: (url: string) => Promise<void> }) {
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
      await onCapture(url.trim());
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
      <button className="add" onClick={() => setOpen(true)} aria-label="Save a URL">
        + URL
      </button>
    );
  }

  return (
    <form className="capture" onSubmit={submit}>
      <input
        autoFocus
        type="url"
        inputMode="url"
        placeholder="Paste a URL to save"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label="URL to save"
      />
      <div className="capture-row">
        <button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" className="ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {err && <p className="capture-err">{err}</p>}
    </form>
  );
}
