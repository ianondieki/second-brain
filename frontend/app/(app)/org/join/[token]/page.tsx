import { redirect } from "next/navigation";

import { invitationPath, isInvitationToken } from "@/app/(public)/invitations/[token]/paths";

/**
 * The way back to an invitation link through sign-in (REQ-TEN-02). "Sign in to accept" asks /login to return here, a
 * signed-in page under /org (so the sign-in screens' return-path rule, and their script, stay as they are: docs/spec/07
 * item 5); signed in, this sends the person on to the invitation's own page, where Accept is. Signed out, the proxy
 * sends a visit here to /login first, as for any /org page. A token of any other shape goes to the home page.
 */
export default async function JoinRedirect({ params }: PageProps<"/org/join/[token]">) {
  const { token } = await params;
  redirect(isInvitationToken(token) ? invitationPath(token) : "/");
}
