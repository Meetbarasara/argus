import { describe, expect, it } from "vitest";
import { seconds } from "./format";

// seconds() feeds the dashboard MTTR tile straight from float API values — it must
// round, never interpolate a raw float ("42.831460674157306s").
describe("seconds", () => {
  it("handles null/undefined", () => {
    expect(seconds(null)).toBe("—");
    expect(seconds(undefined)).toBe("—");
  });
  it("rounds sub-minute values", () => {
    expect(seconds(0)).toBe("0s");
    expect(seconds(7.5)).toBe("7.5s");
    expect(seconds(42.831460674157306)).toBe("43s");
  });
  it("rounds the remainder in the minutes branch", () => {
    expect(seconds(253.5)).toBe("4m 14s");
    expect(seconds(460)).toBe("7m 40s");
  });
});
