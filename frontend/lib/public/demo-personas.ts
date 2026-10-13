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

/**
 * The line under a persona's name. In English, the API's own line ("Telco A (fixture): owner and admin"). The API writes
 * it in English only, so in another language it is derived here (REQ-FND-04): an organisation persona shows its
 * organisation's name (a proper name, as written), a developer its verification level in a translated sentence, staff
 * nothing more than the role line above it.
 */
export function personaDetail(
  persona: Pick<DemoPersona, "role" | "detail">,
  locale: string,
  level: (value: string) => string,
): string | null {
  if (locale === "en") return persona.detail.trim() || null;
  if (persona.role.startsWith("org_")) {
    const at = persona.detail.indexOf(":");
    return at > 0 ? persona.detail.slice(0, at).trim() : null;
  }
  if (persona.role === "developer") {
    const found = /\bD[0-9]\b/.exec(persona.detail);
    return found ? level(found[0]) : null;
  }
  return null;
}
