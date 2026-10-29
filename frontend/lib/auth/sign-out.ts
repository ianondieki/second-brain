import { withCsrf } from "@/lib/api/csrf";
import { forgetEmail } from "@/lib/auth/remembered-email";
import { forgetOffline } from "@/components/offline/clear";
import { forgetRecent } from "@/components/palette/remember";

/**
 * Ends the session the app's one way (the account menu's Sign out and the invitation page's "Sign out and use another
 * address"): this device's offline copies go first (P27, D-69), awaited, whatever the API then answers; then POST
 * /api/auth/logout with only the CSRF helper (not the typed client: Sign out is on every signed-in page). Only 204
 * (ended) or 401 (already gone) count as signed out, and only then are the remembered address and the palette's
 * recent pages forgotten. Anything else, a network failure included, answers false: the person may still be signed in.
 */
export async function endSession(): Promise<boolean> {
  await forgetOffline();
  const status = await withCsrf()("/api/auth/logout", { method: "POST", credentials: "same-origin" }).then(
    (response) => response.status,
    () => 0,
  );
  if (status !== 204 && status !== 401) return false;
  forgetEmail(); // the next person on this device should not see this address offered back
  forgetRecent(); // nor the command palette's recent pages (P25)
  return true;
}
