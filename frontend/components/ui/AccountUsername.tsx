/**
 * The signed-in account's email as a hidden `autocomplete="username"` field, for forms whose only visible fields are
 * passwords (set or change the password, confirm with the current one). Password managers read it to save or fill
 * the right account when a site has several (Chromium, "Create amazing password forms": use hidden fields for
 * implicit information; its own example hides the field with display: none, which is what `hidden` does). Hidden,
 * it is never focused or announced, and the app never submits it: forms post JSON built from their state.
 * Forms that already show a real email field (login, signup) must not add it.
 */
export function AccountUsername({ email }: { email: string }) {
  return <input type="email" name="username" autoComplete="username" defaultValue={email} hidden />;
}
