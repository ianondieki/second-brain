import { PortalNavFor } from "@/components/PortalNavFor";
import { getMe } from "@/lib/api/server";
import { homeOf, isPending } from "@/lib/auth/routing";

import { PortalLoading, type LoadingShape } from "./PortalLoading";

/**
 * The loading screen of a page outside the portals' sections (notifications, settings, Plan & billing): the person's
 * own navigation, as the page draws it (PortalNavFor), around skeletons. /api/auth/me is the page's first read and is
 * shared with it (cached per request), so this costs no extra call.
 */
export async function AccountLoading({ shape, action = true }: { shape: LoadingShape; action?: boolean }) {
  const me = await getMe().catch(() => null);
  const signedIn = me && !isPending(me) ? me : null;
  return (
    <PortalLoading
      homeHref={signedIn ? homeOf(signedIn) : "/"}
      nav={signedIn ? <PortalNavFor me={signedIn} /> : undefined}
      shape={shape}
      action={action}
    />
  );
}
