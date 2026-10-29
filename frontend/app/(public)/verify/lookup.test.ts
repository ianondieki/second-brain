import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CertificateCheck } from "./certificate";

// lookupCertificate (verify/lookup.ts): GET /api/verify/{cert_id} settled into what /verify/{id} shows.

const mocks = vi.hoisted(() => ({ get: vi.fn(), forwardHeaders: vi.fn() }));

vi.mock("@/lib/api/server", () => ({
  serverApi: () => ({ GET: mocks.get }),
  forwardHeaders: mocks.forwardHeaders,
}));

const { lookupCertificate } = await import("./lookup");

const RECORD: CertificateCheck = {
  cert_id: "TXEMFBJ89RRTQS87",
  status: "timestamped",
  status_label: "Timestamped",
  content_hash: "0".repeat(64),
  timestamp: "2026-09-29T11:06:25Z",
  tsa_serial: "0x01",
  key_id: "ed25519:e60ca1fa824c4587",
  signature: "c2ln",
};

function answer(status: number, data?: unknown) {
  return { data, response: new Response(null, { status }) };
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.forwardHeaders.mockReset().mockResolvedValue({ "x-forwarded-for": "203.0.113.7" });
});

describe("lookupCertificate", () => {
  it("returns the record, asking with the address only (no session cookie)", async () => {
    mocks.get.mockResolvedValue(answer(200, RECORD));
    expect(await lookupCertificate("TXEMFBJ89RRTQS87")).toEqual({ kind: "found", record: RECORD });
    expect(mocks.forwardHeaders).toHaveBeenCalledWith({ session: false });
    const [path, options] = mocks.get.mock.calls[0];
    expect(path).toBe("/api/verify/{cert_id}");
    expect(options.params).toEqual({ path: { cert_id: "TXEMFBJ89RRTQS87" } });
    expect(options.headers).toEqual({ "x-forwarded-for": "203.0.113.7" });
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });

  it.each([
    [404, "notFound"],
    [422, "notFound"],
    [429, "rateLimited"],
    [500, "unavailable"],
    [503, "unavailable"],
    [401, "unavailable"],
  ])("maps %i to %s", async (status, kind) => {
    mocks.get.mockResolvedValue(answer(status));
    expect(await lookupCertificate("TXEMFBJ89RRTQS87")).toEqual({ kind });
  });

  it("maps a thrown call (timeout, network) to unavailable", async () => {
    mocks.get.mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    expect(await lookupCertificate("TXEMFBJ89RRTQS87")).toEqual({ kind: "unavailable" });
  });
});
