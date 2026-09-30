/**
 * The login page carrying `path` as its return path: a signed-out visit to a signed-in page lands here (proxy.ts,
 * lib/return-path.ts), and signing in goes back to `path` (P16-C1).
 */
export function loginReturningTo(path: string): RegExp {
  const encoded = new URLSearchParams({ next: path }).toString().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`/login\\?${encoded}$`);
}
