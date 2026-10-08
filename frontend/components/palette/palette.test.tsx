import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DEV_PALETTE, SEARCH_SACCO } from "./fixtures";
import { shortcutFor } from "./PaletteSlot";
import { PaletteTrigger } from "./PaletteTrigger";
import { RECENT_KEY } from "./recent";

// D-67 (P25; REQ-UX-01, REQ-UX-06): the command palette. WAI-ARIA APG combobox with a grouped listbox in a modal
// dialog; opened by Ctrl/⌘ K anywhere, "/" outside a text field and the top bar's Search button; its code loads on
// first use; the API's search groups are left out when the call fails.

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), pathname: "/dev" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace, refresh: nav.refresh }),
  usePathname: () => nav.pathname,
}));

const loads = vi.hoisted(() => ({ count: 0 }));
vi.mock("./load", () => {
  let palette: Promise<typeof import("./CommandPalette")> | null = null;
  return {
    loadPalette: () => {
      loads.count += 1;
      palette ??= import("./CommandPalette");
      return palette;
    },
  };
});

beforeAll(() => {
  // jsdom implements <dialog> but not its modal methods.
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  loads.count = 0;
  nav.pathname = "/dev";
  nav.push.mockReset();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(new Response(JSON.stringify(SEARCH_SACCO), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderTrigger() {
  render(
    <>
      <input aria-label="A field on the page" />
      <PaletteTrigger data={DEV_PALETTE} />
    </>,
  );
  return screen.getByRole("button", { name: "Search or jump to" });
}

async function openWith(key: () => void) {
  key();
  return screen.findByRole("dialog", { name: "Search or jump to" });
}

describe("PaletteTrigger", () => {
  it("names the shortcut as the platform writes it", () => {
    expect(shortcutFor("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)")).toBe("⌘ K");
    expect(shortcutFor("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBe("⌘ K");
    expect(shortcutFor("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("Ctrl K");
    expect(shortcutFor("")).toBe("Ctrl K");
  });

  it("is a named button with the shortcut as this computer writes it, and loads nothing until used", () => {
    const button = renderTrigger();
    expect(button.getAttribute("aria-haspopup")).toBe("dialog");
    expect(button.getAttribute("aria-keyshortcuts")).toContain("Control+K");
    expect(within(button).getByText("Ctrl K").getAttribute("aria-hidden")).toBe("true");
    expect(loads.count).toBe(0);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens on Ctrl K and on ⌘ K, even in a text field", async () => {
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    expect(loads.count).toBe(1);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    const field = screen.getByRole("textbox", { name: "A field on the page" });
    field.focus();
    await openWith(() => fireEvent.keyDown(field, { key: "K", metaKey: true }));
  });

  it('opens on "/" outside a text field, never while typing in one', async () => {
    renderTrigger();
    const field = screen.getByRole("textbox", { name: "A field on the page" });
    fireEvent.keyDown(field, { key: "/" });
    await act(async () => {});
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(loads.count).toBe(0);
    await openWith(() => fireEvent.keyDown(document.body, { key: "/" }));
  });

  it("starts loading the palette when the pointer rests on the button or it takes focus", () => {
    const button = renderTrigger();
    fireEvent.pointerEnter(button);
    fireEvent.focus(button);
    expect(loads.count).toBe(2); // the same one request (load.ts keeps it), asked twice
  });

  it("loads the palette's code through a dynamic import only (no static import of the palette)", () => {
    const here = join(process.cwd(), "components/palette");
    const trigger = readFileSync(join(here, "PaletteTrigger.tsx"), "utf8");
    expect(trigger).not.toMatch(/^import \{[^}]*\} from "\.\/CommandPalette";/m);
    expect(trigger).toMatch(/^import type \{ CommandPaletteProps \} from "\.\/CommandPalette";/m);
    expect(readFileSync(join(here, "load.ts"), "utf8")).toContain('import("./CommandPalette")');
  });

  it("remembers a detail page this browser opens, by its address and the title on its screen", async () => {
    nav.pathname = "/dev/ideas/abc";
    render(
      <main>
        <h1>Repayment nudges for SACCO members</h1>
        <PaletteTrigger data={DEV_PALETTE} />
      </main>,
    );
    await waitFor(() => expect(localStorage.getItem(RECENT_KEY)).toContain("/dev/ideas/abc"));
    expect(JSON.parse(localStorage.getItem(RECENT_KEY)!)).toEqual([{ href: "/dev/ideas/abc", title: "Repayment nudges for SACCO members" }]);
  });
});

describe("CommandPalette", () => {
  it("is a combobox controlling a grouped listbox, the first option active", async () => {
    renderTrigger();
    fireEvent.click(screen.getByRole("button", { name: "Search or jump to" }));
    const dialog = await screen.findByRole("dialog", { name: "Search or jump to" });
    const combo = within(dialog).getByRole("combobox", { name: "Search pages, your work, problems and companies" });
    expect(document.activeElement).toBe(combo);
    const listbox = within(dialog).getByRole("listbox");
    expect(combo.getAttribute("aria-controls")).toBe(listbox.id);
    expect(combo.getAttribute("aria-expanded")).toBe("true");
    const groups = within(listbox).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["Go to", "Actions"]);
    const options = within(listbox).getAllByRole("option");
    expect(options[0].textContent).toContain("Home");
    expect(combo.getAttribute("aria-activedescendant")).toBe(options[0].id);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
    expect(within(groups[1]).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "New proposal",
      "Switch to dark appearance",
      "Sign out",
    ]);
  });

  it("moves the active option with the arrows (wrapping), Home and End", async () => {
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    const combo = screen.getByRole("combobox");
    const options = screen.getAllByRole("option");
    const active = () => combo.getAttribute("aria-activedescendant");
    fireEvent.keyDown(combo, { key: "ArrowDown" });
    expect(active()).toBe(options[1].id);
    fireEvent.keyDown(combo, { key: "ArrowUp" });
    fireEvent.keyDown(combo, { key: "ArrowUp" });
    expect(active()).toBe(options.at(-1)!.id);
    fireEvent.keyDown(combo, { key: "Home" });
    expect(active()).toBe(options[0].id);
    fireEvent.keyDown(combo, { key: "End" });
    expect(active()).toBe(options.at(-1)!.id);
    expect(options.at(-1)!.getAttribute("aria-selected")).toBe("true");
  });

  it("filters as you type, marks the typed letters, and opens the active option with Enter", async () => {
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    const combo = screen.getByRole("combobox");
    fireEvent.change(combo, { target: { value: "disc" } });
    const option = screen.getByRole("option", { name: "Discover" });
    expect(option.querySelector("mark")?.textContent).toBe("Disc");
    fireEvent.keyDown(combo, { key: "Enter" });
    expect(nav.push).toHaveBeenCalledWith("/dev/discover");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the active option in a new tab with Ctrl Enter", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    const combo = screen.getByRole("combobox");
    fireEvent.change(combo, { target: { value: "help" } });
    fireEvent.keyDown(combo, { key: "Enter", ctrlKey: true });
    expect(open).toHaveBeenCalledWith("/help", "_blank", "noopener,noreferrer");
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("closes on Escape and gives focus back to what opened it", async () => {
    const button = renderTrigger();
    button.focus();
    await openWith(() => fireEvent.click(button));
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("adds the API's groups after a pause in typing, the typed letters marked", async () => {
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "sacco" } });
    const ideas = await screen.findByRole("group", { name: "Your ideas" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const sent = fetchMock.mock.calls[0][0] as Request;
    expect(new URL(sent.url).pathname + new URL(sent.url).search).toBe("/api/me/search?q=sacco");
    expect(sent.method).toBe("GET");
    const option = within(ideas).getByRole("option");
    expect(option.textContent).toContain("Repayment nudges for SACCO members");
    expect(option.querySelector("mark")?.textContent).toBe("SACCO");
    expect(screen.getByRole("group", { name: "Problems" })).toBeTruthy();
  });

  it("asks the API once per pause, aborting the call a new keystroke replaces", async () => {
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    const combo = screen.getByRole("combobox");
    fireEvent.change(combo, { target: { value: "sa" } });
    fireEvent.change(combo, { target: { value: "sac" } });
    fireEvent.change(combo, { target: { value: "sacco" } });
    await screen.findByRole("group", { name: "Your ideas" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["a server error", () => fetchMock.mockResolvedValue(new Response("{}", { status: 500 }))],
    ["the rate limit", () => fetchMock.mockResolvedValue(new Response("{}", { status: 429 }))],
    ["no network", () => fetchMock.mockRejectedValue(new TypeError("offline"))],
  ])("on %s, says search is unavailable, leaves its groups out and keeps the rest", async (_, fail) => {
    fail();
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ho" } });
    expect(await screen.findByText("Search is unavailable right now. Sections and recent pages still work.")).toBeTruthy();
    expect(screen.getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual(["Go to"]);
    expect(screen.getByRole("option", { name: "Home" })).toBeTruthy();
    expect(screen.queryByText(/Nothing matches/)).toBeNull();
  });

  it("says search is unavailable, not that nothing matches, when nothing local matches either", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzqx" } });
    expect(await screen.findByText("Search is unavailable right now. Sections and recent pages still work.")).toBeTruthy();
    expect(screen.queryByText(/Nothing matches/)).toBeNull();
  });

  it("says in one sentence when a successful search finds nothing", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ q: "zzqx", groups: [] }), { status: 200 }));
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzqx" } });
    expect(await screen.findByText("Nothing matches “zzqx”.")).toBeTruthy();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByRole("combobox").hasAttribute("aria-activedescendant")).toBe(false);
  });

  it("lists the recent pages this browser remembered", async () => {
    localStorage.setItem(RECENT_KEY, JSON.stringify([{ href: "/dev/engagements/e1", title: "Fuel-level alerts" }]));
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    const recent = screen.getByRole("group", { name: "Recent" });
    fireEvent.click(within(recent).getByRole("option", { name: "Fuel-level alerts" }));
    expect(nav.push).toHaveBeenCalledWith("/dev/engagements/e1");
  });

  it("switches the appearance from the Actions group", async () => {
    renderTrigger();
    await openWith(() => fireEvent.keyDown(document.body, { key: "k", ctrlKey: true }));
    fireEvent.click(screen.getByRole("option", { name: "Switch to dark appearance" }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
