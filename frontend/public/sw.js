/* Wazo's service worker (P27 track F; REQ-UX-08; D-69). Hand-written, no library, no build step.
 *
 * What it does, and nothing more:
 * - /_next/static/* (the hashed, immutable build files the pages request): cache-first, kept per build version, and
 *   only a 200 script, stylesheet, font or image of this origin with no query. No page's text is read for addresses.
 * - A full-page load (mode "navigate", destination "document") of exactly /dev/engagements, /org/engagements,
 *   /dev/engagements/<id> or /org/engagements/<id> (an ?org= query allowed, nothing else): network first, the
 *   answer kept in the signed-in person's cache (trackers-<hash>), and that copy served when the network fails, if it
 *   is at most 7 days old by its Date header. At most 20 pages, the oldest dropped first.
 * - Any other page load that fails: the /offline page, cached when the worker installs.
 * - Never intercepted or stored: anything that is not GET, another origin, /api/*, /admin*, every other page (the
 *   messages pages, the inbox, ideas, billing, settings, any proposal or render route): those go to the network as if
 *   there were no worker, and only a failed page load among them gets /offline.
 *
 * The cache belongs to one person. The signed-in shell tells the worker whose it is ({type: "user", hash}, the hash the
 * command palette's Recent list already uses; never the id): every other person's cache is deleted at once. Sign-out
 * sends {type: "clear"} (and deletes the caches itself), and so does any page load that lands on /login or /signup.
 * With no person's cache present nothing is stored. Answers are stored as they came (the server sends them
 * `Cache-Control: private, no-store`, so this cache is the only copy); the worker never rewrites a page.
 */
"use strict";

const VERSION = new URL(self.location.href).searchParams.get("v") || "0";
const STATIC = `static-${VERSION}`;
const SHELL = `offline-${VERSION}`;
const PEOPLE = "trackers-";
const OFFLINE_URL = "/offline";
const MAX_PAGES = 20;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
/** A copy this fresh is not fetched again for a visit (the page load that just stored it). */
const FRESH_MS = 60 * 1000;

const ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
/** The two engagements lists and one engagement's tracker, in either portal. Nothing below a tracker. */
const TRACKER = new RegExp(`^/(?:dev|org)/engagements(?:/${ID})?$`);
/** Never touched at all, not even with /offline. */
const NEVER = /^\/(?:api(?:\/|$)|admin(?:\/|$))/;
/** Where a signed-out person lands: whatever was kept for the last person goes. */
const SIGNED_OUT = /^\/(?:login|signup)(?:\/|$)/;
const HASH = /^[0-9a-f]{8,64}$/;
/** What a build file may be: a script, a stylesheet, a font or an image. Anything else under /_next/static is not kept. */
const BUILD_TYPE = /^(?:text\/css|(?:application|text)\/javascript|font\/|image\/)/;

/** Whether a page may be kept: the path, and at most an ?org= query. */
function keepable(url) {
  if (url.origin !== self.location.origin || !TRACKER.test(url.pathname)) return false;
  for (const name of url.searchParams.keys()) if (name !== "org") return false;
  return true;
}

/** The signed-in person's cache name, or null when the shell has not said whose it is (or after sign-out). */
async function personCache() {
  const names = (await caches.keys()).filter((name) => name.startsWith(PEOPLE));
  return names.length === 1 ? names[0] : null;
}

async function forgetPeople(keep) {
  const names = (await caches.keys()).filter((name) => name.startsWith(PEOPLE) && name !== keep);
  await Promise.all(names.map((name) => caches.delete(name)));
}

/** The age of a stored answer by its Date header; Infinity without one. */
function age(response) {
  const date = Date.parse(response.headers.get("date") || "");
  return Number.isNaN(date) ? Infinity : Date.now() - date;
}

/** Only a whole, same-origin HTML page that was not redirected (a lapsed session answers with /login). */
function storable(response) {
  return (
    response.ok &&
    response.type === "basic" &&
    !response.redirected &&
    (response.headers.get("content-type") || "").startsWith("text/html")
  );
}

/** Deletes every stored page older than 7 days by its Date header (or without one). */
async function sweep(cache) {
  const keys = await cache.keys();
  await Promise.all(
    keys.map(async (key) => {
      const response = await cache.match(key, { ignoreVary: true });
      if (!response || age(response) > MAX_AGE_MS) await cache.delete(key);
    }),
  );
}

/**
 * Stores a page in the person's cache, drops what is older than 7 days, then the oldest beyond 20. The build files the
 * page loads are kept as the page requests them (buildFile); the page's text is never read for addresses.
 */
async function keepPage(url, response) {
  const name = await personCache();
  if (!name) return;
  const cache = await caches.open(name);
  await cache.put(url, response);
  await sweep(cache);
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_PAGES)).map((key) => cache.delete(key)));
}

/** The person's copy of a page if it is at most 7 days old (an older one is deleted). */
async function keptPage(url) {
  const name = await personCache();
  if (!name) return null;
  const cache = await caches.open(name);
  const response = await cache.match(url, { ignoreVary: true });
  if (!response) return null;
  if (age(response) > MAX_AGE_MS) {
    await cache.delete(url);
    return null;
  }
  return response;
}

/**
 * Every read and write of the person's cache runs one at a time, in order: a page being stored can never land in a
 * cache that a sign-out or another person's sign-in has just deleted (it would re-create it).
 */
let queue = Promise.resolve();
function serial(task) {
  const run = queue.then(task, task);
  queue = run.catch(() => {});
  return run;
}

/** Fetches /offline again (in the person's language, by their cookie) for the shell cache; a failure keeps the old one. */
async function keepOfflinePage() {
  const response = await fetch(OFFLINE_URL, {
    cache: "reload",
    credentials: "same-origin",
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok || response.type !== "basic" || response.redirected)
    throw new Error("the offline page could not be fetched");
  await (await caches.open(SHELL)).put(OFFLINE_URL, response);
}

async function offlinePage() {
  const cache = await caches.open(SHELL);
  return (await cache.match(OFFLINE_URL, { ignoreVary: true })) || Response.error();
}

/** Clients the worker answered from its cache, by id, with the copy's Date (the shell asks to show its banner). */
const servedFromCache = new Map();

async function navigate(event, url) {
  try {
    const response = await fetch(event.request);
    const landed = response.url ? new URL(response.url) : url;
    if (SIGNED_OUT.test(landed.pathname)) event.waitUntil(serial(() => forgetPeople(null)));
    else if (keepable(url) && storable(response)) {
      const copy = response.clone();
      event.waitUntil(serial(() => keepPage(url.href, copy)));
    }
    return response;
  } catch {
    const kept = keepable(url) ? await serial(() => keptPage(url.href)) : null;
    if (kept) {
      if (event.resultingClientId) servedFromCache.set(event.resultingClientId, kept.headers.get("date") || "");
      return kept;
    }
    return offlinePage();
  }
}

/**
 * A build file the page itself requested: from the cache when it is there, else fetched and, when it is a whole
 * same-origin script, stylesheet, font or image, kept (an HTML 404 under /_next/static, say, is not).
 */
async function buildFile(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (
    response.status === 200 &&
    response.type === "basic" &&
    !response.redirected &&
    BUILD_TYPE.test(response.headers.get("content-type") || "")
  ) {
    const copy = response.clone();
    cache.put(request, copy).catch(() => {});
  }
  return response;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      await keepOfflinePage();
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      // Another build's pages load another build's files: a new version starts with no kept pages.
      const older = names.some(
        (name) => (name.startsWith("static-") && name !== STATIC) || (name.startsWith("offline-") && name !== SHELL),
      );
      await Promise.all(
        names
          .filter((name) => (name.startsWith(PEOPLE) ? older : name !== STATIC && name !== SHELL))
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || NEVER.test(url.pathname)) return;
  // The URL is already resolved ("..", "%2e%2e"): a path that leaves /_next/static is not a build file. No query either.
  if (url.pathname.startsWith("/_next/static/") && !url.search) {
    event.respondWith(buildFile(request));
  } else if (request.mode === "navigate" && request.destination === "document") {
    event.respondWith(navigate(event, url));
  }
});

/** The page language /offline was last fetched in for a person ({type: "user", lang}); this worker's lifetime only. */
let offlineLang = null;

/**
 * What the shell asks, one at a time and in order (so a visit never lands before the person is set; serial). `later`
 * takes work that must not hold the answers queued behind this one (the /offline refetch: its own cache, no person's).
 */
async function answer(data, source, later) {
  if (!data || typeof data !== "object") return null;
  if (data.type === "user" && typeof data.hash === "string" && HASH.test(data.hash)) {
    const name = `${PEOPLE}${data.hash}`;
    const created = !(await caches.has(name));
    const lang = typeof data.lang === "string" ? data.lang : "";
    await forgetPeople(name);
    await sweep(await caches.open(name));
    // /offline in this person's language: fetched again only for a new person's cache or a page language changed.
    if (created || lang !== offlineLang) {
      offlineLang = lang;
      later(keepOfflinePage().catch(() => {}));
    }
    return { ok: true };
  }
  if (data.type === "clear") {
    await forgetPeople(null);
    offlineLang = null;
    later(keepOfflinePage().catch(() => {}));
    return { ok: true };
  }
  if (data.type === "visit" && typeof data.url === "string") {
    // A page reached inside the app (no page load went through the worker): fetched once more, as a page.
    const url = new URL(data.url, self.location.origin);
    url.hash = "";
    if (!keepable(url)) return { ok: false };
    const kept = await keptPage(url.href);
    if (kept && age(kept) < FRESH_MS) return { ok: true };
    const response = await fetch(url.href, {
      credentials: "same-origin",
      headers: { accept: "text/html" },
      signal: AbortSignal.timeout(15000),
    }).catch(() => null);
    if (response && SIGNED_OUT.test(new URL(response.url || url.href).pathname)) await forgetPeople(null);
    else if (response && storable(response)) await keepPage(url.href, response);
    return { ok: true };
  }
  if (data.type === "status") {
    const id = source && source.id;
    return { cached: servedFromCache.has(id), date: servedFromCache.get(id) || "" };
  }
  return null;
}

self.addEventListener("message", (event) => {
  const port = event.ports && event.ports[0];
  const later = (work) => event.waitUntil(work);
  const done = serial(() => answer(event.data, event.source, later)).catch(() => ({ ok: false }));
  event.waitUntil(done.then((reply) => port && port.postMessage(reply)));
});
