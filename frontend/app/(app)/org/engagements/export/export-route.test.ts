import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { exportOutcome, exportRefusalHref, exportRefusalParam } from "./outcome";

// REQ-ENG-17 (P28 review MAJOR 7): GET /org/engagements/export streams the API's CSV with the person's session on a
// 200 (its name, type and truncation mark passed on, never cached) and sends any other answer back to the list with
// ?export=<why> (and the Retry-After of a 429), where one server-rendered sentence says it.

const ORG = "0199c000-0000-7000-8000-0000000000a1";
const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/server", () => ({
  serverApi: () => ({ GET: mocks.get }),
  forwardHeaders: async () => ({ cookie: "__Host-bridge_session=s", "x-forwarded-for": "198.51.100.7" }),
}));

const { GET } = await import("./route");

const request = (org = ORG) => new NextRequest(`http://localhost:3000/org/engagements/export?org=${org}`);

beforeEach(() => mocks.get.mockReset());

describe("the export route", () => {
  it("streams the file with the session, keeping its name, type and truncation mark, never cached", async () => {
    const body = new Response("\\uFEFFreference,title\\r\\n").body;
    mocks.get.mockResolvedValue({
      data: body,
      response: new Response(null, {
        status: 200,
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": 'attachment; filename="engagements-2026-10-13.csv"',
          "X-Export-Truncated": "true",
          "Set-Cookie": "x=y",
        },
      }),
    });
    const answer = await GET(request());
    expect(answer.status).toBe(200);
    expect(answer.headers.get("Content-Disposition")).toBe('attachment; filename="engagements-2026-10-13.csv"');
    expect(answer.headers.get("Content-Type")).toBe("text/csv; charset=utf-8");
    expect(answer.headers.get("X-Export-Truncated")).toBe("true");
    expect(answer.headers.get("Cache-Control")).toBe("no-store");
    expect(answer.headers.get("Set-Cookie")).toBeNull();
    expect(await answer.text()).toContain("reference,title");
    const [path, options] = mocks.get.mock.calls[0];
    expect(path).toBe("/api/orgs/{org_id}/engagements.csv");
    expect(options.params).toEqual({ path: { org_id: ORG } });
    expect(options.headers.cookie).toBe("__Host-bridge_session=s");
    expect(options.parseAs).toBe("stream");
    expect(options.cache).toBe("no-store");
  });

  it.each([
    [402, "plan_limit", {}, "plan"],
    [429, "rate_limited", { "Retry-After": "900" }, "rateLimited&retry=900"],
    [401, "unauthenticated", {}, "signedOut"],
    [404, "not_found", {}, "notFound"],
    [500, undefined, {}, "failed"],
  ])("sends a %i back to the list with its reason", async (status, code, headers, why) => {
    mocks.get.mockResolvedValue({
      error: code ? { detail: { code, message: "x" } } : undefined,
      response: new Response(null, { status, headers }),
    });
    const answer = await GET(request());
    expect(answer.status).toBe(303);
    const [reason, retry] = why.split("&");
    const raw = answer.headers.get("Location")!;
    // Relative, never the server's own (bind) address.
    expect(raw.startsWith("/org/engagements?")).toBe(true);
    const location = new URL(raw, "http://visitor.example");
    expect(location.pathname).toBe("/org/engagements");
    expect(location.searchParams.get("export")).toBe(reason);
    expect(location.searchParams.get("org")).toBe(ORG);
    expect(location.searchParams.get("retry")).toBe(retry ? retry.split("=")[1] : null);
  });

  it("asks the API nothing for an organisation id that is not one", async () => {
    const bad = await GET(request("..%2F..%2Fapi"));
    const raw = bad.headers.get("Location")!;
    expect(raw).toBe("/org/engagements?export=notFound");
    expect(mocks.get).not.toHaveBeenCalled();
  });
});

describe("the reasons", () => {
  it("map statuses and codes, and read only known ones back", () => {
    expect(exportOutcome(403, "entitlement_required")).toBe("plan");
    expect(exportRefusalHref("plan", null)).toBe("/org/engagements?export=plan");
    expect(exportRefusalParam("rateLimited")).toBe("rateLimited");
    expect(exportRefusalParam("<script>")).toBeNull();
  });
});
