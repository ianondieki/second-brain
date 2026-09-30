import { describe, expect, it } from "vitest";

import { cn } from "./cn";

describe("cn", () => {
  it("joins class names with one space, in order, skipping false, null, undefined and empty strings", () => {
    const quiet = false;
    expect(cn("flex", quiet && "opacity-50", null, undefined, "", "gap-2")).toBe("flex gap-2");
    expect(cn("a", "b", "c")).toBe("a b c");
  });

  it("is an empty string when nothing is left", () => {
    expect(cn()).toBe("");
    expect(cn(false, null, undefined)).toBe("");
  });
});
