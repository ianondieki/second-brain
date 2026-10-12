// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runInNewContext } from "node:vm";

import { beforeEach, describe, expect, it, vi } from "vitest";

// P27 track F (REQ-UX-08; D-69): public/sw.js loaded as the browser would, in a stub `self` with a Cache Storage
// held in memory. What it may keep (the two engagements lists and the trackers, for the signed-in person only, at
// most 20 for 7 days), what it never touches, and how a person's cache goes on sign-out and on someone else's sign-in.

const ORIGIN = "https://wazo.test";
const SOURCE = readFileSync(join(process.cwd(), "public/sw.js"), "utf8");
const ID = "0b8f4c1e-5a2d-4e7f-9c3b-1d2e3f4a5b6c";
const ORG = "7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
const ALICE = "a1b2c3d4e5f60718293a";
const BRIAN = "b9c8d7e6f5a40312ab4c";
const DAY = 24 * 60 * 60 * 1000;

class FakeCache {
  readonly entries = new Map<string, Response>();
  private key(request: string | Request | { url: string }) {
    return new URL(typeof request === "string" ? request : request.url, ORIGIN).href;
  }
  async match(request: string | Request) {
    return this.entries.get(this.key(request))?.clone();
  }
  async put(request: string | Request, response: Response) {
    const key = this.key(request);
    this.entries.delete(key); // the Cache API appends a replaced entry at the end
    this.entries.set(key, response);
  }
  async delete(request: string | Request) {
    return this.entries.delete(this.key(request));
  }
  async keys() {
    return [...this.entries.keys()].map((url) => new Request(url));
  }
}

class FakeStorage {
  readonly named = new Map<string, FakeCache>();
  async open(name: string) {
    if (!this.named.has(name)) this.named.set(name, new FakeCache());
    return this.named.get(name)!;
  }
  async keys() {
    return [...this.named.keys()];
  }
  async delete(name: string) {
    return this.named.delete(name);
  }
}

interface Answer {
  body?: string;
  status?: number;
  type?: string;
  date?: Date | null;
  redirectedTo?: string;
  contentType?: string;
}

/** A response as fetch() gives it to a worker: same-origin ("basic"), with its final URL. */
function answer(
  url: string,
  {
    body = "<html><body>page</body></html>",
    status = 200,
    type = "basic",
    date = new Date(),
    redirectedTo,
    contentType = "text/html; charset=utf-8",
  }: Answer = {},
) {
  const headers = new Headers({ "content-type": contentType, "cache-control": "private, no-store" });
  if (date) headers.set("date", date.toUTCString());
  const response = new Response(body, { status, headers });
  Object.defineProperties(response, {
    type: { value: type },
    url: { value: new URL(redirectedTo ?? url, ORIGIN).href },
    redirected: { value: Boolean(redirectedTo) },
  });
  return response;
}

type Listener = (event: unknown) => void;

function worker(version = "build-1") {
  const listeners = new Map<string, Listener>();
  const caches = new FakeStorage();
  const network = { online: true, answers: new Map<string, Answer>() };
  const fetch = vi.fn(async (input: string | { url: string }) => {
    if (!network.online) throw new TypeError("Failed to fetch");
    const url = new URL(typeof input === "string" ? input : input.url, ORIGIN);
    return answer(url.href, network.answers.get(url.pathname + url.search) ?? {});
  });
  const self = {
    location: new URL(`/sw.js?v=${version}`, ORIGIN),
    addEventListener: (type: string, listener: Listener) => listeners.set(type, listener),
    skipWaiting: vi.fn(async () => {}),
    clients: { claim: vi.fn(async () => {}) },
  };
  runInNewContext(SOURCE, {
    self,
    caches,
    fetch,
    Response,
    Request,
    Headers,
    URL,
    AbortSignal,
    Date,
    Promise,
    Map,
    Set,
    Number,
    Error,
    TypeError,
    Math,
  });

  async function fire(type: string, event: Record<string, unknown>) {
    const waits: Promise<unknown>[] = [];
    let responded: Promise<Response> | undefined;
    listeners.get(type)!({
      ...event,
      waitUntil: (p: Promise<unknown>) => waits.push(p),
      respondWith: (p: Promise<Response>) => (responded = p),
    });
    const response = responded ? await responded : undefined;
    // waitUntil may be called while the response is being made: wait for every one of them.
    for (let i = 0; i < waits.length; i += 1) await waits[i];
    return response;
  }

  return {
    caches,
    network,
    fetch,
    self,
    install: () => fire("install", {}),
    activate: () => fire("activate", {}),
    /** A full page load (the address bar, a reload, a link outside the app's router). */
    load: (path: string, extra: Record<string, unknown> = {}) =>
      fire("fetch", {
        request: { url: new URL(path, ORIGIN).href, method: "GET", mode: "navigate", destination: "document" },
        resultingClientId: "client-1",
        ...extra,
      }),
    request: (path: string, request: Record<string, unknown>) =>
      fire("fetch", {
        request: { url: new URL(path, ORIGIN).href, method: "GET", mode: "cors", destination: "", ...request },
      }),
    async tell(data: unknown, source = { id: "client-1" }) {
      let reply: unknown;
      await fire("message", { data, source, ports: [{ postMessage: (value: unknown) => (reply = value) }] });
      return reply;
    },
    kept() {
      const people = [...caches.named.keys()].filter((name) => name.startsWith("trackers-"));
      return people.length === 1
        ? [...caches.named.get(people[0])!.entries.keys()].map((url) => url.slice(ORIGIN.length))
        : [];
    },
  };
}

type Worker = ReturnType<typeof worker>;

async function signedIn(hash = ALICE, version?: string): Promise<Worker> {
  const w = worker(version);
  w.network.answers.set("/offline", {
    body: '<html><link rel="stylesheet" href="/_next/static/css/app.css"><script src="/_next/static/chunks/main.js"></script>You are offline</html>',
  });
  await w.install();
  await w.activate();
  expect(await w.tell({ type: "user", hash })).toEqual({ ok: true });
  return w;
}

async function textOf(response: Response | undefined) {
  return response ? response.text() : "(not intercepted)";
}

beforeEach(() => {
  vi.useRealTimers();
});

describe("the service worker's install and versions", () => {
  it("caches /offline when it installs (never reading it for addresses), then takes over at once", async () => {
    const w = await signedIn();
    expect(await w.caches.named.get("offline-build-1")!.match("/offline")).toBeTruthy();
    // The page names two build files: neither is fetched for it (the pages' own requests keep them).
    expect(
      w.fetch.mock.calls.map(([input]) => new URL(typeof input === "string" ? input : input.url, ORIGIN).pathname),
    ).toEqual([
      "/offline",
      "/offline", // fetched again when the shell says whose the cache is: the page in that person's language
    ]);
    expect(w.caches.named.get("static-build-1")?.entries.size ?? 0).toBe(0);
    expect(w.self.skipWaiting).toHaveBeenCalled();
    expect(w.self.clients.claim).toHaveBeenCalled();
  });

  it("drops another build's files and every kept page when a new version activates", async () => {
    const w = await signedIn();
    await w.load(`/dev/engagements/${ID}`);
    w.network.answers.set("/_next/static/chunks/a.js", { contentType: "text/javascript", body: "x" });
    await w.request("/_next/static/chunks/a.js", { destination: "script" });
    await new Promise((r) => setTimeout(r, 0));
    expect([...w.caches.named.keys()].sort()).toEqual(["offline-build-1", "static-build-1", `trackers-${ALICE}`]);
    const next = worker("build-2");
    // The new version starts from the same storage.
    for (const [name, cache] of w.caches.named) next.caches.named.set(name, cache);
    next.network.answers.set("/offline", { body: "<html>offline</html>" });
    await next.install();
    await next.activate();
    // Only the new version's shell cache is left (its build files are kept as its pages request them).
    expect([...next.caches.named.keys()].sort()).toEqual(["offline-build-2"]);
  });
});

describe("what the service worker keeps", () => {
  it.each([
    "/dev/engagements",
    "/org/engagements",
    `/org/engagements?org=${ORG}`,
    `/dev/engagements/${ID}`,
    `/org/engagements/${ID}`,
    `/org/engagements/${ID}?org=${ORG}`,
  ])("keeps %s and serves that copy when the network fails", async (path) => {
    const w = await signedIn();
    w.network.answers.set(path, { body: `<html>the page at ${path}</html>` });
    expect(await textOf(await w.load(path))).toBe(`<html>the page at ${path}</html>`);
    expect(w.kept()).toEqual([path]);
    w.network.online = false;
    expect(await textOf(await w.load(path))).toBe(`<html>the page at ${path}</html>`);
    // The shell asks whether its page came from the cache, to show the banner.
    expect(await w.tell({ type: "status" })).toMatchObject({ cached: true });
  });

  it.each([
    `/dev/engagements/${ID}/messages`,
    `/org/engagements/${ID}/messages`,
    "/org/inbox",
    `/org/inbox/${ID}`,
    `/org/inbox/shortlist?org=${ORG}`,
    "/dev",
    "/org",
    "/dev/ideas",
    `/dev/ideas/${ID}`,
    `/dev/ideas/${ID}/edit`,
    "/billing",
    "/billing/invoices",
    "/settings/profile",
    "/settings/security",
    "/notifications",
    "/dev/engagements/calendar",
    "/org/engagements/board",
    `/dev/engagements/${ID.toUpperCase()}`,
    `/dev/engagements/${ID}/`,
    `/dev/engagements/${ID}?tab=history`,
    `/org/engagements?org=${ORG}&full=1`,
    `/org/proposals/${ID}/render`,
    "/dev/engagements?view=calendar",
    `/org/engagements?view=board&org=${ORG}`,
  ])("never keeps %s, and gives /offline when it cannot be loaded", async (path) => {
    const w = await signedIn();
    expect(await textOf(await w.load(path))).toBe("<html><body>page</body></html>");
    expect(w.kept()).toEqual([]);
    w.network.online = false;
    expect(await textOf(await w.load(path))).toContain("You are offline");
    expect(await w.tell({ type: "status" })).toMatchObject({ cached: false });
  });

  it.each([
    ["/api/me/engagements", { mode: "cors" }],
    [`/api/orgs/${ORG}/proposals/${ID}/tier2`, { mode: "navigate", destination: "document" }],
    [`/api/orgs/${ORG}/proposals/${ID}/tier2/render`, { mode: "navigate", destination: "iframe" }],
    ["/admin", { mode: "navigate", destination: "document" }],
    ["/admin/moderation", { mode: "navigate", destination: "document" }],
    [`/dev/engagements/${ID}?_rsc=abc`, { mode: "cors" }], // the app router's own fetch of a page's data
    [`/dev/engagements/${ID}`, { mode: "navigate", destination: "iframe" }],
    [`/dev/engagements/${ID}`, { mode: "navigate", destination: "document", method: "POST" }],
    ["/photos/nairobi-800.webp", { mode: "no-cors", destination: "image" }],
    ["/fonts/fraunces-v1.woff2", { mode: "cors", destination: "font" }],
  ])("never intercepts %s (%o)", async (path, request) => {
    const w = await signedIn();
    expect(await w.request(path, request)).toBeUndefined();
    expect(w.fetch).toHaveBeenCalledTimes(2); // the install's /offline and its refetch for the person only
  });

  it("never intercepts another origin", async () => {
    const w = await signedIn();
    expect(
      await w.request("https://elsewhere.test/dev/engagements", { mode: "navigate", destination: "document" }),
    ).toBeUndefined();
  });

  it("serves the build files from its cache once fetched (cache-first)", async () => {
    const w = await signedIn();
    w.network.answers.set("/_next/static/chunks/page-abc.js", { body: "chunk", contentType: "text/javascript" });
    expect(await textOf(await w.request("/_next/static/chunks/page-abc.js", { destination: "script" }))).toBe("chunk");
    await new Promise((r) => setTimeout(r, 0));
    w.network.online = false;
    expect(await textOf(await w.request("/_next/static/chunks/page-abc.js", { destination: "script" }))).toBe("chunk");
  });

  it("never reads a kept page's text for addresses, whatever a title an adversary wrote says", async () => {
    const w = await signedIn();
    w.network.answers.set(`/dev/engagements/${ID}`, {
      body: '<html><h1>/_next/static/../../api/me/profile /_next/static/%2e%2e/%2e%2e/org/proposals/x/render</h1><script src="/_next/static/chunks/a.js"></script></html>',
    });
    const before = w.fetch.mock.calls.length;
    await w.load(`/dev/engagements/${ID}`);
    expect(w.fetch.mock.calls.length - before).toBe(1); // the page itself
    expect(w.caches.named.get("static-build-1")?.entries.size ?? 0).toBe(0);
  });

  it.each([
    ["/_next/static/../../api/me/profile", "a path that climbs out of /_next/static"],
    ["/_next/static/%2e%2e/%2e%2e/org/proposals/x/render", "an encoded climb"],
    ["/_next/static/chunks/a.js?x=1", "a query"],
  ])("never treats %s as a build file (%s)", async (path) => {
    const w = await signedIn();
    expect(await w.request(path, { destination: "script" })).toBeUndefined();
    expect(w.caches.named.get("static-build-1")?.entries.size ?? 0).toBe(0);
  });

  it("never treats another origin's /_next/static as a build file", async () => {
    const w = await signedIn();
    expect(
      await w.request("https://elsewhere.test/_next/static/chunks/a.js", { destination: "script" }),
    ).toBeUndefined();
  });

  it.each<[Answer, string]>([
    [{ contentType: "text/html; charset=utf-8", body: "<html>not found</html>", status: 200 }, "an HTML answer"],
    [{ contentType: "application/json", body: "{}", status: 200 }, "JSON"],
    [{ contentType: "text/javascript", body: "x", status: 404 }, "a 404"],
    [{ contentType: "text/javascript", body: "x", redirectedTo: "/login" }, "a redirect"],
  ])("serves but never keeps %o under /_next/static (%s)", async (given, what) => {
    const w = await signedIn();
    expect(what).toBeTruthy();
    w.network.answers.set("/_next/static/chunks/odd.js", given);
    await w.request("/_next/static/chunks/odd.js", { destination: "script" });
    await new Promise((r) => setTimeout(r, 0));
    expect(w.caches.named.get("static-build-1")?.entries.size ?? 0).toBe(0);
  });

  it.each([
    ["text/css; charset=utf-8", "/_next/static/chunks/a.css"],
    ["application/javascript; charset=UTF-8", "/_next/static/chunks/a.js"],
    ["font/woff2", "/_next/static/media/a.woff2"],
    ["image/svg+xml", "/_next/static/media/a.svg"],
  ])("keeps a 200 %s build file the page requested", async (contentType, path) => {
    const w = await signedIn();
    w.network.answers.set(path, { contentType, body: "x" });
    await w.request(path, { destination: "script" });
    await new Promise((r) => setTimeout(r, 0));
    expect([...w.caches.named.get("static-build-1")!.entries.keys()]).toEqual([`${ORIGIN}${path}`]);
  });

  it("keeps nothing that is not a whole HTML page of this origin: an error, a redirect to sign-in, another type", async () => {
    const w = await signedIn();
    const path = `/dev/engagements/${ID}`;
    for (const given of [
      { status: 404 },
      { status: 500 },
      { contentType: "application/json" },
      { type: "opaqueredirect" },
    ]) {
      w.network.answers.set(path, given);
      await w.load(path);
      expect(w.kept(), JSON.stringify(given)).toEqual([]);
    }
  });

  it("keeps at most 20 pages, the oldest dropped first", async () => {
    const w = await signedIn();
    const paths = Array.from(
      { length: 21 },
      (_, i) => `/dev/engagements/${ID.slice(0, -2)}${String(i).padStart(2, "0")}`,
    );
    for (const path of paths) await w.load(path);
    expect(w.kept()).toHaveLength(20);
    expect(w.kept()).not.toContain(paths[0]);
    expect(w.kept()).toContain(paths[20]);
    // Opening one again makes it the newest.
    await w.load(paths[1]);
    await w.load("/dev/engagements");
    expect(w.kept()).not.toContain(paths[2]);
    expect(w.kept()).toContain(paths[1]);
  });

  it("never serves a copy older than 7 days by its Date header (and deletes it), nor one with no date", async () => {
    const w = await signedIn();
    const fresh = `/dev/engagements/${ID}`;
    const stale = `/org/engagements/${ID}`;
    w.network.answers.set(fresh, { body: "six days", date: new Date(Date.now() - 6 * DAY) });
    w.network.answers.set(stale, { body: "eight days", date: new Date(Date.now() - 8 * DAY) });
    w.network.answers.set("/dev/engagements", { body: "no date", date: null });
    for (const path of [fresh, stale, "/dev/engagements"]) await w.load(path);
    w.network.online = false;
    expect(await textOf(await w.load(fresh))).toBe("six days");
    expect(await textOf(await w.load(stale))).toContain("You are offline");
    expect(await textOf(await w.load("/dev/engagements"))).toContain("You are offline");
    expect(w.kept()).toEqual([fresh]);
  });

  it("keeps nothing before the shell has said whose the cache is", async () => {
    const w = worker();
    w.network.answers.set("/offline", { body: "You are offline" });
    await w.install();
    await w.activate();
    await w.load(`/dev/engagements/${ID}`);
    expect([...w.caches.named.keys()].filter((name) => name.startsWith("trackers-"))).toEqual([]);
  });
});

describe("whose cache it is", () => {
  it("names the cache by the person's hash and deletes every other person's when someone else signs in", async () => {
    const w = await signedIn(ALICE);
    await w.load(`/dev/engagements/${ID}`);
    expect([...w.caches.named.keys()]).toContain(`trackers-${ALICE}`);
    expect(await w.tell({ type: "user", hash: BRIAN })).toEqual({ ok: true });
    expect([...w.caches.named.keys()].filter((name) => name.startsWith("trackers-"))).toEqual([`trackers-${BRIAN}`]);
    expect(w.kept()).toEqual([]);
    w.network.online = false;
    expect(await textOf(await w.load(`/dev/engagements/${ID}`))).toContain("You are offline");
  });

  it("deletes every person's cache on sign-out ({type: clear}) and keeps nothing after it", async () => {
    const w = await signedIn();
    await w.load(`/dev/engagements/${ID}`);
    expect(await w.tell({ type: "clear" })).toEqual({ ok: true });
    expect([...w.caches.named.keys()].filter((name) => name.startsWith("trackers-"))).toEqual([]);
    await w.load("/dev/engagements");
    expect([...w.caches.named.keys()].filter((name) => name.startsWith("trackers-"))).toEqual([]);
  });

  it("deletes every person's cache when a page load lands on sign-in (a lapsed session)", async () => {
    const w = await signedIn();
    await w.load(`/dev/engagements/${ID}`);
    w.network.answers.set("/dev/engagements", { redirectedTo: "/login?next=%2Fdev%2Fengagements" });
    await w.load("/dev/engagements");
    expect([...w.caches.named.keys()].filter((name) => name.startsWith("trackers-"))).toEqual([]);
  });

  it("sweeps every copy older than 7 days when the person is told again and whenever a page is kept", async () => {
    const w = await signedIn();
    const fresh = `/dev/engagements/${ID}`;
    w.network.answers.set(fresh, { body: "fresh" });
    await w.load(fresh);
    // Make the kept copy 8 days old, as if the browser had been closed since.
    const cache = w.caches.named.get(`trackers-${ALICE}`)!;
    const old = new Date(Date.now() - 8 * DAY).toUTCString();
    await cache.put(`${ORIGIN}${fresh}`, new Response("old", { headers: { date: old, "content-type": "text/html" } }));
    await w.tell({ type: "user", hash: ALICE });
    expect(w.kept()).toEqual([]);
    await cache.put(`${ORIGIN}${fresh}`, new Response("old", { headers: { date: old, "content-type": "text/html" } }));
    await w.load("/dev/engagements");
    expect(w.kept()).toEqual(["/dev/engagements"]);
  });

  it("fetches /offline again when told whose the cache is and on sign-out, so it follows the person's language", async () => {
    const w = await signedIn();
    const offlineFetches = () =>
      w.fetch.mock.calls.filter(([input]) => String(typeof input === "string" ? input : input.url).endsWith("/offline"))
        .length;
    const before = offlineFetches();
    w.network.answers.set("/offline", { body: "Huna mtandao" });
    await w.tell({ type: "user", hash: BRIAN });
    expect(offlineFetches()).toBe(before + 1);
    await w.tell({ type: "clear" });
    expect(offlineFetches()).toBe(before + 2);
    w.network.online = false;
    expect(await textOf(await w.load("/dev/ideas"))).toBe("Huna mtandao");
  });

  it("ignores a hash that is not one", async () => {
    const w = await signedIn();
    expect(await w.tell({ type: "user", hash: "../../etc" })).toBeNull();
    expect(await w.tell({ type: "user", hash: "" })).toBeNull();
    expect([...w.caches.named.keys()]).toContain(`trackers-${ALICE}`);
  });
});

describe("a page reached inside the app ({type: visit})", () => {
  it("fetches a tracker opened without a page load and keeps it", async () => {
    const w = await signedIn();
    w.network.answers.set(`/dev/engagements/${ID}`, { body: "the tracker" });
    expect(await w.tell({ type: "visit", url: `${ORIGIN}/dev/engagements/${ID}#history` })).toEqual({ ok: true });
    expect(w.kept()).toEqual([`/dev/engagements/${ID}`]);
  });

  it("fetches nothing for any other page, and not again for a copy a minute old or less", async () => {
    const w = await signedIn();
    const before = w.fetch.mock.calls.length;
    expect(await w.tell({ type: "visit", url: `${ORIGIN}/dev/engagements/${ID}/messages` })).toEqual({ ok: false });
    expect(await w.tell({ type: "visit", url: "https://elsewhere.test/dev/engagements" })).toEqual({ ok: false });
    expect(await w.tell({ type: "visit", url: `${ORIGIN}/dev/engagements?view=calendar` })).toEqual({ ok: false });
    expect(await w.tell({ type: "visit", url: `${ORIGIN}/org/engagements?view=board&org=${ORG}` })).toEqual({
      ok: false,
    });
    expect(w.fetch.mock.calls.length).toBe(before);
    await w.load("/dev/engagements");
    const after = w.fetch.mock.calls.length;
    await w.tell({ type: "visit", url: `${ORIGIN}/dev/engagements` });
    expect(w.fetch.mock.calls.length).toBe(after);
  });
});
