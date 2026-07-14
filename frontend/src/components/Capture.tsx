import { useState } from "react";

type Kind = "saved" | "bookmark";

export function Capture({ onCapture }: { onCapture: (url: string, kind: Kind) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState<Kind>("saved");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await onCapture(url.trim(), kind);
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
      <div className="capture-kind" role="radiogroup" aria-label="How to save this URL">
        <button
          type="button"
          role="radio"
          aria-checked={kind === "saved"}
          className={kind === "saved" ? "on" : ""}
          onClick={() => setKind("saved")}
        >
          Read later
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={kind === "bookmark"}
          className={kind === "bookmark" ? "on" : ""}
          onClick={() => setKind("bookmark")}
        >
          Bookmark
        </button>
      </div>
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
