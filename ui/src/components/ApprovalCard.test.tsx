import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Approval } from "../api";
import ApprovalCard from "./ApprovalCard";

const fixture: Approval = {
  id: "ap-1",
  incident_id: "inc-1",
  created_at: new Date().toISOString(),
  decided_at: null,
  level: "APPROVE_ACTION",
  status: "PENDING",
  proposed_action: {
    tool: "rollback_deploy",
    params: { deploy_id: "d-0001" },
    target_service: "shopapi",
    rationale: "roll back the bad deploy",
  },
  context: {
    hypothesis: { root_cause: "bad deploy broke payments", confidence: 0.8 },
    evidence_excerpts: [{ kind: "deploy", ref: "d-0001", excerpt: "payment_url changed" }],
    plan_summary: "",
    memory_refs: ["m-1"],
  },
  decided_by: null,
  decision_comment: null,
  modified_action: null,
};

function renderCard(onDecide = vi.fn()) {
  render(
    <MemoryRouter>
      <ApprovalCard approval={fixture} onDecide={onDecide} />
    </MemoryRouter>,
  );
  return onDecide;
}

describe("ApprovalCard", () => {
  it("renders the hypothesis, rationale, and risk level from a fixture", () => {
    renderCard();
    expect(screen.getByText(/bad deploy broke payments/i)).toBeInTheDocument();
    expect(screen.getByText(/roll back the bad deploy/i)).toBeInTheDocument();
    expect(screen.getByText("Approve action")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("calls onDecide with approve when the Approve button is clicked", () => {
    const onDecide = renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onDecide).toHaveBeenCalledWith({ decision: "approve" });
  });

  it("reveals the reject comment box and requires a comment", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Confirm reject" });
    expect(confirm).toBeDisabled();
  });

  it("hides approve/reject on TAKE_OVER and points to the incident resolution form", () => {
    render(
      <MemoryRouter>
        <ApprovalCard approval={{ ...fixture, level: "TAKE_OVER" }} onDecide={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /record your resolution/i })).toHaveAttribute(
      "href",
      "/incidents/inc-1",
    );
  });
});
