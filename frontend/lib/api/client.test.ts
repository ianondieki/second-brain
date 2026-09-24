import { describe, expect, it } from "vitest";

import { readCookie } from "./client";

describe("readCookie", () => {
  it("finds a cookie among others and decodes it", () => {
    expect(readCookie("bridge_csrf", "a=1; bridge_csrf=abc%3D.def; b=2")).toBe("abc=.def");
  });

  it("returns undefined when the cookie is absent", () => {
    expect(readCookie("bridge_csrf", "a=1")).toBeUndefined();
  });
});
