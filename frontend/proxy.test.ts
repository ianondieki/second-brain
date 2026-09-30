import { describe, expect, it, vi } from "vitest";

import { admitsStaff } from "./proxy";

const answer = (status: number, body: unknown = {}) =>
  vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), { status }));

// REQ-ADM-01: only sessions the API admits to the staff console reach /admin; the rest get the unknown-address 404.
describe("admitsStaff", () => {
  it("admits staff, and staff whose second factor must be refreshed", async () => {
    expect(await admitsStaff("__Host-bridge_session=t", answer(200, { role: "admin" }))).toBe(true);
    expect(
      await admitsStaff("__Host-bridge_session=t", answer(403, { detail: { code: "step_up_required", message: "x" } })),
    ).toBe(true);
  });

  it("turns away everyone else, and fails closed", async () => {
    const none = answer(200);
    expect(await admitsStaff(undefined, none)).toBe(false);
    expect(none).not.toHaveBeenCalled();
    expect(await admitsStaff("c", answer(404, { detail: { code: "not_found" } }))).toBe(false);
    expect(await admitsStaff("c", answer(401))).toBe(false);
    expect(await admitsStaff("c", answer(403, { detail: { code: "forbidden" } }))).toBe(false);
    expect(await admitsStaff("c", answer(500))).toBe(false);
    expect(
      await admitsStaff(
        "c",
        vi.fn<typeof fetch>(async () => {
          throw new Error("offline");
        }),
      ),
    ).toBe(false);
  });

  it("forwards only the session cookie it was given", async () => {
    const fetchImpl = answer(200);
    await admitsStaff("__Host-bridge_session=tok", fetchImpl);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/admin\/me$/);
    expect(init?.headers).toEqual({ cookie: "__Host-bridge_session=tok" });
  });
});
