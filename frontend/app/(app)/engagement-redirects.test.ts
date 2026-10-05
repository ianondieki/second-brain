import { beforeEach, describe, expect, it, vi } from "vitest";

import DeveloperEngagementPage from "./dev/engagements/[id]/page";
import OrganisationEngagementPage from "./org/engagements/[id]/page";

// REQ-ENG-11 (P21 re-review): both tracker pages send ?tab=messages (old links, the N18 notices) to the Messages route,
// landing on the thread's heading, the organisation's ?org= kept and the id encoded. The redirect is the page's own
// call: a page that stopped passing ?org= on would fail here.

const calls = vi.hoisted(() => ({ redirect: vi.fn((url: string) => { throw new Error(`REDIRECT ${url}`); }) }));
vi.mock("next/navigation", () => ({ redirect: calls.redirect, notFound: vi.fn() }));
vi.mock("next-intl/server", () => ({ getTranslations: async () => (key: string) => key, getLocale: async () => "en" }));
vi.mock("@/lib/api/server", () => ({ requireMe: async () => ({ side: "developer" }), forwardHeaders: vi.fn(), serverApi: vi.fn() }));
vi.mock("@/components/tracker/data", () => ({ engagement: vi.fn(async () => ({ ok: false, refusal: "notFound" })) }));
vi.mock("./org/data", () => ({ orgContext: vi.fn(async () => ({ me: { memberships: [] }, query: "" })) }));

const ID = "0199b000-0000-7000-8000-00000000e001";

async function landing(page: (props: never) => Promise<unknown>, id: string, query: Record<string, string>) {
  await expect(page({ params: Promise.resolve({ id }), searchParams: Promise.resolve(query) } as never)).rejects.toThrow(/^REDIRECT /);
  return calls.redirect.mock.calls.at(-1)?.[0];
}

beforeEach(() => {
  calls.redirect.mockClear();
});

describe("?tab=messages", () => {
  it("sends the developer to the Messages route's heading", async () => {
    expect(await landing(DeveloperEngagementPage, ID, { tab: "messages" })).toBe(`/dev/engagements/${ID}/messages#messages-heading`);
  });

  it("sends the organisation there with and without ?org=", async () => {
    expect(await landing(OrganisationEngagementPage, ID, { tab: "messages" })).toBe(
      `/org/engagements/${ID}/messages#messages-heading`,
    );
    expect(await landing(OrganisationEngagementPage, ID, { tab: "messages", org: "01a10b26-534a-717a-9846-cfb7ab5c200a" })).toBe(
      `/org/engagements/${ID}/messages?org=01a10b26-534a-717a-9846-cfb7ab5c200a#messages-heading`,
    );
  });

  it("encodes the id and the organisation", async () => {
    expect(await landing(DeveloperEngagementPage, "a/b c", { tab: "messages" })).toBe("/dev/engagements/a%2Fb%20c/messages#messages-heading");
    expect(await landing(OrganisationEngagementPage, "a/b", { tab: "messages", org: "x&y" })).toBe(
      "/org/engagements/a%2Fb/messages?org=x%26y#messages-heading",
    );
  });

  it("does not redirect the tracker's own tabs", async () => {
    await expect(
      OrganisationEngagementPage({ params: Promise.resolve({ id: ID }), searchParams: Promise.resolve({ tab: "history" }) } as never),
    ).resolves.toBeTruthy();
    expect(calls.redirect).not.toHaveBeenCalled();
  });
});
