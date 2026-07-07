// Build the trace tree once from the flat span list (04 §1 spans carry parent_span_id).
// Memoized by the caller. Orphans (parent not in the set) become roots so nothing is hidden.

import type { Span } from "../api";

export interface SpanNode {
  span: Span;
  children: SpanNode[];
  depth: number;
}

const byStart = (a: SpanNode, b: SpanNode) => a.span.started_at.localeCompare(b.span.started_at);

export function buildSpanTree(spans: Span[]): SpanNode[] {
  const byId = new Map<string, SpanNode>();
  for (const span of spans) byId.set(span.span_id, { span, children: [], depth: 0 });

  const roots: SpanNode[] = [];
  for (const node of byId.values()) {
    const pid = node.span.parent_span_id;
    const parent = pid ? byId.get(pid) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }

  const assignDepth = (nodes: SpanNode[], depth: number) => {
    nodes.sort(byStart);
    for (const n of nodes) {
      n.depth = depth;
      assignDepth(n.children, depth + 1);
    }
  };
  assignDepth(roots, 0);
  return roots;
}

// Depth-first flatten honoring collapsed nodes — the render list for a virtualization-free tree.
export function flattenTree(roots: SpanNode[], collapsed: ReadonlySet<string>): SpanNode[] {
  const out: SpanNode[] = [];
  const walk = (nodes: SpanNode[]) => {
    for (const n of nodes) {
      out.push(n);
      if (n.children.length && !collapsed.has(n.span.span_id)) walk(n.children);
    }
  };
  walk(roots);
  return out;
}

export function countDescendants(node: SpanNode): number {
  return node.children.reduce((acc, c) => acc + 1 + countDescendants(c), 0);
}
