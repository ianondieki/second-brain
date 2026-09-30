/**
 * A server read started before the page knows it needs it, so it runs alongside the read that decides (P16-D,
 * REQ-UX-03; vercel-react-best-practices `async-defer-await`). The page awaits it only on the path that uses it. Its
 * failure is marked handled, so a path that returns first (a not-found or blocked state) leaves no unhandled
 * rejection behind; awaiting it still throws the same error (a redirect to sign in included).
 *
 * Only for reads without side effects that the API scopes to the signed-in person: a read the API audits, or one whose
 * refusal it records, still waits for the check that decides whether it happens.
 */
export function started<T>(read: Promise<T>): Promise<T> {
  read.catch(() => undefined);
  return read;
}
