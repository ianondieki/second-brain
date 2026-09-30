import { notFound, redirect } from "next/navigation";

import { apiErrorCode } from "@/lib/api/error-code";
import { forwardHeaders } from "@/lib/api/server";

// Server-side reads of the staff console's API (REQ-ADM-01), shared by its sections. Each read is bounded, so a hung
// API ends in the console's error page. A 404 (no longer staff, or no two-step sign-in) is the console's not-found
// page, a stale second factor asks for a fresh code, and staff without the section's role are told it is not theirs.

const TIMEOUT_MS = 5000;

export type Loaded<T> = { kind: "ok"; data: T } | { kind: "stepUp" } | { kind: "forbidden" };

/** The options of one bounded, uncached read with the visitor's session. */
export async function readOptions() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/** One answer as data, the step-up, or "forbidden"; the rest leaves the page (sign in, not found, error page). */
export function settle<T>(what: string, { data, error, response }: { data?: T; error?: unknown; response: Response }) {
  if (data !== undefined) return { kind: "ok", data } as Loaded<T>;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) notFound();
  if (response.status === 403) {
    return (apiErrorCode(error) === "step_up_required" ? { kind: "stepUp" } : { kind: "forbidden" }) as Loaded<T>;
  }
  throw new Error(`${what} answered ${response.status}`);
}

/** Several reads as one: all their data, or the first step-up or refusal among them. */
export function combine<T extends unknown[]>(...loaded: { [K in keyof T]: Loaded<T[K]> }): Loaded<T> {
  const refused = loaded.find((one) => one.kind !== "ok");
  if (refused) return refused as Loaded<T>;
  return { kind: "ok", data: loaded.map((one) => (one as { data: unknown }).data) as T };
}
