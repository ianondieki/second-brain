import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), order: [] as string[] }));
vi.mock("@/lib/api/client", () => ({ api: { GET: mocks.get } }));
vi.mock("@/components/offline/clear", () => ({
  forgetOffline: async () => {
    mocks.order.push("forget");
  },
}));

import { continueAfterSignIn } from "./session";

// P27 (REQ-UX-08; D-69): after a password, link or code sign-in, this device's offline copies of another person's
// trackers are deleted before any routing, wherever the person goes next.

const router = () =>
  ({ replace: vi.fn((href: string) => mocks.order.push(`route ${href}`)) }) as unknown as Parameters<
    typeof continueAfterSignIn
  >[0];

beforeEach(() => {
  mocks.order = [];
  mocks.get.mockReset();
});

describe("continueAfterSignIn", () => {
  it("deletes the offline copies, then goes to the second factor when it is owed", async () => {
    await continueAfterSignIn(router(), true);
    expect(mocks.order).toEqual(["forget", "route /auth/mfa"]);
  });

  it("deletes the offline copies, then goes home", async () => {
    mocks.get.mockResolvedValue({
      data: {
        side: "org",
        mfa: { enrolled: true, verified: true, required: false },
        user: { staff_role: null },
        memberships: [],
      },
    });
    await continueAfterSignIn(router(), false);
    expect(mocks.order[0]).toBe("forget");
    expect(mocks.order).toHaveLength(2);
  });
});
