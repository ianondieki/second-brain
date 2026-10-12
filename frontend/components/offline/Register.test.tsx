import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/AccountMenu";
import { renderWithIntl } from "@/test/intl";

import { installOffered } from "./install";
import { Register } from "./Register";
import { forgetOffline } from "./worker";

// P27 track F (REQ-UX-08; D-69): the signed-in shell's offline island. It registers the worker with the build's
// version and tells it whose cache it is; offline (or from the cache) it shows the "as of" banner and makes <main>
// read-only until the connection is back; it keeps the install offer for the account menu; sign-out clears the cache.

vi.mock("next/navigation", () => ({
  usePathname: () => location.pathname,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));

const HASH = "a1b2c3d4e5f60718293a";

/** A worker that answers every message on its port (as sw.js does) and remembers what it was told. */
function fakeWorker(answers: Record<string, unknown> = {}) {
  const told: unknown[] = [];
  const worker = {
    postMessage: vi.fn((message: { type: string }, ports?: MessagePort[]) => {
      told.push(message);
      ports?.[0]?.postMessage(answers[message.type] ?? { ok: true });
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
    </main>
  );
}

beforeEach(() => {
  online(true);
  window.history.replaceState(null, "", "/dev/engagements/0b8f4c1e-5a2d-4e7f-9c3b-1d2e3f4a5b6c");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "serviceWorker");
});

describe("the shell's offline island", () => {
  it("draws nothing on the server, so the page hydrates as it was rendered", () => {
    expect(renderToString(<Register hash={HASH} version="build-7" />)).toBe("");
  });

  it("registers /sw.js with the build's version for the whole site and tells it whose cache it is", async () => {
    const { container, told } = fakeWorker();
    fakeCaches(null);
    renderWithIntl(page());
    await waitFor(() => expect(told).toContainEqual({ type: "user", hash: HASH }));
    expect(container.register).toHaveBeenCalledWith("/sw.js?v=build-7", { scope: "/", updateViaCache: "none" });
    // Then the tracker this page is, so it is kept even when it was reached inside the app.
    await waitFor(() => expect(told).toContainEqual({ type: "visit", url: location.href }));
    expect(told.findIndex((m) => (m as { type: string }).type === "user")).toBeLessThan(
      told.findIndex((m) => (m as { type: string }).type === "visit"),
    );
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("clears the cache when the signed-in person cannot be read (no hash)", async () => {
    const { told } = fakeWorker();
    fakeCaches(null);
    renderWithIntl(<Register hash={null} version="build-7" />);
    await waitFor(() => expect(told).toContainEqual({ type: "clear" }));
    expect(told).not.toContainEqual(expect.objectContaining({ type: "user" }));
  });

  it("never registers in the staff console", async () => {
    const { container } = fakeWorker();
    window.history.replaceState(null, "", "/admin/moderation");
    renderWithIntl(<Register hash={HASH} version="build-7" />);
    await act(async () => {});
    expect(container.register).not.toHaveBeenCalled();
  });

  it("offline: the banner says which page and as of when (EAT), and every control in main is disabled", async () => {
    fakeWorker();
    fakeCaches("Mon, 12 Oct 2026 11:05:00 GMT");
    online(false);
    renderWithIntl(page());
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toBe(
      "You're offline. This is Maziwa baridi as of 12 Oct 2026, 14:05 EAT. Actions are available once you're back online.",
    );
    expect(banner.closest("main")).toBe(document.getElementById("main"));
    for (const name of ["Note", "Choice", "Message"])
      expect((screen.getByLabelText(name) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
    // A form cannot be sent another way either (Enter in a field the browser still submits).
    const submitted = vi.fn();
    screen.getByTestId("form").addEventListener("submit", submitted);
    fireEvent.submit(screen.getByTestId("form"));
    expect(submitted.mock.calls[0]?.[0].defaultPrevented).toBe(true);
  });

  it("disables controls that appear while offline, and gives them all back once online", async () => {
    fakeWorker();
    fakeCaches(null);
    online(false);
    renderWithIntl(page());
    await screen.findByRole("status");
    const late = document.createElement("button");
    late.textContent = "Late";
    document.querySelector("form")!.append(late);
    await waitFor(() => expect(late.disabled).toBe(true));

    online(true);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(false);
    expect(late.disabled).toBe(false);
    expect((screen.getByLabelText("Note") as HTMLInputElement).disabled).toBe(false);
    // What the page itself had disabled stays so.
    expect((screen.getByRole("button", { name: "Already off" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the banner when the worker answered this page from its cache, though the browser says it is online", async () => {
    fakeWorker({ status: { cached: true, date: "" } });
    fakeCaches("Mon, 12 Oct 2026 05:30:00 GMT");
    renderWithIntl(page());
    expect((await screen.findByRole("status")).textContent).toContain("as of 12 Oct 2026, 08:30 EAT");
  });

  it("without the copy's Date, says offline without a time", async () => {
    fakeWorker();
    fakeCaches(null);
    renderWithIntl(page());
    act(() => {
      online(false);
      window.dispatchEvent(new Event("offline"));
    });
    expect((await screen.findByRole("status")).textContent).toBe(
      "You're offline. This is Maziwa baridi as you last opened it. Actions are available once you're back online.",
    );
  });
});

describe("Install Wazo", () => {
  it("appears in the account menu only once the browser offered it, and shows the browser's prompt", async () => {
    fakeWorker();
    fakeCaches(null);
    renderWithIntl(
      <>
        <AccountMenu />
        <main id="main">
          <Register hash={HASH} version="build-7" />
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
    fireEvent.click(screen.getByRole("button", { name: "Install Wazo" }));
    expect(offer.prompt).toHaveBeenCalledTimes(1);
    // An offer is used once.
    expect(installOffered()).toBe(false);
    expect(screen.queryByRole("button", { name: "Install Wazo" })).toBeNull();
  });

  it("goes once the app is installed", async () => {
    fakeWorker();
    fakeCaches(null);
    renderWithIntl(<Register hash={HASH} version="build-7" />);
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
