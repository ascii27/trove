import { describe, expect, it } from "vitest";
import { offsetsOf, paintHighlights } from "../highlights";
import type { Highlight } from "../types";

function prose(html: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "prose";
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

function hl(over: Partial<Highlight> & Pick<Highlight, "start_offset" | "end_offset" | "quote">): Highlight {
  return { id: 1, created_at: "2026-07-14", ...over };
}

/** A range over absolute char offsets, mirroring what a user selection yields. */
function rangeAt(root: HTMLElement, start: number, end: number): Range {
  const nodes: Text[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n: Node | null;
  while ((n = walker.nextNode())) nodes.push(n as Text);
  const locate = (target: number): [Text, number] => {
    let pos = 0;
    for (const node of nodes) {
      if (target <= pos + node.data.length) return [node, target - pos];
      pos += node.data.length;
    }
    const last = nodes[nodes.length - 1];
    return [last, last.data.length];
  };
  const r = document.createRange();
  const [sn, so] = locate(start);
  const [en, eo] = locate(end);
  r.setStart(sn, so);
  r.setEnd(en, eo);
  return r;
}

describe("offsetsOf", () => {
  it("maps a selection within one text node to absolute offsets", () => {
    const root = prose("<p>Hello world</p>");
    expect(offsetsOf(root, rangeAt(root, 6, 11))).toEqual({ start: 6, end: 11 }); // "world"
  });

  it("maps a selection spanning element boundaries", () => {
    const root = prose("<p>alpha</p><p>beta</p>"); // text = "alphabeta"
    const off = offsetsOf(root, rangeAt(root, 3, 7)); // "habe"
    expect(off).toEqual({ start: 3, end: 7 });
  });

  it("returns null for an endpoint outside the root", () => {
    const root = prose("<p>inside</p>");
    const outside = document.createElement("p");
    outside.textContent = "outside";
    document.body.appendChild(outside);
    const r = document.createRange();
    r.setStart(root.firstChild!.firstChild!, 0);
    r.setEnd(outside.firstChild!, 3);
    expect(offsetsOf(root, r)).toBeNull();
  });

  it("returns null for a collapsed selection", () => {
    const root = prose("<p>text</p>");
    expect(offsetsOf(root, rangeAt(root, 2, 2))).toBeNull();
  });
});

describe("paintHighlights", () => {
  it("wraps exactly the highlighted characters in one node", () => {
    const root = prose("<p>Hello world</p>");
    paintHighlights(root, [hl({ start_offset: 6, end_offset: 11, quote: "world" })]);
    const marks = root.querySelectorAll("mark.hl");
    expect(marks.length).toBe(1);
    expect(marks[0].textContent).toBe("world");
    expect(marks[0].getAttribute("data-hl-id")).toBe("1");
    expect(root.textContent).toBe("Hello world"); // text preserved
  });

  it("wraps a highlight spanning multiple elements", () => {
    const root = prose("<p>alpha</p><p>beta</p>"); // "alphabeta"
    paintHighlights(root, [hl({ start_offset: 3, end_offset: 7, quote: "habe" })]);
    const marks = root.querySelectorAll("mark.hl");
    expect(marks.length).toBe(2); // one per element it crosses
    expect(Array.from(marks, (m) => m.textContent).join("")).toBe("habe");
  });

  it("wraps two adjacent highlights independently", () => {
    const root = prose("<p>one two three</p>");
    paintHighlights(root, [
      hl({ id: 1, start_offset: 0, end_offset: 3, quote: "one" }),
      hl({ id: 2, start_offset: 8, end_offset: 13, quote: "three" }),
    ]);
    const marks = root.querySelectorAll("mark.hl");
    expect(Array.from(marks, (m) => m.textContent)).toEqual(["one", "three"]);
  });

  it("is idempotent — repainting yields the same DOM", () => {
    const root = prose("<p>Hello world</p>");
    const hs = [hl({ start_offset: 6, end_offset: 11, quote: "world" })];
    paintHighlights(root, hs);
    const once = root.innerHTML;
    paintHighlights(root, hs);
    expect(root.innerHTML).toBe(once);
  });

  it("clears marks when repainted with none", () => {
    const root = prose("<p>Hello world</p>");
    paintHighlights(root, [hl({ start_offset: 6, end_offset: 11, quote: "world" })]);
    paintHighlights(root, []);
    expect(root.querySelectorAll("mark.hl").length).toBe(0);
    expect(root.textContent).toBe("Hello world");
  });

  it("skips a highlight whose quote no longer matches its offsets", () => {
    const root = prose("<p>Hello world</p>");
    paintHighlights(root, [hl({ start_offset: 6, end_offset: 11, quote: "stale" })]);
    expect(root.querySelectorAll("mark.hl").length).toBe(0);
  });
});
