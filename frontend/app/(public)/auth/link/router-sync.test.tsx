import { cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { LinkSignIn } from "./LinkSignIn";

// Stand-in for the Next.js app router's history hook (next/dist/client/components/app-router.js, 16.3): a
// replaceState whose state has no `__NA` marker updates the router's canonical URL; one with `__NA` is treated as
// Next's own and does not. The hook is installed in a parent effect, i.e. after LinkSignIn's first effect has run.

const TOKEN = "tok_ROUTER_SYNC_ABCDEFGHIJKLMNOPQRSTUVW";
const mocks = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => mocks.post(...args), GET: vi.fn() } }));

let original: History["replaceState"];
let routerCanonicalUrl: string;

function installNextHook() {
  const unpatched = window.history.replaceState.bind(window.history);
  window.history.replaceState = function replaceState(data, unused, url) {
    const internal = (data as { __NA?: boolean } | null)?.__NA;
    if (!internal && url) routerCanonicalUrl = String(url); // ACTION_RESTORE with the new URL
    return unpatched(internal ? data : { ...(data ?? {}), __NA: true }, unused, url);
  };
}

beforeEach(() => {
  original = window.history.replaceState;
  mocks.post.mockReset().mockReturnValue(new Promise(() => {})); // consume in flight
  const start = `/auth/link#token=${TOKEN}`;
  window.history.replaceState({ __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: { tree: ["", {}] } }, "", start);
  routerCanonicalUrl = start; // what the router rendered the page with
});

afterEach(() => {
  window.history.replaceState = original;
  cleanup();
});

describe("LinkSignIn and the Next.js router", () => {
  it("also clears the token from the router's own URL once Next's history hook is in place", async () => {
    renderWithIntl(<LinkSignIn />); // runs the page's effects (inside act), no timers yet
    // The app router's effect runs in the same commit, after the page's effects, before the next macrotask.
    installNextHook();
    expect(window.location.hash).toBe("");
    expect(routerCanonicalUrl).toContain(TOKEN); // the immediate scrub alone does not reach the router
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());

    await waitFor(() => expect(routerCanonicalUrl).toBe("/auth/link"));
    expect(routerCanonicalUrl).not.toContain(TOKEN);
    expect(JSON.stringify(window.history.state)).not.toContain(TOKEN);
    expect((window.history.state as { __NA?: boolean }).__NA).toBe(true); // Next's marker survives
  });
});
