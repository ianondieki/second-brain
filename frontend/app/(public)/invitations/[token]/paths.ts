// An invitation link's addresses (REQ-TEN-02), pure, for the server page, its Accept island and /org/join alike.

/** A link's token as the API issues it: 32 random bytes, URL-safe base64, unpadded (tenancy/invitations.py). */
const TOKEN = /^[A-Za-z0-9_-]{43}$/;

export function isInvitationToken(value: string): boolean {
  return TOKEN.test(value);
}

/** The page's own path for a token (its return path through sign-in). */
export function invitationPath(token: string): string {
  return `/invitations/${token}`;
}

/**
 * Where sign-in returns to for a token: /org/join/{token} (app/(app)/org/join), a signed-in page that sends the person on
 * to the invitation's page. A plain /org path, so the sign-in screens' return-path rule needs nothing new.
 */
export function joinPath(token: string): string {
  return `/org/join/${token}`;
}
