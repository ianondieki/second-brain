import { afterEach, describe, expect, it, vi } from "vitest";

import { started } from "./started";

// started (lib/api/started.ts): a read begun early and awaited only on the path that needs it.

describe("started", () => {
  const unhandled = vi.fn();
  afterEach(() => {
    process.off("unhandledRejection", unhandled);
    unhandled.mockReset();
  });

  it("leaves no unhandled rejection when the page returns without awaiting it", async () => {
    process.on("unhandledRejection", unhandled);
    started(Promise.reject(new Error("GET /api/directory/niches answered 500")));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(unhandled).not.toHaveBeenCalled();
  });

  it("still throws the same error to the path that awaits it", async () => {
    const failure = new Error("redirect:/login");
    await expect(started(Promise.reject(failure))).rejects.toBe(failure);
    await expect(started(Promise.resolve(42))).resolves.toBe(42);
  });
});
