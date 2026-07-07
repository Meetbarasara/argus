import { describe, expect, it } from "vitest";
import type { Span } from "../api";
import { buildSpanTree, countDescendants, flattenTree } from "./spanTree";

function span(id: string, parent: string | null, start: string): Span {
  return {
    span_id: id,
    trace_id: "t",
    incident_id: "i",
    parent_span_id: parent,
    name: id,
    kind: "node",
    status: "OK",
    started_at: start,
    ended_at: start,
    duration_ms: 1,
    attrs: {},
  };
}

describe("buildSpanTree", () => {
  it("nests children under parents and sorts siblings by start time", () => {
    const spans = [
      span("root", null, "2026-01-01T00:00:00.000Z"),
      span("b", "root", "2026-01-01T00:00:02.000Z"),
      span("a", "root", "2026-01-01T00:00:01.000Z"),
      span("a1", "a", "2026-01-01T00:00:01.500Z"),
    ];
    const roots = buildSpanTree(spans);
    expect(roots).toHaveLength(1);
    expect(roots[0].span.span_id).toBe("root");
    expect(roots[0].depth).toBe(0);
    expect(roots[0].children.map((c) => c.span.span_id)).toEqual(["a", "b"]);
    expect(roots[0].children[0].depth).toBe(1);
    expect(roots[0].children[0].children[0].span.span_id).toBe("a1");
    expect(roots[0].children[0].children[0].depth).toBe(2);
  });

  it("treats spans whose parent is missing as roots so nothing is hidden", () => {
    const spans = [
      span("orphan", "ghost", "2026-01-01T00:00:00.000Z"),
      span("y", null, "2026-01-01T00:00:01.000Z"),
    ];
    const roots = buildSpanTree(spans);
    expect(roots.map((r) => r.span.span_id).sort()).toEqual(["orphan", "y"]);
  });

  it("keeps every span reachable in a 30-span tree", () => {
    const spans: Span[] = [span("r", null, "2026-01-01T00:00:00.000Z")];
    for (let i = 0; i < 29; i++) {
      const parent = i < 5 ? "r" : `s${i - 5}`;
      spans.push(span(`s${i}`, parent, `2026-01-01T00:01:${String(i).padStart(2, "0")}.000Z`));
    }
    const roots = buildSpanTree(spans);
    const total = roots.reduce((acc, r) => acc + 1 + countDescendants(r), 0);
    expect(total).toBe(30);
  });
});

describe("flattenTree", () => {
  it("hides descendants of collapsed nodes", () => {
    const spans = [
      span("root", null, "2026-01-01T00:00:00.000Z"),
      span("child", "root", "2026-01-01T00:00:01.000Z"),
    ];
    const roots = buildSpanTree(spans);
    expect(flattenTree(roots, new Set()).map((n) => n.span.span_id)).toEqual(["root", "child"]);
    expect(flattenTree(roots, new Set(["root"])).map((n) => n.span.span_id)).toEqual(["root"]);
  });
});
