import { describe, expect, it } from "vitest";

import { loadPalette } from "./load";

// The palette's chunk is requested once, however often the button or a shortcut asks for it.
describe("loadPalette", () => {
  it("imports the palette once and gives its component", async () => {
    const first = loadPalette();
    expect(loadPalette()).toBe(first);
    const loaded = await first;
    expect(typeof loaded.CommandPalette).toBe("function");
  });
});
