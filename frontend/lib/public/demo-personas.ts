import { forwardHeaders, serverApi } from "@/lib/api/server";
import type { paths } from "@/lib/api/schema";
import { sameOriginPath } from "@/lib/api/errors";

// The public demo's personas (REQ-FND-04; docs/platform/tasks/P28.md, track PD): GET /api/public/demo, read on the
// server for /login's picker. The answer is the same for every visitor and the API marks it cacheable for 60 s, so one
// read serves this server process for a minute; a failed read is not kept (the next visitor asks again). The types
// come from the operation (not a schema name), so they follow the API's own.

type PublicDemo = paths["/api/public/demo"]["get"]["responses"][200]["content"]["application/json"];
export type DemoPersona = PublicDemo["personas"][number];
export type DemoRole = DemoPersona["role"];

export const DEMO_ROLES = ["developer", "org_admin", "org_signatory", "org_reviewer", "staff"] as const satisfies readonly DemoRole[];
const ROLES: ReadonlySet<string> = new Set(DEMO_ROLES);

/** How long one answer is reused (the API's own Cache-Control). */
export const PERSONAS_TTL_MS = 60_000;

const KEY = /^[a-z0-9_-]{1,40}$/;

/** A persona this page can draw and sign in as: a plain key, a name, a known role and a home on this site. */
function usable(value: unknown): value is DemoPersona {
  if (typeof value !== "object" || value === null) return false;
  const persona = value as Record<string, unknown>;
  return (
    typeof persona.key === "string" &&
    KEY.test(persona.key) &&
    typeof persona.name === "string" &&
    persona.name.trim() !== "" &&
    typeof persona.role === "string" &&
    ROLES.has(persona.role) &&
    typeof persona.detail === "string" &&
    typeof persona.home === "string" &&
    sameOriginPath(persona.home) !== null
  );
}

let kept: { at: number; personas: DemoPersona[] } | null = null;

/** Forget the kept answer (tests). */
export function forgetDemoPersonas(): void {
  kept = null;
}

/**
 * The personas to offer, in the API's order: [] when the API says the mode is off, null when it could not be read.
 * Entries this page could not use (an unknown role, a home off this site) are left out rather than drawn wrongly.
 */
export async function demoPersonas(now: number = Date.now()): Promise<DemoPersona[] | null> {
  if (kept && now - kept.at < PERSONAS_TTL_MS) return kept.personas;
  try {
    const { data } = await serverApi().GET("/api/public/demo", {
      headers: await forwardHeaders({ session: false }),
      signal: AbortSignal.timeout(4000),
      cache: "no-store",
    });
    if (!data || typeof data.enabled !== "boolean" || !Array.isArray(data.personas)) return null;
    const personas = data.enabled ? data.personas.filter(usable) : [];
    kept = { at: now, personas };
    return personas;
  } catch {
    return null;
  }
}

// The seed marks its fixtures in their names ("Staff Moderator (demo)", "Telco A (fixture)"): the banner on every page
// already says every name here is fictional, so the picker drops the marker at the end of a name.
const SEED_MARK = /\s*\((?:demo|fixture|example)\)\s*$/i;

/** A persona's name as the picker draws it: "Staff Moderator (demo)" is "Staff Moderator" (the name itself when only a mark). */
export function personaName(name: string): string {
  const plain = name.replace(SEED_MARK, "").trim();
  return plain || name.trim();
}

/**
 * An organisation persona's organisation, read from the API's English detail "Telco A (fixture): owner and admin":
 * the part before the first colon, without the seed's mark ("Telco A"). Null when the detail has no such part (no
 * colon, nothing before it): the picker then draws no line rather than a wrong one.
 */
export function personaOrg(detail: string): string | null {
  const at = detail.indexOf(":");
  if (at <= 0) return null;
  return detail.slice(0, at).replace(SEED_MARK, "").trim() || null;
}

/**
 * The line under a persona's name: what that persona does here, built on the web in every language (REQ-FND-04; ux
 * review of P28-PD, MINOR 3) rather than the API's English detail, which repeats the role and carries the seed's words.
 * `about` formats the role's sentence; an organisation persona's names its organisation, and has no line when the
 * organisation cannot be read from the detail.
 */
export function personaLine(
  persona: Pick<DemoPersona, "role" | "detail">,
  about: (role: DemoRole, org: string) => string,
): string | null {
  if (!persona.role.startsWith("org_")) return about(persona.role, "");
  const org = personaOrg(persona.detail);
  return org ? about(persona.role, org) : null;
}
