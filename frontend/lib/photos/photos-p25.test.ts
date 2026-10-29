// @vitest-environment node
import { describe, expect, it } from "vitest";

import { photoWidths } from "./files";
import { greetingPhoto } from "./greeting";
import { ALL_PHOTOS, CREDITED, photo } from "./photos";

// P25 (D-67; REQ-UX-05): the index's roles and the vendored sizes light up without code changes; every photograph
// shown anywhere is credited.
describe("photographs by role and size", () => {
  it("greets by the time of day with the index's greeting roles", () => {
    expect(greetingPhoto("morning").slug).toBe("nairobi-morning");
    expect(greetingPhoto("afternoon").role).toBe("greeting-afternoon");
    expect(greetingPhoto("evening").slug).toBe("nairobi-golden-hour");
  });

  it("lists the 480 px pair where it is vendored, and P24's two sizes where nothing is found", () => {
    expect(photoWidths(photo("kenya-tea"))).toEqual([480, 800, 1600]);
    expect(photoWidths(photo("kenya-tea"), "/nowhere")).toEqual([800, 1600]);
  });

  it("credits every vendored photograph", () => {
    expect(new Set(CREDITED.map((p) => p.slug))).toEqual(new Set(ALL_PHOTOS.map((p) => p.slug)));
  });
});
