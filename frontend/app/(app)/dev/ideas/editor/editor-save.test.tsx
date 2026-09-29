import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Outcome } from "../calls";
import type { Attachment, MyProposal } from "../ideas";
import { EMPTY_STATE } from "../versions";
import type { SaveProblem } from "../outcomes";
import { calls, READY, renderEditor, SAVED, settleLazy } from "./fixtures";

// REQ-PROP-01 review round 1: saving and file actions. Saves never overlap and are never lost (leaving the editor
// saves what was typed); publishing saves first; a file action on a published idea works on the draft's own copies,
// never on the registered version's (a "removed" file must not stay in the next registered version).

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }) }));
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  push.mockReset();
});

type SaveResult = { outcome: Outcome<MyProposal, SaveProblem>; held: [] };

/** A saveState whose answers the test releases one by one, counting how many run at once. */
function slowSaves() {
  const pending: Array<() => void> = [];
  let running = 0;
  let most = 0;
  const saveState = vi.fn(async () => {
    running += 1;
    most = Math.max(most, running);
    await new Promise<void>((resolve) => pending.push(resolve));
    running -= 1;
    return { outcome: { ok: true, value: SAVED }, held: [] } as SaveResult;
  });
  return {
    saveState,
    release: async () => {
      await act(async () => {
        pending.shift()?.();
      });
    },
    most: () => most,
  };
}

const V1: Attachment = {
  id: "0199a000-0000-7000-8000-0000000000f1",
  file_name: "secret.pdf",
  content_type: "application/pdf",
  size_bytes: 2048,
  sha256: "aa11",
  av_status: "clean",
};
// What the API's ensure_draft makes of it: the same file under a new id, in the new draft version.
const COPY: Attachment = { ...V1, id: "0199a000-0000-7000-8000-0000000000c1" };
const WITH_COPY = { id: "p1", draft: { confidential: { attachments: [COPY] } } } as unknown as MyProposal;

describe("saving", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("never runs two saves at once: the second waits and uses the id the first created", async () => {
    const slow = slowSaves();
    await renderEditor({ calls: calls({ saveState: slow.saveState }) });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain v2" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(slow.saveState).toHaveBeenCalledTimes(1); // the second is queued behind the first
    await slow.release();
    expect(slow.saveState).toHaveBeenCalledTimes(2);
    expect(slow.saveState.mock.calls.map((call) => (call as unknown[])[0])).toEqual([null, "p1"]);
    expect(slow.most()).toBe(1);
    await slow.release();
  });

  it("saves what was typed when the editor is left before the autosave fires", async () => {
    const fake = calls();
    await renderEditor({ calls: fake });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain" } });
    cleanup(); // a client-side navigation away within 1.2 s
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(fake.saveState).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fake.saveState).mock.calls[0][1].title).toBe("Cold chain");
  });

  it("publishes only after the pending save finished, with the id it created", async () => {
    const slow = slowSaves();
    const fake = calls({ saveState: slow.saveState });
    await renderEditor({ calls: fake, initial: READY });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain, v2" } });
    fireEvent.click(screen.getByRole("button", { name: /Review and publish/ })); // starts the save
    await settleLazy();
    for (const box of screen.getAllByRole("checkbox")) fireEvent.click(box);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(fake.publish).not.toHaveBeenCalled();
    await slow.release();
    await act(async () => {});
    expect(fake.publish).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fake.publish).mock.calls[0][0]).toBe("p1");
    expect(slow.saveState.mock.calls.map((call) => (call as unknown[])[1])).toHaveLength(1);
  });
});

describe("files of a published idea", () => {
  function fileCalls(remove: Outcome<undefined, never> | { ok: false; problem: "notFound"; fields: [] }) {
    return calls({
      saveState: vi.fn(async () => ({ outcome: { ok: true as const, value: WITH_COPY }, held: [] as [] })),
      removeAttachment: vi.fn(async () => remove),
    });
  }

  it("creates the draft first, then removes the draft's own copy", async () => {
    const fake = fileCalls({ ok: true, value: undefined });
    await renderEditor({ id: "p1", hasDraft: false, initial: READY, attachments: [V1], step: 2, calls: fake });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove secret.pdf" }));
    });
    expect(fake.saveState).toHaveBeenCalledTimes(1); // the next version is drafted before any file action
    expect(fake.removeAttachment).toHaveBeenCalledWith("p1", COPY.id);
    expect(screen.queryByText("secret.pdf")).toBeNull();
  });

  it("keeps a file the API did not remove and says so", async () => {
    const fake = fileCalls({ ok: false, problem: "notFound", fields: [] });
    await renderEditor({ id: "p1", hasDraft: true, initial: READY, attachments: [COPY], step: 2, calls: fake });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Remove secret.pdf" }));
    });
    expect(fake.removeAttachment).toHaveBeenCalledWith("p1", COPY.id);
    expect(screen.getByText("secret.pdf")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

describe("publish checks", () => {
  it("announces what stops publishing and moves focus to it", async () => {
    await renderEditor({ id: "p1", initial: EMPTY_STATE, step: 3 });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/before you can publish/i);
    expect(document.activeElement).toBe(alert);
  });
});
