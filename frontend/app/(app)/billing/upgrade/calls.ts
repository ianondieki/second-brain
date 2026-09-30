import { api, type ApiClient } from "@/lib/api/client";

import { pollRefusal, startRefusal, type Checkout, type PollProblem, type SimulatedOutcome, type StartRefusal } from "./machine";

// The checkout's calls from the browser (same-origin /api through the Next.js rewrite; the client adds the CSRF
// header to the POST). Each settles into the checkout or a refusal the screen words; a thrown fetch is "network".

export type StartOutcome = { ok: true; checkout: Checkout } | { ok: false; refusal: StartRefusal };
export type ReadOutcome = { ok: true; checkout: Checkout } | { ok: false; problem: PollProblem };

export interface StartRequest {
  planCode: string;
  orgId?: string;
  /** Only when the checkout is simulated (the API refuses it from a real provider). */
  simulate?: SimulatedOutcome;
}

type Answer = { data?: unknown; error?: unknown; response: Response };

async function answer(call: () => Promise<Answer>): Promise<{ ok: boolean; status: number; body: unknown }> {
  try {
    const { data, error, response } = await call();
    return { ok: response.ok, status: response.status, body: response.ok ? data : error };
  } catch {
    return { ok: false, status: 0, body: undefined };
  }
}

/** POST /api/billing/checkouts: 201 a new checkout, 200 the one of this plan already in progress. */
export async function startCheckout(request: StartRequest, client: ApiClient = api): Promise<StartOutcome> {
  const result = await answer(() =>
    client.POST("/api/billing/checkouts", {
      body: {
        plan_code: request.planCode,
        ...(request.orgId ? { org_id: request.orgId } : {}),
        ...(request.simulate ? { simulate: request.simulate } : {}),
      },
    }),
  );
  if (result.ok && result.body) return { ok: true, checkout: result.body as Checkout };
  return { ok: false, refusal: startRefusal(result.ok ? 500 : result.status, result.body) };
}

/** GET /api/billing/checkouts/{id}: the API asks the provider, settles a final answer and activates a success. */
export async function readCheckout(id: string, signal?: AbortSignal, client: ApiClient = api): Promise<ReadOutcome> {
  const result = await answer(() =>
    client.GET("/api/billing/checkouts/{checkout_id}", { params: { path: { checkout_id: id } }, signal }),
  );
  if (result.ok && result.body) return { ok: true, checkout: result.body as Checkout };
  return { ok: false, problem: pollRefusal(result.ok ? 500 : result.status, result.body) };
}

export interface CheckoutCalls {
  start: typeof startCheckout;
  read: typeof readCheckout;
}

export const checkoutCalls: CheckoutCalls = { start: startCheckout, read: readCheckout };
