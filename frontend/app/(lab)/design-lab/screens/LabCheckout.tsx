"use client";

import type { CheckoutCalls } from "@/app/(app)/billing/upgrade/calls";
import { Checkout } from "@/app/(app)/billing/upgrade/Checkout";
import type { Checkout as CheckoutOut } from "@/app/(app)/billing/upgrade/machine";

const ID = "0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f";

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
    created_at: "2026-10-01T05:00:00Z",
    settled_at: null,
    poll_after_seconds: 1,
    ...over,
  };
}

/** The real Checkout with in-memory calls: the simulated payment settles on the first poll. */
export function LabCheckout({ locale, sample, succeeded }: { locale: string; sample: React.ReactNode; succeeded: boolean }) {
  const calls: CheckoutCalls = {
    start: async () => ({ ok: true, checkout: checkout() }),
    read: async () => ({ ok: true, checkout: checkout({ status: "succeeded", plan_active: true, settled_at: "2026-10-01T05:00:03Z" }) }),
  };
  return (
    <Checkout
      plan={{ code: "dev_pro_monthly", name: "Pro (monthly)" }}
      price="KES 499 a month"
      lines={["Unlimited published ideas", "Pitch to 10 companies a month", "Scout matches in your inbox"]}
      sample={sample}
      simulated
      billingHref="/billing"
      locale={locale}
      calls={calls}
      initialCheckoutId={succeeded ? ID : undefined}
    />
  );
}
