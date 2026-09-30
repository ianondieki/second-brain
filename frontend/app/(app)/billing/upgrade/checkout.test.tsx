import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { CheckoutCalls, ReadOutcome, StartOutcome } from "./calls";
import { Checkout, type CheckoutProps } from "./Checkout";
import { POLL_BUDGET_MS, type Checkout as CheckoutOut } from "./machine";

// REQ-BIL-08 (P14-F): the simulated M-Pesa steps as the person sees them: confirm, "Check your phone" while polling
// with a growing wait, then the outcome with a way back; refusals as one sentence and at most one action; one primary
// action at a time (docs/spec/07 items 2, 4 and 6).

const ID = "0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f";
const OTHER = "0192a7c4-5b1e-7c3d-8e9f-ffffffffffff";

function checkout(over: Partial<CheckoutOut> = {}): CheckoutOut {
  return {
    id: ID,
    plan_code: "dev_pro_monthly",
    plan_name: "Pro (monthly)",
    side: "developer",
    org_id: null,
    amount_kes_minor: 49900,
    currency: "KES",
    status: "pending",
    failure_code: null,
    simulated: true,
    plan_active: false,
    created_at: "2026-09-30T08:00:00Z",
    settled_at: null,
    poll_after_seconds: 2,
    ...over,
  };
}

function fakeCalls(start: StartOutcome, reads: ReadOutcome[]) {
  const calls = {
    start: vi.fn(async () => start),
    read: vi.fn(async () => reads.shift() ?? { ok: true as const, checkout: checkout() }),
  };
  return calls as typeof calls & CheckoutCalls;
}

function renderCheckout(calls: CheckoutCalls, over: Partial<CheckoutProps> = {}) {
  return renderWithIntl(
    <Checkout
      plan={{ code: "dev_pro_monthly", name: "Pro (monthly)" }}
      price="KES 499 a month"
      lines={["Unlimited published ideas"]}
      simulated
      billingHref="/billing"
      locale="en"
      calls={calls}
      {...over}
    />,
  );
}

const primaries = () => document.querySelectorAll("[data-primary]");
const phase = () => document.querySelector("[data-phase]")?.getAttribute("data-phase");

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  window.history.replaceState(null, "", "/billing/upgrade?plan=dev_pro_monthly");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("the simulated checkout", () => {
  it("confirms, waits on the phone step, then shows the new plan", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout() }, [
      { ok: true, checkout: checkout() },
      { ok: true, checkout: checkout({ status: "succeeded", plan_active: true }) },
    ]);
    renderCheckout(calls, { nextHref: "/dev/ideas/x/edit?step=3" });

    expect(screen.getByText("KES 499 a month")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Payment steps" }).querySelector("[aria-current='step']")?.textContent).toBe(
      "Confirm",
    );
    expect(primaries()).toHaveLength(1);
    fireEvent.click(screen.getByRole("radio", { name: "There is too little money" }));
    fireEvent.click(screen.getByRole("radio", { name: "The payment is confirmed" }));
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);

    expect(calls.start).toHaveBeenCalledWith({ planCode: "dev_pro_monthly", orgId: undefined, simulate: "succeed" });
    expect(phase()).toBe("pending");
    expect(screen.getByRole("heading", { name: "Waiting for the simulated payment" })).toBe(document.activeElement);
    expect(screen.getByText("You can leave this page: your plan changes once the payment is confirmed.")).toBeTruthy();
    const steps = screen.getByRole("list", { name: "Payment steps" });
    expect(steps.querySelector("[data-done]")?.textContent).toContain("Confirm: done");
    expect(steps.querySelector("[aria-current='step']")?.textContent).toBe("Check your phone");
    expect(screen.getByRole("status").textContent).toContain("Waiting for the payment to be confirmed");
    expect(primaries()).toHaveLength(0);
    expect(window.location.search).toContain(`checkout=${ID}`); // a reload carries on with this checkout

    // The first read waits the API's two seconds, the next one and a half times as long.
    await advance(1999);
    expect(calls.read).toHaveBeenCalledTimes(0);
    await advance(1);
    expect(calls.read).toHaveBeenCalledTimes(1);
    await advance(2999);
    expect(calls.read).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(calls.read).toHaveBeenCalledTimes(2);

    expect(phase()).toBe("succeeded");
    expect(screen.getByText("You are now on Pro (monthly).")).toBeTruthy();
    const next = screen.getByRole("link", { name: "Continue where you left off" });
    expect(next.getAttribute("href")).toBe("/dev/ideas/x/edit?step=3");
    expect(next.hasAttribute("data-primary")).toBe(true);
    expect(primaries()).toHaveLength(1);
    // No further reads once the answer is final.
    await advance(60_000);
    expect(calls.read).toHaveBeenCalledTimes(2);
  });

  it("sends no simulated outcome when the provider is real", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout({ simulated: false }) }, []);
    renderCheckout(calls, { simulated: false });
    expect(screen.queryByRole("radio")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pay with M-Pesa" }));
    await advance(0);
    expect(calls.start).toHaveBeenCalledWith({ planCode: "dev_pro_monthly", orgId: undefined, simulate: undefined });
    expect(screen.getByRole("heading", { name: "Check your phone" })).toBeTruthy();
    expect(screen.getByText("Enter your M-Pesa PIN in the prompt on your phone to pay KES 499.")).toBeTruthy();
  });

  it("says why a failed payment failed and offers to try again", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout() }, [
      { ok: true, checkout: checkout({ status: "failed", failure_code: "insufficient_funds" }) },
    ]);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("radio", { name: "There is too little money" }));
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    await advance(2000);
    expect(calls.start).toHaveBeenCalledWith(expect.objectContaining({ simulate: "fail" }));
    expect(phase()).toBe("failed");
    expect(screen.getByRole("alert").textContent).toBe(
      "The M-Pesa account had too little money, so your plan has not changed.",
    );
    expect(primaries()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(phase()).toBe("confirm");
    // Focus moves to the step that opened again, never back to <body>.
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "You pay" }));
    expect(window.location.search).not.toContain("checkout=");
  });

  it("words a cancelled payment", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout({ status: "cancelled", failure_code: "cancelled_by_customer" }) }, []);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    expect(phase()).toBe("cancelled");
    expect(screen.getByRole("heading", { name: "Payment cancelled" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("The payment was cancelled on the phone, so your plan has not changed.");
  });

  it("stops polling after the budget and polls again on Check again", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout() }, []);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    for (let waited = 0; waited <= POLL_BUDGET_MS + 1000; waited += 1000) await advance(1000);
    expect(phase()).toBe("stalled");
    const reads = calls.read.mock.calls.length;
    expect(reads).toBeLessThanOrEqual(20);
    await advance(60_000);
    expect(calls.read).toHaveBeenCalledTimes(reads);
    expect(screen.getByText("No answer yet. Your plan changes only once the payment is confirmed.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await advance(0);
    await advance(2000);
    expect(calls.read).toHaveBeenCalledTimes(reads + 1);
    expect(phase()).toBe("pending");
  });

  it("keeps polling through passing read failures", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout() }, [
      { ok: false, problem: "transient" },
      { ok: true, checkout: checkout({ status: "succeeded", plan_active: true }) },
    ]);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    await advance(2000);
    expect(phase()).toBe("pending");
    await advance(3000);
    expect(phase()).toBe("succeeded");
    // Without a page to go back to, the way on is the plan itself.
    const link = screen.getByRole("link", { name: "See your plan" });
    expect(link.getAttribute("href")).toBe("/billing");
    expect(link.hasAttribute("data-primary")).toBe(true);
  });

  it("offers the way back only once the plan is active", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout({ status: "succeeded", plan_active: false }) }, []);
    renderCheckout(calls, { nextHref: "/dev/ideas/x/edit?step=3" });
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    expect(phase()).toBe("succeeded");
    expect(screen.getByRole("status").textContent).toBe(
      "The payment is confirmed. Your plan changes in a moment: reload this page to see it.",
    );
    expect(screen.queryByRole("link", { name: "Continue where you left off" })).toBeNull();
    expect(screen.getByRole("link", { name: "See your plan" }).getAttribute("href")).toBe("/billing");
  });

  it("stops when the checkout is not the person's", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout() }, [{ ok: false, problem: "notFound" }]);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    await advance(2000);
    expect(phase()).toBe("lost");
    expect(screen.getByRole("alert").textContent).toContain("This payment is not one of yours.");
    await advance(60_000);
    expect(calls.read).toHaveBeenCalledTimes(1);
  });

  it("carries on with a checkout named in the address, reading it at once", async () => {
    const calls = fakeCalls({ ok: true, checkout: checkout() }, [
      { ok: true, checkout: checkout({ status: "succeeded", plan_active: true }) },
    ]);
    renderCheckout(calls, { initialCheckoutId: ID });
    expect(screen.getByRole("status").textContent).toContain("Checking the payment");
    await advance(0);
    expect(calls.start).not.toHaveBeenCalled();
    expect(calls.read).toHaveBeenCalledWith(ID, expect.any(AbortSignal));
    expect(phase()).toBe("succeeded");
  });
});

describe("refused starts", () => {
  it.each([
    ["alreadyOnPlan", "You are already on this plan.", "Back to Plan & billing", "/billing"],
    ["notConfigured", "Payments are not available right now. Try again later.", "Back to Plan & billing", "/billing"],
    ["forbidden", "Only the owner, an admin or a finance member can pay for this organisation's plan.", "Back to Plan & billing", "/billing"],
    ["mfaRequired", "Enter the code from your authenticator app first, then come back to pay.", "Enter your code", "/auth/mfa"],
    ["mfaSetup", "Turn on two-step sign-in first, then come back to pay.", "Turn on two-step sign-in", "/settings/security"],
    ["signedOut", "You are signed out. Log in again, then come back to pay.", "Log in", "/login"],
  ] as const)("%s: one sentence, one action, and no button that would be refused again", async (problem, sentence, action, href) => {
    const calls = fakeCalls({ ok: false, refusal: { problem } }, []);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    const alert = screen.getByRole("alert");
    expect(alert).toBe(document.activeElement);
    expect(alert.querySelector("p")?.textContent).toBe(sentence);
    const links = alert.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].textContent).toBe(action);
    expect(links[0].getAttribute("href")).toBe(href);
    expect(primaries()).toHaveLength(0);
  });

  it("offers the same button again when trying again can help", async () => {
    const calls = fakeCalls({ ok: false, refusal: { problem: "providerError" } }, []);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    expect(screen.getByRole("alert").textContent).toBe("The payment could not be started. Try again in a few minutes.");
    expect(screen.getByRole("alert").querySelectorAll("a")).toHaveLength(0);
    expect(primaries()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    expect(calls.start).toHaveBeenCalledTimes(2);
  });

  it("follows the other plan's checkout in progress", async () => {
    const calls = fakeCalls({ ok: false, refusal: { problem: "otherPending", checkoutId: OTHER } }, [
      { ok: true, checkout: checkout({ id: OTHER, plan_name: "Pro (yearly)", status: "succeeded", plan_active: true }) },
    ]);
    renderCheckout(calls);
    fireEvent.click(screen.getByRole("button", { name: "Start the simulated payment" }));
    await advance(0);
    await advance(0);
    expect(calls.read).toHaveBeenCalledWith(OTHER, expect.any(AbortSignal));
    expect(screen.getByText("You are now on Pro (yearly).")).toBeTruthy();
  });

  it("ignores a second press while starting", async () => {
    let finish: (value: StartOutcome) => void = () => {};
    const calls = fakeCalls({ ok: true, checkout: checkout() }, []);
    calls.start.mockImplementationOnce(() => new Promise<StartOutcome>((resolve) => (finish = resolve)));
    renderCheckout(calls);
    const button = screen.getByRole("button", { name: "Start the simulated payment" });
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Starting…" }));
    expect(calls.start).toHaveBeenCalledTimes(1);
    await act(async () => finish({ ok: true, checkout: checkout() }));
    expect(phase()).toBe("pending");
  });
});
