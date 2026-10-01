import { describe, expect, it } from "vitest";

import { trendDetail } from "./Chips";

describe("trendDetail", () => {
  it("keeps what follows the sentence's last ': ' and leaves other shapes alone", () => {
    expect(trendDetail("Trending in ICT › Networks · Kenya: 4 companies scouting")).toBe("4 companies scouting");
    expect(trendDetail("Trending in Health: primary care · Nairobi: 2 companies scouting")).toBe("2 companies scouting");
    expect(trendDetail("Trending in ICT · Kenya")).toBeNull();
    expect(trendDetail("New this week")).toBeNull();
  });
});
