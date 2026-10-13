import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { roleWords } from "@/app/(app)/org/team/team";
import { AuthShell } from "@/components/AuthShell";
import { ClientStrings } from "@/components/ClientStrings";
import { DemoLocked } from "@/components/DemoLocked";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn } from "@/lib/api/server";
import { clientStrings } from "@/lib/i18n/client-strings";
import { publicDemoOn } from "@/lib/public-demo";
import { loginHref } from "@/lib/return-path";

import { AcceptInvitation } from "./AcceptInvitation";
import { invitationPath, joinPath, readInvitation } from "./invitation";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("invitation");
  // Never indexed, and no referrer leaves the page (the link's token is in its address; the header says the same,
  // security-headers.ts).
  return { title: t("pageTitle"), robots: { index: false, follow: false }, referrer: "no-referrer" };
}

/**
 * An invitation link (REQ-TEN-02; docs/platform/tasks/P28.md track C, AT-C-1): "Join {org}" and the roles it gives,
 * read on the server from the public preview. Signed in, "Accept and join" (the one primary action) and the portal
 * opens; signed out, "Sign in to accept" (back here after, through ?next= and /org/join) and the way to create an account first. A link
 * that opens nothing (spent, revoked, resent over, expired or unknown: one answer) is one calm sentence and the home
 * page. In the public demo accepting is switched off. Server-rendered; only Accept is a client island.
 */
export default async function InvitationPage({ params }: PageProps<"/invitations/[token]">) {
  const { token } = await params;
  const [t, read] = await Promise.all([getTranslations("invitation"), readInvitation(token)]);
  const here = invitationPath(token);

  if (read.kind !== "ok") {
    const gone = read.kind === "gone";
    return (
      <AuthShell>
        <PageHeader title={gone ? t("deadTitle") : t("rateLimitedTitle")} />
        <EmptyState
          className="mt-6"
          sentence={gone ? t("dead") : t("rateLimited")}
          action={gone ? t("home") : (await getTranslations("orgTeam"))("retry")}
          href={gone ? "/" : here}
          data-invitation={read.kind}
        />
      </AuthShell>
    );
  }

  const { org_name: org, roles } = read.preview;
  const [ta, locale, me] = await Promise.all([getTranslations("teamAdmin"), getLocale(), getSignedIn()]);
  const words = roleWords(roles, (role) => ta(`role.${role}`), locale);

  let body;
  if (publicDemoOn()) {
    body = <DemoLocked sentence={t("demoLocked")} />;
  } else if (me) {
    body = (
      <div className="flex flex-col gap-5" data-invitation="signedIn">
        <p className="[overflow-wrap:anywhere] text-ink-soft">{t("signedInAs", { email: me.user.email })}</p>
        <ClientStrings strings={await clientStrings(["invitationAccept"])}>
          <AcceptInvitation token={token} orgName={org} />
        </ClientStrings>
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-5" data-invitation="signedOut">
        <p className="text-ink">{t("signInLead")}</p>
        <div>
          <ButtonLink href={loginHref(joinPath(token))} variant="primary" prefetch={false} className="w-full sm:w-auto">
            {t("signIn")}
          </ButtonLink>
        </div>
        <div className="border-t border-line pt-5">
          <p className="text-sm text-ink-soft">{t("noAccount")}</p>
          <Link href="/signup" prefetch={false} className={standaloneLinkClass}>
            {t("create")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <AuthShell>
      <PageHeader title={t("title", { org })} lead={t("lead", { org, roles: words })} />
      <div className="mt-6">{body}</div>
    </AuthShell>
  );
}
