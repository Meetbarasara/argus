import { describe, expect, it } from "vitest";
import { levelClasses, statusClasses, statusTone } from "./status";

describe("status mapping", () => {
  it("maps state-machine statuses to scannable tones", () => {
    expect(statusTone("RESOLVED")).toBe("success");
    expect(statusTone("WAITING_APPROVAL")).toBe("waiting");
    expect(statusTone("TAKEN_OVER")).toBe("escalated");
    expect(statusTone("FAILED")).toBe("danger");
    expect(statusTone("INVESTIGATING")).toBe("active");
  });

  it("falls back to neutral for an unknown status instead of crashing", () => {
    expect(statusTone("SOMETHING_NEW")).toBe("neutral");
    expect(statusClasses("SOMETHING_NEW")).toBeTruthy();
  });

  it("colors risk levels and tolerates null", () => {
    expect(statusClasses("RESOLVED")).toContain("emerald");
    expect(levelClasses("TAKE_OVER")).toContain("violet");
    expect(levelClasses(null)).toBeTruthy();
  });
});
