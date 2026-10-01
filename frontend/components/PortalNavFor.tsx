import { AdminNav } from "./AdminNav";
import { DevNav } from "./DevNav";
import { OrgNav } from "./OrgNav";

import { homeOf, type Me } from "@/lib/auth/routing";

/**
 * The portal navigation of whoever is signed in, with no section current: for the pages outside the sections (Plan &
 * billing, the settings, Help, a problem card), so the tab bar and the rail stay where they are and the content keeps
 * its column (ux review, round 2). Staff with a console get the console's sections; a pending or sideless account none.
 */
export function PortalNavFor({ me }: { me: Pick<Me, "side" | "mfa" | "user"> }) {
  if (homeOf(me) === "/admin" && me.user.staff_role) return <AdminNav role={me.user.staff_role} />;
  if (me.side === "org") return <OrgNav />;
  if (me.side === "developer") return <DevNav />;
  return null;
}
