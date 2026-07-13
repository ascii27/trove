import { useEffect, useRef, useState } from "react";
import type { Collection } from "../types";

interface Props {
  collections: Collection[];
  memberIds: number[];
  onToggle: (collectionId: number, isMember: boolean) => void;
  onCreate: (name: string) => void;
}

export function CollectionPicker({ collections, memberIds, onToggle, onCreate }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const inCount = memberIds.length;

  return (
    <div className="collpick" ref={ref}>
      <button className="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {inCount > 0 ? `In ${inCount} collection${inCount === 1 ? "" : "s"}` : "Add to collection"}
      </button>
      {open && (
        <div className="collpick-pop" role="menu">
          {collections.length === 0 && <div className="collpick-empty muted">No collections yet — create one below.</div>}
          {collections.map((c) => {
            const isMember = memberIds.includes(c.id);
            return (
              <button
                key={c.id}
                className={`collpick-item ${isMember ? "on" : ""}`}
                role="menuitemcheckbox"
                aria-checked={isMember}
                onClick={() => onToggle(c.id, isMember)}
              >
                <span className="check" aria-hidden="true">
                  {isMember ? "✓" : ""}
                </span>
                <span className="collpick-name">{c.name}</span>
              </button>
            );
          })}
          <form
            className="collpick-new"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              onCreate(name.trim());
              setName("");
            }}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="New collection…"
              aria-label="New collection name"
            />
          </form>
        </div>
      )}
    </div>
  );
}
