import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeResponse"];
export type MfaState = components["schemas"]["MfaState"];
export type Side = Me["side"];
export type SideHome = "/dev" | "/org";
export type Home = SideHome | "/admin";
export type StaffRole = NonNullable<Me["user"]["staff_role"]>;

/**
 * Staff roles that have a section in the staff console (components/AdminNav.tsx ADMIN_SECTIONS; its test keeps the
 * two in step). P15 adds "moderator" with Moderation.
 */
export const CONSOLE_ROLES: readonly StaffRole[] = ["admin"];

/**
 * The portal home of a signed-in side. Staff use the developer portal like everyone else there (a staff member who
 * also belongs to an organisation is routed as before); their console home is `homeOf`. "pending" has no home: route
 * with destinationFor, which sends it to /auth/mfa.
 */
export function homeFor(side: Side): SideHome {
  return side === "org" ? "/org" : "/dev";
}

type Person = Pick<Me, "side" | "mfa"> & { user?: Pick<Me["user"], "staff_role"> | null };

/**
 * Where this person's home is: the staff console (docs/spec/07 item 1: "Admin is a separate console") for a staff
 * member whose role has a console section and whose two-step sign-in is on (the API admits no one else to it); for
 * everyone else, their side's portal. The portals do not send staff away, so a staff member without a section keeps
 * using them.
 */
export function homeOf(me: Person): Home {
  const role = me.side === "staff" ? me.user?.staff_role : null;
  if (role && me.mfa.enrolled && CONSOLE_ROLES.includes(role)) return "/admin";
  return homeFor(me.side);
}

/** Signed in with a password or link, but the second factor has not been entered yet for this session. */
export function isMfaPending(mfa: MfaState): boolean {
  return mfa.enrolled && !mfa.verified;
}

/** The API reports side "pending" (and no memberships) until the second factor is given. */
export function isPending(me: Pick<Me, "side" | "mfa">): boolean {
  return me.side === "pending" || isMfaPending(me.mfa);
}

/** Where a signed-in person goes next: the second-factor page while it is owed, else their home. */
export function destinationFor(me: Person): Home | "/auth/mfa" {
  return isPending(me) ? "/auth/mfa" : homeOf(me);
}

/** An account whose role requires two-step sign-in (org owner, admin, signatory, reviewer; staff) without it. */
export function needsMfaSetup(mfa: MfaState): boolean {
  return mfa.required && !mfa.enrolled;
}

/** Magic and verification links last this long (backend MAGIC_LINK_TTL_MINUTES default). Shown in copy only. */
export const LINK_MINUTES = 15;
