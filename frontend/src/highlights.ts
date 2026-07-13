/**
 * Anchoring highlights to the rendered article, independent of React.
 *
 * A highlight is stored as a half-open character range [start, end) into the
 * concatenated text of the `.prose` root. Because `content_text` is immutable
 * and Markdown rendering is deterministic, those offsets stay valid across
 * re-renders. Repainting is a post-render DOM pass (never baked into the
 * sanitized HTML), and it verifies the text still matches the stored quote
 * before wrapping, so a stale offset paints nothing rather than the wrong span.
 */
import type { Highlight } from "./types";

/** All text nodes under `root`, in document order. */
function textNodes(root: Node): Text[] {
  const doc = root.ownerDocument ?? document;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let n: Node | null;
  while ((n = walker.nextNode())) nodes.push(n as Text);
  return nodes;
}

/** Absolute char offset of a Range boundary point within `root`. */
function pointOffset(root: HTMLElement, node: Node, offset: number): number {
  const r = (root.ownerDocument ?? document).createRange();
  r.setStart(root, 0);
  r.setEnd(node, offset);
  return r.toString().length;
}

/** The text currently occupying [start, end) in `root`. */
function sliceText(root: HTMLElement, start: number, end: number): string {
  let pos = 0;
  let out = "";
  for (const node of textNodes(root)) {
    const len = node.data.length;
    const s = Math.max(start, pos);
    const e = Math.min(end, pos + len);
    if (s < e) out += node.data.slice(s - pos, e - pos);
    pos += len;
  }
  return out;
}

/**
 * Map a DOM Range to absolute [start, end) offsets within `root`.
 * Returns null if either endpoint lies outside `root` or the range is empty.
 */
export function offsetsOf(root: HTMLElement, range: Range): { start: number; end: number } | null {
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  const start = pointOffset(root, range.startContainer, range.startOffset);
  const end = pointOffset(root, range.endContainer, range.endOffset);
  if (end <= start) return null;
  return { start, end };
}

/** Wrap the characters in [start, end) with <mark class="hl" data-hl-id>. */
function wrapRange(root: HTMLElement, start: number, end: number, id: number): void {
  // Collect the segment of each text node that intersects the range first, so
  // the cumulative offsets aren't disturbed by the splitText mutations below.
  const segments: { node: Text; from: number; to: number }[] = [];
  let pos = 0;
  for (const node of textNodes(root)) {
    const len = node.data.length;
    const s = Math.max(start, pos);
    const e = Math.min(end, pos + len);
    if (s < e) segments.push({ node, from: s - pos, to: e - pos });
    pos += len;
  }
  const doc = root.ownerDocument ?? document;
  for (const seg of segments) {
    let node = seg.node;
    if (seg.to < node.data.length) node.splitText(seg.to); // trailing part → sibling
    if (seg.from > 0) node = node.splitText(seg.from); // node now === [from, to)
    const mark = doc.createElement("mark");
    mark.className = "hl";
    mark.dataset.hlId = String(id);
    node.parentNode!.replaceChild(mark, node);
    mark.appendChild(node);
  }
}

/** Remove every highlight <mark> under `root`, restoring the original text. */
function unpaint(root: HTMLElement): void {
  for (const m of Array.from(root.querySelectorAll("mark.hl"))) {
    const parent = m.parentNode!;
    while (m.firstChild) parent.insertBefore(m.firstChild, m);
    parent.removeChild(m);
  }
  root.normalize(); // merge the text nodes back so offsets recompute cleanly
}

/**
 * Repaint `root` so exactly `highlights` are marked. Idempotent: clears any
 * existing marks first, then wraps each highlight whose stored quote still
 * matches the text at its offsets (mismatches are skipped, not mis-painted).
 */
export function paintHighlights(root: HTMLElement, highlights: Highlight[]): void {
  unpaint(root);
  for (const h of highlights) {
    if (sliceText(root, h.start_offset, h.end_offset) !== h.quote) continue;
    wrapRange(root, h.start_offset, h.end_offset, h.id);
  }
}
