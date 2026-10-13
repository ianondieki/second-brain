import { beforeEach, describe, expect, it, vi } from "vitest";

import { demoPersonas, forgetDemoPersonas, personaLine, personaName, personaOrg, PERSONAS_TTL_MS } from "./demo-personas";

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

// The line under each name is built on the web in every language (REQ-FND-04; ux review of P28-PD, MINOR 3): what the
// persona does, never the API's English detail (it repeats the role and carries the seed's "(fixture)").
describe("personaName", () => {
  it("drops the seed's mark at the end of a name, and nothing else", () => {
    expect(personaName("Staff Moderator (demo)")).toBe("Staff Moderator");
    expect(personaName("  Staff Moderator (Demo)  ")).toBe("Staff Moderator");
    expect(personaName("Grace Mwangi")).toBe("Grace Mwangi");
    expect(personaName("Ali (demo) Hassan")).toBe("Ali (demo) Hassan");
    expect(personaName("(demo)")).toBe("(demo)"); // never an empty name
  });
});

describe("personaOrg", () => {
  it("is the organisation's name before the colon, without the seed's mark", () => {
    expect(personaOrg("Telco A (fixture): owner and admin")).toBe("Telco A");
    expect(personaOrg("County Government of C (fixture): owner and admin")).toBe("County Government of C");
    expect(personaOrg("State Department D: signatory")).toBe("State Department D");
    expect(personaOrg("Telco A (fixture): a: b")).toBe("Telco A");
  });

  it("is null when the detail names no organisation (no colon, nothing before it, only the mark)", () => {
    expect(personaOrg("Telco A, owner and admin")).toBeNull();
    expect(personaOrg(": owner")).toBeNull();
    expect(personaOrg(" (fixture): owner")).toBeNull();
    expect(personaOrg("")).toBeNull();
  });
});

describe("personaLine", () => {
  const about = (role: string, org: string) => `${role}|${org}`;

  it("asks for the role's sentence, with the organisation for an organisation persona", () => {
    expect(personaLine({ role: "developer", detail: "Developer, D2" }, about)).toBe("developer|");
    expect(personaLine({ role: "staff", detail: "Platform staff: moderator" }, about)).toBe("staff|");
    expect(personaLine({ role: "org_admin", detail: "Telco A (fixture): owner and admin" }, about)).toBe("org_admin|Telco A");
    expect(personaLine({ role: "org_signatory", detail: "Telco A (fixture): signatory" }, about)).toBe("org_signatory|Telco A");
    expect(personaLine({ role: "org_reviewer", detail: "Telco A (fixture): reviewer" }, about)).toBe("org_reviewer|Telco A");
  });

  it("draws no line for an organisation persona whose organisation cannot be read", () => {
    expect(personaLine({ role: "org_reviewer", detail: "no colon" }, about)).toBeNull();
  });
});
