import { redirect } from "next/navigation";

import { LandingContent } from "@/components/landing/LandingContent";
import { getSignedIn } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";

/** The landing page for visitors; a signed-in person goes to their own home (a server-side redirect, no script). */
export default async function Landing() {
  const me = await getSignedIn();
  if (me) redirect(homeOf(me));
  return <LandingContent />;
}
