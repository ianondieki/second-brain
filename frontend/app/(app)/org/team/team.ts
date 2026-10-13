import type { components } from "@/lib/api/schema";

// Organisation › Team (REQ-TEN-02; docs/spec/07 item 1; docs/platform/tasks/P28.md track C): what the page shows and
// who may change what, from GET /api/orgs/{org_id}/team and the person's own roles. Pure: the page, its client parts
// and the tests share it.

type Schemas = components["schemas"];
export type OrgTeam = Schemas["OrgTeam"];
export type TeamMember = Schemas["OrgTeamMember"];
export type OpenInvitation = Schemas["OrgInvitation"];
export type NicheDefault = Schemas["NicheDefault"];
export type OrgRole = Schemas["OrgRole"];

/** Every role, most powerful first: the order chips, checkboxes and lists use. */
export const ROLES = [
  "owner",
  "admin",
  "signatory",
  "reviewer",
  "finance",
  "viewer",
] as const satisfies readonly OrgRole[];

/** Only an owner grants, removes or takes away these (tenancy/team.py PROTECTED). */
export const PROTECTED_ROLES: ReadonlySet<OrgRole> = new Set(["owner", "signatory"]);

/** Who may be a niche's default reviewer (tenancy/team_settings.py DEFAULT_REVIEWER_ROLES). */
export const REVIEWER_ROLES: ReadonlySet<OrgRole> = new Set(["reviewer", "signatory", "admin"]);

/** Open invitations an organisation may have at once (tenancy/invitations.py MAX_OPEN). */
export const MAX_OPEN_INVITATIONS = 20;

/** A role chip per member, at most two on a row (docs/spec/07 item 2); the rest are named in words after them. */
export const ROLE_CHIPS = 2;

export function sortRoles(roles: readonly OrgRole[]): OrgRole[] {
  return ROLES.filter((role) => roles.includes(role));
}

/** The roles shown as chips (the two most powerful) and the rest, said in words. */
export function splitRoles(roles: readonly OrgRole[]): { chips: OrgRole[]; rest: OrgRole[] } {
  const sorted = sortRoles(roles);
  return { chips: sorted.slice(0, ROLE_CHIPS), rest: sorted.slice(ROLE_CHIPS) };
}

/** Owners and admins manage the team: invitations, removals, niche defaults, the escalation contact. */
export function manages(roles: readonly string[]): boolean {
  return roles.includes("owner") || roles.includes("admin");
}

/** Role changes are an owner's alone (PUT …/members/{user_id}/roles). */
export function isOwner(roles: readonly string[]): boolean {
  return roles.includes("owner");
}

/** The roles this person may give in an invitation: an admin who is not an owner cannot give owner or signatory. */
export function grantableRoles(myRoles: readonly string[]): OrgRole[] {
  return isOwner(myRoles) ? [...ROLES] : ROLES.filter((role) => !PROTECTED_ROLES.has(role));
}

/** Whether this person may remove `member`: an owner or admin, and only an owner removes an owner or a signatory. */
export function mayRemove(myRoles: readonly string[], member: Pick<TeamMember, "roles">): boolean {
  if (!manages(myRoles)) return false;
  return isOwner(myRoles) || !member.roles.some((role) => PROTECTED_ROLES.has(role));
}

/** Members who may be a niche's default reviewer, in the roster's order. */
export function reviewerChoices(members: readonly TeamMember[]): TeamMember[] {
  return members.filter((member) => member.roles.some((role) => REVIEWER_ROLES.has(role)));
}

/** One niche of the "New engagements" list: its slug, its name and who is its default now (null: nobody). */
export interface NicheRow {
  slug: string;
  name: string;
  userId: string | null;
}

/**
 * The organisation's niches (its directory card's, in that order) with each one's default, then any niche that has a
 * default but is no longer on the card (kept, so saving the set never drops it without the person seeing it).
 */
export function nicheRows(
  niches: readonly { slug: string; label: string }[],
  defaults: readonly NicheDefault[],
): NicheRow[] {
  const bySlug = new Map(defaults.map((d) => [d.niche_slug, d]));
  const rows: NicheRow[] = niches.map((niche) => ({
    slug: niche.slug,
    name: niche.label,
    userId: bySlug.get(niche.slug)?.user_id ?? null,
  }));
  const listed = new Set(rows.map((row) => row.slug));
  for (const d of defaults) {
    if (!listed.has(d.niche_slug)) rows.push({ slug: d.niche_slug, name: d.niche_name, userId: d.user_id });
  }
  return rows;
}

/** The PUT body for the niche defaults: the whole set, niches set to nobody left out. */
export function nicheDefaultsBody(choices: Readonly<Record<string, string>>): {
  items: { niche_slug: string; user_id: string }[];
} {
  return {
    items: Object.entries(choices)
      .filter(([, userId]) => userId !== "")
      .map(([niche_slug, user_id]) => ({ niche_slug, user_id })),
  };
}

/** The organisation pages' "?org=" links for the Team page. */
export const TEAM_PATH = "/org/team";
