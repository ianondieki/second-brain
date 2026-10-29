import type { paths } from "@/lib/api/schema";

import type { CommandRequest, ProcurementInput, ProcurementRoute } from "./model";

// A public entity's procurement route (stage 3b; REQ-ENG-06): what its sheet (RouteSheet, loaded when its button is
// pressed) and the server-rendered tracker (the route block, History) share. Never imported by the tracker's client
// first load: its request path, limits and route list travel only with the sheet (docs/spec/07 item 5, the JS budget).

/** The five routes, in the order the sheet offers them (backend models/enums.py ProcurementRoute). */
export const ROUTES = [
  "rfq_tender",
  "direct",
  "ppp_pip",
  "innovation_challenge",
  "pilot_mou",
] as const satisfies readonly ProcurementRoute[];

export function isRoute(value: unknown): value is ProcurementRoute {
  return typeof value === "string" && (ROUTES as readonly string[]).includes(value);
}

/** Direct procurement's justification, and any route's (backend engagements/state_machine.py JUSTIFICATION_*). */
export const JUSTIFICATION_MIN = 20;
export const JUSTIFICATION_MAX = 1000;

/** The route is chosen under the organisation's path, not the engagement's (backend engagements/router.py). */
export const ROUTE_PATH = "/api/orgs/{org_id}/engagements/{engagement_id}/procurement-route" as const;
/** A renamed route fails the type check here, as model.ts's COMMAND_PATHS_EXIST does for the other commands. */
export const ROUTE_PATH_EXISTS: [typeof ROUTE_PATH] extends [keyof paths] ? true : never = true;

/**
 * The justification as the API takes it: control characters dropped but line feeds and tabs (the schema's pattern
 * refuses them with a 422 the person could not see in the field), then trimmed; empty is none.
 */
export function plainJustification(text: string): string {
  // Exactly the characters the API's LINES pattern refuses (backend engagements/schemas.py).
  return text.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "").trim();
}

/** The route's request, with the lock_version the page read (409 stale when it moved). */
export function routeRequest(engagementId: string, orgId: string, lockVersion: number, input: ProcurementInput): CommandRequest {
  return {
    path: ROUTE_PATH,
    params: { org_id: orgId, engagement_id: engagementId },
    body: { ...input, lock_version: lockVersion },
  };
}
