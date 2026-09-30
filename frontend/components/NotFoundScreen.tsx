import { getTranslations } from "next-intl/server";

import { getMe } from "@/lib/api/server";
import { homeOf, isPending, type Me } from "@/lib/auth/routing";

import { AuthShell } from "./AuthShell";
import { SignedInShell } from "./SignedInShell";
import { EmptyState } from "./ui/EmptyState";
import { PageHeader } from "./ui/PageHeader";

/** Who is asking, or null: a failed lookup shows the signed-out frame rather than an error page for a wrong address. */
async function signedIn(): Promise<Me | null> {
  try {
    const me = await getMe();
    return me && !isPending(me) ? me : null;
  } catch {
    return null;
  }
}

/**
 * An address with no page (not-found.tsx): the frame the person was in, the title, one sentence and one link home
 * (docs/spec/07 item 4). Signed in, it is the signed-in shell and their own home; otherwise the signed-out one. It
 * reads nothing from the address, so every unknown address, the staff console's included for anyone who is not
 * staff (proxy.ts), answers the same way for the same person.
 */
export async function NotFoundScreen() {
  const t = await getTranslations("notFound");
  const me = await signedIn();
  const body = (
    <>
      <PageHeader title={t("title")} />
      <EmptyState
        className="mt-6"
        sentence={t("body")}
        action={me ? t("homeSignedIn") : t("home")}
        href={me ? homeOf(me) : "/"}
        primary
      />
    </>
  );
  return me ? <SignedInShell homeHref={homeOf(me)}>{body}</SignedInShell> : <AuthShell>{body}</AuthShell>;
}
