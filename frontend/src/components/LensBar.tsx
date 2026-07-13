import { useEffect, useRef } from "react";

interface Props {
  value: string;
  onChange: (q: string) => void;
  focusTick: number;
}

export function LensBar({ value, onChange, focusTick }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (focusTick > 0) ref.current?.focus();
  }, [focusTick]);

  return (
    <div className="lens-bar">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4.3-4.3" />
      </svg>
      <input
        ref={ref}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="What do you want to read about?"
        aria-label="Search your library"
        autoComplete="off"
      />
      {value && (
        <button className="lens-clear" onClick={() => onChange("")} aria-label="Clear search">
          ×
        </button>
      )}
    </div>
  );
}
