import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { ENGAGEMENT_ID } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { LIMITS } from "@/test/messages";

import type { ThreadCalls } from "./calls";
import { Composer } from "./Composer";

// REQ-ENG-11 / REQ-DEV-03 (P22-CF review): choosing, uploading and removing files load with the first file chosen
// (./attach.ts). When that code cannot be loaded (offline, a new deploy) the composer says so in one sentence and
// nothing is uploaded; the text and Send stay.

vi.mock("./attach", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});
afterEach(cleanup);

describe("files whose code cannot load", () => {
  it("say so in one sentence above the buttons, upload nothing and keep Send", async () => {
    const uploadFile = vi.fn();
    const calls = { postMessage: vi.fn(), uploadFile, removeStaged: vi.fn() } as unknown as ThreadCalls;
    renderWithIntl(<Composer engagementId={ENGAGEMENT_ID} limits={LIMITS} locale="en" calls={calls} onSent={vi.fn()} onClosed={vi.fn()} />);
    fireEvent.change(document.querySelector("input[type=file]")!, { target: { files: [new File(["# Plan"], "plan.md", { type: "" })] } });
    expect((await screen.findByRole("alert")).textContent).toBe(en.trackerMessages.refusal.attachFailed);
    expect(uploadFile).not.toHaveBeenCalled();
    expect(document.querySelector("[data-pending-file]")).toBeNull();
    expect(screen.getByRole("button", { name: "Send" }).getAttribute("aria-disabled")).toBeNull();
  });
});
