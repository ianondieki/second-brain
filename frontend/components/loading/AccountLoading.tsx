import { getMe } from "@/lib/api/server";
import { homeOf, isPending } from "@/lib/auth/routing";

import { LoadingNav } from "./LoadingNav";
import { PortalLoading, type LoadingShape } from "./PortalLoading";

/**
 * The loading screen of a page outside the portals' sections (notifications, settings, Plan & billing): the person's
 * own navigation, as the page draws it (PortalNavFor's choice, with plain links: LoadingNav), around skeletons. /api/auth/me is the page's first read and is
 * shared with it (cached per request), so this costs no extra call.
 */
export async function AccountLoading({ shape, action = true }: { shape: LoadingShape; action?: boolean }) {
  const me = await getMe().catch(() => null);
  const signedIn = me && !isPending(me) ? me : null;
  const home = signedIn ? homeOf(signedIn) : null;
  const nav =
    home === "/admin" && signedIn?.user.staff_role ? (
      <LoadingNav portal="staff" role={signedIn.user.staff_role} />
    ) : signedIn?.side === "org" ? (
      <LoadingNav portal="org" />
    ) : signedIn?.side === "developer" ? (
      <LoadingNav portal="developer" />
    ) : undefined;
  return (
    <PortalLoading
      homeHref={home ?? "/"}
      nav={nav}
      shape={shape}
      action={action}
    />
  );
}
