import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { assistantCalls, CONSENT_ON, PROPOSAL_ID } from "@/test/assistant";
import { READY, renderEditor } from "@/test/ideas-editor";

// REQ-PROP-05 (P13-F review round 1): the writing assistant's panel is code-split from the editor (docs/spec/07
// item 5: the editor is close to its 150 KB budget), and a panel whose code fails to load leaves the editor usable
// and loads afresh on the next press.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

// The first load of the panel's module fails as an offline chunk fetch does; later loads get the real module.
const loads = vi.hoisted(() => ({ count: 0 }));
vi.mock(
  "@/app/(app)/dev/ideas/editor/AssistantPanel",
  async (importOriginal) => {
    loads.count += 1;
    if (loads.count === 1)
      throw new TypeError("Failed to fetch dynamically imported module");
    return importOriginal();
  },
);

afterEach(() => cleanup());

const source = (name: string) =>
  readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

describe("code splitting", () => {
  it("never imports the panel, or the assistant's calls, into the editor's own code", () => {
    const editor = source("./Editor.tsx");
    // `import type` is erased; anything else would put the panel's code on the page.
    const staticImport = (from: string) =>
      new RegExp(
        String.raw`^\s*(import|export)(?!\s+type\b)[^;]*?from\s+["']${from}["']`,
        "m",
      );
    expect(editor).not.toMatch(staticImport(String.raw`\./AssistantPanel`));
    expect(editor).not.toMatch(staticImport(String.raw`\.\./assistant`));
    expect(editor).toContain('import("./AssistantPanel")');
  });
});

describe("a panel whose code did not load", () => {
  it("says so, gives focus back to the button, and loads afresh on the next press", async () => {
    const fake = assistantCalls({
      consentState: vi.fn(async () => ({
        ok: true as const,
        value: CONSENT_ON,
      })),
    });
    const spy = vi.spyOn(console, "error").mockImplementation(() => {}); // React reports the caught error
    await renderEditor({ id: PROPOSAL_ID, initial: READY, assistant: fake });
    const button = () =>
      screen.getByRole("button", { name: "Suggest a clearer teaser" });

    await act(async () => {
      fireEvent.click(button());
    });
    // Wait for the outcome, not a fixed delay: the failed import settles later under load.
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        "We could not reach the server. Check your connection, then try again.",
      ),
    );
    await waitFor(() => expect(document.activeElement).toBe(button()));
    expect(fake.suggest).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(button());
    });
    await waitFor(() =>
      expect(document.getElementById("assistant-panel")).not.toBeNull(),
    );
    await waitFor(() => expect(fake.suggest).toHaveBeenCalledTimes(1));
    expect(loads.count).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
    spy.mockRestore();
  });
});
