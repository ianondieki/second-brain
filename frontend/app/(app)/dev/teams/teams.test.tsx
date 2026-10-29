import { cleanup, render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

import { PeersSection } from "../peers/PeersSection";
import {
  closedReason,
  inviteRefusal,
  nameList,
  nicheNames,
  sortThreads,
  teamPostRefusal,
  toThreadPage,
  type Peer,
  type PeersPage,
  type TeamThread,
  type ThreadSummary,
} from "./teams";

// REQ-DEV-03 (P22-CF; D-58, D-62): Home's Peers read stands whatever the API says (only a lost session leaves Home)
// and asks for three (a first page of three is not counted); the section in its states; the team-up rules the screens
// word (thread order, why a thread closed, the refusals) and the team thread in the engagement thread's shape.

const GET = vi.fn();
const redirect = vi.fn((path: string) => {
  throw new Error(`NEXT_REDIRECT ${path}`);
});
vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirect(path),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@/lib/api/server", () => ({ forwardHeaders: async () => ({}), serverApi: () => ({ GET }) }));
vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

const { homePeers, myPublishedIdeas, peersPage, teamThread } = await import("./data");

const status = (code: number, errorCode = "x") => ({
  data: undefined,
  error: { detail: { code: errorCode, message: "x" } },
  response: new Response(null, { status: code }),
});

function peer(overrides: Partial<Peer> = {}): Peer {
  return {
    user_id: "01a11222-e68f-71fd-aa2e-f66d099bfab0",
    handle: "dev-kb3dysnk",
    headline: "Payments and USSD for SACCOs",
    county_name: "Nairobi City",
    shared_niches: ["microfinance-saccos", "networks-telecommunications"],
    same_county: true,
    ...overrides,
  };
}

function summary(overrides: Partial<ThreadSummary> = {}): ThreadSummary {
  return {
    id: "01a11223-32cd-732d-9755-f7206d3c33e4",
    counterpart: { user_id: peer().user_id, handle: "dev-kb3dysnk", headline: null },
    problem: { id: "01a11223-00af-7170-aa03-9bf3c39eef4a", title: "Tower sites go down when generators run dry" },
    created_at: "2026-10-06T10:00:00+03:00",
    last_message_at: "2026-10-06T12:00:00+03:00",
    unread: 0,
    open: true,
    closed_at: null,
    closed_reason: null,
    ...overrides,
  };
}

beforeEach(() => {
  GET.mockReset();
  redirect.mockClear();
});
afterEach(cleanup);

describe("Home's Peers read", () => {
  it("asks for the first three and gives the page", async () => {
    const page: PeersPage = { peers: [peer()], next: null, opted_in: true };
    GET.mockResolvedValueOnce({ data: page, response: new Response(null, { status: 200 }) });
    await expect(homePeers()).resolves.toEqual(page);
    expect(GET).toHaveBeenCalledWith("/api/me/peers", expect.objectContaining({ params: { query: { limit: 3 } }, cache: "no-store" }));
  });

  it("leaves the section out on 404 (an organisation), 429, 500, a timeout and offline", async () => {
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(homePeers()).resolves.toBeNull();
    GET.mockResolvedValueOnce(status(429, "too_many_peer_pages"));
    await expect(homePeers()).resolves.toBeNull();
    GET.mockResolvedValueOnce(status(500));
    await expect(homePeers()).resolves.toBeNull();
    GET.mockRejectedValueOnce(Object.assign(new Error("timed out"), { name: "TimeoutError" }));
    await expect(homePeers()).resolves.toBeNull();
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(homePeers()).resolves.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("signs in again on 401", async () => {
    GET.mockResolvedValueOnce(status(401));
    await expect(homePeers()).rejects.toThrow("NEXT_REDIRECT /login");
  });
});

describe("the peers page and thread reads", () => {
  it("says when the hourly limit of pages is reached, and sends anyone else home", async () => {
    GET.mockResolvedValueOnce(status(429, "too_many_peer_pages"));
    await expect(peersPage()).resolves.toBe("tooMany");
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(peersPage()).rejects.toThrow("NEXT_REDIRECT /dev");
  });

  it("answers a thread that is not the caller's, or not an id, with the not-found page", async () => {
    await expect(teamThread("nope")).rejects.toThrow("NEXT_NOT_FOUND");
    expect(GET).not.toHaveBeenCalled();
    GET.mockResolvedValueOnce(status(404, "not_found"));
    await expect(teamThread(summary().id)).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("the ideas a counterpart can be credited on", () => {
  const idea = (id: string, status: string, moderation_state: string, title: string | null) => ({ id, status, moderation_state, title });

  it("are the caller's published, clear and titled ideas only", async () => {
    GET.mockResolvedValueOnce({
      data: {
        items: [
          idea("draft", "draft", "clear", "A draft"),
          idea("ok", "published", "clear", "Fuel-level alerts"),
          idea("held", "published", "held", "Held for review"),
          idea("untitled", "published", "clear", null),
          idea("empty", "published", "clear", ""),
        ],
      },
      response: new Response(null, { status: 200 }),
    });
    await expect(myPublishedIdeas()).resolves.toEqual([{ id: "ok", title: "Fuel-level alerts" }]);
    expect(GET).toHaveBeenCalledWith("/api/me/proposals", expect.anything());
  });

  it("are none when they cannot be read (a refusal or the network), so the page offers no credit step", async () => {
    GET.mockResolvedValueOnce(status(500));
    await expect(myPublishedIdeas()).resolves.toEqual([]);
    GET.mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(myPublishedIdeas()).resolves.toEqual([]);
  });
});

describe("Home's Peers section", () => {
  it("is left out when the read failed", async () => {
    expect(await PeersSection({ peers: null })).toBeNull();
  });

  it("not visible to peers: one sentence and the way to turn it on in Settings", async () => {
    render(await resolveServerTree(await PeersSection({ peers: { peers: [], next: null, opted_in: false } })));
    const section = screen.getByRole("region", { name: "Peers" });
    expect(section.getAttribute("data-home")).toBe("peers");
    expect(within(section).getByText(en.teams.home.off)).toBeTruthy();
    const links = within(section).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([["Turn on in Settings", "/settings/profile"]]);
    expect(section.querySelector("[data-primary]")).toBeNull();
  });

  it("visible: up to three peers with what they share as plain text, and See all", async () => {
    const four = [
      peer(),
      peer({ user_id: "b", handle: "dev-5jtjq2m3", headline: null, same_county: false, shared_niches: ["agriculture"] }),
      peer({ user_id: "c", handle: "dev-c", shared_niches: [] }),
      peer({ user_id: "d", handle: "dev-d" }),
    ];
    render(await resolveServerTree(await PeersSection({ peers: { peers: four, next: null, opted_in: true } })));
    const section = screen.getByRole("region", { name: "Peers" });
    const rows = section.querySelectorAll("[data-peer]");
    expect([...rows].map((row) => row.getAttribute("data-peer"))).toEqual(["dev-kb3dysnk", "dev-5jtjq2m3", "dev-c"]);
    expect(rows[0].textContent).toContain("Payments and USSD for SACCOs");
    expect(rows[0].textContent).toContain("Same county");
    expect(rows[0].textContent).toContain("2 shared niches");
    expect(rows[1].textContent).toContain("1 shared niche");
    expect(rows[1].querySelector("[data-same-county]")).toBeNull();
    expect(rows[2].textContent).not.toContain("shared");
    // No chips: plain text only.
    expect(section.querySelectorAll("[data-badge], .badge")).toHaveLength(0);
    expect(within(section).getByRole("link", { name: "See all" }).getAttribute("href")).toBe("/dev/peers");
  });

  it("visible with no one near: one sentence and See all", async () => {
    render(await resolveServerTree(await PeersSection({ peers: { peers: [], next: null, opted_in: true } })));
    const section = screen.getByRole("region", { name: "Peers" });
    expect(section.querySelector("[data-peers-empty]")?.textContent).toBe(en.teams.home.empty);
    expect(within(section).getAllByRole("link")).toHaveLength(1);
  });
});

describe("team-up rules", () => {
  it("draws open threads first, each group newest first", () => {
    const a = summary({ id: "a", open: false, last_message_at: "2026-10-06T15:00:00+03:00" });
    const b = summary({ id: "b", last_message_at: "2026-10-05T09:00:00+03:00" });
    const c = summary({ id: "c", last_message_at: null, created_at: "2026-10-06T13:00:00+03:00" });
    const d = summary({ id: "d", open: false, last_message_at: "2026-10-04T15:00:00+03:00" });
    expect(sortThreads([a, b, c, d]).map((t) => t.id)).toEqual(["c", "b", "a", "d"]);
  });

  it("says why a thread closed", () => {
    expect(closedReason(summary())).toBeNull();
    expect(closedReason(summary({ open: false, closed_reason: "left" }))).toBe("left");
    expect(closedReason(summary({ open: false, closed_reason: "blocked" }))).toBe("blocked");
    expect(closedReason(summary({ open: false, closed_reason: null }))).toBe("ended");
  });

  it("names shared niches it knows, in order, joined as the language joins a list", () => {
    const names = { agriculture: "Agriculture", "microfinance-saccos": "Microfinance & SACCOs" };
    expect(nicheNames(["microfinance-saccos", "unknown", "agriculture"], names)).toEqual(["Microfinance & SACCOs", "Agriculture"]);
    expect(nameList(["a", "b", "c"], "en")).toBe("a, b, and c");
    expect(nameList(["a"], "en")).toBe("a");
  });

  it("words each invitation refusal", () => {
    const refused = (code: number, errorCode?: string) => inviteRefusal(code, errorCode ? { detail: { code: errorCode } } : undefined);
    expect(refused(403, "peers_off")).toBe("peersOff");
    expect(refused(404, "peer_unavailable")).toBe("peerUnavailable");
    expect(refused(404, "problem_unavailable")).toBe("problemUnavailable");
    expect(refused(409, "already_invited")).toBe("alreadyInvited");
    expect(refused(429, "too_many_invitations")).toBe("tooMany");
    expect(refused(422)).toBe("invalid");
    expect(refused(500)).toBe("failed");
  });

  it("words a refused team message as the composer does (a closed thread reads again)", () => {
    expect(teamPostRefusal(409, { detail: { code: "thread_closed" } })).toBe("readOnly");
    expect(teamPostRefusal(429, { detail: { code: "too_many_messages" } })).toBe("tooMany");
    expect(teamPostRefusal(404, undefined)).toBe("cannotPost");
    expect(teamPostRefusal(422, undefined)).toBe("invalid");
    expect(teamPostRefusal(500, undefined)).toBe("generic");
  });

  it("gives the team thread the engagement thread's shape: the other developer by handle, no files", () => {
    const read: TeamThread = {
      thread: summary({ unread: 1 }),
      can_post: true,
      max_chars: 4000,
      last_read_at: null,
      items: [
        { id: "m1", mine: true, body: "Hello", redacted: false, created_at: "2026-10-06T11:00:00+03:00" },
        { id: "m2", mine: false, body: "Hi", redacted: false, created_at: "2026-10-06T12:00:00+03:00" },
      ],
      next_cursor: null,
    };
    const page = toThreadPage(read, "dev-kb3dysnk");
    expect(page.status).toBe("open");
    expect(page.unread).toBe(1);
    expect(page.limits).toEqual({ max_chars: 4000, max_attachments: 0, max_attachment_bytes: 0, accepted_types: [] });
    expect(page.items.map((m) => [m.sender_name, m.sender_party, m.attachments.length, (m as { avatar?: string }).avatar])).toEqual([
      ["", "developer", 0, "kb3dysnk"],
      ["dev-kb3dysnk", "developer", 0, "kb3dysnk"],
    ]);
    expect(toThreadPage({ ...read, thread: summary({ open: false, closed_reason: "left" }) }, "x").status).toBe("read_only");
  });
});
