import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), usual: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ api: { GET: mocks.get } }));
vi.mock("@/lib/auth/session", () => ({ continueAfterSignIn: mocks.usual }));

import { continueToReturnPath } from "./sign-in-return";

const router = () => ({ replace: vi.fn() }) as unknown as Parameters<typeof continueToReturnPath>[0];
const signedIn = { side: "developer", mfa: { enrolled: true, verified: true, required: false }, user: { staff_role: null } };

beforeEach(() => {
  mocks.get.mockReset();
  mocks.usual.mockReset();
});

// P16-A open item 2 (P16-C1): after signing in, back to the page the reader asked for, through the second factor.
describe("continueToReturnPath", () => {
  it("keeps the return path through the second factor", async () => {
    const r = router();
    await continueToReturnPath(r, true, "/settings/notifications");
    expect(r.replace).toHaveBeenCalledWith("/auth/mfa?next=%2Fsettings%2Fnotifications");
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("lands on the page once fully signed in", async () => {
    mocks.get.mockResolvedValue({ data: signedIn });
    const r = router();
    await continueToReturnPath(r, false, "/dev/discover?view=gap");
    expect(r.replace).toHaveBeenCalledWith("/dev/discover?view=gap");
  });

  it("sends a session still owing its second factor there first, keeping the page", async () => {
    mocks.get.mockResolvedValue({ data: { ...signedIn, side: "pending", mfa: { enrolled: true, verified: false, required: true } } });
    const r = router();
    await continueToReturnPath(r, false, "/org/inbox");
    expect(r.replace).toHaveBeenCalledWith("/auth/mfa?next=%2Forg%2Finbox");
  });

  it("goes the usual way (home) without a return path, or with an unsafe one", async () => {
    for (const next of [undefined, "//evil.example", "https://evil.example/dev", "/\\evil", "/%2F%2Fevil"]) {
      const r = router();
      await continueToReturnPath(r, false, next);
      expect(mocks.usual).toHaveBeenLastCalledWith(r, false);
      expect(r.replace).not.toHaveBeenCalled();
    }
  });
});
