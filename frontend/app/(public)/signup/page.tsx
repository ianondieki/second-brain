import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { ClientStrings } from "@/components/ClientStrings";
import { IntlScope } from "@/components/IntlScope";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn, getSignupConsents } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";
import { publicDemoOn } from "@/lib/public-demo";
import { retryWhen } from "@/lib/retry-after";

import { isInvitationToken, readInvitation } from "../invitations/[token]/invitation";
import { SignupForm } from "./SignupForm";

// With ?invitation= the address carries an invitation link's token: no referrer leaves the page (as on the link's own
// page, security-headers.ts), and it is never indexed.
export async function generateMetadata({ searchParams }: PageProps<"/signup">): Promise<Metadata> {
  const t = await getTranslations("signup");
  const invited = (await searchParams).invitation !== undefined;
  return invited
    ? { title: t("title"), referrer: "no-referrer", robots: { index: false, follow: false } }
    : { title: t("title") };
}

/**
 * Sign up; a person already signed in goes to their own home (a server-side redirect, like / and /login). With
 * `?invitation=<token>` (REQ-TEN-02, from an invitation link's "Create an account"), the form is an invitee's: the
 * organisation named from the link's public preview, no side choice and no organisation details; a link that no
 * longer opens anything is the invitation page's dead-link sentence instead.
 */
export default async function SignupPage({ searchParams }: PageProps<"/signup">) {
  const me = await getSignedIn();
  if (me) redirect(homeOf(me));
  if (publicDemoOn()) return <DemoSignup />;
  const requested = (await searchParams).invitation;
  const token = typeof requested === "string" && isInvitationToken(requested) ? requested : null;
  const invited = token ? await readInvitation(token) : null;
  const [t, consents] = await Promise.all([getTranslations("signup"), getSignupConsents()]);
  if (token && invited?.kind === "rateLimited") {
    // Too many invitation previews from here: when to try again (the API's Retry-After), not a dead link.
    const [ti, tr] = await Promise.all([getTranslations("invitation"), getTranslations("retryAfter")]);
    const when = retryWhen(invited.retryAfter);
    return (
      <AuthShell photo="signUp">
        <PageHeader title={ti("rateLimitedTitle")} lead={ti("rateLimited")} />
        <EmptyState
          className="mt-6"
          sentence={when.count === undefined ? tr(when.key) : tr(when.key, { count: when.count })}
          action={(await getTranslations("orgTeam"))("retry")}
          href={`/signup?invitation=${token}`}
          data-signup="rateLimited"
        />
      </AuthShell>
    );
  }
  if (requested !== undefined && invited?.kind !== "ok") {
    const ti = await getTranslations("invitation");
    return (
      <AuthShell photo="signUp">
        <PageHeader title={ti("deadTitle")} />
        <EmptyState className="mt-6" sentence={ti("dead")} action={t("plainSignup")} href="/signup" />
      </AuthShell>
    );
  }
  return (
    <AuthShell photo="signUp">
      <PageHeader title={t("title")} lead={t("lead")} />
      <IntlScope namespaces={["signup", "fields", "validation", "errors", "orgKind"]}>
        {/* The password field's show/hide words are server-formatted (components/ui/PasswordField.tsx). */}
        <ClientStrings strings={await clientStrings(["fields"])}>
          <SignupForm
            initialConsents={consents}
            invitation={invited?.kind === "ok" && token ? { token, org: invited.preview.org_name } : undefined}
          />
        </ClientStrings>
      </IntlScope>
    </AuthShell>
  );
}

/**
 * The public demo (REQ-FND-04): creating an account is switched off (the API refuses it too), so the page is one
 * sentence and one action, the persona picker on /login (its one primary action).
 */
async function DemoSignup() {
  const [t, tDemo] = await Promise.all([getTranslations("signup"), getTranslations("publicDemo")]);
  return (
    <AuthShell photo="signUp">
      <PageHeader title={t("title")} />
      <EmptyState
        className="mt-8"
        sentence={tDemo("signupLocked")}
        action={tDemo("signupAction")}
        href="/login"
        primary
        data-demo-locked=""
      />
    </AuthShell>
  );
}
