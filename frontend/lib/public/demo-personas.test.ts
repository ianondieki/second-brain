import { beforeEach, describe, expect, it, vi } from "vitest";

import { demoPersonas, forgetDemoPersonas, personaDetail, PERSONAS_TTL_MS } from "./demo-personas";

// REQ-FND-04: /login's persona picker reads GET /api/public/demo on the server, reused for a minute.

vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }), headers: async () => new Headers() }));

const PERSONAS = [
  { key: "amina", name: "Amina Wanjiru", role: "developer", detail: "Developer, D2", home: "/dev" },
  { key: "grace", name: "Grace Mwangi", role: "org_admin", detail: "Telco A, owner and admin", home: "/org" },
  { key: "moderator", name: "Staff Moderator", role: "staff", detail: "Platform staff", home: "/admin" },
];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

beforeEach(() => {
  forgetDemoPersonas();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("demoPersonas", () => {
  it("returns the API's personas in its order, asking GET /api/public/demo without a session", async () => {
    fetchMock.mockResolvedValue(json({ enabled: true, personas: PERSONAS, reset_hour_eat: 3 }));
    expect(await demoPersonas(0)).toEqual(PERSONAS);
    const request = fetchMock.mock.calls[0][0];
    expect(new URL(request.url).pathname).toBe("/api/public/demo");
    expect(request.method).toBe("GET");
    expect(request.headers.get("cookie")).toBeNull();
  });

  it("reuses one answer for a minute, then asks again", async () => {
    fetchMock.mockImplementation(async () => json({ enabled: true, personas: PERSONAS, reset_hour_eat: 3 }));
    await demoPersonas(1_000);
    await demoPersonas(1_000 + PERSONAS_TTL_MS - 1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await demoPersonas(1_000 + PERSONAS_TTL_MS);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("is empty when the API says the mode is off", async () => {
    fetchMock.mockResolvedValue(json({ enabled: false, personas: [], reset_hour_eat: null }));
    expect(await demoPersonas(0)).toEqual([]);
  });

  it("is null when the API cannot be read, and keeps no failure", async () => {
    fetchMock.mockRejectedValueOnce(new Error("offline"));
    expect(await demoPersonas(0)).toBeNull();
    fetchMock.mockResolvedValueOnce(json({ detail: { code: "x" } }, 500));
    expect(await demoPersonas(0)).toBeNull();
    fetchMock.mockResolvedValueOnce(json({ enabled: true, personas: PERSONAS, reset_hour_eat: 3 }));
    expect(await demoPersonas(0)).toHaveLength(3);
  });

  it("leaves out a persona it could not draw or send safely", async () => {
    fetchMock.mockResolvedValue(
      json({
        enabled: true,
        reset_hour_eat: 3,
        personas: [
          ...PERSONAS,
          { key: "x", name: "Off site", role: "developer", detail: "", home: "https://evil.example/" },
          { key: "y", name: "Protocol relative", role: "developer", detail: "", home: "//evil.example" },
          { key: "z", name: "Unknown role", role: "owner", detail: "", home: "/org" },
          { key: "Bad Key!", name: "Odd key", role: "developer", detail: "", home: "/dev" },
          { key: "n", name: " ", role: "developer", detail: "", home: "/dev" },
          null,
        ],
      }),
    );
    expect((await demoPersonas(0))?.map((p) => p.key)).toEqual(["amina", "grace", "moderator"]);
  });
});

// The API writes each persona's detail line in English only: in another language the web derives it (REQ-FND-04).
describe("personaDetail", () => {
  const level = (value: string) => `Kiwango cha uthibitisho ${value}`;

  it("is the API's own line in English", () => {
    expect(personaDetail({ role: "org_admin", detail: "Telco A (fixture): owner and admin" }, "en", level)).toBe(
      "Telco A (fixture): owner and admin",
    );
    expect(personaDetail({ role: "staff", detail: " " }, "en", level)).toBeNull();
  });

  it("is derived in Swahili: the organisation's name, a developer's level in a translated line, nothing for staff", () => {
    expect(personaDetail({ role: "org_signatory", detail: "Telco A (fixture): signatory" }, "sw", level)).toBe("Telco A (fixture)");
    expect(personaDetail({ role: "org_admin", detail: "County Government of C (fixture): owner" }, "sw", level)).toBe(
      "County Government of C (fixture)",
    );
    expect(personaDetail({ role: "developer", detail: "Developer, D2" }, "sw", level)).toBe("Kiwango cha uthibitisho D2");
    expect(personaDetail({ role: "developer", detail: "Developer" }, "sw", level)).toBeNull();
    expect(personaDetail({ role: "staff", detail: "Platform staff: moderator" }, "sw", level)).toBeNull();
    expect(personaDetail({ role: "org_reviewer", detail: "no colon" }, "sw", level)).toBeNull();
  });
});
