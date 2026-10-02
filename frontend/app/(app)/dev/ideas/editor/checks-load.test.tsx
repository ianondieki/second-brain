import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PROPOSAL_ID } from "@/test/assistant";
import { checksCalls } from "@/test/checks";
import { READY, renderEditor } from "@/test/ideas-editor";

// P19-F (REQ-PROP-04, REQ-REPO-01): the teaser checks card is code-split from the editor (docs/spec/07 item 5: the
// editor sits at its 150 KB budget). Until a check is pressed the page holds only its heading and two buttons; a card
// whose code fails to load leaves the editor usable, says so politely, and loads afresh on the next press.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

// The first load of the card's module fails as an offline chunk fetch does; later loads get the real module.
const loads = vi.hoisted(() => ({ count: 0 }));
vi.mock("@/app/(app)/dev/ideas/editor/Checks", async (importOriginal) => {
  loads.count += 1;
  if (loads.count === 1) throw new TypeError("Failed to fetch dynamically imported module");
  return importOriginal();
});

afterEach(() => cleanup());

const source = (name: string) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

describe("code splitting", () => {
  it("never imports the card, its answers or the checks' calls into the editor's own code", () => {
    const editor = source("./Editor.tsx");
    // `import type` is erased; anything else would put the card's code on the page.
    const staticImport = (from: string) =>
      new RegExp(String.raw`^\s*(import|export)(?!\s+type\b)[^;]*?from\s+["']${from}["']`, "m");
    expect(editor).not.toMatch(staticImport(String.raw`\./Checks`));
    expect(editor).not.toMatch(staticImport(String.raw`\./CheckAnswer`));
    expect(editor).not.toMatch(staticImport(String.raw`\.\./checks`));
    expect(editor).toContain('import("./Checks")');
  });

  it("keeps the checks' calls free of the API client until a check runs", () => {
    const calls = source("../checks.ts");
    expect(calls).not.toMatch(/^\s*import(?!\s+type\b)[^;]*?from\s+["']@\/lib\/api\/client["']/m);
    expect(calls).toContain('import("./save")');
  });
});

describe("a card whose code did not load", () => {
  it("says so politely, gives focus back to the button, and loads afresh on the next press", async () => {
    const fake = checksCalls();
    const spy = vi.spyOn(console, "error").mockImplementation(() => {}); // React reports the caught error
    await renderEditor({ id: PROPOSAL_ID, initial: READY, checks: fake });
    const button = () => screen.getByRole("button", { name: "Check overlap" });

    await act(async () => {
      fireEvent.click(button());
    });
    const notice = await screen.findByText("We could not reach the server. Check your connection, then try again.");
    expect(notice.closest("[role]")!.getAttribute("role")).toBe("status");
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(button()));
    expect(fake.overlap).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(button());
    });
    await waitFor(() => expect(fake.overlap).toHaveBeenCalledTimes(1));
    expect(loads.count).toBe(2);
    expect(document.querySelector("[data-check='overlap']")!.textContent).toBe(
      "No overlap with other published ideas (compared with 12).",
    );
    spy.mockRestore();
  });
});
