import { withCsrf } from "./csrf";
import type { components } from "./schema";

// POST /api/auth/demo/sign-in (REQ-FND-04; docs/platform/tasks/P28.md, track PD): the public demo's one-press persona
// sign-in. The API leaves the route out of its OpenAPI schema on purpose (it exists only in the public demo), so the
// typed client cannot name it; this sends it the way that client sends every POST: same origin, a JSON body, and the
// double-submit CSRF header through withCsrf (with its one retry on a stale token). The answer is the schema's
// SessionResponse, as POST /api/auth/login's.

export type SessionResponse = components["schemas"]["SessionResponse"];

export const DEMO_SIGN_IN_PATH = "/api/auth/demo/sign-in";

type Send = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** Signed in (the session cookie is set), or refused with the HTTP status (0: the request did not complete). */
export type DemoSignIn = { ok: true; data: SessionResponse } | { ok: false; status: number };

export async function demoSignIn(persona: string, send: Send = withCsrf()): Promise<DemoSignIn> {
  let response: Response;
  try {
    response = await send(DEMO_SIGN_IN_PATH, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ persona }),
    });
  } catch {
    return { ok: false, status: 0 };
  }
  if (!response.ok) return { ok: false, status: response.status };
  try {
    const data = (await response.json()) as SessionResponse;
    return data && typeof data.mfa_required === "boolean" ? { ok: true, data } : { ok: false, status: response.status };
  } catch {
    return { ok: false, status: response.status };
  }
}
