import { describe, expect, it } from "vitest";
import { dayLabel, groupPosts, UNSORTED, UNTAGGED } from "../xgroup";
import { xPost } from "./factory";

// Local-noon timestamps keep day bucketing stable regardless of the test machine's zone.
const at = (y: number, m: number, d: number) => {
  const dt = new Date(y, m - 1, d, 12, 0, 0);
  return dt.toISOString().replace(/\.\d+Z$/, "");
};
const NOW = new Date(2026, 10, 11, 18, 0, 0);

describe("groupPosts", () => {
  it("groups by day, newest first, with friendly labels", () => {
    const posts = [
      xPost({ id: 1, published_at: at(2026, 11, 11) }),
      xPost({ id: 2, published_at: at(2026, 11, 11) }),
      xPost({ id: 3, published_at: at(2026, 11, 10) }),
      xPost({ id: 4, published_at: at(2026, 11, 2) }),
    ];
    const groups = groupPosts(posts, "date", NOW);
    expect(groups.map((g) => g.label.split(",")[0])).toEqual(["Today", "Yesterday", "Monday"]);
    expect(groups[0].posts.map((p) => p.id)).toEqual([1, 2]);
  });

  it("groups by theme, biggest first, unsorted last", () => {
    const posts = [
      xPost({ id: 1, theme: null }),
      xPost({ id: 2, theme: "Climate" }),
      xPost({ id: 3, theme: "AI agents" }),
      xPost({ id: 4, theme: "AI agents" }),
    ];
    expect(groupPosts(posts, "theme").map((g) => [g.label, g.posts.length])).toEqual([
      ["AI agents", 2],
      ["Climate", 1],
      [UNSORTED, 1],
    ]);
  });

  it("groups by tag, listing a multi-tag post under each tag", () => {
    const posts = [xPost({ id: 1, topics: ["ideas", "evals"] }), xPost({ id: 2, topics: ["evals"] }), xPost({ id: 3 })];
    const groups = groupPosts(posts, "tag");
    expect(groups.map((g) => g.label)).toEqual(["evals", "ideas", UNTAGGED]);
    expect(groups[0].posts.map((p) => p.id)).toEqual([1, 2]);
  });

  it("labels other-year dates with the year", () => {
    expect(dayLabel(new Date(2025, 0, 3, 12), NOW)).toMatch(/2025/);
  });
});
