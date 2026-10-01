import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { TopBar } from "./TopBar";
import { TopBarBase } from "./TopBarBase";

// docs/spec/07 item 1: a skip link, then the top bar with the working name (a link home) on the left and at most one
// control on the right; not sticky, so it never covers focused content (REQ-UX-06).

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(cleanup);

async function renderTree(node: ReactNode) {
  renderWithIntl(<>{await resolveServerTree(node)}</>);
}

describe("TopBar", () => {
  it("opens with a skip link to the main content, then the working name linking home", async () => {
    await renderTree(<TopBar />);
    const focusable = [...document.querySelectorAll("a, button")];
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(focusable[0]).toBe(skip);
    expect(skip.getAttribute("href")).toBe("#main");
    expect(skip.className.split(" ")).toEqual(expect.arrayContaining(["sr-only", "focus:not-sr-only"]));
    const home = screen.getByRole("link", { name: "Wazo" });
    expect(home.getAttribute("href")).toBe("/");
    expect(home.className.split(" ")).toContain("min-h-11");
  });

  it("links home to the portal it is given and holds its one control on the right of the bar", async () => {
    await renderTree(
      <TopBar homeHref="/org?org=1">
        <button type="button">Account</button>
      </TopBar>,
    );
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Wazo" }).getAttribute("href")).toBe("/org?org=1");
    // The lattice band is the header's first child; the bar holds the brand (wordmark and the prototype badge) and the control.
    const bar = header.lastElementChild!;
    expect([...bar.children].map((child) => child.textContent)).toEqual(["WazoPrototype", "Account"]);
    expect(bar.className.split(" ")).toContain("justify-between");
  });

  it("is not sticky, so it never covers what has focus", async () => {
    await renderTree(<TopBar />);
    const header = screen.getByRole("banner");
    expect(header.className).not.toMatch(/\b(sticky|fixed)\b/);
    expect(header.firstElementChild!.className).not.toMatch(/\b(sticky|fixed)\b/);
  });
});

describe("TopBarBase", () => {
  it("draws its home link with the anchor it is given (a plain one on the static not-found screen)", async () => {
    function Marked(props: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
      return <a data-anchor="marked" {...props} />;
    }
    await renderTree(<TopBarBase homeHref="/dev" Anchor={Marked} />);
    const home = screen.getByRole("link", { name: "Wazo" });
    expect(home.getAttribute("data-anchor")).toBe("marked");
    expect(home.getAttribute("href")).toBe("/dev");
    cleanup();
    await renderTree(<TopBarBase Anchor="a" />);
    expect(screen.getByRole("link", { name: "Wazo" }).getAttribute("href")).toBe("/");
  });
});
