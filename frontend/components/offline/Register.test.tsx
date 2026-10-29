import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { useState } from "react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/AccountMenu";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { installOffered } from "./install";
import { InstallOffer } from "./InstallOffer";
import { OfflineBanner } from "./OfflineSlot";
import { Register } from "./Register";
import { forgetOffline } from "./clear";

// P27 track F (REQ-UX-08; D-69): the offline part of the pages the worker keeps (and both Homes). The island registers
// the worker with the build's version and tells it whose cache it is; offline (or from the cache) it marks the page
// offline, which shows the server-drawn "as of" banner, and makes <main> read-only until the connection is back; it keeps
// the install offer for the account menu; sign-out clears the cache.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/components/palette/PaletteSlot", () => ({ accountHash: async () => null }));
vi.mock("next/navigation", () => ({
  usePathname: () => location.pathname,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));

const USER_ID = "0b8f4c1e-0000-4000-8000-00000000a11c";
/** The page's rendered hash, as the server computes it (PaletteSlot accountHash). */
const HASH = createHash("sha256").update(`wazo-recent|${USER_ID}`).digest("hex").slice(0, 20);
/** GET /api/auth/me: the live session's user id; null signed out (401); undefined unreadable (the request fails). */
const session = { me: USER_ID as string | null | undefined };

/** A worker that answers every message on its port (as sw.js does) and remembers what it was told. */
function fakeWorker(answers: Record<string, unknown> = {}) {
  const told: unknown[] = [];
  const worker = {
    postMessage: vi.fn((message: { type: string }, ports?: MessagePort[]) => {
      told.push(message);
      ports?.[0]?.postMessage(answers[message.type] ?? { ok: true });
      // As sw.js: "from the cache" is answered once per page load.
      if (message.type === "status") delete answers.status;
    }),
  };
  const registration = { active: worker };
  const container = {
    register: vi.fn(async () => registration),
    ready: Promise.resolve(registration),
    getRegistration: vi.fn(async () => registration),
  };
  Object.defineProperty(navigator, "serviceWorker", { value: container, configurable: true });
  return { worker, told, container };
}

/** Cache Storage with the page's own copy (its Date) and some caches. */
function fakeCaches(date: string | null, names: string[] = []) {
  const store = new Set(names);
  const caches = {
    match: vi.fn(async () => new Response("<html></html>", { headers: date ? { date } : {} })),
    keys: vi.fn(async () => [...store]),
    delete: vi.fn(async (name: string) => store.delete(name)),
  };
  vi.stubGlobal("caches", caches);
  return { caches, store };
}

function online(value: boolean) {
  Object.defineProperty(navigator, "onLine", { value, configurable: true });
}

function page() {
  return (
    <main id="main">
      <Register hash={HASH} version="build-7" />
      <div>
        <h1>Maziwa baridi</h1>
        <form data-testid="form" onSubmit={(event) => event.preventDefault()}>
          <input aria-label="Note" />
          <select aria-label="Choice">
            <option>One</option>
          </select>
          <textarea aria-label="Message" />
          <button type="submit">Send</button>
          <button type="button" disabled>
            Already off
          </button>
        </form>
      </div>
    </main>
  );
}

/** Whether a control cannot be used. */
const off = (element: Element) => element.matches(":disabled");

beforeEach(() => {
  session.me = USER_ID;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url !== "/api/auth/me" || session.me === undefined) throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify(session.me === null ? {} : { user: { id: session.me } }), {
        status: session.me === null ? 401 : 200,
      });
    }),
  );
  online(true);
  window.history.replaceState(null, "", "/dev/engagements/0b8f4c1e-5a2d-4e7f-9c3b-1d2e3f4a5b6c");
  document.documentElement.removeAttribute("data-offline");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("the offline island", () => {
  it("draws nothing, on the server or in the browser, so the page hydrates as it was rendered", () => {
    expect(renderToString(<Register hash={HASH} version="build-7" />)).toBe("");
  });

  it("registers /sw.js with the build's version for the whole site, says whose cache it is, then asks to keep the page", async () => {
    const { container, told } = fakeWorker();
    fakeCaches(null);
    renderWithIntl(page());
    await waitFor(() => expect(told).toContainEqual({ type: "visit", url: location.href }));
    expect(container.register).toHaveBeenCalledWith("/sw.js?v=build-7");
    const types = told.map((m) => (m as { type: string }).type);
    expect(types.indexOf("user")).toBeGreaterThanOrEqual(0);
    expect(types.indexOf("user")).toBeLessThan(types.indexOf("visit"));
    expect(told).toContainEqual({ type: "user", hash: HASH, lang: document.documentElement.lang });
    expect(document.documentElement.hasAttribute("data-offline")).toBe(false);
  });

  it("checks the page's hash against the live session before it speaks, with the session's cookie and no cache", async () => {
    const { told } = fakeWorker();
    renderWithIntl(page());
    await waitFor(() => expect(told).toContainEqual({ type: "user", hash: HASH, lang: document.documentElement.lang }));
    expect(fetch).toHaveBeenCalledWith("/api/auth/me", { credentials: "same-origin", cache: "no-store" });
  });

  it.each([
    ["someone else is signed in now", "0b8f4c1e-0000-4000-8000-0000000b41a2"],
    ["no one is signed in (401)", null],
  ])("a stale page (%s) says nothing to the worker and loads itself again", async (_why, me) => {
    session.me = me;
    const { told } = fakeWorker();
    const reload = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      reload,
      href: window.location.href,
      pathname: window.location.pathname,
    });
    renderWithIntl(page());
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(told).toEqual([]);
  });

  it("takes the page's own word when the session cannot be read (offline: a cached page)", async () => {
    session.me = undefined;
    const { told } = fakeWorker();
    renderWithIntl(page());
    await waitFor(() => expect(told).toContainEqual(expect.objectContaining({ type: "user", hash: HASH })));
  });

  it("ignores a reply that arrives after its run ended (another page, person or build)", async () => {
    let answer: (() => void) | undefined;
    const { worker } = fakeWorker();
    worker.postMessage.mockImplementation((message: { type: string }, ports?: MessagePort[]) => {
      if (message.type === "status") answer = () => ports?.[0]?.postMessage({ cached: true });
    });
    const { unmount } = renderWithIntl(page());
    await waitFor(() => expect(answer).toBeDefined());
    unmount();
    answer!();
    await new Promise((r) => setTimeout(r, 10));
    expect(document.documentElement.hasAttribute("data-offline")).toBe(false);
    expect(document.querySelectorAll("[data-offline-locked]")).toHaveLength(0);
  });

  it("clears the cache when the signed-in person cannot be read (no hash)", async () => {
    const { told } = fakeWorker();
    renderWithIntl(<Register hash={null} version="build-7" />);
    await waitFor(() => expect(told).toContainEqual({ type: "clear" }));
    expect(told).not.toContainEqual(expect.objectContaining({ type: "user" }));
  });

  it("offline: marks the page offline (the banner shows) and disables every control in main", async () => {
    fakeWorker();
    online(false);
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    // The worker says the page was not its copy: "offline", not "cached" (its clocks' instant is right; they stay).
    await waitFor(() => expect(document.documentElement.getAttribute("data-offline")).toBe("offline"));
    for (const name of ["Note", "Choice", "Message"]) expect(off(screen.getByLabelText(name))).toBe(true);
    expect(off(screen.getByRole("button", { name: "Send" }))).toBe(true);
    // Nothing can be sent: the submit button does nothing.
    const submitted = vi.fn();
    screen.getByTestId("form").addEventListener("submit", submitted);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(submitted).not.toHaveBeenCalled();
  });

  it("gives every control back once online, but those the page had disabled itself", async () => {
    fakeWorker();
    online(false);
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    expect(screen.getByRole("button", { name: "Send" }).hasAttribute("data-offline-locked")).toBe(true);

    online(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(document.documentElement.hasAttribute("data-offline")).toBe(false);
    expect(off(screen.getByRole("button", { name: "Send" }))).toBe(false);
    expect(off(screen.getByLabelText("Note"))).toBe(false);
    expect(document.querySelectorAll("[data-offline-locked]")).toHaveLength(0);
    // What the page itself had disabled stays so.
    expect(off(screen.getByRole("button", { name: "Already off" }))).toBe(true);
  });

  it("locks controls that appear while offline", async () => {
    fakeWorker();
    online(false);
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    const late = document.createElement("button");
    late.textContent = "Late";
    document.querySelector("form")!.append(late);
    await waitFor(() => expect(off(late)).toBe(true));
  });

  it("disables again a control a client component enables while offline", async () => {
    fakeWorker();
    online(false);
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    send.disabled = false; // as React would, on a re-render with disabled={false}
    await waitFor(() => expect(send.disabled).toBe(true));
  });

  it("unlocks a page reached inside the app from a cached one (it is fresh), and does not reload it once online", async () => {
    fakeWorker({ status: { cached: true } });
    const reload = vi.fn();
    const at = (pathname: string) =>
      vi.stubGlobal("location", { ...window.location, reload, href: `${window.location.origin}${pathname}`, pathname });
    at(window.location.pathname);
    let navigate = () => {};
    function Shell() {
      const [, setN] = useState(0);
      navigate = () => setN((n) => n + 1);
      return page();
    }
    renderWithIntl(<Shell />);
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    // A client-side navigation to another page, fetched online: the same island, a new pathname.
    at("/dev/engagements");
    act(() => navigate());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(false));
    expect(off(screen.getByRole("button", { name: "Send" }))).toBe(false);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(reload).not.toHaveBeenCalled();
  });

  it("back online, loads a page the worker answered from its cache again instead of unlocking it stale", async () => {
    fakeWorker({ status: { cached: true } });
    const reload = vi.fn();
    vi.stubGlobal("location", {
      ...window.location,
      reload,
      href: window.location.href,
      pathname: window.location.pathname,
    });
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(reload).toHaveBeenCalledTimes(1);
    expect(off(screen.getByRole("button", { name: "Send" }))).toBe(true);
  });

  it("takes a page read without a connection for the worker's copy until the worker says otherwise", async () => {
    // A worker that has not answered yet (sw.ready never settles here).
    const container = { register: vi.fn(async () => ({})), ready: new Promise(() => {}), getRegistration: vi.fn() };
    Object.defineProperty(navigator, "serviceWorker", { value: container, configurable: true });
    online(false);
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.getAttribute("data-offline")).toBe("cached"));
  });

  it("marks the page offline when the worker answered it from its cache, though the browser says it is online", async () => {
    fakeWorker({ status: { cached: true, date: "" } });
    renderWithIntl(page());
    await waitFor(() => expect(document.documentElement.hasAttribute("data-offline")).toBe(true));
    // P27: a page from the worker's copy says so (its deadline clocks are hidden: their instant is the copy's).
    expect(document.documentElement.getAttribute("data-offline")).toBe("cached");
  });

  it("follows the browser going offline after the page loaded, and leaves nothing behind when it goes", async () => {
    fakeWorker();
    const { unmount } = renderWithIntl(page());
    await act(async () => {});
    act(() => {
      online(false);
      window.dispatchEvent(new Event("offline"));
    });
    expect(document.documentElement.hasAttribute("data-offline")).toBe(true);
    unmount();
    expect(document.documentElement.hasAttribute("data-offline")).toBe(false);
  });
});

describe("the offline banner", () => {
  it("names the page and the time this answer was made, in Nairobi time, as a status", async () => {
    const { container } = renderWithIntl(
      <>
        {await resolveServerTree(await OfflineBanner({ page: "Maziwa baridi", at: new Date("2026-10-12T11:05:00Z") }))}
      </>,
    );
    const banner = container.querySelector<HTMLElement>("[data-offline-banner]")!;
    expect(banner.getAttribute("role")).toBe("status");
    expect(banner.textContent).toBe(
      "You're offline. This is Maziwa baridi as of 12 Oct 2026, 14:05 EAT. Actions are available once you're back online.",
    );
  });

  it("is shown by the stylesheet only while the page is marked offline", () => {
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toMatch(/\n\[data-offline-banner\] \{\n  display: none;\n\}/);
    expect(css).toMatch(/\nhtml\[data-offline\] \[data-offline-banner\] \{\n  display: flex;\n\}/);
  });
});

describe("Install Wazo (the offer kept on both Homes)", () => {
  it("appears in the account menu only once the browser offered it, and shows the browser's prompt", async () => {
    fakeWorker();
    fakeCaches(null);
    renderWithIntl(
      <>
        <AccountMenu />
        <main id="main">
          <InstallOffer />
        </main>
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.queryByRole("button", { name: "Install Wazo" })).toBeNull();

    const offer = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), {
      prompt: vi.fn(async () => ({ outcome: "accepted" })),
    });
    act(() => {
      window.dispatchEvent(offer);
    });
    expect(offer.defaultPrevented).toBe(true); // kept for the menu, not the browser's own bar
    expect(installOffered()).toBe(true);
    fireEvent.click(await screen.findByRole("button", { name: "Install Wazo" }));
    expect(offer.prompt).toHaveBeenCalledTimes(1);
    // An offer is used once.
    expect(installOffered()).toBe(false);
    expect(screen.queryByRole("button", { name: "Install Wazo" })).toBeNull();
  });

  it("goes once the app is installed", async () => {
    fakeWorker();
    fakeCaches(null);
    renderWithIntl(<InstallOffer />);
    act(() => {
      window.dispatchEvent(Object.assign(new Event("beforeinstallprompt", { cancelable: true }), { prompt: vi.fn() }));
    });
    expect(installOffered()).toBe(true);
    act(() => {
      window.dispatchEvent(new Event("appinstalled"));
    });
    expect(installOffered()).toBe(false);
  });
});

describe("sign-out's clearing (forgetOffline)", () => {
  it("deletes every person's offline cache, here and in the worker, and nothing else", async () => {
    const { told } = fakeWorker();
    const { store } = fakeCaches(null, [
      `trackers-${HASH}`,
      "trackers-b9c8d7e6f5a40312ab4c",
      "static-build-7",
      "offline-build-7",
    ]);
    await forgetOffline();
    expect([...store]).toEqual(["static-build-7", "offline-build-7"]);
    expect(told).toEqual([{ type: "clear" }]);
  });

  it("resolves at once where there is no worker or Cache Storage", async () => {
    await expect(forgetOffline()).resolves.toBeUndefined();
  });
});
