import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { TrendCalls, TrendOutcome } from "./calls";
import { DraftTrends } from "./DraftTrends";
import { TrendDecision } from "./TrendDecision";
import { seededTrend, trendRefusalOf, trendReviewHref } from "./trends";

// REQ-DEV-02 (P22-BF; D-60): trend cards on the research page. Publish or Reject behind a confirmation and the
// step-up; a card naming an organisation no source names can only be rejected; "Draft trends now" queues the run.

const router = vi.hoisted(() => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const confirmStepUp = vi.hoisted(() => vi.fn(async () => ({ ok: true as const })));
vi.mock("../calls", () => ({ confirmStepUp }));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
beforeEach(() => router.refresh.mockReset());
afterEach(cleanup);

function calls(...outcomes: TrendOutcome[]): TrendCalls {
  const decide = vi.fn();
  for (const outcome of outcomes) decide.mockResolvedValueOnce(outcome);
  decide.mockResolvedValue({ ok: true });
  return { decide, draft: vi.fn(async () => ({ ok: true as const })) };
}

async function decide(name: "Publish" | "Reject") {
  fireEvent.click(screen.getByRole("button", { name }));
  const dialog = document.querySelector("dialog[open]") as HTMLDialogElement;
  const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent === name)!;
  await act(async () => fireEvent.click(confirm));
}

describe("trend cards' rules", () => {
  it("links the review page, labels hand-written cards and words refusals", () => {
    expect(trendReviewHref("c1")).toBe("/admin/research/trends/c1");
    expect(seededTrend({ llm_trace_id: null })).toBe(true);
    expect(seededTrend({ llm_trace_id: "trace" })).toBe(false);
    expect(trendRefusalOf(403, { detail: { code: "step_up_required", message: "x" } })).toEqual({ kind: "stepUp" });
    expect(trendRefusalOf(409, { detail: { code: "unsourced_name", message: "x" } })).toEqual({ kind: "refusal", code: "unsourced_name" });
    expect(trendRefusalOf(404, undefined)).toEqual({ kind: "refusal", code: "not_found" });
    expect(trendRefusalOf(500, undefined)).toEqual({ kind: "refusal", code: "generic" });
  });
});

describe("the trend decision", () => {
  it("publishes after the confirmation", async () => {
    const api = calls();
    renderWithIntl(<TrendDecision cardId="c1" calls={api} />);
    expect(screen.getByRole("button", { name: "Publish" }).hasAttribute("data-primary")).toBe(true);
    await decide("Publish");
    expect(api.decide).toHaveBeenCalledWith("c1", "publish");
    expect(screen.getByRole("status").textContent).toBe("Published. Developers see it on Home in turn.");
  });

  it("asks for a fresh code, then repeats the decision", async () => {
    const api = calls({ ok: false, refusal: { kind: "stepUp" } });
    renderWithIntl(<TrendDecision cardId="c1" calls={api} />);
    await decide("Reject");
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm" })));
    expect(api.decide).toHaveBeenCalledTimes(2);
    expect(api.decide).toHaveBeenLastCalledWith("c1", "reject");
    expect(screen.getByRole("status").textContent).toBe("Rejected.");
  });

  it("leaves only Reject for a card naming an organisation no source names", async () => {
    const api = calls({ ok: false, refusal: { kind: "refusal", code: "unsourced_name" } });
    renderWithIntl(<TrendDecision cardId="c1" calls={api} />);
    await decide("Publish");
    expect(screen.getByRole("alert").textContent).toContain("no source names");
    expect(screen.getByRole("button", { name: "Publish" }).getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(true);
  });
});

describe("Draft trends now", () => {
  it("queues the run and says what follows, as a secondary action", async () => {
    const api = calls();
    renderWithIntl(<DraftTrends calls={api} />);
    const button = screen.getByRole("button", { name: "Draft trends now" });
    expect(button.hasAttribute("data-primary")).toBe(false);
    await act(async () => fireEvent.click(button));
    expect(api.draft).toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("Queued.");
  });

  it("says when it could not be queued", async () => {
    const api = { ...calls(), draft: vi.fn(async () => ({ ok: false as const, refusal: { kind: "refusal" as const, code: "generic" as const } })) };
    renderWithIntl(<DraftTrends calls={api} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Draft trends now" })));
    expect(screen.getByRole("status").textContent).toBe("The run could not be queued. Try again.");
  });
});
