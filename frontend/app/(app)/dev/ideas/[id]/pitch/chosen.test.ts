import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PitchOption } from "./picker";

// REQ-PROP-03 (review round 1, MAJOR 1): choices from another page or search are shown only when the API resolves
// them by id and the picker lists them; everything else is dropped, so it can be neither shown nor sent.

const GET = vi.fn();
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({ GET }),
}));

const { chosenOptions } = await import("./data");

const PROPOSAL = "0199a000-0000-7000-8000-0000000000aa";
const SAFCELL = "0199a000-0000-7000-8000-00000000000a";
const GHOST = "0199a000-0000-7000-8000-00000000000f";

function option(id: string, name: string, available = true): PitchOption {
  return {
    card: {
      id,
      slug: name.toLowerCase(),
      name,
      kind: "company",
      niches: [],
      county: null,
      badge: { level: "e2", text: "Legal entity verified" },
      responsiveness: null,
    },
    outcome: "delivered",
    available,
    reason: available ? null : "tagged",
    message: null,
  };
}

function answer(data: unknown, status = 200) {
  return { data, response: new Response(null, { status }) };
}

beforeEach(() => GET.mockReset());

describe("choices from another page or search", () => {
  it("are read by id, then found in the picker by name, with their outcome and availability", async () => {
    GET.mockImplementation(async (path: string) =>
      path === "/api/directory/orgs/{org_id}"
        ? answer({ name: "Safcell" })
        : answer({ groups: [{ niche: null, orgs: [option(SAFCELL.toUpperCase(), "Safcell")] }] }),
    );
    const found = await chosenOptions(PROPOSAL, [SAFCELL]);
    expect(found.map((o) => o.card.name)).toEqual(["Safcell"]);
    expect(GET).toHaveBeenCalledWith("/api/directory/orgs/{org_id}", expect.objectContaining({ params: { path: { org_id: SAFCELL } } }));
    expect(GET).toHaveBeenCalledWith(
      "/api/me/proposals/{proposal_id}/pitch/orgs",
      expect.objectContaining({ params: { path: { proposal_id: PROPOSAL }, query: { q: "Safcell", limit: 100 } } }),
    );
  });

  it("are dropped when the directory does not know them, the picker does not list them, or a read fails", async () => {
    GET.mockImplementation(async (path: string, init: { params: { path: { org_id?: string } } }) => {
      if (path === "/api/directory/orgs/{org_id}") {
        if (init.params.path.org_id === GHOST) return answer(undefined, 404);
        return answer({ name: "Safcell" });
      }
      return answer({ groups: [{ niche: null, orgs: [option("0199a000-0000-7000-8000-000000000999", "Other")] }] });
    });
    expect(await chosenOptions(PROPOSAL, [SAFCELL, GHOST, "not-an-id"])).toEqual([]);
    // A picker read that fails drops the id too.
    GET.mockImplementation(async (path: string) =>
      path === "/api/directory/orgs/{org_id}" ? answer({ name: "Safcell" }) : answer(undefined, 503),
    );
    expect(await chosenOptions(PROPOSAL, [SAFCELL])).toEqual([]);
  });

  it("keep an unavailable one as the picker says, so the page shows why and never ticks it", async () => {
    GET.mockImplementation(async (path: string) =>
      path === "/api/directory/orgs/{org_id}"
        ? answer({ name: "Safcell" })
        : answer({ groups: [{ niche: null, orgs: [option(SAFCELL, "Safcell", false)] }] }),
    );
    const [found] = await chosenOptions(PROPOSAL, [SAFCELL]);
    expect(found.available).toBe(false);
  });

  it("read at most one batch of ids", async () => {
    GET.mockResolvedValue(answer(undefined, 404));
    const ids = Array.from({ length: 25 }, (_, i) => `0199a000-0000-7000-8000-${String(i).padStart(12, "0")}`);
    await chosenOptions(PROPOSAL, ids);
    expect(GET).toHaveBeenCalledTimes(20);
  });
});
